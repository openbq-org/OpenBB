"""Federal Reserve Bank of Atlanta Business Inflation Expectations Model."""

from datetime import date as dateType
from typing import Any, Literal

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

URL = (
    "https://www.atlantafed.org/-/media/Project/Atlanta/FRBA/Documents"
    "/research-and-data/data/business-inflation-expectations/bie-data.xlsx"
)

_SURVEY_SHEET = "BIE Survey results"
_RESPONDENTS = "Number of Respondents"

_SURVEY_QUESTIONS: dict[str, str] = {
    "sales": "Question 1:",
    "profit": "Question 2:",
    "costs": "Question 3:",
    "projections": "Question 4:",
}

_QUARTERLY_TABLES: dict[str, tuple[str, bool]] = {
    "long_term_inflation": ("Quarterly - Long-Term Infl Exp", False),
    "price_change": ("Quarterly- Price Change", True),
    "unit_sales_levels": ("Quarterly- Unit Sales Levels", True),
    "price_factors": ("Quarterly-Price Fact (Disc)", True),
}

_QUESTION_OPTIONS = [
    {"label": "Sales Levels", "value": "sales"},
    {"label": "Profit Margins", "value": "profit"},
    {"label": "Unit Costs", "value": "costs"},
    {"label": "Projected Unit Costs", "value": "projections"},
    {"label": "Long-Term Inflation (Quarterly)", "value": "long_term_inflation"},
    {"label": "Price Change (Quarterly)", "value": "price_change"},
    {"label": "Unit Sales Levels (Quarterly)", "value": "unit_sales_levels"},
    {"label": "Price Factors (Quarterly, Discontinued)", "value": "price_factors"},
]


class FederalReserveAtlantaBusinessInflationQueryParams(QueryParams):
    """Atlanta Fed Business Inflation Expectations Query Parameters."""

    __json_schema_extra__ = {
        "question": {"x-widget_config": {"options": _QUESTION_OPTIONS}},
    }

    question: Literal[
        "sales",
        "profit",
        "costs",
        "projections",
        "long_term_inflation",
        "price_change",
        "unit_sales_levels",
        "price_factors",
    ] = Field(
        default="costs",
        description="The Business Inflation Expectations question to return. The first"
        " four are the monthly survey's questions (sales levels, profit margins, unit"
        " costs, and projected unit costs); the rest are the quarterly long-term"
        " inflation, price-change, unit-sales-levels, and projected price-factor"
        " (discontinued) questions.",
    )
    start_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("start_date", "")
    )
    end_date: dateType | None = Field(
        default=None, description=QUERY_DESCRIPTIONS.get("end_date", "")
    )


class FederalReserveAtlantaBusinessInflationData(Data):
    """Atlanta Fed Business Inflation Expectations Data."""

    date: dateType = Field(description="The survey date.")


class FederalReserveAtlantaBusinessInflationFetcher(
    Fetcher[
        FederalReserveAtlantaBusinessInflationQueryParams,
        list[FederalReserveAtlantaBusinessInflationData],
    ]
):
    """Atlanta Fed Business Inflation Expectations Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FederalReserveAtlantaBusinessInflationQueryParams:
        """Transform the query params."""
        return FederalReserveAtlantaBusinessInflationQueryParams(**params)

    @staticmethod
    def extract_data(
        query: FederalReserveAtlantaBusinessInflationQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Download the BIE workbook from the Atlanta Fed."""
        from openbb_core.provider.utils.helpers import make_request

        from openbb_federal_reserve.utils.cache import (
            cached,
            seconds_until_next_release,
        )

        def _producer() -> bytes:
            """Fetch the raw BIE workbook bytes."""
            response = make_request(URL)
            response.raise_for_status()
            return response.content

        content = cached(
            "atlanta_bie", lambda: seconds_until_next_release("monthly"), _producer
        )
        if not content:
            raise EmptyDataError("The request was returned empty.")
        return [{"_raw": content}]

    @staticmethod
    def _survey_rows(
        query: FederalReserveAtlantaBusinessInflationQueryParams,
        content: bytes,
    ) -> list[dict[str, Any]]:
        """Pivot one monthly-survey question's block to wide ``date`` rows."""
        from io import BytesIO

        from pandas import isna, read_excel, to_datetime, to_numeric

        frame = read_excel(
            BytesIO(content), engine="openpyxl", sheet_name=_SURVEY_SHEET, header=None
        )
        markers = frame.iloc[1]
        labels = frame.iloc[2]

        def _text(value: Any) -> str:
            """Return a trimmed, newline-collapsed string for a cell, else empty."""
            if value is None or (isinstance(value, float) and isna(value)):
                return ""
            return " ".join(str(value).split())

        starts = {
            _text(markers[column]).split(":")[0] + ":": column
            for column in frame.columns
            if _text(markers[column]).startswith("Question")
        }
        ordered = sorted(starts.values())
        marker = _SURVEY_QUESTIONS[query.question]
        start = starts[marker]
        bound = next((c for c in ordered if c > start), len(frame.columns))

        buckets: dict[Any, str] = {}
        for column in range(start, bound):
            label = _text(labels[column])
            if label:
                buckets[column] = label

        body = frame.iloc[3:].copy()
        body["date"] = to_datetime(body[0], errors="coerce", format="mixed")
        body = body.dropna(subset=["date"])
        body["date"] = body["date"].dt.date
        body[1] = to_numeric(body[1], errors="coerce")
        for column in buckets:
            body[column] = to_numeric(body[column], errors="coerce")
        if query.start_date:
            body = body[body["date"] >= query.start_date]
        if query.end_date:
            body = body[body["date"] <= query.end_date]

        rows: list[dict[str, Any]] = []
        for row in body.sort_values("date").to_dict(orient="records"):
            record: dict[str, Any] = {"date": row["date"]}
            count = row[1]
            record[_RESPONDENTS] = (
                None if isinstance(count, float) and isna(count) else count
            )
            for column, label in buckets.items():
                cell = row[column]
                record[label] = None if isinstance(cell, float) and isna(cell) else cell
            rows.append(record)
        return rows

    @staticmethod
    def transform_data(
        query: FederalReserveAtlantaBusinessInflationQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[FederalReserveAtlantaBusinessInflationData]:
        """Pivot the selected question to wide ``date`` + per-bucket columns."""
        from openbb_federal_reserve.utils.workbook import melt_sheet, pivot_wide

        content = data[0]["_raw"]
        if query.question in _SURVEY_QUESTIONS:
            rows = FederalReserveAtlantaBusinessInflationFetcher._survey_rows(
                query, content
            )
        else:
            sheet, group_header = _QUARTERLY_TABLES[query.question]
            records = melt_sheet(
                content,
                sheet,
                group_header=group_header,
                start_date=query.start_date,
                end_date=query.end_date,
            )
            rows = pivot_wide(records, index="date", column="series", value="value")
        return [
            FederalReserveAtlantaBusinessInflationData.model_validate(record)
            for record in rows
        ]
