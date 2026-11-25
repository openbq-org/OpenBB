"""Options Chains Standard Model."""

from datetime import (
    date as dateType,
    datetime,
)
from typing import Any, get_args, get_origin

from pydantic import (
    Field,
    GetJsonSchemaHandler,
    create_model,
    field_validator,
    model_serializer,
)
from pydantic.json_schema import JsonSchemaValue

from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import (
    DATA_DESCRIPTIONS,
    QUERY_DESCRIPTIONS,
)
from openbb_core.provider.utils.options_chains_properties import OptionsChainsProperties


class OptionsChainsQueryParams(QueryParams):
    """Options Chains Query."""

    symbol: str = Field(description=QUERY_DESCRIPTIONS.get("symbol", ""))

    @field_validator("symbol", mode="before", check_fields=False)
    @classmethod
    def to_upper(cls, v: str) -> str:
        """Return the symbol in uppercase."""
        return v.upper()


class OptionsChainsData(OptionsChainsProperties):
    """Options Chains Data.

    Note: The attached properties and methods are available only when working with an instance of this class,
    initialized with validated provider data. The items below bind to the `results` object in the function's output.

    Properties
    ----------
    dataframe: DataFrame
        Return all data as a Pandas DataFrame, with additional computed columns (Breakeven, GEX, DEX) if available.
    expirations: List[str]
        Return a list of unique expiration dates, as strings.
    strikes: List[float]
        Return a list of unique strike prices.
    has_iv: bool
        Return True if the data contains implied volatility.
    has_greeks: bool
        Return True if the data contains greeks.
    total_oi: Dict
        Return open interest stats as a nested dictionary with keys: total, expiration, strike.
        Both, "expiration" and "strike", contain a list of records with fields: Calls, Puts, Total, Net Percent, PCR.
    total_volume: Dict
        Return volume stats as a nested dictionary with keys: total, expiration, strike.
        Both, "expiration" and "strike", contain a list of records with fields: Calls, Puts, Total, Net Percent, PCR.
    total_dex: Dict
        Return Delta Dollars (DEX), if available, as a nested dictionary with keys: total, expiration, strike.
        Both, "expiration" and "strike", contain a list of records with fields: Calls, Puts, Total, Net Percent, PCR.
    total_gex: Dict
        Return Gamma Exposure (GEX), if available, as a nested dictionary with keys: total, expiration, strike.
        Both, "expiration" and "strike", contain a list of records with fields: Calls, Puts, Total, Net Percent, PCR.
    last_price: float
        Manually set the underlying price by assigning a float value to this property.
        Certain provider/symbol combinations may not return the underlying price,
        and it may be necessary, or desirable, to set it post-initialization.
        This property can be used to override the underlying price returned by the provider.
        It is not set automatically, and this property will return None if it is not set.

    Methods
    -------
    filter_data(
        date: Optional[Union[str, int]] = None,
        column: Optional[str] = None,
        option_type: Optional[Literal["call", "put"]] = None,
        moneyness: Optional[Literal["otm", "itm"]] = None,
        value_min: Optional[float] = None,
        value_max: Optional[float] = None,
        stat: Optional[Literal["open_interest", "volume", "dex", "gex"]] = None,
        by: Literal["expiration", "strike"] = "expiration",
    ) -> DataFrame:
        Return statistics by strike or expiration; or, the filtered chains data.
    skew(
        date: Optional[Union[int, str]] = None, underlying_price: Optional[float] = None)
    -> DataFrame:
        Return skewness of the options, either vertical or horizontal, by nearest DTE.
    straddle(
        days: Optional[int] = None, strike: Optional[float] = None, underlying_price: Optional[float] = None
    ) -> DataFrame:
        Calculates the cost of a straddle, by nearest DTE. Use a negative strike price for short options.
    strangle(
        days: Optional[int] = None, moneyness: Optional[float] = None, underlying_price: Optional[float] = None
    ) -> DataFrame:
        Calculates the cost of a strangle, by nearest DTE and % moneyness.
        Use a negative value for moneyness for short options.
    synthetic_long(
        days: Optional[int] = None, strike: Optional[float] = None, underlying_price: Optional[float] = None
    ) -> DataFrame:
        Calculates the cost of a synthetic long position, by nearest DTE and strike price.
    synthetic_short(
        days: Optional[int] = None, strike: Optional[float] = None, underlying_price: Optional[float] = None
    ) -> DataFrame:
        Calculates the cost of a synthetic short position, by nearest DTE and strike price.
    vertical_call(
        days: Optional[int] = None, sold: Optional[float] = None, bought: Optional[float] = None,
        underlying_price: Optional[float] = None
    ) -> DataFrame:
        Calculates the cost of a vertical call spread, by nearest DTE and strike price to sold and bought levels.
    vertical_put(
        days: Optional[int] = None, sold: Optional[float] = None, bought: Optional[float] = None,
        underlying_price: Optional[float] = None
    ) -> DataFrame:
        Calculates the cost of a vertical put spread, by nearest DTE and strike price to sold and bought levels.
    strategies(
        days: Optional[int] = None,
        straddle_strike: Optional[float] = None,
        strangle_moneyness: Optional[List[float]] = None,
        synthetic_longs: Optional[List[float]] = None,
        synthetic_shorts: Optional[List[float]] = None,
        vertical_calls: Optional[List[tuple]] = None,
        vertical_puts: Optional[List[tuple]] = None,
        underlying_price: Optional[float] = None,
    ) -> DataFrame:
        Method for combining multiple strategies and parameters in a single DataFrame.
        To get all expirations, set days to -1.

    Raises
    ------
    OpenBBError
        OpenBBError will raise when accessing properties and methods if required, specific, data was not found.
    """

    underlying_symbol: list[str | None] = Field(
        default_factory=list,
        description="Underlying symbol for the option.",
    )
    underlying_price: list[float | None] = Field(
        default_factory=list,
        description="Price of the underlying stock.",
        json_schema_extra={"x-unit_measurement": "currency"},
    )
    contract_symbol: list[str] = Field(description="Contract symbol for the option.")
    eod_date: list[dateType | None] = Field(
        default_factory=list,
        description="Date for which the options chains are returned.",
    )
    expiration: list[dateType] = Field(description="Expiration date of the contract.")
    dte: list[int | None] = Field(
        default_factory=list, description="Days to expiration of the contract."
    )
    strike: list[float] = Field(
        description="Strike price of the contract.",
        json_schema_extra={"x-unit_measurement": "currency"},
    )
    option_type: list[str] = Field(description="Call or Put.")
    contract_size: list[int | float | None] = Field(
        default_factory=list, description="Number of underlying units per contract."
    )
    open_interest: list[int | float | None] = Field(
        default_factory=list, description="Open interest on the contract."
    )
    volume: list[int | float | None] = Field(
        default_factory=list, description=DATA_DESCRIPTIONS.get("volume", "")
    )
    theoretical_price: list[float | None] = Field(
        default_factory=list,
        description="Theoretical value of the option.",
        json_schema_extra={"x-unit_measurement": "currency"},
    )
    last_trade_price: list[float | None] = Field(
        default_factory=list,
        description="Last trade price of the option.",
        json_schema_extra={"x-unit_measurement": "currency"},
    )
    last_trade_size: list[int | float | None] = Field(
        default_factory=list, description="Last trade size of the option."
    )
    last_trade_time: list[datetime | None] = Field(
        default_factory=list,
        description="The timestamp of the last trade.",
    )
    tick: list[str | None] = Field(
        default_factory=list,
        description="Whether the last tick was up or down in price.",
    )
    bid: list[float | None] = Field(
        default_factory=list,
        description="Current bid price for the option.",
        json_schema_extra={"x-unit_measurement": "currency"},
    )
    bid_size: list[int | float | None] = Field(
        default_factory=list, description="Bid size for the option."
    )
    bid_time: list[datetime | None] = Field(
        default_factory=list,
        description="The timestamp of the bid price.",
    )
    bid_exchange: list[str | None] = Field(
        default_factory=list, description="The exchange of the bid price."
    )
    ask: list[float | None] = Field(
        default_factory=list,
        description="Current ask price for the option.",
        json_schema_extra={"x-unit_measurement": "currency"},
    )
    ask_size: list[int | float | None] = Field(
        default_factory=list, description="Ask size for the option."
    )
    ask_time: list[datetime | None] = Field(
        default_factory=list,
        description="The timestamp of the ask price.",
    )
    ask_exchange: list[str | None] = Field(
        default_factory=list, description="The exchange of the ask price."
    )
    mark: list[float | None] = Field(
        default_factory=list,
        description="The mid-price between the latest bid and ask.",
        json_schema_extra={"x-unit_measurement": "currency"},
    )
    open: list[float | None] = Field(
        default_factory=list,
        description=DATA_DESCRIPTIONS.get("open", ""),
        json_schema_extra={"x-unit_measurement": "currency"},
    )
    open_bid: list[float | None] = Field(
        default_factory=list,
        description="The opening bid price for the option that day.",
        json_schema_extra={"x-unit_measurement": "currency"},
    )
    open_ask: list[float | None] = Field(
        default_factory=list,
        description="The opening ask price for the option that day.",
        json_schema_extra={"x-unit_measurement": "currency"},
    )
    high: list[float | None] = Field(
        default_factory=list,
        description=DATA_DESCRIPTIONS.get("high", ""),
        json_schema_extra={"x-unit_measurement": "currency"},
    )
    bid_high: list[float | None] = Field(
        default_factory=list,
        description="The highest bid price for the option that day.",
        json_schema_extra={"x-unit_measurement": "currency"},
    )
    ask_high: list[float | None] = Field(
        default_factory=list,
        description="The highest ask price for the option that day.",
        json_schema_extra={"x-unit_measurement": "currency"},
    )
    low: list[float | None] = Field(
        default_factory=list,
        description=DATA_DESCRIPTIONS.get("low", ""),
        json_schema_extra={"x-unit_measurement": "currency"},
    )
    bid_low: list[float | None] = Field(
        default_factory=list,
        description="The lowest bid price for the option that day.",
        json_schema_extra={"x-unit_measurement": "currency"},
    )
    ask_low: list[float | None] = Field(
        default_factory=list,
        description="The lowest ask price for the option that day.",
        json_schema_extra={"x-unit_measurement": "currency"},
    )
    close: list[float | None] = Field(
        default_factory=list,
        description=DATA_DESCRIPTIONS.get("close", ""),
        json_schema_extra={"x-unit_measurement": "currency"},
    )
    close_size: list[int | float | None] = Field(
        default_factory=list,
        description="The closing trade size for the option that day.",
    )
    close_time: list[datetime | None] = Field(
        default_factory=list,
        description="The time of the closing price for the option that day.",
    )
    close_bid: list[float | None] = Field(
        default_factory=list,
        description="The closing bid price for the option that day.",
        json_schema_extra={"x-unit_measurement": "currency"},
    )
    close_bid_size: list[int | float | None] = Field(
        default_factory=list,
        description="The closing bid size for the option that day.",
    )
    close_bid_time: list[datetime | None] = Field(
        default_factory=list,
        description="The time of the bid closing price for the option that day.",
    )
    close_ask: list[float | None] = Field(
        default_factory=list,
        description="The closing ask price for the option that day.",
    )
    close_ask_size: list[int | float | None] = Field(
        default_factory=list,
        description="The closing ask size for the option that day.",
    )
    close_ask_time: list[datetime | None] = Field(
        default_factory=list,
        description="The time of the ask closing price for the option that day.",
    )
    prev_close: list[float | None] = Field(
        default_factory=list,
        description=DATA_DESCRIPTIONS.get("prev_close", ""),
        json_schema_extra={"x-unit_measurement": "currency"},
    )
    change: list[float | None] = Field(
        default_factory=list, description="The change in the price of the option."
    )
    change_percent: list[float | None] = Field(
        default_factory=list,
        description="Change, in normalized percentage points, of the option.",
        json_schema_extra={"x-unit_measurement": "percent", "x-frontend_multiply": 100},
    )
    implied_volatility: list[float | None] = Field(
        default_factory=list,
        description="Implied volatility of the option.",
        json_schema_extra={"x-unit_measurement": "decimal"},
    )
    delta: list[float | None] = Field(
        default_factory=list,
        description="Delta of the option.",
        json_schema_extra={"x-unit_measurement": "decimal"},
    )
    gamma: list[float | None] = Field(
        default_factory=list,
        description="Gamma of the option.",
        json_schema_extra={"x-unit_measurement": "decimal"},
    )
    theta: list[float | None] = Field(
        default_factory=list,
        description="Theta of the option.",
        json_schema_extra={"x-unit_measurement": "decimal"},
    )
    vega: list[float | None] = Field(
        default_factory=list,
        description="Vega of the option.",
        json_schema_extra={"x-unit_measurement": "decimal"},
    )
    rho: list[float | None] = Field(
        default_factory=list,
        description="Rho of the option.",
        json_schema_extra={"x-unit_measurement": "decimal"},
    )

    @field_validator("expiration", mode="before", check_fields=False)
    @classmethod
    def _date_validate(cls, v):
        """Return the datetime object from the date string."""
        if isinstance(v[0], datetime):
            return [datetime.strftime(d, "%Y-%m-%d") if d else None for d in v]
        if isinstance(v[0], str):
            return [datetime.strptime(d, "%Y-%m-%d") if d else None for d in v]
        return v

    @model_serializer
    def model_serialize(self):
        """Return the serialized data."""
        data: dict = {}
        for field in type(self).model_fields:
            value = getattr(self, field)
            if isinstance(value, list):
                if value:  # Check if the list is not empty
                    if isinstance(value[0], datetime):
                        data[field] = [str(v) if v else None for v in value]
                    else:
                        data[field] = value
            else:
                data[field] = value  # pragma: no cover

        records = [dict(zip(data.keys(), values)) for values in zip(*data.values())]

        return records

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        core_schema: Any,
        handler: GetJsonSchemaHandler,
    ) -> JsonSchemaValue:
        """Return a JSON schema that matches serialized row records."""
        _ = (core_schema, handler)

        row_fields: dict[str, Any] = {}
        for field_name, field_info in cls.model_fields.items():
            annotation: Any = field_info.annotation
            inner = (
                get_args(annotation)[0]
                if get_origin(annotation) is list
                else annotation
            )

            if inner is datetime or (get_origin(inner) is None and inner is dateType):
                inner = str | None

            row_fields[field_name] = (
                (
                    inner | None
                    if get_origin(inner) is None and inner is not type(None)
                    else inner
                ),
                Field(
                    default=None,
                    description=field_info.description,
                    json_schema_extra=field_info.json_schema_extra,
                ),
            )

        row_model = create_model(f"{cls.__name__}Item", **row_fields)  # type: ignore[call-overload]
        items_schema = row_model.model_json_schema(
            ref_template="#/components/schemas/{model}",
        )
        defs = items_schema.pop("$defs", None)

        schema: JsonSchemaValue = {
            "type": "array",
            "description": (cls.__doc__ or "").split("\n\n", maxsplit=1)[0].strip(),
            "items": items_schema,
            "title": cls.__name__,
        }
        if defs:
            schema["$defs"] = defs

        return schema
