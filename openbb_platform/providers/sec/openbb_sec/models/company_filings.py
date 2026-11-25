"""SEC Company Filings Model."""

from datetime import (
    date as dateType,
    datetime,
)
from typing import Any

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.company_filings import (
    CompanyFilingsData,
    CompanyFilingsQueryParams,
)
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field, field_validator

from openbb_sec.utils.definitions import FORM_LIST, HEADERS


class SecCompanyFilingsQueryParams(CompanyFilingsQueryParams):
    """SEC Company Filings Query.

    Source: https://sec.gov/
    """

    __json_schema_extra__ = {
        "symbol": {
            "x-widget_config": {
                "type": "endpoint",
                "optionsEndpoint": "/api/v1/sec/companies",
                "style": {"popupWidth": 950},
            }
        },
        "form_type": {
            "multiple_items_allowed": True,
            "choices": FORM_LIST,
            "x-widget_config": {
                "type": "text",
                "multiSelect": False,
                "multiple": True,
            },
        },
    }

    cik: str | int | None = Field(
        description="Lookup filings by Central Index Key (CIK) instead of by symbol.",
        default=None,
    )
    start_date: dateType | None = Field(
        default=None,
        description=QUERY_DESCRIPTIONS.get("start_date", ""),
    )
    end_date: dateType | None = Field(
        default=None,
        description=QUERY_DESCRIPTIONS.get("end_date", ""),
    )
    form_type: str | None = Field(
        description="SEC form type to filter by.",
        default=None,
    )
    limit: int | None = Field(
        default=None,
        description=QUERY_DESCRIPTIONS.get("limit", ""),
    )
    use_cache: bool = Field(
        description="Whether or not to use cache.  If True, cache will store for one day.",
        default=True,
    )

    @field_validator("form_type", mode="before", check_fields=False)
    @classmethod
    def validate_form_type(cls, v):
        """Normalize form_type, accepting catalog and live EDGAR form codes."""
        if not v:
            return None
        if isinstance(v, str):
            forms = v.split(",")
        elif isinstance(v, list):
            forms = v
        else:
            raise OpenBBError("Unexpected form_type value.")
        normalized = [
            form.upper() if form.upper() in FORM_LIST else form
            for form in (item.strip() for item in forms)
            if form
        ]
        return ",".join(normalized) if normalized else None


class SecCompanyFilingsData(CompanyFilingsData):
    """SEC Company Filings Data."""

    __alias_dict__ = {
        "filing_date": "filingDate",
        "accepted_date": "acceptanceDateTime",
        "filing_url": "filingDetailUrl",
        "report_url": "primaryDocumentUrl",
        "report_type": "form",
        "report_date": "reportDate",
        "primary_doc_description": "primaryDocDescription",
        "primary_doc": "primaryDocument",
        "accession_number": "accessionNumber",
        "file_number": "fileNumber",
        "film_number": "filmNumber",
        "is_inline_xbrl": "isInlineXBRL",
        "is_xbrl": "isXBRL",
        "complete_submission_url": "completeSubmissionUrl",
        "filing_detail_url": "filingDetailUrl",
    }

    report_date: dateType | None = Field(
        description="The date of the filing.",
        default=None,
    )
    report_url: str = Field(
        description="URL to the actual report.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Document",
                "pinned": "left",
                "cellDataType": "text",
                "renderFn": "cellOnClick",
                "renderFnParams": {
                    "actionType": "groupBy",
                    "groupBy": {
                        "paramName": "url",
                        "valueField": "report_url",
                    },
                },
            }
        },
    )
    act: str | int | None = Field(description="The SEC Act number.", default=None)
    items: str | float | None = Field(description="The SEC Item numbers.", default=None)
    primary_doc_description: str | None = Field(
        description="The description of the primary document.",
        default=None,
    )
    primary_doc: str | None = Field(
        description="The filename of the primary document.",
        default=None,
    )
    accession_number: str | int | None = Field(
        description="The accession number.",
        default=None,
    )
    file_number: str | int | None = Field(
        description="The file number.",
        default=None,
    )
    film_number: str | int | None = Field(
        description="The film number.",
        default=None,
    )
    is_inline_xbrl: str | int | None = Field(
        description="Whether the filing is an inline XBRL filing.",
        default=None,
    )
    is_xbrl: str | int | None = Field(
        description="Whether the filing is an XBRL filing.",
        default=None,
    )
    size: str | int | None = Field(description="The size of the filing.", default=None)
    complete_submission_url: str | None = Field(
        description="The URL to the complete filing submission.",
        default=None,
    )
    filing_detail_url: str | None = Field(
        description="The URL to the filing details.",
        default=None,
    )

    @field_validator("report_date", mode="before", check_fields=False)
    @classmethod
    def validate_report_date(cls, v: str | dateType | None):
        """Validate report_date."""
        if isinstance(v, dateType):
            return v
        v = v if v != "" else None
        return (
            datetime.strptime(v, "%Y-%m-%d").date()
            if v and isinstance(v, str)
            else None
        )


