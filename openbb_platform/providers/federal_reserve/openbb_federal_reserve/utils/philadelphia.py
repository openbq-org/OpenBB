"""Federal Reserve Bank of Philadelphia download and parsing helpers."""

from __future__ import annotations

BASE_URL = "https://www.philadelphiafed.org"
MEDIA_URL = f"{BASE_URL}/-/media/frbp/assets"


def fetch_philadelphia(url: str, cache_key: str, cadence: str) -> bytes:
    """Download a Philadelphia Fed file, caching the raw bytes by release cadence.

    Parameters
    ----------
    url : str
        The absolute file URL.
    cache_key : str
        The stable disk-cache key for the download.
    cadence : str
        The release cadence passed to ``seconds_until_next_release``.

    Returns
    -------
    bytes
        The raw response body.
    """
    from openbb_core.provider.utils.helpers import make_request

    from openbb_federal_reserve.utils.cache import cached, seconds_until_next_release

    def _producer() -> bytes:
        """Fetch the raw file bytes, rejecting HTML error pages served as 200."""
        response = make_request(url, timeout=60)
        response.raise_for_status()
        if response.content[:15].lstrip().startswith(b"<"):
            from openbb_core.app.model.abstract.error import OpenBBError

            raise OpenBBError(f"No Philadelphia Fed file was found at '{url}'.")
        return response.content

    return cached(
        ("philadelphia", cache_key),
        lambda: seconds_until_next_release(cadence),
        _producer,
    )


def read_workbook(content: bytes, sheet_name: str, header: int = 0):
    """Read one sheet of a Philadelphia Fed workbook into a DataFrame.

    A ``.xlsx`` payload (ZIP, magic ``PK``) is repacked without its ``docProps``
    parts to dodge the ``openpyxl`` core-properties crash, then read with the
    ``openpyxl`` engine; any other payload is read with the default engine so
    legacy ``.xls`` files resolve through ``xlrd``.

    Parameters
    ----------
    content : bytes
        The raw workbook bytes.
    sheet_name : str
        The exact sheet name to read.
    header : int
        The zero-based header row offset.

    Returns
    -------
    pandas.DataFrame
        The parsed sheet.
    """
    from io import BytesIO

    from pandas import read_excel

    if content[:2] == b"PK":
        return read_excel(
            BytesIO(_strip_doc_props(content)),
            engine="openpyxl",
            sheet_name=sheet_name,
            header=header,
        )
    return read_excel(BytesIO(content), sheet_name=sheet_name, header=header)


def quarter_start(year, quarter):
    """Combine integer year and quarter columns into quarter-start ``date`` values.

    Parameters
    ----------
    year : pandas.Series
        The four-digit year column.
    quarter : pandas.Series
        The quarter column, 1 to 4.

    Returns
    -------
    pandas.Series
        Quarter-start ``datetime.date`` values.
    """
    from pandas import PeriodIndex, Series

    periods = PeriodIndex(
        year.astype(int).astype(str) + "Q" + quarter.astype(int).astype(str),
        freq="Q",
    )
    return Series(periods.to_timestamp(), index=year.index).dt.date


def parse_two_digit_month(series):
    """Parse a ``%b-%y`` month label, mapping future years back a century.

    ``pandas`` reads two-digit years above the pivot into the 21st century, so a
    label like ``May-68`` parses to 2068; any date after today is shifted back
    100 years to its intended 20th-century value.

    Parameters
    ----------
    series : pandas.Series
        The raw ``%b-%y`` month labels.

    Returns
    -------
    pandas.Series
        Month-start ``datetime.date`` values.
    """
    from pandas import DateOffset, Timestamp, to_datetime

    parsed = to_datetime(series, format="%b-%y", errors="coerce")
    future = parsed > Timestamp.now()
    parsed = parsed.mask(future, parsed - DateOffset(years=100))
    return parsed.dt.date


def _strip_doc_props(content: bytes) -> bytes:
    """Repack an ``.xlsx`` ZIP without its ``docProps`` core-properties parts."""
    import zipfile
    from io import BytesIO

    source = zipfile.ZipFile(BytesIO(content))
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.namelist():
            if item.startswith("docProps/"):
                continue
            target.writestr(item, source.read(item))
    buffer.seek(0)
    return buffer.getvalue()
