"""FRED Manufacturing Outlook - Texas - Model."""

from typing import Any, Literal
from warnings import warn

from openbb_core.provider.abstract.annotated_result import AnnotatedResult
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.manufacturing_outlook_texas import (
    ManufacturingOutlookTexasData,
    ManufacturingOutlookTexasQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field, field_validator

from openbb_fred.models.series import FredSeriesFetcher
from openbb_fred.utils.api import unwrap_series
from openbb_fred.utils.query import UseCacheQueryParams

PERCENT_COLUMN: dict[str, Any] = {"x-unit_measurement": "percent"}

TEXAS_MANUFACTURING_OUTLOOK = {
    "current_business_activity": {
        "diffusion_index": "BACTSAMFRBDAL",
        "percent_reporting_increase": "BACTISAMFRBDAL",
        "percent_reporting_decrease": "BACTDSAMFRBDAL",
        "percent_reporting_no_change": "BACTNSAMFRBDAL",
    },
    "future_business_activity": {
        "diffusion_index": "FBACTSAMFRBDAL",
        "percent_reporting_increase": "FBACTISAMFRBDAL",
        "percent_reporting_decrease": "FBACTDSAMFRBDAL",
        "percent_reporting_no_change": "FBACTNSAMFRBDAL",
    },
    "current_business_outlook": {
        "diffusion_index": "COLKSAMFRBDAL",
        "percent_reporting_increase": "COLKISAMFRBDAL",
        "percent_reporting_decrease": "COLKDSAMFRBDAL",
        "percent_reporting_no_change": "COLKNSAMFRBDAL",
    },
    "future_business_outlook": {
        "diffusion_index": "FCOLKSAMFRBDAL",
        "percent_reporting_increase": "FCOLKISAMFRBDAL",
        "percent_reporting_decrease": "FCOLKDSAMFRBDAL",
        "percent_reporting_no_change": "FCOLKNSAMFRBDAL",
    },
    "current_capex": {
        "diffusion_index": "CEXPSAMFRBDAL",
        "percent_reporting_increase": "CEXPISAMFRBDAL",
        "percent_reporting_decrease": "CEXPDSAMFRBDAL",
        "percent_reporting_no_change": "CEXPNSAMFRBDAL",
    },
    "future_capex": {
        "diffusion_index": "FCEXPSAMFRBDAL",
        "percent_reporting_increase": "FCEXPISAMFRBDAL",
        "percent_reporting_decrease": "FCEXPDSAMFRBDAL",
        "percent_reporting_no_change": "FCEXPNSAMFRBDAL",
    },
    "current_prices_paid": {
        "diffusion_index": "PRMSAMFRBDAL",
        "percent_reporting_increase": "PRMISAMFRBDAL",
        "percent_reporting_decrease": "PRMDSAMFRBDAL",
        "percent_reporting_no_change": "PRMNSAMFRBDAL",
    },
    "future_prices_paid": {
        "diffusion_index": "FPRMSAMFRBDAL",
        "percent_reporting_increase": "FPRMISAMFRBDAL",
        "percent_reporting_decrease": "FPRMDSAMFRBDAL",
        "percent_reporting_no_change": "FPRMNSAMFRBDAL",
    },
    "current_production": {
        "diffusion_index": "PRODSAMFRBDAL",
        "percent_reporting_increase": "PRODISAMFRBDAL",
        "percent_reporting_decrease": "PRODDSAMFRBDAL",
        "percent_reporting_no_change": "PRODNSAMFRBDAL",
    },
    "future_production": {
        "diffusion_index": "FPRODSAMFRBDAL",
        "percent_reporting_increase": "FPRODISAMFRBDAL",
        "percent_reporting_decrease": "FPRODDSAMFRBDAL",
        "percent_reporting_no_change": "FPRODNSAMFRBDAL",
    },
    "current_inventory": {
        "diffusion_index": "FGISAMFRBDAL",
        "percent_reporting_increase": "FGIISAMFRBDAL",
        "percent_reporting_decrease": "FGIDSAMFRBDAL",
        "percent_reporting_no_change": "FGINSAMFRBDAL",
    },
    "future_inventory": {
        "diffusion_index": "FFGISAMFRBDAL",
        "percent_reporting_increase": "FFGIISAMFRBDAL",
        "percent_reporting_decrease": "FFGIDSAMFRBDAL",
        "percent_reporting_no_change": "FFGINSAMFRBDAL",
    },
    "current_new_orders": {
        "diffusion_index": "VNWOSAMFRBDAL",
        "percent_reporting_increase": "VNWOISAMFRBDAL",
        "percent_reporting_decrease": "VNWODSAMFRBDAL",
        "percent_reporting_no_change": "VNWONSAMFRBDAL",
    },
    "future_new_orders": {
        "diffusion_index": "FVNWOSAMFRBDAL",
        "percent_reporting_increase": "FVNWOISAMFRBDAL",
        "percent_reporting_decrease": "FVNWODSAMFRBDAL",
        "percent_reporting_no_change": "FVNWONSAMFRBDAL",
    },
    "current_new_orders_growth": {
        "diffusion_index": "GROSAMFRBDAL",
        "percent_reporting_increase": "GROISAMFRBDAL",
        "percent_reporting_decrease": "GRODSAMFRBDAL",
        "percent_reporting_no_change": "GRONSAMFRBDAL",
    },
    "future_new_orders_growth": {
        "diffusion_index": "FGROSAMFRBDAL",
        "percent_reporting_increase": "FGROISAMFRBDAL",
        "percent_reporting_decrease": "FGRODSAMFRBDAL",
        "percent_reporting_no_change": "FGRONSAMFRBDAL",
    },
    "current_unfilled_orders": {
        "diffusion_index": "UFILSAMFRBDAL",
        "percent_reporting_increase": "UFILISAMFRBDAL",
        "percent_reporting_decrease": "UFILDSAMFRBDAL",
        "percent_reporting_no_change": "UFILNSAMFRBDAL",
    },
    "future_unfilled_orders": {
        "diffusion_index": "FUFILSAMFRBDAL",
        "percent_reporting_increase": "FUFILISAMFRBDAL",
        "percent_reporting_decrease": "FUFILDSAMFRBDAL",
        "percent_reporting_no_change": "FUFILNSAMFRBDAL",
    },
    "current_shipments": {
        "diffusion_index": "VSHPSAMFRBDAL",
        "percent_reporting_increase": "VSHPISAMFRBDAL",
        "percent_reporting_decrease": "VSHPDSAMFRBDAL",
        "percent_reporting_no_change": "VSHPNSAMFRBDAL",
    },
    "future_shipments": {
        "diffusion_index": "FVSHPSAMFRBDAL",
        "percent_reporting_increase": "FVSHPISAMFRBDAL",
        "percent_reporting_decrease": "FVSHPDSAMFRBDAL",
        "percent_reporting_no_change": "FVSHPNSAMFRBDAL",
    },
    "current_delivery_time": {
        "diffusion_index": "DTMSAMFRBDAL",
        "percent_reporting_increase": "DTMISAMFRBDAL",
        "percent_reporting_decrease": "DTMDSAMFRBDAL",
        "percent_reporting_no_change": "DTMNSAMFRBDAL",
    },
    "future_delivery_time": {
        "diffusion_index": "FDTMSAMFRBDAL",
        "percent_reporting_increase": "FDTMISAMFRBDAL",
        "percent_reporting_decrease": "FDTMDSAMFRBDAL",
        "percent_reporting_no_change": "FDTMNSAMFRBDAL",
    },
    "current_employment": {
        "diffusion_index": "NEMPSAMFRBDAL",
        "percent_reporting_increase": "NEMPISAMFRBDAL",
        "percent_reporting_decrease": "NEMPDSAMFRBDAL",
        "percent_reporting_no_change": "NEMPNSAMFRBDAL",
    },
    "future_employment": {
        "diffusion_index": "FNEMPSAMFRBDAL",
        "percent_reporting_increase": "FNEMPISAMFRBDAL",
        "percent_reporting_decrease": "FNEMPDSAMFRBDAL",
        "percent_reporting_no_change": "FNEMPNSAMFRBDAL",
    },
    "current_wages": {
        "diffusion_index": "WGSSAMFRBDAL",
        "percent_reporting_increase": "WGSISAMFRBDAL",
        "percent_reporting_decrease": "WGSDSAMFRBDAL",
        "percent_reporting_no_change": "WGSNSAMFRBDAL",
    },
    "future_wages": {
        "diffusion_index": "FWGSSAMFRBDAL",
        "percent_reporting_increase": "FWGSISAMFRBDAL",
        "percent_reporting_decrease": "FWGSDSAMFRBDAL",
        "percent_reporting_no_change": "FWGSNSAMFRBDAL",
    },
    "current_hours_worked": {
        "diffusion_index": "AVGWKSAMFRBDAL",
        "percent_reporting_increase": "AVGWKISAMFRBDAL",
        "percent_reporting_decrease": "AVGWKDSAMFRBDAL",
        "percent_reporting_no_change": "AVGWKNSAMFRBDAL",
    },
    "future_hours_worked": {
        "diffusion_index": "FAVGWKSAMFRBDAL",
        "percent_reporting_increase": "FAVGWKISAMFRBDAL",
        "percent_reporting_decrease": "FAVGWKDSAMFRBDAL",
        "percent_reporting_no_change": "FAVGWKNSAMFRBDAL",
    },
}

ID_TO_FIELD = {}
for t, subtopics in TEXAS_MANUFACTURING_OUTLOOK.items():
    for subtopic, code in subtopics.items():
        ID_TO_FIELD[code] = subtopic

ID_TO_TOPIC = {}
for t, subtopics in TEXAS_MANUFACTURING_OUTLOOK.items():
    for subtopic, code in subtopics.items():
        ID_TO_TOPIC[code] = t

TEXAS_MANUFACTURING_OUTLOOK_CHOICES = [
    "business_activity",
    "business_outlook",
    "capex",
    "prices_paid",
    "production",
    "inventory",
    "new_orders",
    "new_orders_growth",
    "unfilled_orders",
    "shipments",
    "delivery_time",
    "employment",
    "wages",
    "hours_worked",
]

TexasManufacturingOutlookChoices = Literal[
    "business_activity",
    "business_outlook",
    "capex",
    "prices_paid",
    "production",
    "inventory",
    "new_orders",
    "new_orders_growth",
    "unfilled_orders",
    "shipments",
    "delivery_time",
    "employment",
    "wages",
    "hours_worked",
]


class FredManufacturingOutlookTexasQueryParams(
    UseCacheQueryParams, ManufacturingOutlookTexasQueryParams
):
    """FRED Manufacturing Outlook - Texas - Query Params."""

    __json_schema_extra__ = {
        "topic": {
            "multiple_items_allowed": True,
            "choices": TEXAS_MANUFACTURING_OUTLOOK_CHOICES,
        }
    }

    topic: TexasManufacturingOutlookChoices | str = Field(
        default="new_orders_growth",
        description="The topic for the survey response.",
    )
    frequency: None | Literal["annual", "quarter"] = Field(
        default=None,
        description="""
        Frequency aggregation to convert monthly data to lower frequency. None is monthly.
        """,
        json_schema_extra={
            "choices": [
                "annual",
                "quarter",
            ]
        },
    )
    aggregation_method: None | Literal["avg", "sum", "eop"] = Field(
        default=None,
        description="""
        A key that indicates the aggregation method used for frequency aggregation.
            avg = Average
            sum = Sum
            eop = End of Period
        """,
        json_schema_extra={"choices": ["avg", "sum", "eop"]},
    )
    transform: (
        None | Literal["chg", "ch1", "pch", "pc1", "pca", "cch", "cca", "log"]
    ) = Field(
        default=None,
        description="""
        Transformation type
            None = No transformation
            chg = Change
            ch1 = Change from Year Ago
            pch = Percent Change
            pc1 = Percent Change from Year Ago
            pca = Compounded Annual Rate of Change
            cch = Continuously Compounded Rate of Change
            cca = Continuously Compounded Annual Rate of Change
            log = Natural Log
        """,
        json_schema_extra={
            "choices": ["chg", "ch1", "pch", "pc1", "pca", "cch", "cca", "log"]
        },
    )

    @field_validator("topic", mode="before", check_fields=False)
    @classmethod
    def validate_topic(cls, v):
        """Validate topic."""
        if v is None:
            return "new_orders_growth"
        new_topics: list = []
        topics: list = []
        if isinstance(v, list):
            topics = v
        if isinstance(v, str):
            topics = v.split(",")
        for topic in topics:
            if topic in TEXAS_MANUFACTURING_OUTLOOK_CHOICES:
                new_topics.append(topic)
            else:
                warn(f"Invalid topic: {topic}")
        if not new_topics:
            new_topics = ["new_orders_growth"]

        v = ",".join(new_topics)

        return v


class FredManufacturingOutlookTexasData(ManufacturingOutlookTexasData):
    """FRED Manufacturing Outlook - Texas - Data."""

    percent_reporting_increase: float | None = Field(
        default=None,
        description="Percent of respondents reporting an increase over the last month.",
        json_schema_extra=PERCENT_COLUMN,
    )
    percent_reporting_decrease: float | None = Field(
        default=None,
        description="Percent of respondents reporting a decrease over the last month.",
        json_schema_extra=PERCENT_COLUMN,
    )
    percent_reporting_no_change: float | None = Field(
        default=None,
        description="Percent of respondents reporting no change over the last month.",
        json_schema_extra=PERCENT_COLUMN,
    )


class FredManufacturingOutlookTexasFetcher(
    Fetcher[
        FredManufacturingOutlookTexasQueryParams,
        list[FredManufacturingOutlookTexasData],
    ]
):
    """FRED Manufacturing Outlook - Texas - Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FredManufacturingOutlookTexasQueryParams:
        """Transform query parameters."""
        return FredManufacturingOutlookTexasQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FredManufacturingOutlookTexasQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
        """Fetch data."""
        ids: list = []
        topics = query.topic.split(",")
        for topic in topics:
            future_series = list(
                TEXAS_MANUFACTURING_OUTLOOK["future_" + topic].values()
            )
            current_series = list(
                TEXAS_MANUFACTURING_OUTLOOK["current_" + topic].values()
            )
            topic_ids = future_series + current_series
            ids.extend(topic_ids)

        frequency = query.frequency[:1].lower() if query.frequency else None
        try:
            response = await FredSeriesFetcher.fetch_data(
                dict(
                    symbol=",".join(ids),
                    start_date=query.start_date,
                    end_date=query.end_date,
                    transform=query.transform,
                    frequency=frequency,
                    aggregation_method=query.aggregation_method,
                    use_cache=query.use_cache,
                ),
                credentials,
            )
        except Exception as e:
            raise e from e

        rows, metadata = unwrap_series(response)

        return {
            "metadata": metadata,
            "data": [d.model_dump() for d in rows],
        }

    @staticmethod
    def transform_data(
        query: FredManufacturingOutlookTexasQueryParams,
        data: dict,
        **kwargs: Any,
    ) -> AnnotatedResult[list[FredManufacturingOutlookTexasData]]:
        """Transform data."""
        from pandas import Categorical, DataFrame

        df = DataFrame(data.get("data", []))
        if df.empty:
            raise EmptyDataError(
                "The request was returned empty."
                + " You may be experiencing rate limiting from the FRED API."
                + " Please try again later and reduce the number of topics selected."
            )
        metadata = data.get("metadata", {})
        df = df.melt(id_vars="date", var_name="symbol", value_name="value").query(
            "value.notnull()"
        )
        df["topic"] = df.symbol.map(ID_TO_TOPIC)
        df["field"] = df["symbol"].map(ID_TO_FIELD)

        df = df.pivot(
            columns="field", index=["date", "topic"], values="value"
        ).reset_index()
        topic_categories = [
            d for d in TEXAS_MANUFACTURING_OUTLOOK if d in df["topic"].unique()
        ]
        df = df.fillna("N/A").replace("N/A", None)

        df["topic"] = Categorical(
            df["topic"],
            categories=topic_categories,
            ordered=True,
        )
        df = df.sort_values(["date", "topic"])

        for col in df.columns:
            if col in [
                "percent_reporting_increase",
                "percent_reporting_decrease",
                "percent_reporting_no_change",
            ]:
                df[col] = df[col].astype(float)

        records = df.to_dict(orient="records")

        return AnnotatedResult(
            result=[
                FredManufacturingOutlookTexasData.model_validate(r) for r in records
            ],
            metadata=metadata,
        )