class SecCompanyFilingsFetcher(
    Fetcher[SecCompanyFilingsQueryParams, list[SecCompanyFilingsData]]
):
    """SEC Company Filings Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> SecCompanyFilingsQueryParams:
        """Transform query params."""
        return SecCompanyFilingsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: SecCompanyFilingsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Extract the data from the SEC endpoint."""
        import asyncio

        from pandas import DataFrame

        from openbb_sec.utils.cache import cached_request
        from openbb_sec.utils.helpers import symbol_map

        filings = DataFrame()

        if query.symbol and not query.cik:
            query.cik = await symbol_map(
                query.symbol.lower(), use_cache=query.use_cache
            )
            if not query.cik:
                raise OpenBBError(f"CIK not found for symbol {query.symbol}")
        if query.cik is None:
            raise OpenBBError("CIK or symbol must be provided.")

        # The leading 0s need to be inserted but are typically removed from the data to store as an integer.
        if len(query.cik) != 10:  # ty: ignore[invalid-argument-type]
            cik_: str = ""
            temp = 10 - len(query.cik)  # ty: ignore[invalid-argument-type]
            for i in range(temp):
                cik_ = cik_ + "0"
            query.cik = cik_ + str(query.cik)

        url = f"https://data.sec.gov/submissions/CIK{query.cik}.json"
        data = await cached_request(
            url, headers=HEADERS, use_cache=query.use_cache, expire=3600 * 24
        )

        # This seems to work for the data structure.
        filings = (
            DataFrame(data["filings"].get("recent"))
            if "filings" in data
            else DataFrame()
        )
        results = filings.to_dict("records")

        # If there are lots of filings, there will be custom pagination.
        if (
            (query.limit and len(filings) >= 1000)
            or query.form_type is not None
            or query.limit == 0
        ):
            urls: list = []
            new_urls = (
                DataFrame(data["filings"].get("files"))
                if "filings" in data
                else DataFrame()
            )
            for i in new_urls.index:
                new_cik: str = data["filings"]["files"][i]["name"]
                new_url: str = "https://data.sec.gov/submissions/" + new_cik
                urls.append(new_url)

            extra = await asyncio.gather(
                *[
                    cached_request(
                        new_url,
                        headers=HEADERS,
                        use_cache=query.use_cache,
                        expire=3600 * 24,
                    )
                    for new_url in urls
                ]
            )
            for result in extra:
                if result:
                    results.extend(DataFrame(result).to_dict("records"))

        return results

    @staticmethod
    def transform_data(
        query: SecCompanyFilingsQueryParams, data: list[dict], **kwargs: Any
    ) -> list[SecCompanyFilingsData]:
        """Transform the data."""
        from numpy import nan
        from openbb_core.provider.utils.helpers import run_async
        from pandas import NA, DataFrame, Index, to_datetime

        # XOM got a new CIK in July 2026, so all historical filings are under the old CIK.
        # This is special handling for the transition.
        if query.symbol == "XOM":
            query.symbol = None
            query.cik = "0000034088"
            legacy_filings = run_async(
                SecCompanyFilingsFetcher.aextract_data, query, None
            )
            data.extend(legacy_filings)

        if not data:
            raise EmptyDataError(
                f"No filings found for CIK {query.cik}, or symbol {query.symbol}"
            )
        cols = [
            "reportDate",
            "filingDate",
            "acceptanceDateTime",
            "act",
            "form",
            "items",
            "primaryDocDescription",
            "primaryDocument",
            "accessionNumber",
            "fileNumber",
            "filmNumber",
            "isInlineXBRL",
            "isXBRL",
            "size",
        ]
        filings = DataFrame(data, columns=Index(cols)).astype(str)
        filings["reportDate"] = to_datetime(filings["reportDate"]).dt.date
        filings["filingDate"] = to_datetime(filings["filingDate"]).dt.date
        filings = filings.sort_values(by=["filingDate", "reportDate"], ascending=False)
        if query.start_date:
            filings = filings[filings["filingDate"] >= query.start_date]
        if query.end_date:
            filings = filings[filings["filingDate"] <= query.end_date]
        base_url = f"https://www.sec.gov/Archives/edgar/data/{str(int(query.cik))}/"  # ty: ignore[invalid-argument-type]
        filings["primaryDocumentUrl"] = (
            base_url
            + filings["accessionNumber"].str.replace("-", "")
            + "/"
            + filings["primaryDocument"]
        )
        filings["completeSubmissionUrl"] = (
            base_url + filings["accessionNumber"] + ".txt"
        )
        filings["filingDetailUrl"] = (
            base_url + filings["accessionNumber"] + "-index.htm"
        )
        if query.form_type:
            form_types = query.form_type.replace("_", " ").split(",")
            filings = filings[
                filings.form.str.contains("|".join(form_types), case=False, na=False)
            ]
        if query.limit:
            filings = filings.head(query.limit) if query.limit != 0 else filings

        if len(filings) == 0:
            raise EmptyDataError("No filings were found using the filters provided.")
        filings = filings.replace({NA: None, nan: None})

        return [
            SecCompanyFilingsData.model_validate(d) for d in filings.to_dict("records")
        ]
