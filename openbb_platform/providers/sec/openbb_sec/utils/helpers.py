"""SEC Helpers module."""

from openbb_core.app.model.abstract.error import OpenBBError
from pandas import DataFrame

from openbb_sec.utils.cache import cached_request, cached_text
from openbb_sec.utils.definitions import HEADERS, SEC_HEADERS
from openbb_sec.utils.ratelimit import sec_amake_request as amake_request

_REFERENCE_EXPIRE = 3600 * 24 * 2


async def sec_callback(response, session):
    """Response callback for SEC requests."""
    content_type = response.headers.get("Content-Type", "")
    if "application/json" in content_type:
        return await response.json()
    if "text/html" in content_type:
        return await response.text(encoding="latin-1")
    return await response.text()


async def get_all_companies(use_cache: bool = True) -> DataFrame:
    """Get all company names, tickers, and CIK numbers registered with the SEC.

    Companies are sorted by market cap.

    Returns
    -------
    DataFrame: Pandas DataFrame with columns for Symbol, Company Name, and CIK Number.

    Example
    -------
    >>> tickers = get_all_companies()
    """
    url = "https://www.sec.gov/files/company_tickers.json"
    response = await cached_request(
        url, headers=SEC_HEADERS, use_cache=use_cache, expire=_REFERENCE_EXPIRE
    )

    if not response or not isinstance(response, dict):
        raise OpenBBError(
            "Empty or invalid response from SEC company tickers endpoint."
        )

    df = DataFrame.from_dict(response, orient="index")
    cols = ["cik", "symbol", "name"]
    if len(df.columns) != len(cols):
        raise OpenBBError(
            f"Unexpected SEC response format. Expected {len(cols)} fields, got {len(df.columns)}: {df.columns.tolist()}"
        )
    df.columns = cols
    return df.astype(str)


async def get_all_ciks(use_cache: bool = True) -> DataFrame:
    """Get a list of entity names and their CIK number."""
    url = "https://www.sec.gov/Archives/edgar/cik-lookup-data.txt"

    async def callback(response, session):
        """Response callback for CIK lookup data."""
        return await response.text(encoding="latin-1")

    response = await cached_request(
        url,
        headers=SEC_HEADERS,
        response_callback=callback,
        use_cache=use_cache,
        expire=_REFERENCE_EXPIRE,
    )
    data = response
    lines = data.split("\n")
    data_list = []
    delimiter = ":"
    for line in lines:
        row = line.split(delimiter)
        data_list.append((row + [None, None])[:2])
    df = DataFrame(data_list)
    df = df.iloc[:, 0:2]
    cols = ["Institution", "CIK Number"]
    df.columns = cols
    df = df.dropna()

    return df.astype(str)


async def get_mf_and_etf_map(use_cache: bool = True) -> DataFrame:
    """Return the CIK number of a ticker symbol for querying the SEC API."""
    symbols = DataFrame()

    url = "https://www.sec.gov/files/company_tickers_mf.json"
    response = await cached_request(
        url,
        headers=SEC_HEADERS,
        response_callback=sec_callback,
        use_cache=use_cache,
        expire=_REFERENCE_EXPIRE,
    )

    symbols = DataFrame(data=response["data"], columns=response["fields"])

    return symbols.astype(str)


def _sec_range_read(url: str, ua: str, byte_range: str | None = None) -> bytes:
    """Read bytes from a SEC URL, optionally a specific range."""
    import urllib.request

    headers = {"User-Agent": ua}
    if byte_range:
        headers["Range"] = byte_range
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    return urllib.request.urlopen(request, timeout=120).read()  # noqa: S310


