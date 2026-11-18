"""Cboe Index Constituents Model."""

from datetime import datetime
from typing import Any, Literal

from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.index_constituents import (
    IndexConstituentsData,
    IndexConstituentsQueryParams,
)
from openbb_core.provider.utils.descriptions import DATA_DESCRIPTIONS
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field, field_validator

from openbb_cboe.utils.constants import CONSTITUENT_CHOICES_ENDPOINT
from openbb_cboe.utils.helpers import CONSTITUENTS_AU, CONSTITUENTS_EU

AU_ALIASES = {
    "symbol": "Symbol",
    "name": "Constituent Name",
    "weight": "Weight",
    "close": "Closing Price",
    "currency": "Currency",
    "market": "Market",
    "region": "Region",
    "shares_outstanding": "Shares in Issue",
    "sedol": "SEDOL Code",
    "isin": "ISIN Code",
    "gics": "GICS",
    "security_state": "Security State",
    "float_ratio": "Float Ratio",
    "adjustment_factor": "Adjustment Factor",
    "exchange_rate": "Exchange Rate",
    "market_cap": "Total Market Capitalisation",
    "adjusted_market_cap": "Adjusted Market Capitalisation",
}


class CboeIndexConstituentsQueryParams(IndexConstituentsQueryParams):
    """Cboe Index Constituents Query.

    Source: https://www.cboe.com/
    """

    __json_schema_extra__ = {
        "symbol": {
            "x-widget_config": {
                "type": "endpoint",
                "optionsEndpoint": CONSTITUENT_CHOICES_ENDPOINT,
                "style": {"popupWidth": 600},
            },
        },
    }

    symbol: CONSTITUENTS_EU | CONSTITUENTS_AU = Field(
        default="BUK100P",
        description="Symbol to get data for. European indices return current-day"
        + " constituent quotes; Cboe Australia (CXA) indices return the index"
        + " composition with weights.",
    )
    session: Literal["eod", "sod"] = Field(
        default="eod",
        description="Only valid for Cboe Australia (CXA) indices."
        + " 'eod' is the last close, 'sod' is the projected next-session open.",
        json_schema_extra={"choices": ["eod", "sod"]},
    )


async def _with_company_names(rows: list[dict]) -> list[dict]:
    """Name each constituent from the Cboe Europe symbology."""
    from openbb_cboe.utils.europe import get_eu_company_names

    if not rows:
        return rows

    try:
        names = await get_eu_company_names()
    except Exception:  # noqa: BLE001
        return rows

    for row in rows:
        symbol = str(row.get("symbol") or "")
        row.setdefault("name", names.get(symbol.rsplit("-", 1)[0]))

    return rows


