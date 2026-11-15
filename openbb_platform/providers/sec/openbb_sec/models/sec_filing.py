"""SEC Filing Model."""

import contextlib
from datetime import date as dateType
from typing import Any

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import ConfigDict, Field, PrivateAttr, computed_field


class SecFilingQueryParams(QueryParams):
    """SEC Filing Query Parameters."""

    __json_schema_extra__ = {
        "url": {
            "x-widget_config": {
                "label": "Filing URL",
            }
        }
    }

    url: str | None = Field(
        default=None,
        description="URL for the SEC filing."
        + " The specific URL is not directly used or downloaded,"
        + " but is used to generate the base URL for the filing."
        + " e.g. https://www.sec.gov/Archives/edgar/data/317540/000031754024000045/coke-20240731.htm"
        + " and https://www.sec.gov/Archives/edgar/data/317540/000031754024000045/"
        + " are both valid URLs for the same filing.",
    )
    use_cache: bool = Field(
        default=True,
        description="Use cache for the index headers and cover page. Default is True.",
    )


class SecFilingData(Data):
    """SEC Filing Data."""

    # For Workspace, ConfigDict is used to enter the widget configuration at the "$.data" level.
    # Here, we are using a subset of the data - the document URLs with direct links - to avoid nested data.
    # This creates column definitions for the target output while preserving the structure of the model.
    model_config = ConfigDict(
        json_schema_extra={
            "x-widget_config": {
                "dataKey": "results.document_urls",
                "table": {
                    "columnsDefs": [
                        {
                            "field": "sequence",
                            "headerName": "Sequence",
                            "headerTooltip": "The sequence of the document.",
                            "type": "number",
                            "pinned": "left",
                            "maxWidth": 105,
                        },
                        {
                            "field": "type",
                            "headerName": "Document Type",
                            "headerTooltip": "The type of document.",
                            "type": "text",
                            "maxWidth": 150,
                        },
                        {
                            "field": "filename",
                            "headerName": "Filename",
                            "headerTooltip": "The filename of the document.",
                            "type": "text",
                            "maxWidth": 250,
                        },
                        {
                            "field": "content_description",
                            "headerName": "Description",
                            "headerTooltip": "Description of the document.",
                            "type": "text",
                            "minWidth": 600,
                        },
                        {
                            "field": "url",
                            "headerName": "URL",
                            "headerTooltip": "The URL of the document.",
                            "type": "text",
                            "maxWidth": 75,
                        },
                    ],
                },
            }
        }
    )

    base_url: str = Field(
        title="Base URL",
        description="Base URL of the filing.",
        json_schema_extra={
            "x-widget_config": {
                "exclude": True
            }  # Tells the widget factory to exclude this field. Has no effect on endpoint.
        },
    )
    name: str = Field(
        title="Entity Name",
        description="Name of the entity filing.",
        json_schema_extra={"x-widget_config": {"exclude": True}},
    )
    cik: str = Field(
        title="CIK",
        description="Central Index Key.",
        json_schema_extra={"x-widget_config": {"exclude": True}},
    )
    trading_symbols: list | None = Field(
        default=None,
        title="Trading Symbols",
        description="Trading symbols, if available.",
        json_schema_extra={"x-widget_config": {"exclude": True}},
    )
    sic: str = Field(
        title="SIC",
        description="Standard Industrial Classification.",
        json_schema_extra={"x-widget_config": {"exclude": True}},
    )
    sic_organization_name: str = Field(
        title="SIC Organization",
        description="SIC Organization Name.",
        json_schema_extra={"x-widget_config": {"exclude": True}},
    )
    filing_date: dateType = Field(
        title="Filing Date",
        description="Filing date.",
        json_schema_extra={"x-widget_config": {"exclude": True}},
    )
    period_ending: dateType | None = Field(
        default=None,
        title="Period Ending",
        description="Date of the ending period for the filing, if available.",
        json_schema_extra={"x-widget_config": {"exclude": True}},
    )
    fiscal_year_end: str | None = Field(
        default=None,
        title="Fiscal Year End",
        description="Fiscal year end of the entity, if available. Format: MM-DD",
        json_schema_extra={"x-widget_config": {"exclude": True}},
    )
    document_type: str = Field(
        title="Document Type",
        description="Specific SEC filing type.",
        json_schema_extra={"x-widget_config": {"exclude": True}},
    )
    has_cover_page: bool = Field(
        title="Has Cover Page",
        description="True if the filing has a cover page.",
        json_schema_extra={"x-widget_config": {"exclude": True}},
    )
    description: str | None = Field(
        default=None,
        title="Content Description",
        description="Description of attached content, mostly applicable to 8-K filings.",
        json_schema_extra={"x-widget_config": {"exclude": True}},
    )
    cover_page: dict | None = Field(
        default=None,
        title="Cover Page",
        description="Cover page information, if available.",
        json_schema_extra={"x-widget_config": {"exclude": True}},
    )
    document_urls: list = Field(
        title="Document URLs",
        description="List of files associated with the filing.",
        json_schema_extra={"x-widget_config": {"exclude": True}},
    )