def _zip_member_text(url: str, member: str, ua: str) -> str | None:
    """Return the decompressed text of one zip member via HTTP range reads.

    Reads the end-of-central-directory and central directory to locate the
    member, then downloads only that member's compressed bytes - avoiding a full
    download of large structured-data-set archives.
    """
    import struct
    import zlib

    tail = _sec_range_read(url, ua, "bytes=-65536")
    eocd = tail.rfind(b"PK\x05\x06")
    if eocd < 0:
        return None
    cd_size, cd_off = struct.unpack("<II", tail[eocd + 12 : eocd + 20])
    central = _sec_range_read(url, ua, f"bytes={cd_off}-{cd_off + cd_size - 1}")

    target = None
    pos = 0
    while pos + 46 <= len(central) and central[pos : pos + 4] == b"PK\x01\x02":
        method = struct.unpack("<H", central[pos + 10 : pos + 12])[0]
        comp_size = struct.unpack("<I", central[pos + 20 : pos + 24])[0]
        name_len, extra_len, comment_len = struct.unpack(
            "<HHH", central[pos + 28 : pos + 34]
        )
        local_off = struct.unpack("<I", central[pos + 42 : pos + 46])[0]
        name = central[pos + 46 : pos + 46 + name_len].decode("utf-8", "ignore")
        if name == member:
            target = (method, comp_size, local_off)
            break
        pos += 46 + name_len + extra_len + comment_len
    if not target:
        return None

    method, comp_size, local_off = target
    local = _sec_range_read(url, ua, f"bytes={local_off}-{local_off + 29}")
    lname_len, lextra_len = struct.unpack("<HH", local[26:30])
    data_start = local_off + 30 + lname_len + lextra_len
    raw = _sec_range_read(url, ua, f"bytes={data_start}-{data_start + comp_size - 1}")
    return (zlib.decompress(raw, -15) if method == 8 else raw).decode("utf-8", "ignore")


def _series_names_from_dataset(
    listing_url: str, pattern: str, member: str, sid_col: str, name_col: str, ua: str
) -> dict:
    """Build a series_id -> series_name map from one SEC structured data set."""
    import re

    listing = _sec_range_read(listing_url, ua).decode("utf-8", "ignore")
    zips = sorted(
        set(re.findall(rf'href="([^"]*{pattern}[^"]*\.zip)"', listing, re.IGNORECASE))
    )
    if not zips:
        return {}
    text = _zip_member_text("https://www.sec.gov" + zips[-1], member, ua)
    if not text:
        return {}
    lines = text.splitlines()
    if not lines or sid_col not in (header := lines[0].split("\t")):
        return {}
    if name_col not in header:
        return {}
    sid_idx = header.index(sid_col)
    name_idx = header.index(name_col)
    mapping: dict = {}
    for line in lines[1:]:
        cols = line.split("\t")
        if len(cols) > max(sid_idx, name_idx):
            series_id = cols[sid_idx]
            if series_id and series_id != "N/A":
                mapping.setdefault(series_id, cols[name_idx])
    return mapping


def _fetch_series_name_map() -> dict:
    """Merge series_id -> series_name from the N-PORT and N-MFP data sets.

    N-PORT (most funds and ETFs) and N-MFP (money market funds) are large
    quarterly/monthly archives, but the series names live in small members read
    via HTTP range requests. Both are merged so every filing fund is covered.
    """
    import contextlib

    ua = SEC_HEADERS.get("User-Agent", "OpenBB Platform support@openbb.co")
    base = "https://www.sec.gov/data-research/sec-markets-data"
    mapping: dict = {}
    with contextlib.suppress(Exception):
        mapping.update(
            _series_names_from_dataset(
                f"{base}/dera-form-n-mfp-data-sets",
                "nmfp",
                "NMFP_SUBMISSION.tsv",
                "SERIESID",
                "SERIES_NAME",
                ua,
            )
        )
    with contextlib.suppress(Exception):
        mapping.update(
            _series_names_from_dataset(
                f"{base}/form-n-port-data-sets",
                "nport",
                "FUND_REPORTED_INFO.tsv",
                "SERIES_ID",
                "SERIES_NAME",
                ua,
            )
        )
    return mapping


async def get_series_name_map(use_cache: bool = True) -> dict:
    """Return a cached SEC series_id -> series_name map (N-PORT + N-MFP)."""
    import asyncio

    from openbb_sec.utils.cache import aget_cached, aset_cached

    cache_key = "sec_series_name_map"
    if use_cache:
        cached = await aget_cached(cache_key)
        if cached is not None:
            return cached
    mapping = await asyncio.to_thread(_fetch_series_name_map)
    if use_cache and mapping:
        await aset_cached(cache_key, mapping, expire=604800)
    return mapping


