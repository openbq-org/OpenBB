"""FRED AMERIBOR Model."""

from datetime import date as dateType
from typing import Any, Literal

from openbb_core.provider.abstract.annotated_result import AnnotatedResult
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.ameribor import (
    AmeriborData,
    AmeriborQueryParams,
)
from openbb_core.provider.utils.descriptions import DATA_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_fred.models.series import FredSeriesFetcher
from openbb_fred.utils.api import unwrap_series
from openbb_fred.utils.query import UseCacheQueryParams

TIME_AXIS: dict[str, Any] = {"x-widget_config": {"chartDataType": "time"}}
CATEGORY_AXIS: dict[str, Any] = {"x-widget_config": {"chartDataType": "category"}}
PERCENT_SERIES: dict[str, Any] = {
    "x-unit_measurement": "percent",
    "x-widget_config": {"chartDataType": "series"},
}
LABEL_EXCLUDED_FROM_CHART: dict[str, Any] = {
    "x-widget_config": {"chartDataType": "excluded"}
}

MATURITY_TO_FRED_ID = {
    "all": "AMERIBOR,AMBOR30,AMBOR90,AMBOR30T,AMBOR90T",
    "overnight": "AMERIBOR",
    "average_30d": "AMBOR30",
    "average_90d": "AMBOR90",
    "term_30d": "AMBOR30T",
    "term_90d": "AMBOR90T",
}


class FredAmeriborQueryParams(UseCacheQueryParams, AmeriborQueryParams):
    """FRED AMERIBOR Query."""

    __json_schema_extra__ = {
        "maturity": {
            "multiple_items_allowed": True,
        }
    }

    maturity: (
        Literal[
            "all", "overnight", "average_30d", "average_90d", "term_30d", "term_90d"
        ]
        | str
    ) = Field(
        default="all",
        description="Period of AMERIBOR rate.",
    )
    frequency: (
        None
        | Literal[
            "a",
            "q",
            "m",
            "w",
            "wef",
            "weth",
            "wew",
            "wetu",
            "wem",
            "wesu",
            "wesa",
            "bwew",
            "bwem",
        ]
    ) = Field(
        default=None,
        description="""Frequency aggregation to convert daily data to lower frequency.
    a = Annual
    q = Quarterly
    m = Monthly
    w = Weekly
    wef = Weekly, Ending Friday
    weth = Weekly, Ending Thursday
    wew = Weekly, Ending Wednesday
    wetu = Weekly, Ending Tuesday
    wem = Weekly, Ending Monday
    wesu = Weekly, Ending Sunday
    wesa = Weekly, Ending Saturday
    bwew = Biweekly, Ending Wednesday
    bwem = Biweekly, Ending Monday""",
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
        description="""Transformation type
    None = No transformation
    chg = Change
    ch1 = Change from Year Ago
    pch = Percent Change
    pc1 = Percent Change from Year Ago
    pca = Compounded Annual Rate of Change
    cch = Continuously Compounded Rate of Change
    cca = Continuously Compounded Annual Rate of Change
    log = Natural Log""",
    )


class FredAmeriborData(AmeriborData):
    """FRED AMERIBOR Data."""

    date: dateType = Field(
        description=DATA_DESCRIPTIONS.get("date", ""),
        json_schema_extra=TIME_AXIS,
    )
    symbol: str | None = Field(
        default=None,
        description=DATA_DESCRIPTIONS.get("symbol", ""),
        json_schema_extra=CATEGORY_AXIS,
    )
    maturity: str = Field(
        description="Maturity length of the item.",
        json_schema_extra=LABEL_EXCLUDED_FROM_CHART,
    )
    rate: float = Field(
        description="Interest rate.",
        json_schema_extra=PERCENT_SERIES,
    )
    title: str | None = Field(
        default=None,
        description="Title of the series.",
        json_schema_extra=LABEL_EXCLUDED_FROM_CHART,
    )


class FredAmeriborFetcher(Fetcher[FredAmeriborQueryParams, list[FredAmeriborData]]):
    """FRED Ameribor Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FredAmeriborQueryParams:
        """Transform query."""
        return FredAmeriborQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FredAmeriborQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
        """Extract data."""
        maturities = query.maturity.split(",")

        if "all" in maturities:
            ids = MATURITY_TO_FRED_ID["all"]
        elif len(maturities) == 1:
            ids = MATURITY_TO_FRED_ID[query.maturity]
        else:
            ids = ",".join([MATURITY_TO_FRED_ID[m] for m in maturities])

        try:
            response = await FredSeriesFetcher.fetch_data(
                dict(
                    symbol=ids,
                    start_date=query.start_date,
                    end_date=query.end_date,
                    frequency=query.frequency,
                    aggregation_method=query.aggregation_method,
                    transform=query.transform,
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
        query: FredAmeriborQueryParams,
        data: dict,
        **kwargs: Any,
    ) -> AnnotatedResult[list[FredAmeriborData]]:
        """Transform data."""
        from pandas import Categorical, DataFrame

        if not data["data"]:
            raise EmptyDataError("The request was returned with no data.")
        metadata = data.get("metadata", {})
        maturity_dict = {
            "AMERIBOR": "overnight",
            "AMBOR30": "day_30",
            "AMBOR90": "day_90",
            "AMBOR30T": "day_30",
            "AMBOR90T": "day_90",
        }

        df = DataFrame(data.get("data", []))
        df = df.melt(id_vars="date", var_name="symbol", value_name="value").query(
            "value.notnull()"
        )
        df = df.rename(columns={"value": "rate"}).sort_values(by="date")
        df["rate"] = df["rate"].astype(float)

        df["maturity"] = df["symbol"].apply(lambda x: maturity_dict.get(x, x))
        df["title"] = df["symbol"].apply(lambda x: metadata.get(x, {}).get("title", x))
        maturity_categories = ["overnight", "day_30", "day_90"]
        df["maturity"] = Categorical(
            df["maturity"], categories=maturity_categories, ordered=True
        )
        df = df.sort_values(by=["date", "maturity"])
        records = df.to_dict(orient="records")

        return AnnotatedResult(
            result=[FredAmeriborData.model_validate(d) for d in records],
            metadata=metadata,
        )