class LazyDict(dict):
    """Dictionary that loads and caches values on demand via a loader callback."""

    def __init__(self, labels: dict, loader):
        """Initialize the LazyDict."""
        super().__init__()
        self._labels: dict = dict(labels)
        self._loader = loader
        self._cache: dict = {}

    def keys(self):
        """Available keys."""
        return self._labels.keys()

    def labels(self) -> dict:
        """Return a mapping of key to display label."""
        return dict(self._labels)

    def __getitem__(self, key):
        """Load and cache the value for a key."""
        if key not in self._labels:
            raise KeyError(key)
        if key not in self._cache:
            self._cache[key] = self._loader(key)
        return self._cache[key]

    def get(self, key, default=None):
        """Value for a key, or default if unknown."""
        return self[key] if key in self._labels else default

    def __iter__(self):
        """Iterate over the keys."""
        return iter(self._labels)

    def __len__(self):
        """Return the number of keys."""
        return len(self._labels)

    def __contains__(self, key):
        """Return True if the key is known."""
        return key in self._labels

    def items(self):
        """Iterate over (key, value) pairs."""
        for key in self._labels:
            yield key, self[key]

    def values(self):
        """Iterate over values."""
        for key in self._labels:
            yield self[key]

    def __repr__(self) -> str:
        """Return the string representation."""
        return f"LazyDict(keys={list(self._labels)})"


_PRIMARY_DOC_TYPES = ("10-K", "10-Q", "10-K/A", "10-Q/A", "20-F", "40-F", "8-K", "6-K")


