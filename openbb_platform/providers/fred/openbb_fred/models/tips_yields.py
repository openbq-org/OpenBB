"""FRED TIPS Yields Model."""

from datetime import date as dateType
from typing import Any, Literal

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.abstract.annotated_result import AnnotatedResult
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.tips_yields import (
    TipsYieldsData,
    TipsYieldsQueryParams,
)
from openbb_core.provider.utils.descriptions import DATA_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_fred.utils.query import UseCacheQueryParams

TIME_COLUMN: dict[str, Any] = {"x-widget_config": {"chartDataType": "time"}}
CATEGORY_COLUMN: dict[str, Any] = {"x-widget_config": {"chartDataType": "category"}}
EXCLUDED_COLUMN: dict[str, Any] = {"x-widget_config": {"chartDataType": "excluded"}}
SERIES_PERCENT_COLUMN: dict[str, Any] = {
    "x-unit_measurement": "percent",
    "x-widget_config": {"cellDataType": "number", "chartDataType": "series"},
}


class FredTipsYieldsQueryParams(UseCacheQueryParams, TipsYieldsQueryParams):
    """FRED TIPS Yields Query."""

    maturity: Literal["10", "20", "30"] | None = Field(
        default=None,
        description="The maturity of the security in years - 10, 20, 30 - defaults to all."
        + " Note that the maturity is the tenor of the security, not the time to maturity.",
        json_schema_extra={"choices": ["10", "20", "30"]},
    )
    frequency: (
        Literal[
            "a",
            "q",
            "m",
            "w",
            "d",
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
        | None
    ) = Field(
        default=None,
        description="""Frequency aggregation to convert high frequency data to lower frequency.
            None = No change
            a = Annual
            q = Quarterly
            m = Monthly
            w = Weekly
            d = Daily
            wef = Weekly, Ending Friday
            weth = Weekly, Ending Thursday
            wew = Weekly, Ending Wednesday
            wetu = Weekly, Ending Tuesday
            wem = Weekly, Ending Monday
            wesu = Weekly, Ending Sunday
            wesa = Weekly, Ending Saturday
            bwew = Biweekly, Ending Wednesday
            bwem = Biweekly, Ending Monday
        """,
        json_schema_extra={
            "choices": [
                "a",
                "q",
                "m",
                "w",
                "d",
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
        },
    )
    aggregation_method: Literal["avg", "sum", "eop"] | None = Field(
        default=None,
        description="""A key that indicates the aggregation method used for frequency aggregation.
            avg = Average
            sum = Sum
            eop = End of Period
        """,
        json_schema_extra={"choices": ["avg", "sum", "eop"]},
    )
    transform: Literal["chg", "ch1", "pch", "pc1", "pca", "cch", "cca"] | None = Field(
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
        """,
        json_schema_extra={
            "choices": ["chg", "ch1", "pch", "pc1", "pca", "cch", "cca"]
        },
    )


class FredTipsYieldsData(TipsYieldsData):
    """FRED TIPS Yields Data."""

    date: dateType = Field(
        description=DATA_DESCRIPTIONS.get("date", ""),
        json_schema_extra=TIME_COLUMN,
    )
    symbol: str | None = Field(
        default=None,
        description=DATA_DESCRIPTIONS.get("symbol", ""),
        json_schema_extra=CATEGORY_COLUMN,
    )
    due: dateType | None = Field(
        default=None,
        description="The due date (maturation date) of the security.",
        json_schema_extra=EXCLUDED_COLUMN,
    )
    name: str | None = Field(
        default=None,
        description="The name of the security.",
        json_schema_extra=EXCLUDED_COLUMN,
    )
    value: float | None = Field(
        default=None,
        description="The yield value.",
        json_schema_extra=SERIES_PERCENT_COLUMN,
    )


class FredTipsYieldsFetcher(
    Fetcher[
        FredTipsYieldsQueryParams,
        list[FredTipsYieldsData],
    ]
):
    """FRED TIPS Yields Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FredTipsYieldsQueryParams:
        """Transform the query."""
        return FredTipsYieldsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FredTipsYieldsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
        """Extract the data."""
        from pandas import DataFrame, to_datetime

        from openbb_fred.models.search import FredSearchData, FredSearchFetcher
        from openbb_fred.models.series import FredSeriesFetcher
        from openbb_fred.utils.api import unwrap_series

        async def get_tips_series():
            """Get series IDs for the TIPS."""
            fetcher = FredSearchFetcher()
            found = await fetcher.fetch_data(
                params={"release_id": 72}, credentials=credentials
            )
            res = [d for d in found if isinstance(d, FredSearchData)]
            df = DataFrame([d.model_dump() for d in res])
            df = df.query("not title.str.contains('DISCONTINUED')").set_index(
                "series_id"
            )

            df["due"] = df.title.apply(lambda x: x.split("Due ")[-1].strip()).apply(
                to_datetime
            )
            df = df[["due", "observation_start", "observation_end", "title"]]
            return df.sort_values(by="due").reset_index()

        try:
            ids_df = await get_tips_series()
            ids = ids_df.series_id.to_list()
        except Exception as e:
            message = str(e) or f"FRED request failed ({type(e).__name__})."
            raise OpenBBError(message) from e

        if query.maturity:
            ids = [
                i
                for i in ids
                if i.rsplit("DTP", maxsplit=1)[-1].startswith(str(query.maturity))
            ]
        due_map = ids_df.set_index("series_id")["due"].dt.date.to_dict()
        title_map = (
            ids_df.set_index("series_id")["title"]
            .str.replace("Treasury Inflation-Indexed", "TIPS")
            .str.replace("  ", " ")
            .str.strip()
            .to_dict()
        )

        params = {
            k: v
            for k, v in {
                "symbol": ",".join(ids),
                "start_date": query.start_date,
                "end_date": query.end_date,
                "frequency": query.frequency,
                "aggregation_method": query.aggregation_method,
                "transform": query.transform,
            }.items()
            if v is not None
        }

        try:
            fetcher = FredSeriesFetcher()
            res = await fetcher.fetch_data(params=params, credentials=credentials)
            rows, meta = unwrap_series(res)
            df = DataFrame([d.model_dump() for d in rows])
        except Exception as e:
            message = str(e) or f"FRED request failed ({type(e).__name__})."
            raise OpenBBError(message) from e

        for k, v in title_map.items():
            if k in meta:
                meta[k]["title"] = v

        df = (
            df.melt(
                id_vars="date",
                value_vars=[d for d in df.columns if d != "date"],
                var_name="symbol",
            )
            .dropna()
            .sort_values(by="date")
        )
        df = df.reset_index(drop=True)
        df["due"] = df.symbol.map(due_map)
        df["name"] = df.symbol.map(title_map)
        df = df[["date", "due", "symbol", "name", "value"]]
        df = df.sort_values(by=["date", "due"])
        records = df.to_dict(orient="records")
        output = {
            "records": records,
            "meta": meta,
        }

        return output

    @staticmethod
    def transform_data(
        query: FredTipsYieldsQueryParams,
        data: dict,
        **kwargs: Any,
    ) -> AnnotatedResult[list[FredTipsYieldsData]]:
        """Transform the data."""
        results = data.get("records", [])
        meta = data.get("meta", {})
        if not results:
            raise EmptyDataError(
                "There was an error with the request and was returned empty."
            )

        return AnnotatedResult(
            result=[FredTipsYieldsData.model_validate(r) for r in results],
            metadata=meta,
        )