async def get_nport_fund_choices(use_cache: bool = True) -> list[dict]:
    """Return fund-dropdown choices mapping ticker symbol to SEC series for NPORT-P.

    Tickers come from the SEC mutual fund / ETF file (company_tickers_mf.json) and
    are labelled with the actual series name from the N-PORT data set. Funds with
    no N-PORT series are excluded (they have no NPORT-P data); the assembled list
    is deduplicated by symbol, sorted by ticker, and cached for a day.
    """
    from openbb_sec.utils.cache import aget_cached, aset_cached

    cache_key = "sec_nport_fund_choices"
    if use_cache:
        cached = await aget_cached(cache_key)
        if cached is not None:
            return cached

    funds = await get_mf_and_etf_map(use_cache=use_cache)
    series_names = await get_series_name_map(use_cache=use_cache)

    seen: set = set()
    choices: list = []
    for row in funds.itertuples(index=False):
        symbol = str(getattr(row, "symbol", "") or "").strip()
        if not symbol or symbol.lower() == "nan" or symbol in seen:
            continue
        series_id = str(getattr(row, "seriesId", "") or "").strip()
        name = series_names.get(series_id)
        if series_names and not name:
            continue
        seen.add(symbol)
        cik = str(getattr(row, "cik", "") or "").strip().lstrip("0")
        choices.append(
            {
                "label": f"{symbol} - {name}" if name else symbol,
                "value": symbol,
                "extraInfo": {
                    "description": f"Series {series_id}" if series_id else "",
                    "rightOfDescription": f"CIK {cik}" if cik else "",
                },
            }
        )
    choices = sorted(choices, key=lambda c: c["value"])
    if use_cache and choices:
        await aset_cached(cache_key, choices, expire=86400)
    return choices


def _format_aum(value: "float | None") -> str:
    """Format a dollar amount as a compact AUM string."""
    if not value:
        return ""
    for unit, factor in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if value >= factor:
            return f"${value / factor:.1f}{unit} AUM"
    return f"${value:,.0f} AUM"


def _fetch_13f_filers() -> dict:
    """Return CIK -> {name, aum} for current 13F filers.

    Joins the SUBMISSION (accession -> CIK), COVERPAGE (accession -> manager
    name) and SUMMARYPAGE (accession -> total portfolio value) members of the
    latest SEC Form 13F structured data set via HTTP range requests. The largest
    reported value per filer is kept. Covers institutions and companies.
    """
    import re
    from datetime import datetime

    ua = SEC_HEADERS.get("User-Agent", "OpenBB Platform support@openbb.co")
    listing = _sec_range_read(
        "https://www.sec.gov/data-research/sec-markets-data/form-13f-data-sets", ua
    ).decode("utf-8", "ignore")
    zips = re.findall(
        r'href="([^"]*-(\d{2}[a-z]{3}\d{4})_form13f\.zip)"', listing, re.IGNORECASE
    )
    if not zips:
        return {}
    latest = max(zips, key=lambda z: datetime.strptime(z[1], "%d%b%Y"))  # noqa: DTZ007
    url = "https://www.sec.gov" + latest[0]

    def _column_map(member: str, key_col: str, val_col: str, cast=None) -> dict:
        text = _zip_member_text(url, member, ua)
        if not text:
            return {}
        lines = text.splitlines()
        header = lines[0].split("\t")
        if key_col not in header or val_col not in header:
            return {}
        ki, vi = header.index(key_col), header.index(val_col)
        out: dict = {}
        for line in lines[1:]:
            cols = line.split("\t")
            if len(cols) > max(ki, vi):
                value = cols[vi].strip()
                if cast is not None:
                    try:
                        value = cast(value)
                    except (TypeError, ValueError):
                        value = None
                out[cols[ki]] = value
        return out

    cik_by_acc = _column_map("SUBMISSION.tsv", "ACCESSION_NUMBER", "CIK")
    name_by_acc = _column_map("COVERPAGE.tsv", "ACCESSION_NUMBER", "FILINGMANAGER_NAME")
    aum_by_acc = _column_map(
        "SUMMARYPAGE.tsv", "ACCESSION_NUMBER", "TABLEVALUETOTAL", float
    )

    filers: dict = {}
    for acc, raw_cik in cik_by_acc.items():
        cik = str(raw_cik or "").lstrip("0")
        name = str(name_by_acc.get(acc) or "").strip()
        if not cik or not name:
            continue
        aum = aum_by_acc.get(acc)
        current = filers.get(cik)
        if current is None or (aum or 0) > (current["aum"] or 0):
            filers[cik] = {"name": name, "aum": aum}
    return filers