class Filing(Data):
    """SEC Filing base model."""

    _url: str = PrivateAttr(default="")
    _index_headers_url: str = PrivateAttr(default="")
    _full_submission_url: str = PrivateAttr(default="")
    _index_headers_download: str = PrivateAttr(default="")
    _document_urls: list = PrivateAttr(default_factory=list)
    _filing_date: str = PrivateAttr(default="")
    _period_ending: str = PrivateAttr(default="")
    _document_type: str = PrivateAttr(default="")
    _name: str = PrivateAttr(default="")
    _cik: str = PrivateAttr(default="")
    _sic: str = PrivateAttr(default="")
    _sic_organization_name: str | None = PrivateAttr(default="")
    _description: str | None = PrivateAttr(default=None)
    _cover_page_url: str | None = PrivateAttr(default=None)
    _fiscal_year_end: str = PrivateAttr(default="")
    _fiscal_period: str = PrivateAttr(default="")
    _cover_page: dict = PrivateAttr(default_factory=dict)
    _trading_symbols: list = PrivateAttr(default_factory=list)
    _use_cache: bool = PrivateAttr(default=True)
    _items: dict = PrivateAttr(default_factory=dict)
    _shares_outstanding: dict = PrivateAttr(default_factory=dict)
    _fiscal_year: str = PrivateAttr(default="")
    _archive: dict = PrivateAttr(default_factory=dict)
    _archive_loaded: bool = PrivateAttr(default=False)
    _txt_loaded: bool = PrivateAttr(default=False)

    @computed_field(title="Base URL", description="Base URL of the filing.")
    @property
    def base_url(self) -> str:
        """Base URL of the filing."""
        return self._url

    @computed_field(title="Entity Name", description="Name of the entity filing.")
    @property
    def name(self) -> str:
        """Entity name."""
        return self._name

    @computed_field(title="CIK", description="Central Index Key.")
    @property
    def cik(self) -> str:
        """Central Index Key."""
        return self._cik

    @computed_field(
        title="Trading Symbols", description="Trading symbols, if available."
    )
    @property
    def trading_symbols(self) -> list | None:
        """Trading symbols, if available."""
        return self._trading_symbols

    @computed_field(title="SIC", description="Standard Industrial Classification.")
    @property
    def sic(self) -> str:
        """Standard Industrial Classification."""
        return self._sic

    @computed_field(title="SIC Organization", description="SIC Organization Name.")
    @property
    def sic_organization_name(self) -> str | None:
        """Standard Industrial Classification Organization Name."""
        return self._sic_organization_name

    @computed_field(title="Filing Date", description="Filing date.")
    @property
    def filing_date(self) -> dateType:
        """Filing date."""
        return dateType.fromisoformat(self._filing_date)

    @computed_field(
        title="Period Ending",
        description="Date of the ending period for the filing, if available.",
    )
    @property
    def period_ending(self) -> dateType | None:
        """Date of the ending period for the filing."""
        if self._period_ending:
            return dateType.fromisoformat(self._period_ending)
        return None

    @computed_field(
        title="Fiscal Year End",
        description="Fiscal year end of the entity, if available. Format: MM-DD",
    )
    @property
    def fiscal_year_end(self) -> str | None:
        """Fiscal year end date of the entity."""
        return self._fiscal_year_end

    @computed_field(title="Document Type", description="Specific SEC filing type.")
    @property
    def document_type(self) -> str:
        """Document type."""
        return self._document_type

    @computed_field(
        title="Has Cover Page", description="True if the filing has a cover page."
    )
    @property
    def has_cover_page(self) -> bool:
        """True if the filing has a cover page."""
        return bool(self._cover_page_url)

    @computed_field(
        title="Cover Page", description="Cover page information, if available."
    )
    @property
    def cover_page(self) -> dict | None:
        """Cover page information, if available."""
        return self._cover_page

    @computed_field(
        title="Content Description",
        description="Description of attached content, mostly applicable to 8-K filings.",
    )
    @property
    def description(self) -> str | None:
        """Document description, if available."""
        return self._description

    @computed_field(
        title="Document URLs", description="List of files associated with the filing."
    )
    @property
    def document_urls(self) -> list | None:
        """List of document URLs."""
        return self._document_urls

    def __init__(self, url: str, use_cache: bool = True):
        """Initialize the Filing class."""
        from urllib.parse import urlparse

        from openbb_core.provider.utils.helpers import run_async

        from openbb_sec.utils.helpers import cik_map

        super().__init__()

        if not url or not isinstance(url, str) or not url.strip():
            raise ValueError("Please enter a URL.")

        parsed = urlparse(url.strip())

        if parsed.scheme not in ("http", "https"):
            raise ValueError("Invalid SEC URL supplied, must use http or https scheme.")

        host = (parsed.hostname or "").lower()
        if host != "sec.gov" and not host.endswith(".sec.gov"):
            raise ValueError(
                "Invalid SEC URL supplied, host must be sec.gov"
                " (e.g. https://www.sec.gov/...)."
            )

        path = parsed.path
        if "/data/" not in path:
            raise ValueError("Invalid SEC URL supplied, must be a filing URL.")

        segments = path.split("/data/", 1)[1].split("/")
        if len(segments) < 2:
            raise ValueError("Invalid SEC URL supplied, must be a filing URL.")

        check_val: str = segments[1]

        if len(check_val) != 18 or not check_val.isdigit():
            raise ValueError("Invalid SEC URL supplied, must be a filing URL.")

        url = parsed.scheme + "://" + parsed.netloc + path

        new_url = url.split(check_val, maxsplit=1)[0] + check_val + "/"

        cik_check = new_url.split("/")[-3]
        new_url = new_url.replace(f"/{cik_check}/", f"/{cik_check.lstrip('0')}/")
        self._url = new_url
        self._use_cache = use_cache
        accession_dashed = (
            check_val[:-8] + "-" + check_val[-8:-6] + "-" + check_val[-6:]
        )
        self._index_headers_url = self._url + accession_dashed + "-index-headers.htm"
        self._full_submission_url = self._url + accession_dashed + ".txt"
        self._download_index_headers()

        if self._document_urls:
            for doc in self._document_urls:
                if doc.get("url", "").endswith("R1.htm"):
                    self._cover_page_url = doc.get("url")
                    break

        if self.has_cover_page and not self._cover_page:
            self._download_cover_page()

        if not self._trading_symbols:
            symbol = run_async(cik_map, self._cik, use_cache)
            if symbol:
                self._trading_symbols = [symbol]

    @staticmethod
    async def _adownload_file(url, use_cache: bool = True):
        """Download a file asynchronously from a SEC URL."""
        from urllib.parse import urlparse

        from openbb_sec.utils.cache import cached_request
        from openbb_sec.utils.definitions import HEADERS, SEC_HEADERS
        from openbb_sec.utils.helpers import sec_callback

        host = (urlparse(url).hostname or "").lower()
        if host == "www.sec.gov":
            headers = SEC_HEADERS
        else:
            # Hosts like xbrl.sec.gov return 404 when Host: www.sec.gov is pinned.
            headers = {k: v for k, v in SEC_HEADERS.items() if k.lower() != "host"}
            if "definitelynot@fakecompany.com" in headers.get(
                "User-Agent", ""
            ) and HEADERS.get("User-Agent"):
                headers["User-Agent"] = HEADERS["User-Agent"]

        return await cached_request(
            url,
            headers=headers,
            response_callback=sec_callback,
            raise_for_status=True,
            use_cache=use_cache,
        )

    @staticmethod
    def download_file(url, read_html_table: bool = False, use_cache: bool = True):
        """Download a file from a SEC URL."""
        from openbb_core.provider.utils.helpers import run_async  # noqa
        from warnings import warn

        try:
            response = run_async(Filing._adownload_file, url, use_cache)

            if read_html_table is True:
                if not url.endswith(".htm") and not url.endswith(".html"):
                    warn(f"File is not a HTML file: {url}")
                    return response

                return Filing.try_html_table(response)

            return response

        except Exception as e:
            raise RuntimeError(f"Failed to download file: {e} -> {e.args}") from e

    @staticmethod
    def try_html_table(text: str, **kwargs) -> list:
        """Attempt to parse tables from a HTML string. All keyword arguments passed to `pandas.read_html`"""
        from io import StringIO  # noqa
        from pandas import read_html

        try:
            return read_html(StringIO(text), **kwargs)
        except Exception as e:
            raise RuntimeError(f"Failed to parse table: {e}") from e

    def _download_index_headers(
        self,
    ):
        """Download the index headers table."""
        import re  # noqa
        from bs4 import BeautifulSoup

        try:
            if not self._index_headers_download:
                try:
                    response = self.download_file(
                        self._index_headers_url, False, self._use_cache
                    )
                except Exception:
                    response = self.download_file(
                        self._full_submission_url, False, self._use_cache
                    )
                self._index_headers_download = response
            else:
                response = self._index_headers_download

            soup = BeautifulSoup(response, "html.parser")
            pre = soup.find("pre")
            text = pre.text if pre is not None else response

            def document_to_dict(doc):
                """Convert the document section to a dictionary."""
                doc_dict: dict = {}
                type_match = re.search(r"<TYPE>(.*?)\n", doc)
                doc_dict["type"] = type_match.group(1).strip() if type_match else ""
                seq_match = re.search(r"<SEQUENCE>(.*?)\n", doc)
                doc_dict["sequence"] = seq_match.group(1).strip() if seq_match else ""
                filename_match = re.search(r"<FILENAME>(.*?)\n", doc)
                doc_dict["filename"] = (
                    filename_match.group(1).strip() if filename_match else ""
                )
                description_match = re.search(r"<DESCRIPTION>(.*?)\n", doc)
                if description_match:
                    doc_dict["description"] = description_match.group(1).strip()

                body_match = re.search(
                    r"<TEXT>(.*?)</TEXT>", doc, re.DOTALL
                ) or re.search(r"<TEXT>(.*)", doc, re.DOTALL)
                if body_match:
                    body = body_match.group(1)
                    body = re.sub(
                        r"\s*</(?:TEXT|DOCUMENT)>\s*$", "", body, flags=re.IGNORECASE
                    )
                    doc_dict["content"] = body.strip()

                doc_dict["url"] = (
                    self.base_url + doc_dict["filename"] if doc_dict["filename"] else ""
                )
                return doc_dict

            # Isolate each document by tag
            documents = re.findall(r"<DOCUMENT>.*?</DOCUMENT>", text, re.DOTALL)
            # Convert each document to a dictionary
            document_dicts = [document_to_dict(doc) for doc in documents]

            if document_dicts:
                self._document_urls = document_dicts

            lines = text.split("\n")
            n_items = 0

            for line in lines:
                if ":" not in line:
                    continue

                value = line.split(":")[1].strip()

                if n_items == 9:
                    break

                if "CONFORMED PERIOD OF REPORT" in line:
                    as_of_date = value
                    self._period_ending = (
                        as_of_date[:4] + "-" + as_of_date[4:6] + "-" + as_of_date[6:]
                    )
                elif "FILED AS OF DATE" in line:
                    filing_date = value
                    self._filing_date = (
                        filing_date[:4] + "-" + filing_date[4:6] + "-" + filing_date[6:]
                    )
                    n_items += 1
                elif "COMPANY CONFORMED NAME" in line:
                    self._name = value
                    n_items += 1
                elif "CONFORMED SUBMISSION TYPE" in line:
                    self._document_type = value
                    n_items += 1
                elif "CENTRAL INDEX KEY" in line:
                    self._cik = value
                    n_items += 1
                elif "STANDARD INDUSTRIAL CLASSIFICATION" in line:
                    self._sic = value
                    n_items += 1
                elif "ORGANIZATION NAME" in line:
                    self._sic_organization_name = value
                    n_items += 1
                elif "FISCAL YEAR END" in line:
                    fy = value
                    self._fiscal_year_end = fy[:2] + "-" + fy[2:]
                    n_items += 1
                # There might be two lines of ITEM INFORMATION
                elif "ITEM INFORMATION" in line:
                    info = value
                    self._description = (
                        self._description + "; " + info if self._description else info
                    )
                    n_items += 1
                continue

        except Exception as e:
            raise RuntimeError(
                f"Failed to download and read the index headers table: {e}"
            ) from e

    @staticmethod
    def _multiplier_map(string) -> int:
        """Map a string to a multiplier."""
        if string.lower() == "millions":
            return 1000000
        if string.lower() == "hundreds of thousands":
            return 100000
        if string.lower() == "tens of thousands":
            return 10000
        if string.lower() == "thousands":
            return 1000
        if string.lower() == "hundreds":
            return 100
        if string.lower() == "tens":
            return 10
        return 1

    def _download_cover_page(
        self,
    ):
        """Download the cover page table."""
        from pandas import MultiIndex, to_datetime

        symbols_list: list = []
        try:
            response = self.download_file(self._cover_page_url, True, self._use_cache)
            if not response:
                raise RuntimeError("Failed to download cover page table")
            df = response[0]
            if isinstance(df.columns, MultiIndex):
                df = df.droplevel(0, axis=1)

            if df.empty or len(df) < 1:
                raise RuntimeError("Failed to read cover page table")

            fiscal_year = df[df.iloc[:, 0] == "Document Fiscal Year Focus"]

            if not fiscal_year.empty:
                fiscal_year = fiscal_year.iloc[:, 1].values[0]
            elif fiscal_year.empty:
                fiscal_year = None

            if fiscal_year:
                self._fiscal_year = fiscal_year

            fiscal_period = df[df.iloc[:, 0] == "Document Fiscal Period Focus"]

            if not fiscal_period.empty:
                fiscal_period = fiscal_period.iloc[:, 1].values[0]
            elif fiscal_period.empty:
                fiscal_period = None

            if fiscal_period:
                self._fiscal_period = fiscal_period

            title = (
                df.columns[0][0]
                if isinstance(df.columns, MultiIndex)
                else df.columns[0]
            )

            if title and "- shares" in title:
                shares_multiplier = title.split(" shares in ")[-1]
                multiplier = self._multiplier_map(shares_multiplier)
                first_col = df.iloc[:, 0].astype(str)
                shares_outstanding = (
                    df[first_col.str.contains("Shares Outstanding", na=False)]
                    .iloc[:, 2]
                    .values[0]
                )
                as_of_date = (
                    df.columns[2][1]
                    if isinstance(df.columns, MultiIndex)
                    else df.columns[2]
                )

                if as_of_date and shares_outstanding:
                    self._shares_outstanding = {
                        to_datetime(as_of_date).strftime("%Y-%m-%d"): int(
                            shares_outstanding * multiplier
                        )
                    }

            if not df.empty:
                first_col = df.iloc[:, 0].astype(str)
                second_col = df.iloc[:, 1].fillna("").astype(str)
                trading_symbols_df = df[
                    first_col.str.lower().isin(
                        ["trading symbol", "no trading symbol flag"]
                    )
                ]
                symbols_dict: dict = {}
                trading_symbols = (
                    trading_symbols_df.iloc[:, 1]
                    .fillna("")
                    .astype(str)
                    .str.strip()
                    .str.replace("true", "No Trading Symbol")
                    .tolist()
                )
                symbol_names = second_col[
                    first_col.str.strip() == "Title of 12(b) Security"
                ].tolist()
                exchange_names = (
                    second_col[first_col.str.strip() == "Security Exchange Name"]
                    .fillna("No Exchange")
                    .tolist()
                )
                if trading_symbols:
                    self._trading_symbols = sorted(
                        [d for d in trading_symbols if d and d != "No Trading Symbol"]
                    )
                    symbols_dict = dict(zip(symbol_names, trading_symbols))
                    exchanges_dict = dict(zip(symbol_names, exchange_names))

                    for k, v in symbols_dict.items():
                        symbols_list.append(
                            {
                                "Title": k,
                                "Symbol": v,
                                "Exchange": exchanges_dict.get(k, "No Exchange"),
                            }
                        )

                df.columns = [d[1] if isinstance(d, tuple) else d for d in df.columns]
                df = df.iloc[:, :2].dropna(how="any")
                df.columns = ["key", "value"]
                output = df.set_index("key").to_dict()["value"]

                if not output.get("SIC") and self._sic:
                    output["SIC"] = self._sic
                    output["SIC Organization Name"] = self.sic_organization_name

                for k, v in output.copy().items():
                    if k in [
                        "Title of 12(b) Security",
                        "Trading Symbol",
                        "Security Exchange Name",
                        "No Trading Symbol Flag",
                    ]:
                        del output[k]

                if symbols_list:
                    output["12(b) Securities"] = symbols_list

                self._cover_page = output

        except IndexError:
            pass

        except Exception as e:
            raise RuntimeError(
                f"Failed to download and read the cover page table: {e}"
            ) from e

    def get_main_document_url(self) -> str | None:
        """URL of the primary filing document."""
        if not self._document_urls:
            return None

        for doc in self._document_urls:
            doc_type = (doc.get("type") or "").upper()
            url = doc.get("url", "")
            if doc_type in _PRIMARY_DOC_TYPES and url.endswith((".htm", ".html")):
                return url

        for doc in self._document_urls:
            url = doc.get("url", "")
            if url.endswith((".htm", ".html")) and not url.endswith("R1.htm"):
                return url

        return None

    def get_main_document_content(self) -> str | None:
        """Content of the primary filing document."""
        url = self.get_main_document_url()
        if url:
            content = self._get_document(url, False, self._use_cache)
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="ignore")
            return content
        inline = [doc for doc in self._document_urls if doc.get("content")]
        if not inline:
            return None
        primary = next(
            (d for d in inline if (d.get("type") or "").upper() in _PRIMARY_DOC_TYPES),
            inline[0],
        )
        return primary["content"]

    def get_embedded_document(self, identifier: str) -> str | None:
        """Content of the filing document matching a type identifier."""
        if not self._document_urls:
            return None
        ident = identifier.upper()
        for doc in self._document_urls:
            if (doc.get("type") or "").upper() == ident:
                url = doc.get("url", "")
                if not url:
                    continue
                content = self._get_document(url, False, self._use_cache)
                if isinstance(content, bytes):
                    content = content.decode("utf-8", errors="ignore")
                return content
        return None

    def _get_document(
        self, url: str, read_html_table: bool = False, use_cache: bool = True
    ):
        """Resolve a filing sub-document from the cached archive, else download it."""
        if not self._archive_loaded:
            self._load_archive()
        filename = url.rstrip("/").rsplit("/", 1)[-1]
        raw = self._archive.get(filename)
        if raw is None and not self._txt_loaded and not self._archive:
            self._load_txt_members()
            raw = self._archive.get(filename)
        if raw is not None:
            return self._materialize(filename, raw, read_html_table)
        result = self.download_file(url, read_html_table, use_cache)
        if (
            not read_html_table
            and isinstance(result, str)
            and filename.lower().endswith(".json")
        ):
            import json  # noqa: PLC0415

            with contextlib.suppress(ValueError):
                return json.loads(result)
        return result

    def _accession_dash(self) -> str | None:
        """Dashed accession number derived from the filing URL."""
        accession = self._url.rstrip("/").rsplit("/", 1)[-1]
        if len(accession) != 18 or not accession.isdigit():
            return None
        return f"{accession[:10]}-{accession[10:12]}-{accession[12:]}"

    def _load_archive(self):
        """Populate the member map from the filing's XBRL ZIP, once."""
        self._archive_loaded = True
        dash = self._accession_dash()
        if not dash:
            return
        self._archive.update(
            self._members_from_zip(f"{self._url}{dash}-xbrl.zip", self._use_cache)
        )

    def _load_txt_members(self):
        """Merge the complete-submission documents into the member map, once."""
        self._txt_loaded = True
        dash = self._accession_dash()
        if not dash:
            return
        self._archive.update(
            self._members_from_txt(f"{self._url}{dash}.txt", self._use_cache)
        )

    @staticmethod
    def _members_from_zip(url: str, use_cache: bool = True) -> dict:
        """Member map of filename to bytes from a filing ZIP, empty on failure."""
        from io import BytesIO  # noqa: PLC0415
        from zipfile import ZipFile  # noqa: PLC0415

        from openbb_sec.utils.cache import cached_bytes  # noqa: PLC0415
        from openbb_sec.utils.definitions import SEC_HEADERS  # noqa: PLC0415

        out: dict = {}
        try:
            raw = cached_bytes(
                url, headers=SEC_HEADERS, use_cache=use_cache, raise_for_status=True
            )
            if not raw:
                return out
            with ZipFile(BytesIO(raw)) as archive:
                for name in archive.namelist():
                    if name.endswith("/"):
                        continue
                    out[name.rsplit("/", 1)[-1]] = archive.read(name)
        except Exception:  # noqa: BLE001
            return out
        return out

    @staticmethod
    def _members_from_txt(url: str, use_cache: bool = True) -> dict:
        """Member map of filename to document text from a complete submission."""
        import re  # noqa: PLC0415

        from openbb_sec.utils.cache import cached_text  # noqa: PLC0415
        from openbb_sec.utils.definitions import SEC_HEADERS  # noqa: PLC0415

        out: dict = {}
        try:
            text = cached_text(
                url, headers=SEC_HEADERS, use_cache=use_cache, raise_for_status=True
            )
            if not text:
                return out
            for doc in re.findall(r"<DOCUMENT>(.*?)</DOCUMENT>", text, re.DOTALL):
                name_match = re.search(r"<FILENAME>(.*?)\n", doc)
                if not name_match:
                    continue
                filename = name_match.group(1).strip()
                body_match = re.search(r"<TEXT>(.*?)</TEXT>", doc, re.DOTALL)
                out[filename] = body_match.group(1) if body_match else doc
        except Exception:  # noqa: BLE001
            return out
        return out

    @staticmethod
    def _materialize(filename: str, raw, read_html_table: bool = False):
        """Convert an archive member to the type download_file would return."""
        import json  # noqa: PLC0415

        name = filename.lower()
        if name.endswith(".json"):
            data = (
                raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else raw
            )
            return json.loads(data)
        if read_html_table:
            text = (
                raw.decode("latin-1", errors="ignore")
                if isinstance(raw, bytes)
                else raw
            )
            return Filing.try_html_table(text)
        if isinstance(raw, str):
            return raw
        encoding = "latin-1" if name.endswith((".htm", ".html")) else "utf-8"
        return raw.decode(encoding, errors="ignore")

    @property
    def exhibits(self) -> LazyDict:
        """Exhibit documents keyed by type."""
        mapping: dict = {}
        for doc in self._document_urls or []:
            dtype = (doc.get("type") or "").upper()
            if dtype.startswith("EX"):
                mapping.setdefault(dtype, doc)
        labels = {k: (v.get("description") or k) for k, v in mapping.items()}
        return LazyDict(labels, lambda key: mapping[key])

    @property
    def items(self) -> LazyDict:
        """Parsed filing items keyed by item identifier."""
        items_data = self._items or {}
        labels = {
            k: (v.get("name", k) if isinstance(v, dict) else k)
            for k, v in items_data.items()
        }
        return LazyDict(labels, lambda key: items_data[key])

    @staticmethod
    def _ensure_bytes(content) -> bytes:
        """Coerce content to bytes."""
        if isinstance(content, bytes):
            return content
        if isinstance(content, bytearray):
            return bytes(content)
        if isinstance(content, str):
            return content.encode("utf-8")
        return str(content).encode("utf-8")

    def _clean_html_to_text(self, html, keep_tables: bool = False) -> str:
        """Convert filing HTML to markdown via the html2markdown module."""
        from openbb_sec.utils.filing_sections import (
            strip_markdown_footers,  # noqa: PLC0415
        )
        from openbb_sec.utils.html2markdown import html_to_markdown  # noqa: PLC0415

        if not html:
            return ""
        if isinstance(html, bytes):
            html = html.decode("utf-8", errors="ignore")
        return strip_markdown_footers(
            html_to_markdown(html, base_url=self._url, keep_tables=keep_tables)
        )

    def __repr__(self):
        """Return the string representation of the class."""
        repr_str = "SEC Filing(\n"

        for k, v in self.model_computed_fields.items():
            type_name = getattr(v.return_type, "__name__", None) or str(v.return_type)
            repr_str += f"  {k} : {type_name} - {v.description}\n"

        repr_str += ")"

        return repr_str