class CboeIndexConstituentsData(IndexConstituentsData):
    """Cboe Index Constituents Data."""

    __alias_dict__ = {
        "prev_close": "prev_day_close",
        "change": "price_change",
        "change_percent": "price_change_percent",
        "last_price": "current_price",
        "asset_type": "type",
    }

    security_type: str | None = Field(
        default=None, description="The type of security represented."
    )
    weight: float | None = Field(
        default=None,
        description="Weight of the constituent in the index, as a normalized"
        + " percentage. Only valid for Cboe Australia (CXA) indices.",
        json_schema_extra={"x-unit_measurement": "percent", "x-frontend_multiply": 100},
    )
    last_price: float | None = Field(
        default=None, description="Last price for the symbol."
    )
    open: float | None = Field(
        default=None, description=DATA_DESCRIPTIONS.get("open", "")
    )
    high: float | None = Field(
        default=None, description=DATA_DESCRIPTIONS.get("high", "")
    )
    low: float | None = Field(
        default=None, description=DATA_DESCRIPTIONS.get("low", "")
    )
    close: float | None = Field(
        default=None, description=DATA_DESCRIPTIONS.get("close", "")
    )
    volume: int | None = Field(
        default=None, description=DATA_DESCRIPTIONS.get("volume", "")
    )
    prev_close: float | None = Field(
        default=None, description=DATA_DESCRIPTIONS.get("prev_close", "")
    )
    change: float | None = Field(default=None, description="Change in price.")
    change_percent: float | None = Field(
        default=None, description="Change in price as a normalized percentage."
    )
    tick: str | None = Field(
        default=None, description="Whether the last sale was an up or down tick."
    )
    last_trade_time: datetime | None = Field(
        default=None, description="Last trade timestamp for the symbol."
    )
    asset_type: str | None = Field(
        default=None,
        description="Type of asset.",
    )
    market: str | None = Field(
        default=None, description="Market the constituent trades on."
    )
    region: str | None = Field(default=None, description="Domicile of the constituent.")
    currency: str | None = Field(
        default=None, description="Currency the constituent is priced in."
    )
    isin: str | None = Field(default=None, description="ISIN of the constituent.")
    sedol: str | None = Field(default=None, description="SEDOL of the constituent.")
    gics: str | None = Field(
        default=None, description="GICS sub-industry code of the constituent."
    )
    security_state: str | None = Field(
        default=None, description="Trading state of the constituent at capture."
    )
    shares_outstanding: float | None = Field(
        default=None, description="Shares in issue used for the index calculation."
    )
    float_ratio: float | None = Field(
        default=None, description="Free-float ratio applied to the market cap."
    )
    adjustment_factor: float | None = Field(
        default=None, description="Index adjustment factor applied to the market cap."
    )
    exchange_rate: float | None = Field(
        default=None, description="Rate used to convert into the index currency."
    )
    market_cap: float | None = Field(
        default=None, description="Total market capitalization of the constituent."
    )
    adjusted_market_cap: float | None = Field(
        default=None,
        description="Free-float adjusted market capitalization used for the weight.",
    )

    @field_validator("last_trade_time", mode="before", check_fields=False)
    @classmethod
    def date_validate(cls, v):
        """Return the datetime object from the date string."""
        return datetime.strptime(v, "%Y-%m-%dT%H:%M:%S")


class CboeIndexConstituentsFetcher(
    Fetcher[
        CboeIndexConstituentsQueryParams,
        list[CboeIndexConstituentsData],
    ]
):
    """Transform the query, extract and transform the data from the Cboe endpoints."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> CboeIndexConstituentsQueryParams:
        """Transform the query."""
        return CboeIndexConstituentsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: CboeIndexConstituentsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Return the raw data from the Cboe endpoint."""
        from typing import get_args

        from openbb_core.provider.utils.helpers import amake_request

        from openbb_cboe.utils.helpers import get_au_index_constituents

        if query.symbol in get_args(CONSTITUENTS_AU):
            return await get_au_index_constituents(query.symbol, session=query.session)

        url = (
            "https://cdn.cboe.com/api/global/european_indices/constituent_quotes/"
            + f"{query.symbol}.json"
        )
        data = await amake_request(url)
        rows = data.get("data", []) if isinstance(data, dict) else data

        return await _with_company_names(rows)

    @staticmethod
    def transform_data(
        query: CboeIndexConstituentsQueryParams, data: list[dict], **kwargs: Any
    ) -> list[CboeIndexConstituentsData]:
        """Transform the data to the standard format."""
        from typing import get_args

        from pandas import DataFrame, to_numeric

        if not data:
            raise EmptyDataError()

        df = DataFrame(data)

        if query.symbol in get_args(CONSTITUENTS_AU):
            df = df.rename(columns={v: k for k, v in AU_ALIASES.items()})
            df = df[[c for c in AU_ALIASES if c in df.columns]]

            for col in (
                "weight",
                "close",
                "shares_outstanding",
                "float_ratio",
                "adjustment_factor",
                "exchange_rate",
                "market_cap",
                "adjusted_market_cap",
            ):
                if col in df.columns:
                    df[col] = to_numeric(df[col], errors="coerce")

            # A handful of members are carried without a local ticker; the SEDOL
            # is the only identifier present and the standard model requires one.
            df["symbol"] = df["symbol"].replace("", None).fillna(df["sedol"])
            df = df.sort_values("weight", ascending=False)
        else:
            df["price_change_percent"] = df["price_change_percent"] / 100
            df = df.replace(0, None).dropna(how="all", axis=1)
            df = df.drop(columns=["exchange_id"])

        df = df.astype(object).where(df.notna(), None)

        return [
            CboeIndexConstituentsData.model_validate(d)
            for d in df.to_dict(orient="records")
        ]