async def get_13f_filer_choices(use_cache: bool = True) -> list[dict]:
    """Return dropdown choices for current 13F filers (institutions and companies).

    Each filer is keyed by CIK and labelled with its filing-manager name; company
    filers are additionally tagged with their ticker. Choices are sorted by total
    portfolio value (largest filers first) and cached for a day.
    """
    import asyncio

    from openbb_sec.utils.cache import aget_cached, aset_cached

    cache_key = "sec_13f_filer_choices"
    if use_cache:
        cached = await aget_cached(cache_key)
        if cached is not None:
            return cached

    filers = await asyncio.to_thread(_fetch_13f_filers)

    ticker_by_cik: dict = {}
    try:
        companies = await get_all_companies(use_cache=use_cache)
        for row in companies.itertuples(index=False):
            cik = str(getattr(row, "cik", "") or "").lstrip("0")
            symbol = str(getattr(row, "symbol", "") or "").strip()
            if cik and symbol and cik not in ticker_by_cik:
                ticker_by_cik[cik] = symbol
    except Exception:  # noqa: BLE001
        ticker_by_cik = {}

    ranked = sorted(
        ((cik, info) for cik, info in filers.items() if info["aum"]),
        key=lambda kv: kv[1]["aum"],
        reverse=True,
    )
    choices: list = []
    for cik, info in ranked:
        ticker = ticker_by_cik.get(cik)
        choices.append(
            {
                "label": f"{info['name']} ({ticker})" if ticker else info["name"],
                "value": cik,
                "extraInfo": {
                    "description": f"CIK {cik}",
                    "rightOfDescription": _format_aum(info["aum"]),
                },
            }
        )
    if use_cache and choices:
        await aset_cached(cache_key, choices, expire=86400)
    return choices


async def search_institutions(keyword: str, use_cache: bool = True) -> DataFrame:
    """Search for an institution by name.  It is case-insensitive."""
    institutions = await get_all_ciks(use_cache=use_cache)
    hp = institutions["Institution"].str.contains(keyword, case=False)
    return institutions[hp]


async def symbol_map(symbol: str, use_cache: bool = True) -> str:
    """Return the CIK number of a ticker symbol for querying the SEC API."""
    symbol = symbol.upper().replace(".", "-")
    symbols = await get_all_companies(use_cache=use_cache)

    if symbol not in symbols["symbol"].to_list():
        symbols = await get_mf_and_etf_map(use_cache=use_cache)
        if symbol not in symbols["symbol"].to_list():
            return ""
    cik = symbols[symbols["symbol"] == symbol]["cik"].iloc[0]
    cik_: str = ""
    temp = 10 - len(cik)
    for i in range(temp):
        cik_ = cik_ + "0"

    return str(cik_ + cik)


async def cik_map(cik: str | int, use_cache: bool = True) -> str:
    """Convert a CIK number to a ticker symbol.  Enter CIK as an integer with no leading zeros.

    Function is not meant for funds.

    Parameters
    ----------
    cik : int
        The CIK number to convert to a ticker symbol.

    Returns
    -------
    str: The ticker symbol associated with the CIK number.
    """
    _cik = str(cik) if isinstance(cik, int) else cik.lstrip("0")
    symbol = ""
    companies = await get_all_companies(use_cache=use_cache)
    if _cik in companies["cik"].to_list():
        symbol = companies[companies["cik"] == _cik]["symbol"].iloc[0]
    else:
        return f"Error: CIK, {_cik}, does not have a unique ticker."

    return symbol


def get_schema_filelist(query: str = "", url: str = "", use_cache: bool = True) -> list:
    """Get a list of schema files from the SEC website."""
    from io import StringIO  # noqa
    from pandas import read_html

    results: list = []
    url = url if url else f"https://xbrl.fasb.org/us-gaap/{query}"
    _url = url
    _url = url + "/" if query else _url
    content = cached_text(_url, use_cache=use_cache, raise_for_status=False)
    data = read_html(StringIO(content))[0]["Name"].dropna()
    if len(data) > 0:
        data.iloc[0] = url if not query else url + "/"
        results = data.to_list()

    return results


async def download_zip_file(
    url, symbol: str | None = None, use_cache: bool = True
) -> list[dict]:
    """Download a list of files from URLs."""
    from io import BytesIO
    from zipfile import ZipFile

    from pandas import concat, read_csv, to_datetime

    results = DataFrame()

    async def callback(response, session):
        """Response callback for ZIP file downloads."""
        return await response.read()

    response = await cached_request(
        url, headers=HEADERS, response_callback=callback, use_cache=use_cache
    )

    try:
        data = read_csv(BytesIO(response), compression="zip", sep="|")
        results = data.iloc[:-2]
    except ValueError:
        zip_file = ZipFile(BytesIO(response))
        file_list = [d.filename for d in zip_file.infolist()]
        for item in file_list:
            with zip_file.open(item) as _item:
                _file = read_csv(
                    _item,
                    encoding="ISO-8859-1",
                    sep="|",
                    low_memory=False,
                    on_bad_lines="skip",
                )
                results = concat([results, _file.iloc[:-2]])

    if "SETTLEMENT DATE" in results.columns:
        results = results.rename(
            columns={
                "SETTLEMENT DATE": "date",
                "SYMBOL": "symbol",
                "CUSIP": "cusip",
                "QUANTITY (FAILS)": "quantity",
                "PRICE": "price",
                "DESCRIPTION": "description",
            }
        )
        if symbol:
            results = results[results["symbol"] == symbol]
        results["date"] = to_datetime(results["date"], format="%Y%m%d").dt.date
        # Replace invalid decimal values with None
        results["price"] = results["price"].mask(
            ~results["price"].str.contains(r"^\d+(?:\.\d+)?$", regex=True), None
        )
        results["price"] = results["price"].astype(float)

    return results.reset_index(drop=True).to_dict("records")