SecBaseFiling = Filing


_DEFAULT_FILING_SYMBOL = "AAPL"


class SecFilingFetcher(Fetcher[SecFilingQueryParams, SecFilingData]):
    """SEC Filing Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> SecFilingQueryParams:
        """Transform the query parameters."""
        return SecFilingQueryParams(**params)

    @staticmethod
    async def _default_filing_url(use_cache: bool) -> str:
        """Resolve the most recent filing URL for the default symbol."""
        from openbb_core.provider.abstract.annotated_result import AnnotatedResult

        from openbb_sec.models.company_filings import SecCompanyFilingsFetcher

        fetched = await SecCompanyFilingsFetcher().fetch_data(
            {"symbol": _DEFAULT_FILING_SYMBOL, "use_cache": use_cache, "limit": 1}, {}
        )
        filings = (
            (fetched.result or []) if isinstance(fetched, AnnotatedResult) else fetched
        )
        if not filings:
            raise OpenBBError("No filings found for the default symbol.")
        return str(filings[0].report_url)

    @staticmethod
    async def aextract_data(
        query: SecFilingQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
        """Extract the raw data from the SEC site."""
        url = query.url or await SecFilingFetcher._default_filing_url(query.use_cache)
        try:
            data = SecBaseFiling(url, query.use_cache)
        except Exception as e:
            raise OpenBBError(e) from e

        return data.model_dump(exclude_none=True)

    @staticmethod
    def transform_data(
        query: SecFilingQueryParams, data: dict, **kwargs: Any
    ) -> SecFilingData:
        """Transform the raw data into a structured format."""
        return SecFilingData.model_validate(data)
