"""FRED Manufacturing Outlook - New York - Model."""

from typing import Any, Literal
from warnings import warn

from openbb_core.provider.abstract.annotated_result import AnnotatedResult
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.manufacturing_outlook_texas import (
    ManufacturingOutlookTexasData,
    ManufacturingOutlookTexasQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError, OpenBBError
from pydantic import Field, field_validator

from openbb_fred.utils.query import UseCacheQueryParams

PERCENT_COLUMN: dict[str, Any] = {"x-unit_measurement": "percent"}

NY_MANUFACTURING_OUTLOOK = {
    "current_hours_worked": {
        "sa": {
            "diffusion_index": "AWCDISA066MSFRBNY",
            "percent_reporting_increase": "AWCISA156MSFRBNY",
            "percent_reporting_decrease": "AWCDSA156MSFRBNY",
            "percent_reporting_no_change": "AWCNSA156MSFRBNY",
        },
        "not_sa": {
            "diffusion_index": "AWCDINA066MNFRBNY",
            "percent_reporting_increase": "AWCINA156MNFRBNY",
            "percent_reporting_decrease": "AWCDNA156MNFRBNY",
            "percent_reporting_no_change": "AWCNNA156MNFRBNY",
        },
    },
    "future_hours_worked": {
        "sa": {
            "diffusion_index": "AWFDISA066MSFRBNY",
            "percent_reporting_increase": "AWFISA156MSFRBNY",
            "percent_reporting_decrease": "AWFDSA156MSFRBNY",
            "percent_reporting_no_change": "AWFNSA156MSFRBNY",
        },
        "not_sa": {
            "diffusion_index": "AWFDINA066MNFRBNY",
            "percent_reporting_increase": "AWFINA156MNFRBNY",
            "percent_reporting_decrease": "AWFDNA156MNFRBNY",
            "percent_reporting_no_change": "AWFNNA156MNFRBNY",
        },
    },
    "current_business_outlook": {
        "sa": {
            "diffusion_index": "GACDISA066MSFRBNY",
            "percent_reporting_increase": "GACISA156MSFRBNY",
            "percent_reporting_decrease": "GACDSA156MSFRBNY",
            "percent_reporting_no_change": "GACNSA156MSFRBNY",
        },
        "not_sa": {
            "diffusion_index": "GACDINA066MNFRBNY",
            "percent_reporting_increase": "GACINA156MNFRBNY",
            "percent_reporting_decrease": "GACDNA156MNFRBNY",
            "percent_reporting_no_change": "GACNNA156MNFRBNY",
        },
    },
    "future_business_outlook": {
        "sa": {
            "diffusion_index": "GAFDISA066MSFRBNY",
            "percent_reporting_increase": "GAFISA156MSFRBNY",
            "percent_reporting_decrease": "GAFDSA156MSFRBNY",
            "percent_reporting_no_change": "GAFNSA156MSFRBNY",
        },
        "not_sa": {
            "diffusion_index": "GAFDINA066MNFRBNY",
            "percent_reporting_increase": "GAFINA156MNFRBNY",
            "percent_reporting_decrease": "GAFDNA156MNFRBNY",
            "percent_reporting_no_change": "GAFNNA156MNFRBNY",
        },
    },
    "current_employment": {
        "sa": {
            "diffusion_index": "NECDISA066MSFRBNY",
            "percent_reporting_increase": "NECISA156MSFRBNY",
            "percent_reporting_decrease": "NECDSA156MSFRBNY",
            "percent_reporting_no_change": "NECNSA156MSFRBNY",
        },
        "not_sa": {
            "diffusion_index": "NECDINA066MNFRBNY",
            "percent_reporting_increase": "NECINA156MNFRBNY",
            "percent_reporting_decrease": "NECDNA156MNFRBNY",
            "percent_reporting_no_change": "NECNNA156MNFRBNY",
        },
    },
    "future_employment": {
        "sa": {
            "diffusion_index": "NEFDISA066MSFRBNY",
            "percent_reporting_increase": "NEFISA156MSFRBNY",
            "percent_reporting_decrease": "NEFDSA156MSFRBNY",
            "percent_reporting_no_change": "NEFNSA156MSFRBNY",
        },
        "not_sa": {
            "diffusion_index": "NEFDINA066MNFRBNY",
            "percent_reporting_increase": "NEFINA156MNFRBNY",
            "percent_reporting_decrease": "NEFDNA156MNFRBNY",
            "percent_reporting_no_change": "NEFNNA156MNFRBNY",
        },
    },
    "current_inventories": {
        "sa": {
            "diffusion_index": "IVCDISA066MSFRBNY",
            "percent_reporting_increase": "IVCISA156MSFRBNY",
            "percent_reporting_decrease": "IVCDSA156MSFRBNY",
            "percent_reporting_no_change": "IVCNSA156MSFRBNY",
        },
        "not_sa": {
            "diffusion_index": "IVCDINA066MNFRBNY",
            "percent_reporting_increase": "IVCINA156MNFRBNY",
            "percent_reporting_decrease": "IVCDNA156MNFRBNY",
            "percent_reporting_no_change": "IVCNNA156MNFRBNY",
        },
    },
    "future_inventories": {
        "sa": {
            "diffusion_index": "IVFDISA066MSFRBNY",
            "percent_reporting_increase": "IVFISA156MSFRBNY",
            "percent_reporting_decrease": "IVFDSA156MSFRBNY",
            "percent_reporting_no_change": "IVFNSA156MSFRBNY",
        },
        "not_sa": {
            "diffusion_index": "IVFDINA066MNFRBNY",
            "percent_reporting_increase": "IVFINA156MNFRBNY",
            "percent_reporting_decrease": "IVFDNA156MNFRBNY",
            "percent_reporting_no_change": "IVFNNA156MNFRBNY",
        },
    },
    "current_prices_received": {
        "sa": {
            "diffusion_index": "PRCDISA066MSFRBNY",
            "percent_reporting_increase": "PRCISA156MSFRBNY",
            "percent_reporting_decrease": "PRCDSA156MSFRBNY",
            "percent_reporting_no_change": "PRCNSA156MSFRBNY",
        },
        "not_sa": {
            "diffusion_index": "PRCDINA066MNEMFRBNY",
            "percent_reporting_increase": "PRCINA156MNEMFRBNY",
            "percent_reporting_decrease": "PRCDNA156MNEMFRBNY",
            "percent_reporting_no_change": "PRCNNA156MNEMFRBNY",
        },
    },
    "future_prices_received": {
        "sa": {
            "diffusion_index": "PRFDISA066MSFRBNY",
            "percent_reporting_increase": "PRFISA156MSFRBNY",
            "percent_reporting_decrease": "PRFDSA156MSFRBNY",
            "percent_reporting_no_change": "PRFNSA156MSFRBNY",
        },
        "not_sa": {
            "diffusion_index": "PRFDINA066MNEMFRBNY",
            "percent_reporting_increase": "PRFINA156MNEMFRBNY",
            "percent_reporting_decrease": "PRFDNA156MNEMFRBNY",
            "percent_reporting_no_change": "PRFNNA156MNEMFRBNY",
        },
    },
    "current_prices_paid": {
        "sa": {
            "diffusion_index": "PPCDISA066MSFRBNY",
            "percent_reporting_increase": "PPCISA156MSFRBNY",
            "percent_reporting_decrease": "PPCDSA156MSFRBNY",
            "percent_reporting_no_change": "PPCNSA156MSFRBNY",
        },
        "not_sa": {
            "diffusion_index": "PPCDINA066MNEMFRBNY",
            "percent_reporting_increase": "PPCINA156MNEMFRBNY",
            "percent_reporting_decrease": "PPCDNA156MNEMFRBNY",
            "percent_reporting_no_change": "PPCNNA156MNEMFRBNY",
        },
    },
    "future_prices_paid": {
        "sa": {
            "diffusion_index": "PPFDISA066MSFRBNY",
            "percent_reporting_increase": "PPFISA156MSFRBNY",
            "percent_reporting_decrease": "PPFDSA156MSFRBNY",
            "percent_reporting_no_change": "PPFNSA156MSFRBNY",
        },
        "not_sa": {
            "diffusion_index": "PPFDINA066MNEMFRBNY",
            "percent_reporting_increase": "PPFINA156MNEMFRBNY",
            "percent_reporting_decrease": "PPFDNA156MNEMFRBNY",
            "percent_reporting_no_change": "PPFNNA156MNEMFRBNY",
        },
    },
    "future_capex": {
        "sa": {
            "diffusion_index": "CEFDISA066MSFRBNY",
            "percent_reporting_increase": "CEFISA156MSFRBNY",
            "percent_reporting_decrease": "CEFDSA156MSFRBNY",
            "percent_reporting_no_change": "CEFNSA156MSFRBNY",
        },
        "not_sa": {
            "diffusion_index": "CEFDINA066MNFRBNY",
            "percent_reporting_increase": "CEFINA156MNFRBNY",
            "percent_reporting_decrease": "CEFDNA156MNFRBNY",
            "percent_reporting_no_change": "CEFNNA156MNFRBNY",
        },
    },
    "current_unfilled_orders": {
        "sa": {
            "diffusion_index": "UOCDISA066MSFRBNY",
            "percent_reporting_increase": "UOCISA156MSFRBNY",
            "percent_reporting_decrease": "UOCDSA156MSFRBNY",
            "percent_reporting_no_change": "UOCNSA156MSFRBNY",
        },
        "not_sa": {
            "diffusion_index": "UOCDINA066MNFRBNY",
            "percent_reporting_increase": "UOCINA156MNFRBNY",
            "percent_reporting_decrease": "UOCDNA156MNFRBNY",
            "percent_reporting_no_change": "UOCNNA156MNFRBNY",
        },
    },
    "future_unfilled_orders": {
        "sa": {
            "diffusion_index": "UOFDISA066MSFRBNY",
            "percent_reporting_increase": "UOFISA156MSFRBNY",
            "percent_reporting_decrease": "UOFDSA156MSFRBNY",
            "percent_reporting_no_change": "UOFNSA156MSFRBNY",
        },
        "not_sa": {
            "diffusion_index": "UOFDINA066MNFRBNY",
            "percent_reporting_increase": "UOFINA156MNFRBNY",
            "percent_reporting_decrease": "UOFDNA156MNFRBNY",
            "percent_reporting_no_change": "UOFNNA156MNFRBNY",
        },
    },
    "current_new_orders": {
        "sa": {
            "diffusion_index": "NOCDISA066MSFRBNY",
            "percent_reporting_increase": "NOCISA156MSFRBNY",
            "percent_reporting_decrease": "NOCDSA156MSFRBNY",
            "percent_reporting_no_change": "NOCNSA156MSFRBNY",
        },
        "not_sa": {
            "diffusion_index": "NOCDINA066MNFRBNY",
            "percent_reporting_increase": "NOCINA156MNFRBNY",
            "percent_reporting_decrease": "NOCDNA156MNFRBNY",
            "percent_reporting_no_change": "NOCNNA156MNFRBNY",
        },
    },
    "future_new_orders": {
        "sa": {
            "diffusion_index": "NOFDISA066MSFRBNY",
            "percent_reporting_increase": "NOFISA156MSFRBNY",
            "percent_reporting_decrease": "NOFDSA156MSFRBNY",
            "percent_reporting_no_change": "NOFNSA156MSFRBNY",
        },
        "not_sa": {
            "diffusion_index": "NOFDINA066MNFRBNY",
            "percent_reporting_increase": "NOFINA156MNFRBNY",
            "percent_reporting_decrease": "NOFDNA156MNFRBNY",
            "percent_reporting_no_change": "NOFNNA156MNFRBNY",
        },
    },
    "current_shipments": {
        "sa": {
            "diffusion_index": "SHCDISA066MSFRBNY",
            "percent_reporting_increase": "SHCISA156MSFRBNY",
            "percent_reporting_decrease": "SHCDSA156MSFRBNY",
            "percent_reporting_no_change": "SHCNSA156MSFRBNY",
        },
        "not_sa": {
            "diffusion_index": "SHCDINA066MNFRBNY",
            "percent_reporting_increase": "SHCINA156MNFRBNY",
            "percent_reporting_decrease": "SHCDNA156MNFRBNY",
            "percent_reporting_no_change": "SHCNNA156MNFRBNY",
        },
    },
    "future_shipments": {
        "sa": {
            "diffusion_index": "SHFDISA066MSFRBNY",
            "percent_reporting_increase": "SHFISA156MSFRBNY",
            "percent_reporting_decrease": "SHFDSA156MSFRBNY",
            "percent_reporting_no_change": "SHFNSA156MSFRBNY",
        },
        "not_sa": {
            "diffusion_index": "SHFDINA066MNFRBNY",
            "percent_reporting_increase": "SHFINA156MNFRBNY",
            "percent_reporting_decrease": "SHFDNA156MNFRBNY",
            "percent_reporting_no_change": "SHFNNA156MNFRBNY",
        },
    },
    "current_delivery_times": {
        "sa": {
            "diffusion_index": "DTCDISA066MSFRBNY",
            "percent_reporting_increase": "DTCISA156MSFRBNY",
            "percent_reporting_decrease": "DTCDSA156MSFRBNY",
            "percent_reporting_no_change": "DTCNSA156MSFRBNY",
        },
        "not_sa": {
            "diffusion_index": "DTCDINA066MNFRBNY",
            "percent_reporting_increase": "DTCINA156MNFRBNY",
            "percent_reporting_decrease": "DTCDNA156MNFRBNY",
            "percent_reporting_no_change": "DTCNNA156MNFRBNY",
        },
    },
    "future_delivery_times": {
        "sa": {
            "diffusion_index": "DTFDISA066MSFRBNY",
            "percent_reporting_increase": "DTFISA156MSFRBNY",
            "percent_reporting_decrease": "DTFDSA156MSFRBNY",
            "percent_reporting_no_change": "DTFNSA156MSFRBNY",
        },
        "not_sa": {
            "diffusion_index": "DTFDINA066MNFRBNY",
            "percent_reporting_increase": "DTFINA156MNFRBNY",
            "percent_reporting_decrease": "DTFDNA156MNFRBNY",
            "percent_reporting_no_change": "DTFNNA156MNFRBNY",
        },
    },
}

ID_TO_TOPIC = {}
ID_TO_FIELD = {}
for key, value in NY_MANUFACTURING_OUTLOOK.items():
    for sub_key, sub_value in value.items():
        for sub_sub_key, sub_sub_value in sub_value.items():
            series = sub_sub_value
            topic = key
            ID_TO_TOPIC[series] = topic
            ID_TO_FIELD[series] = sub_sub_key

NY_MANUFACTURING_OUTLOOK_CHOICES = [
    "business_outlook",
    "hours_worked",
    "employment",
    "inventories",
    "prices_received",
    "prices_paid",
    "capex",
    "unfilled_orders",
    "new_orders",
    "shipments",
    "delivery_times",
]

NyManufacturingOutlookChoices = Literal[
    "business_outlook",
    "hours_worked",
    "employment",
    "inventories",
    "prices_received",
    "prices_paid",
    "capex",
    "unfilled_orders",
    "new_orders",
    "shipments",
    "delivery_times",
]


class FredManufacturingOutlookNYQueryParams(
    UseCacheQueryParams, ManufacturingOutlookTexasQueryParams
):
    """FRED Manufacturing Outlook - New York - Query Params."""

    __json_schema_extra__ = {
        "topic": {
            "multiple_items_allowed": True,
            "choices": NY_MANUFACTURING_OUTLOOK_CHOICES,
            "x-widget_config": {
                "value": "new_orders",
            },
        },
    }

    topic: NyManufacturingOutlookChoices | str = Field(
        default="new_orders",
        description="The topic for the survey response.",
    )
    seasonally_adjusted: bool = Field(
        default=False,
        description="Whether the data is seasonally adjusted, default is False",
    )
    frequency: Literal["quarter", "annual"] | None = Field(
        default=None,
        description="Frequency aggregation to convert monthly data to lower frequency. None is monthly.",
    )
    aggregation_method: Literal["avg", "sum", "eop"] | None = Field(
        default=None,
        description="""A key that indicates the aggregation method used for frequency aggregation.
        avg = Average
        sum = Sum
        eop = End of Period
        """,
    )
    transform: (
        Literal["chg", "ch1", "pch", "pc1", "pca", "cch", "cca", "log"] | None
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
        log = Natural Log
        """,
    )

    @field_validator("topic", mode="before", check_fields=False)
    @classmethod
    def validate_topic(cls, v):
        """Validate topic."""
        if v is None:
            return "new_orders"
        new_topics: list = []
        topics: list = []
        if isinstance(v, list):
            topics = v
        if isinstance(v, str):
            topics = v.split(",")
        for t in topics:
            if t in NY_MANUFACTURING_OUTLOOK_CHOICES:
                new_topics.append(t)
            else:
                warn(f"Invalid topic: {t}")
        if not new_topics:
            new_topics = ["new_orders"]

        v = ",".join(new_topics)

        return v


class FredManufacturingOutlookNYData(ManufacturingOutlookTexasData):
    """FRED Manufacturing Outlook - New York - Data."""

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


class FredManufacturingOutlookNYFetcher(
    Fetcher[
        FredManufacturingOutlookNYQueryParams,
        list[FredManufacturingOutlookNYData],
    ]
):
    """FRED Manufacturing Outlook - New York - Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> FredManufacturingOutlookNYQueryParams:
        """Transform query parameters."""
        return FredManufacturingOutlookNYQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FredManufacturingOutlookNYQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict:
        """Fetch data."""
        from openbb_fred.models.series import FredSeriesFetcher
        from openbb_fred.utils.api import unwrap_series

        ids: list = []
        topics = query.topic.split(",")
        seasonality = "sa" if query.seasonally_adjusted is True else "not_sa"
        for t in topics:
            future_series = list(
                NY_MANUFACTURING_OUTLOOK.get("future_" + t, {})
                .get(seasonality, {})
                .values()
            )
            current_series = list(
                NY_MANUFACTURING_OUTLOOK.get("current_" + t, {})
                .get(seasonality, {})
                .values()
            )
            topic_ids = future_series + current_series
            ids.extend(topic_ids)

        if not ids:
            raise OpenBBError("No valid topic selected. Please select a valid topic.")

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
            message = str(e) or f"FRED request failed ({type(e).__name__})."
            raise OpenBBError(message) from e

        rows, metadata = unwrap_series(response)

        return {
            "metadata": metadata,
            "data": [d.model_dump() for d in rows],
        }

    @staticmethod
    def transform_data(
        query: FredManufacturingOutlookNYQueryParams,
        data: dict,
        **kwargs: Any,
    ) -> AnnotatedResult[list[FredManufacturingOutlookNYData]]:
        """Transform data."""
        from numpy import nan
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
            d for d in NY_MANUFACTURING_OUTLOOK if d in df["topic"].unique()
        ]
        df = df.replace(nan, None)

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
            result=[FredManufacturingOutlookNYData.model_validate(r) for r in records],
            metadata=metadata,
        )