async def get_ftd_urls() -> dict:
    """Get Fails-to-Deliver Data URLs."""
    from pandas import Series

    results = {}
    position = None
    key = "title"
    value = "Fails-to-Deliver Data"

    r = await amake_request("https://www.sec.gov/data.json", headers=SEC_HEADERS)
    data = r.get("dataset", {})

    for index, d in enumerate(data):
        if key in d and d[key] == value:
            position = index
            break
    if position is not None:
        fails = data[position]["distribution"]
        key = "downloadURL"
        urls = list(map(lambda d: d[key], filter(lambda d: key in d, fails)))
        dates = [d[-11:-4] for d in urls]
        ftd_urls = Series(index=dates, data=urls)
        ftd_urls.index = ftd_urls.index.str.replace("_", "")
        results = ftd_urls.to_dict()

    return results


async def get_series_id(
    symbol: str | None = None, cik: str | None = None, use_cache: bool = True
):
    """Map the fund to the series and class IDs for validating the correct filing.

    For an exact match, use a symbol.
    """
    symbol = symbol if symbol else ""
    cik = cik if cik else ""

    results = DataFrame()
    if not symbol and not cik:
        raise OpenBBError("Either symbol or cik must be provided.")

    target = symbol if symbol else cik
    choice = "cik" if not symbol else "symbol"
    funds = await get_mf_and_etf_map(use_cache=use_cache)

    results = funds[
        funds["cik"].str.contains(target, case=False)
        | funds["seriesId"].str.contains(target, case=False)
        | funds["classId"].str.contains(target, case=False)
        | funds["symbol"].str.contains(target, case=False)
    ]

    if len(results) > 0:
        results = results[results[choice if not symbol else choice] == target]

        return results


async def get_nport_candidates(symbol: str, use_cache: bool = True) -> list[dict]:
    """Get a fund's portfolio-holdings filings for a given symbol.

    Returns NPORT-P filings (most funds and ETFs) and N-MFP filings (money
    market funds), newest first. The fetcher routes parsing by the form type.
    """
    results = []
    _series_id = await get_series_id(symbol, use_cache=use_cache)
    series_id = (
        await symbol_map(symbol, use_cache)
        if _series_id is None or len(_series_id) == 0
        else _series_id["seriesId"].iloc[0]
    )
    if series_id == "" or series_id is None:
        raise OpenBBError("Fund not found for, the symbol: " + symbol)

    forms = "NPORT-P,N-MFP,N-MFP1,N-MFP2,N-MFP3"
    base = (
        f"https://efts.sec.gov/LATEST/search-index?q={series_id}"
        f"&dateRange=all&forms={forms}"
    )
    offset = 0
    while offset < 10000:
        response = await cached_request(
            f"{base}&from={offset}",
            headers=HEADERS,
            response_callback=sec_callback,
            use_cache=use_cache,
        )
        hits = (
            response.get("hits", {}).get("hits", [])
            if isinstance(response, dict)
            else []
        )
        if not hits:
            break
        results.extend(
            {
                "name": d["_source"]["display_names"][0],
                "cik": d["_source"]["ciks"][0],
                "file_date": d["_source"]["file_date"],
                "period_ending": d["_source"].get("period_ending")
                or d["_source"]["file_date"],
                "form_type": d["_source"]["form"],
                "primary_doc": (
                    f"https://www.sec.gov/Archives/edgar/data/{int(d['_source']['ciks'][0])}"  # noqa
                    + f"/{d['_id'].replace('-', '').replace(':', '/')}"  # noqa
                ),
            }
            for d in hits
        )
        offset += len(hits)
        if offset >= response["hits"]["total"]["value"]:
            break

    return sorted(results, key=lambda d: d["file_date"], reverse=True)
