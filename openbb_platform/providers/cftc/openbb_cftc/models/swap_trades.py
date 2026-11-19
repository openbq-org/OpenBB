"""DTCC Public Price Dissemination Swap Trades Model."""

from collections.abc import Iterable
from datetime import (
    UTC,
    date as dateType,
    datetime,
)
from typing import Any, Literal

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.app.service.system_service import SystemService
from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field, field_validator, model_validator

api_prefix = SystemService().system_settings.api_settings.prefix

MAX_CONCURRENT_DOWNLOADS = 4

_NUMERIC_FIELDS = frozenset(
    {
        "call_amount",
        "exchange_rate",
        "fixed_rate_leg_1",
        "fixed_rate_leg_2",
        "fixed_rate_payment_frequency_period_multiplier_leg_1",
        "fixed_rate_payment_frequency_period_multiplier_leg_2",
        "floating_rate_payment_frequency_period_multiplier_leg_1",
        "floating_rate_payment_frequency_period_multiplier_leg_2",
        "floating_rate_reset_frequency_period_multiplier_leg_1",
        "floating_rate_reset_frequency_period_multiplier_leg_2",
        "index_factor",
        "notional_amount_leg_1",
        "notional_amount_leg_2",
        "notional_quantity_leg_1",
        "notional_quantity_leg_2",
        "option_premium_amount",
        "package_transaction_price",
        "package_transaction_spread",
        "price",
        "put_amount",
        "quantity_frequency_multiplier_leg_1",
        "quantity_frequency_multiplier_leg_2",
        "spread_leg_1",
        "spread_leg_2",
        "strike_price",
        "total_notional_quantity_leg_1",
        "total_notional_quantity_leg_2",
    }
)


class CftcSwapTradesQueryParams(QueryParams):
    """DTCC Public Price Dissemination Swap Trades Query Parameters."""

    __json_schema_extra__ = {
        "asset_class": {"multiple_items_allowed": False},
    }

    asset_class: Literal["rates", "forex"] = Field(
        default="rates",
        description="Asset class of the transactions. Only the two priceable classes"
        + " are offered: rates, valued against the DTCC-reported curve, and forex."
        + " Credit index prints have their own CDS Index Trades endpoint.",
    )
    start_date: dateType | None = Field(
        default=None,
        description="Start of the report-date window (UTC). Default is the end date, a"
        + " single day. Every day in the window is a separately published file, so a long"
        + " window is a proportionally larger download.",
    )
    end_date: dateType | None = Field(
        default=None,
        description="End of the report-date window (UTC). Default is the most recent date"
        + " whose file holds transactions matching the query; a file is published every"
        + " calendar day, but weekends and holidays carry almost none. Retained 366 days.",
        json_schema_extra={"x-widget_config": {"value": "$currentDate-1d"}},
    )
    currency: str | None = Field(
        default=None,
        description="Filter by the leg 1 notional currency. E.g., 'USD'.",
    )
    underlier: str | None = Field(
        default=None,
        description="Filter by UPI underlier name, matched as a case-insensitive substring."
        + " E.g., 'SOFR'.",
    )
    upi_fisn: str | None = Field(
        default=None,
        description="Filter by UPI FISN, matched as a case-insensitive substring."
        + " E.g., 'Swap OIS'.",
    )
    ticker: str | None = Field(
        default=None,
        description="Filter to the exact UPI ticker, the Unique Product Identifier the"
        + " source's TICKER report keys on. E.g., 'QZXQ4R16245X' for a SOFR OIS. The"
        + " window is answered by the source's search API, one filtered query across"
        + " the date range, cached per day.",
    )
    action_type: Literal["NEWT", "MODI", "CORR", "TERM", "EROR", "REVI"] | None = Field(
        default=None,
        description="Filter by action type. E.g., 'NEWT' for new trades.",
        json_schema_extra={
            "x-widget_config": {
                "options": [
                    {"label": label, "value": value}
                    for label, value in (
                        ("New", "NEWT"),
                        ("Modify", "MODI"),
                        ("Correct", "CORR"),
                        ("Terminate", "TERM"),
                        ("Error", "EROR"),
                        ("Revive", "REVI"),
                    )
                ]
            }
        },
    )
    cleared: bool | None = Field(
        default=None,
        description="Filter by whether the transaction is centrally cleared. True keeps"
        + " cleared and intent-to-clear trades (Cleared 'Y' or 'I'); False keeps bilateral"
        + " trades (Cleared 'N').",
    )
    trade_type: (
        Literal["spot", "forward", "basis", "cross_currency", "inflation"] | None
    ) = Field(
        default=None,
        description="Filter by trade-type family, for the rates asset class: 'spot' and"
        + " 'forward' are single-currency fixed-vs-floating swaps in a recognized curve"
        + " family, split by whether the trade has already started; 'basis' floats two"
        + " indices in the same currency against each other; 'cross_currency' floats two"
        + " different currencies; 'inflation' is a zero-coupon swap of a fixed breakeven"
        + " against a published price index. Ignored outside the rates asset class.",
        json_schema_extra={
            "x-widget_config": {
                "options": [
                    {"label": label, "value": value}
                    for label, value in (
                        ("Spot", "spot"),
                        ("Forward", "forward"),
                        ("Basis", "basis"),
                        ("Cross-Currency", "cross_currency"),
                        ("Inflation", "inflation"),
                    )
                ]
            }
        },
    )
    min_notional: float | None = Field(
        default=None,
        description="Filter out transactions with a leg 1 notional below this amount.",
    )
    max_notional: float | None = Field(
        default=None,
        description="Filter out transactions with a leg 1 notional above this amount.",
    )
    limit: int | None = Field(
        default=None,
        description="Number of transactions to return. Default is all matching.",
    )
    use_cache: bool = Field(
        default=True,
        description="Cache the daily file locally, revalidating it against the source ETag.",
    )

    @field_validator("asset_class", mode="before")
    @classmethod
    def _to_lower(cls, v):
        """Accept an asset class in any case."""
        return v.lower() if isinstance(v, str) else v


class CftcSwapTradesData(Data):
    """DTCC Public Price Dissemination Swap Trades Data."""

    __alias_dict__ = {
        "action_type": "Action type",
        "event_type": "Event type",
        "event_timestamp": "Event timestamp",
        "amendment_indicator": "Amendment indicator",
        "asset_class": "Asset Class",
        "product_name": "Product name",
        "cleared": "Cleared",
        "mandatory_clearing_indicator": "Mandatory clearing indicator",
        "execution_timestamp": "Execution Timestamp",
        "effective_date": "Effective Date",
        "expiration_date": "Expiration Date",
        "maturity_date_of_the_underlier": "Maturity date of the underlier",
        "non_standardized_term_indicator": "Non-standardized term indicator",
        "platform_identifier": "Platform identifier",
        "prime_brokerage_transaction_indicator": "Prime brokerage transaction indicator",
        "block_trade_election_indicator": "Block trade election indicator",
        "large_notional_off_facility_swap_election_indicator": "Large notional off-facility swap election indicator",
        "notional_amount_leg_1": "Notional amount-Leg 1",
        "notional_amount_leg_2": "Notional amount-Leg 2",
        "notional_currency_leg_1": "Notional currency-Leg 1",
        "notional_currency_leg_2": "Notional currency-Leg 2",
        "notional_quantity_leg_1": "Notional quantity-Leg 1",
        "notional_quantity_leg_2": "Notional quantity-Leg 2",
        "total_notional_quantity_leg_1": "Total notional quantity-Leg 1",
        "total_notional_quantity_leg_2": "Total notional quantity-Leg 2",
        "quantity_frequency_multiplier_leg_1": "Quantity frequency multiplier-Leg 1",
        "quantity_frequency_multiplier_leg_2": "Quantity frequency multiplier-Leg 2",
        "quantity_unit_of_measure_leg_1": "Quantity unit of measure-Leg 1",
        "quantity_unit_of_measure_leg_2": "Quantity unit of measure-Leg 2",
        "quantity_frequency_leg_1": "Quantity frequency-Leg 1",
        "quantity_frequency_leg_2": "Quantity frequency-Leg 2",
        "notional_amount_in_effect_on_associated_effective_date_leg_1": "Notional amount in effect on associated effective date-Leg 1",
        "notional_amount_in_effect_on_associated_effective_date_leg_2": "Notional amount in effect on associated effective date-Leg 2",
        "effective_date_of_the_notional_amount_leg_1": "Effective date of the notional amount-Leg 1",
        "effective_date_of_the_notional_amount_leg_2": "Effective date of the notional amount-Leg 2",
        "end_date_of_the_notional_amount_leg_1": "End date of the notional amount-Leg 1",
        "end_date_of_the_notional_amount_leg_2": "End date of the notional amount-Leg 2",
        "call_amount": "Call amount",
        "call_currency": "Call currency",
        "put_amount": "Put amount",
        "put_currency": "Put currency",
        "exchange_rate": "Exchange rate",
        "exchange_rate_basis": "Exchange rate basis",
        "first_exercise_date": "First exercise date",
        "fixed_rate_leg_1": "Fixed rate-Leg 1",
        "fixed_rate_leg_2": "Fixed rate-Leg 2",
        "option_premium_amount": "Option Premium Amount",
        "option_premium_currency": "Option Premium Currency",
        "price": "Price",
        "price_unit_of_measure": "Price unit of measure",
        "spread_leg_1": "Spread-Leg 1",
        "spread_leg_2": "Spread-Leg 2",
        "spread_currency_leg_1": "Spread currency-Leg 1",
        "spread_currency_leg_2": "Spread currency-Leg 2",
        "strike_price": "Strike Price",
        "strike_price_currency_currency_pair": "Strike price currency/currency pair",
        "post_priced_swap_indicator": "Post-priced swap indicator",
        "price_currency": "Price currency",
        "price_notation": "Price notation",
        "spread_notation_leg_1": "Spread notation-Leg 1",
        "spread_notation_leg_2": "Spread notation-Leg 2",
        "strike_price_notation": "Strike price notation",
        "fixed_rate_day_count_convention_leg_1": "Fixed rate day count convention-leg 1",
        "fixed_rate_day_count_convention_leg_2": "Fixed rate day count convention-leg 2",
        "floating_rate_day_count_convention_leg_1": "Floating rate day count convention-leg 1",
        "floating_rate_day_count_convention_leg_2": "Floating rate day count convention-leg 2",
        "floating_rate_reset_frequency_period_leg_1": "Floating rate reset frequency period-leg 1",
        "floating_rate_reset_frequency_period_leg_2": "Floating rate reset frequency period-leg 2",
        "floating_rate_reset_frequency_period_multiplier_leg_1": "Floating rate reset frequency period multiplier-leg 1",
        "floating_rate_reset_frequency_period_multiplier_leg_2": "Floating rate reset frequency period multiplier-leg 2",
        "other_payment_amount": "Other payment amount",
        "fixed_rate_payment_frequency_period_leg_1": "Fixed rate payment frequency period-Leg 1",
        "floating_rate_payment_frequency_period_leg_1": "Floating rate payment frequency period-Leg 1",
        "fixed_rate_payment_frequency_period_leg_2": "Fixed rate payment frequency period-Leg 2",
        "floating_rate_payment_frequency_period_leg_2": "Floating rate payment frequency period-Leg 2",
        "fixed_rate_payment_frequency_period_multiplier_leg_1": "Fixed rate payment frequency period multiplier-Leg 1",
        "floating_rate_payment_frequency_period_multiplier_leg_1": "Floating rate payment frequency period multiplier-Leg 1",
        "fixed_rate_payment_frequency_period_multiplier_leg_2": "Fixed rate payment frequency period multiplier-Leg 2",
        "floating_rate_payment_frequency_period_multiplier_leg_2": "Floating rate payment frequency period multiplier-Leg 2",
        "other_payment_type": "Other payment type",
        "other_payment_currency": "Other payment currency",
        "settlement_currency_leg_1": "Settlement currency-Leg 1",
        "settlement_currency_leg_2": "Settlement currency-Leg 2",
        "settlement_location": "Settlement location",
        "collateralisation_category": "Collateralisation category",
        "custom_basket_indicator": "Custom basket indicator",
        "index_factor": "Index factor",
        "underlier_id_leg_1": "Underlier ID-Leg 1",
        "underlier_id_leg_2": "Underlier ID-Leg 2",
        "underlier_id_source_leg_1": "Underlier ID source-Leg 1",
        "underlying_asset_name": "Underlying Asset Name",
        "underlying_asset_subtype_or_underlying_contract_subtype_leg_1": "Underlying asset subtype or underlying contract subtype-Leg 1",
        "underlying_asset_subtype_or_underlying_contract_subtype_leg_2": "Underlying asset subtype or underlying contract subtype-Leg 2",
        "embedded_option_type": "Embedded Option type",
        "option_type": "Option Type",
        "option_style": "Option Style",
        "package_indicator": "Package indicator",
        "package_transaction_price": "Package transaction price",
        "package_transaction_price_currency": "Package transaction price currency",
        "package_transaction_price_notation": "Package transaction price notation",
        "package_transaction_spread": "Package transaction spread",
        "package_transaction_spread_currency": "Package transaction spread currency",
        "package_transaction_spread_notation": "Package transaction spread notation",
        "physical_delivery_location_leg_1": "Physical delivery location-Leg 1",
        "delivery_type": "Delivery Type",
        "unique_product_identifier": "Unique Product Identifier",
        "upi_fisn": "UPI FISN",
        "upi_underlier_name": "UPI Underlier Name",
    }

    trade_key: str | None = Field(
        default=None,
        description="Asset-class-qualified dissemination identifier, e.g."
        + " 'IR:4402189634000000101'. The qualifier keeps the 19-digit identifier out of"
        + " IEEE-754 double range, which truncates it past its 16th digit.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Trade",
                "cellDataType": "text",
                "formatterFn": "none",
                "renderFn": "cellOnClick",
                "renderFnParams": {
                    "actionType": "groupBy",
                    "groupBy": {
                        "paramName": "dissemination_identifier",
                        "valueField": "trade_key",
                    },
                },
            }
        },
    )
    action_type: str | None = Field(
        default=None,
        description="Action performed on the transaction: NEWT, MODI, CORR, TERM, EROR, or REVI.",
        json_schema_extra={"x-widget_config": {"headerName": "Action type"}},
    )
    event_type: str | None = Field(
        default=None,
        description="Event giving rise to the report: TRAD, COMP, ETRM, NOVA, EXER, or CLRG.",
        json_schema_extra={"x-widget_config": {"headerName": "Event type"}},
    )
    event_timestamp: datetime | None = Field(
        default=None,
        description="Event timestamp.",
        json_schema_extra={"x-widget_config": {"headerName": "Event timestamp"}},
    )
    amendment_indicator: bool | None = Field(
        default=None,
        description="Amendment indicator.",
        json_schema_extra={"x-widget_config": {"headerName": "Amendment indicator"}},
    )
    asset_class: str | None = Field(
        default=None,
        description="Asset class of the transaction.",
        json_schema_extra={"x-widget_config": {"headerName": "Asset Class"}},
    )
    product_name: str | None = Field(
        default=None,
        description="Product name. Superseded by the UPI fields and no longer populated.",
        json_schema_extra={"x-widget_config": {"headerName": "Product name"}},
    )
    cleared: str | None = Field(
        default=None,
        description="Clearing status: Y (cleared), N (not cleared), or I (intent to clear).",
        json_schema_extra={"x-widget_config": {"headerName": "Cleared"}},
    )
    mandatory_clearing_indicator: bool | None = Field(
        default=None,
        description="Mandatory clearing indicator.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Mandatory clearing indicator"}
        },
    )
    execution_timestamp: datetime | None = Field(
        default=None,
        description="Execution Timestamp.",
        json_schema_extra={"x-widget_config": {"headerName": "Execution Timestamp"}},
    )
    effective_date: dateType | None = Field(
        default=None,
        description="Effective Date.",
        json_schema_extra={"x-widget_config": {"headerName": "Effective Date"}},
    )
    expiration_date: dateType | None = Field(
        default=None,
        description="Expiration Date.",
        json_schema_extra={"x-widget_config": {"headerName": "Expiration Date"}},
    )
    maturity_date_of_the_underlier: dateType | None = Field(
        default=None,
        description="Maturity date of the underlier.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Maturity date of the underlier"}
        },
    )
    non_standardized_term_indicator: bool | None = Field(
        default=None,
        description="Non standardized term indicator.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Non - standardized term indicator"}
        },
    )
    platform_identifier: str | None = Field(
        default=None,
        description="MIC of the execution venue.",
        json_schema_extra={"x-widget_config": {"headerName": "Platform identifier"}},
    )
    prime_brokerage_transaction_indicator: bool | None = Field(
        default=None,
        description="Prime brokerage transaction indicator.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Prime brokerage transaction indicator"}
        },
    )
    block_trade_election_indicator: bool | None = Field(
        default=None,
        description="Block trade election indicator.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Block trade election indicator"}
        },
    )
    large_notional_off_facility_swap_election_indicator: bool | None = Field(
        default=None,
        description="Large notional off facility swap election indicator.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Large notional off - facility swap election indicator"
            }
        },
    )
    notional_amount_leg_1: float | None = Field(
        default=None,
        description="Notional amount of leg 1. Values above the cap are disseminated at the cap.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Notional amount - Leg 1"}
        },
    )
    notional_amount_leg_2: float | None = Field(
        default=None,
        description="Notional amount of leg 2. Values above the cap are disseminated at the cap.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Notional amount - Leg 2"}
        },
    )
    notional_currency_leg_1: str | None = Field(
        default=None,
        description="Notional currency Leg 1.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Notional currency - Leg 1"}
        },
    )
    notional_currency_leg_2: str | None = Field(
        default=None,
        description="Notional currency Leg 2.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Notional currency - Leg 2"}
        },
    )
    notional_quantity_leg_1: float | None = Field(
        default=None,
        description="Notional quantity Leg 1.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Notional quantity - Leg 1"}
        },
    )
    notional_quantity_leg_2: float | None = Field(
        default=None,
        description="Notional quantity Leg 2.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Notional quantity - Leg 2"}
        },
    )
    total_notional_quantity_leg_1: float | None = Field(
        default=None,
        description="Total notional quantity Leg 1.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Total notional quantity - Leg 1"}
        },
    )
    total_notional_quantity_leg_2: float | None = Field(
        default=None,
        description="Total notional quantity Leg 2.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Total notional quantity - Leg 2"}
        },
    )
    quantity_frequency_multiplier_leg_1: float | None = Field(
        default=None,
        description="Quantity frequency multiplier Leg 1.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Quantity frequency multiplier - Leg 1"}
        },
    )
    quantity_frequency_multiplier_leg_2: float | None = Field(
        default=None,
        description="Quantity frequency multiplier Leg 2.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Quantity frequency multiplier - Leg 2"}
        },
    )
    quantity_unit_of_measure_leg_1: str | None = Field(
        default=None,
        description="Quantity unit of measure Leg 1.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Quantity unit of measure - Leg 1"}
        },
    )
    quantity_unit_of_measure_leg_2: str | None = Field(
        default=None,
        description="Quantity unit of measure Leg 2.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Quantity unit of measure - Leg 2"}
        },
    )
    quantity_frequency_leg_1: str | None = Field(
        default=None,
        description="Quantity frequency Leg 1.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Quantity frequency - Leg 1"}
        },
    )
    quantity_frequency_leg_2: str | None = Field(
        default=None,
        description="Quantity frequency Leg 2.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Quantity frequency - Leg 2"}
        },
    )
    notional_amount_in_effect_on_associated_effective_date_leg_1: str | None = Field(
        default=None,
        description="Notional amount in effect on associated effective date Leg 1.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Notional amount in effect on associated effective date - Leg 1"
            }
        },
    )
    notional_amount_in_effect_on_associated_effective_date_leg_2: str | None = Field(
        default=None,
        description="Notional amount in effect on associated effective date Leg 2.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Notional amount in effect on associated effective date - Leg 2"
            }
        },
    )
    effective_date_of_the_notional_amount_leg_1: str | None = Field(
        default=None,
        description="Effective date of the notional amount Leg 1.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Effective date of the notional amount - Leg 1"
            }
        },
    )
    effective_date_of_the_notional_amount_leg_2: str | None = Field(
        default=None,
        description="Effective date of the notional amount Leg 2.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Effective date of the notional amount - Leg 2"
            }
        },
    )
    end_date_of_the_notional_amount_leg_1: str | None = Field(
        default=None,
        description="End date of the notional amount Leg 1.",
        json_schema_extra={
            "x-widget_config": {"headerName": "End date of the notional amount - Leg 1"}
        },
    )
    end_date_of_the_notional_amount_leg_2: str | None = Field(
        default=None,
        description="End date of the notional amount Leg 2.",
        json_schema_extra={
            "x-widget_config": {"headerName": "End date of the notional amount - Leg 2"}
        },
    )
    call_amount: float | None = Field(
        default=None,
        description="Call amount.",
        json_schema_extra={"x-widget_config": {"headerName": "Call amount"}},
    )
    call_currency: str | None = Field(
        default=None,
        description="Call currency.",
        json_schema_extra={"x-widget_config": {"headerName": "Call currency"}},
    )
    put_amount: float | None = Field(
        default=None,
        description="Put amount.",
        json_schema_extra={"x-widget_config": {"headerName": "Put amount"}},
    )
    put_currency: str | None = Field(
        default=None,
        description="Put currency.",
        json_schema_extra={"x-widget_config": {"headerName": "Put currency"}},
    )
    exchange_rate: float | None = Field(
        default=None,
        description="Exchange rate.",
        json_schema_extra={"x-widget_config": {"headerName": "Exchange rate"}},
    )
    exchange_rate_basis: str | None = Field(
        default=None,
        description="Exchange rate basis.",
        json_schema_extra={"x-widget_config": {"headerName": "Exchange rate basis"}},
    )
    first_exercise_date: dateType | None = Field(
        default=None,
        description="First exercise date.",
        json_schema_extra={"x-widget_config": {"headerName": "First exercise date"}},
    )
    fixed_rate_leg_1: float | None = Field(
        default=None,
        description="Fixed rate of leg 1, expressed as a decimal.",
        json_schema_extra={"x-widget_config": {"headerName": "Fixed rate - Leg 1"}},
    )
    fixed_rate_leg_2: float | None = Field(
        default=None,
        description="Fixed rate of leg 2, expressed as a decimal.",
        json_schema_extra={"x-widget_config": {"headerName": "Fixed rate - Leg 2"}},
    )
    option_premium_amount: float | None = Field(
        default=None,
        description="Option Premium Amount.",
        json_schema_extra={"x-widget_config": {"headerName": "Option Premium Amount"}},
    )
    option_premium_currency: str | None = Field(
        default=None,
        description="Option Premium Currency.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Option Premium Currency"}
        },
    )
    price: float | None = Field(
        default=None,
        description="Price.",
        json_schema_extra={"x-widget_config": {"headerName": "Price"}},
    )
    price_unit_of_measure: str | None = Field(
        default=None,
        description="Price unit of measure.",
        json_schema_extra={"x-widget_config": {"headerName": "Price unit of measure"}},
    )
    spread_leg_1: float | None = Field(
        default=None,
        description="Spread Leg 1.",
        json_schema_extra={"x-widget_config": {"headerName": "Spread - Leg 1"}},
    )
    spread_leg_2: float | None = Field(
        default=None,
        description="Spread Leg 2.",
        json_schema_extra={"x-widget_config": {"headerName": "Spread - Leg 2"}},
    )
    spread_currency_leg_1: str | None = Field(
        default=None,
        description="Spread currency Leg 1.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Spread currency - Leg 1"}
        },
    )
    spread_currency_leg_2: str | None = Field(
        default=None,
        description="Spread currency Leg 2.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Spread currency - Leg 2"}
        },
    )
    strike_price: float | None = Field(
        default=None,
        description="Strike Price.",
        json_schema_extra={"x-widget_config": {"headerName": "Strike Price"}},
    )
    strike_price_currency_currency_pair: str | None = Field(
        default=None,
        description="Strike price currency/currency pair.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Strike price currency/currency pair"}
        },
    )
    post_priced_swap_indicator: bool | None = Field(
        default=None,
        description="Post priced swap indicator.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Post - priced swap indicator"}
        },
    )
    price_currency: str | None = Field(
        default=None,
        description="Price currency.",
        json_schema_extra={"x-widget_config": {"headerName": "Price currency"}},
    )
    price_notation: str | None = Field(
        default=None,
        description="Price notation.",
        json_schema_extra={"x-widget_config": {"headerName": "Price notation"}},
    )
    spread_notation_leg_1: str | None = Field(
        default=None,
        description="Spread notation Leg 1.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Spread notation - Leg 1"}
        },
    )
    spread_notation_leg_2: str | None = Field(
        default=None,
        description="Spread notation Leg 2.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Spread notation - Leg 2"}
        },
    )
    strike_price_notation: str | None = Field(
        default=None,
        description="Strike price notation.",
        json_schema_extra={"x-widget_config": {"headerName": "Strike price notation"}},
    )
    fixed_rate_day_count_convention_leg_1: str | None = Field(
        default=None,
        description="ISO 20022 day count code for the leg 1 fixed rate.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Fixed rate day count convention - leg 1"}
        },
    )
    fixed_rate_day_count_convention_leg_2: str | None = Field(
        default=None,
        description="ISO 20022 day count code for the leg 2 fixed rate.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Fixed rate day count convention - leg 2"}
        },
    )
    floating_rate_day_count_convention_leg_1: str | None = Field(
        default=None,
        description="ISO 20022 day count code for the leg 1 floating rate.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Floating rate day count convention - leg 1"
            }
        },
    )
    floating_rate_day_count_convention_leg_2: str | None = Field(
        default=None,
        description="ISO 20022 day count code for the leg 2 floating rate.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Floating rate day count convention - leg 2"
            }
        },
    )
    floating_rate_reset_frequency_period_leg_1: str | None = Field(
        default=None,
        description="Floating rate reset frequency period leg 1.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Floating rate reset frequency period - leg 1"
            }
        },
    )
    floating_rate_reset_frequency_period_leg_2: str | None = Field(
        default=None,
        description="Floating rate reset frequency period leg 2.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Floating rate reset frequency period - leg 2"
            }
        },
    )
    floating_rate_reset_frequency_period_multiplier_leg_1: float | None = Field(
        default=None,
        description="Floating rate reset frequency period multiplier leg 1.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Floating rate reset frequency period multiplier - leg 1"
            }
        },
    )
    floating_rate_reset_frequency_period_multiplier_leg_2: float | None = Field(
        default=None,
        description="Floating rate reset frequency period multiplier leg 2.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Floating rate reset frequency period multiplier - leg 2"
            }
        },
    )
    other_payment_amount: str | None = Field(
        default=None,
        description="Other payment amount.",
        json_schema_extra={"x-widget_config": {"headerName": "Other payment amount"}},
    )
    fixed_rate_payment_frequency_period_leg_1: str | None = Field(
        default=None,
        description="Fixed rate payment frequency period Leg 1.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Fixed rate payment frequency period - Leg 1"
            }
        },
    )
    floating_rate_payment_frequency_period_leg_1: str | None = Field(
        default=None,
        description="Floating rate payment frequency period Leg 1.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Floating rate payment frequency period - Leg 1"
            }
        },
    )
    fixed_rate_payment_frequency_period_leg_2: str | None = Field(
        default=None,
        description="Fixed rate payment frequency period Leg 2.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Fixed rate payment frequency period - Leg 2"
            }
        },
    )
    floating_rate_payment_frequency_period_leg_2: str | None = Field(
        default=None,
        description="Floating rate payment frequency period Leg 2.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Floating rate payment frequency period - Leg 2"
            }
        },
    )
    fixed_rate_payment_frequency_period_multiplier_leg_1: float | None = Field(
        default=None,
        description="Fixed rate payment frequency period multiplier Leg 1.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Fixed rate payment frequency period multiplier - Leg 1"
            }
        },
    )
    floating_rate_payment_frequency_period_multiplier_leg_1: float | None = Field(
        default=None,
        description="Floating rate payment frequency period multiplier Leg 1.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Floating rate payment frequency period multiplier - Leg 1"
            }
        },
    )
    fixed_rate_payment_frequency_period_multiplier_leg_2: float | None = Field(
        default=None,
        description="Fixed rate payment frequency period multiplier Leg 2.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Fixed rate payment frequency period multiplier - Leg 2"
            }
        },
    )
    floating_rate_payment_frequency_period_multiplier_leg_2: float | None = Field(
        default=None,
        description="Floating rate payment frequency period multiplier Leg 2.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Floating rate payment frequency period multiplier - Leg 2"
            }
        },
    )
    other_payment_type: str | None = Field(
        default=None,
        description="Other payment type.",
        json_schema_extra={"x-widget_config": {"headerName": "Other payment type"}},
    )
    other_payment_currency: str | None = Field(
        default=None,
        description="Other payment currency.",
        json_schema_extra={"x-widget_config": {"headerName": "Other payment currency"}},
    )
    settlement_currency_leg_1: str | None = Field(
        default=None,
        description="Settlement currency Leg 1.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Settlement currency - Leg 1"}
        },
    )
    settlement_currency_leg_2: str | None = Field(
        default=None,
        description="Settlement currency Leg 2.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Settlement currency - Leg 2"}
        },
    )
    settlement_location: str | None = Field(
        default=None,
        description="Settlement location.",
        json_schema_extra={"x-widget_config": {"headerName": "Settlement location"}},
    )
    collateralisation_category: str | None = Field(
        default=None,
        description="Collateralisation category.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Collateralisation category"}
        },
    )
    custom_basket_indicator: bool | None = Field(
        default=None,
        description="Custom basket indicator.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Custom basket indicator"}
        },
    )
    index_factor: float | None = Field(
        default=None,
        description="Index factor.",
        json_schema_extra={"x-widget_config": {"headerName": "Index factor"}},
    )
    underlier_id_leg_1: str | None = Field(
        default=None,
        description="Underlier ID Leg 1.",
        json_schema_extra={"x-widget_config": {"headerName": "Underlier ID - Leg 1"}},
    )
    underlier_id_leg_2: str | None = Field(
        default=None,
        description="Underlier ID Leg 2.",
        json_schema_extra={"x-widget_config": {"headerName": "Underlier ID - Leg 2"}},
    )
    underlier_id_source_leg_1: str | None = Field(
        default=None,
        description="Underlier ID source Leg 1.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Underlier ID source - Leg 1"}
        },
    )
    underlying_asset_name: str | None = Field(
        default=None,
        description="Underlying Asset Name.",
        json_schema_extra={"x-widget_config": {"headerName": "Underlying Asset Name"}},
    )
    underlying_asset_subtype_or_underlying_contract_subtype_leg_1: str | None = Field(
        default=None,
        description="Underlying asset subtype or underlying contract subtype Leg 1.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Underlying asset subtype or underlying contract subtype - Leg 1"
            }
        },
    )
    underlying_asset_subtype_or_underlying_contract_subtype_leg_2: str | None = Field(
        default=None,
        description="Underlying asset subtype or underlying contract subtype Leg 2.",
        json_schema_extra={
            "x-widget_config": {
                "headerName": "Underlying asset subtype or underlying contract subtype - Leg 2"
            }
        },
    )
    embedded_option_type: str | None = Field(
        default=None,
        description="Embedded Option type.",
        json_schema_extra={"x-widget_config": {"headerName": "Embedded Option type"}},
    )
    option_type: str | None = Field(
        default=None,
        description="Option Type.",
        json_schema_extra={"x-widget_config": {"headerName": "Option Type"}},
    )
    option_style: str | None = Field(
        default=None,
        description="Option Style.",
        json_schema_extra={"x-widget_config": {"headerName": "Option Style"}},
    )
    package_indicator: bool | None = Field(
        default=None,
        description="Package indicator.",
        json_schema_extra={"x-widget_config": {"headerName": "Package indicator"}},
    )
    package_transaction_price: float | None = Field(
        default=None,
        description="Package transaction price.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Package transaction price"}
        },
    )
    package_transaction_price_currency: str | None = Field(
        default=None,
        description="Package transaction price currency.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Package transaction price currency"}
        },
    )
    package_transaction_price_notation: str | None = Field(
        default=None,
        description="Package transaction price notation.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Package transaction price notation"}
        },
    )
    package_transaction_spread: float | None = Field(
        default=None,
        description="Package transaction spread.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Package transaction spread"}
        },
    )
    package_transaction_spread_currency: str | None = Field(
        default=None,
        description="Package transaction spread currency.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Package transaction spread currency"}
        },
    )
    package_transaction_spread_notation: str | None = Field(
        default=None,
        description="Package transaction spread notation.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Package transaction spread notation"}
        },
    )
    physical_delivery_location_leg_1: str | None = Field(
        default=None,
        description="Physical delivery location Leg 1.",
        json_schema_extra={
            "x-widget_config": {"headerName": "Physical delivery location - Leg 1"}
        },
    )
    delivery_type: str | None = Field(
        default=None,
        description="Delivery Type.",
        json_schema_extra={"x-widget_config": {"headerName": "Delivery Type"}},
    )
    unique_product_identifier: str | None = Field(
        default=None,
        description="ISO 4914 Unique Product Identifier (UPI).",
        json_schema_extra={
            "x-widget_config": {"headerName": "Unique Product Identifier"}
        },
    )
    upi_fisn: str | None = Field(
        default=None,
        description="Financial Instrument Short Name associated with the UPI.",
        json_schema_extra={"x-widget_config": {"headerName": "UPI FISN"}},
    )
    upi_underlier_name: str | None = Field(
        default=None,
        description="Name of the underlier associated with the UPI.",
        json_schema_extra={"x-widget_config": {"headerName": "UPI Underlier Name"}},
    )

    is_capped: bool | None = Field(
        default=None,
        description="Whether any amount on the transaction was disseminated at a"
        + " reporting cap rather than its true value.",
        json_schema_extra={"x-widget_config": {"headerName": "Is Capped"}},
    )
    trade_type: str | None = Field(
        default=None,
        description="Trade-type family for a rates-asset-class print: 'spot',"
        + " 'forward', 'basis', or 'cross_currency'. Not populated for other asset"
        + " classes.",
        json_schema_extra={"x-widget_config": {"headerName": "Trade Type"}},
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_values(cls, values):
        """Drop empty strings, strip cap markers and thousands separators."""
        if not isinstance(values, dict):
            return values

        alias_to_field = {v: k for k, v in cls.__alias_dict__.items()}
        normalized: dict = {}
        capped = False

        for key, value in values.items():
            if not isinstance(value, str):
                if value is not None:
                    normalized[key] = value
                continue

            text = value.strip()

            if not text:
                continue

            field = alias_to_field.get(key, key)

            if field in _NUMERIC_FIELDS:
                if text.endswith("+"):
                    text = text[:-1]
                    capped = True

                text = text.replace(",", "")

                if not text:
                    continue

            normalized[key] = text

        normalized.setdefault("is_capped", capped)
        identifier = normalized.pop("Dissemination Identifier", None)
        normalized.pop("Original Dissemination Identifier", None)

        if identifier:
            asset = normalized.get("Asset Class") or "NA"
            normalized.setdefault("trade_key", f"{asset}:{identifier}")

        return normalized


def _classify_rates_swap(record: dict, today: dateType) -> str | None:
    """Classify a rates-asset-class print into one of the Swap Trades table's four."""
    from openbb_cftc.utils.swap import classify_rates_swap

    return classify_rates_swap(record, today)


def _curve_ok(day_records: Iterable[dict], currency: str, day: str, memo: dict) -> bool:
    """Whether the currency's rate curve bootstraps from the day's own prints."""
    from openbb_core.provider.utils.errors import EmptyDataError as EmptyError

    from openbb_cftc.utils import store
    from openbb_cftc.utils.fx_vol import rate_discount_factor

    key = ("curve", day, currency)

    if key in memo:
        return memo[key]

    cache_key = f"priceable-curve:{day}:{currency}"
    today = datetime.now(UTC).date().isoformat()
    persisted = store.get_curve(cache_key) if day < today else None

    if persisted is not None:
        memo[key] = persisted

        return persisted

    try:
        rate_discount_factor(day_records, currency, dateType.fromisoformat(day), 1)
        ok = True
    except EmptyError:
        ok = False

    if day < today:
        store.put_curve(cache_key, day, ok)

    memo[key] = ok

    return ok


def _spot_ok(
    fx_records: Iterable[dict] | None,
    other_currency: str,
    currency: str,
    day: str,
    memo: dict,
) -> bool:
    """Whether the pair's spot can be established from the day's forex prints."""
    from openbb_cftc.utils import store
    from openbb_cftc.utils.fx_vol import fx_spot

    key = ("spot", day, other_currency, currency)

    if key in memo:
        return memo[key]

    cache_key = f"priceable-spot:{day}:{other_currency}/{currency}"
    today = datetime.now(UTC).date().isoformat()
    persisted = store.get_curve(cache_key) if day < today else None

    if persisted is not None:
        memo[key] = persisted

        return persisted

    if not fx_records:
        memo[key] = False

        return False

    ok = (
        fx_spot(fx_records, other_currency, currency, dateType.fromisoformat(day))
        is not None
    )

    if day < today:
        store.put_curve(cache_key, day, ok)

    memo[key] = ok

    return ok


def _priceable(
    record: dict,
    day_records: Iterable[dict],
    day: str,
    today: dateType,
    fx_records: Iterable[dict] | None,
    memo: dict,
    index_levels: dict[str, dict] | None = None,
) -> bool:
    """Whether the print values by its own identifier, by the valuation's own gates."""
    return _priceable_by_family(
        record, day_records, day, today, fx_records, memo, index_levels
    )


def _inflation_priceable(
    record: dict,
    day_records: Iterable[dict],
    day: str,
    today: dateType,
    memo: dict,
    index_levels: dict[str, dict] | None,
) -> bool:
    """Whether an inflation print has a curve, a breakeven, and its published index."""
    from openbb_cftc.utils.inflation import (
        INFLATION_INDICES,
        build_breakeven_curve,
        index_ratio,
    )
    from openbb_cftc.utils.swap import extract_inflation_trade

    trade = extract_inflation_trade(record, today)

    if trade is None or not _curve_ok(day_records, trade["currency"], day, memo):
        return False

    curve_date = dateType.fromisoformat(day)
    breakeven_key = f"breakeven:{trade['currency']}"

    if breakeven_key not in memo:
        memo[breakeven_key] = bool(
            build_breakeven_curve(day_records, trade["currency"], curve_date, 1)
        )

    if not memo[breakeven_key]:
        return False

    if trade["effective_date"] >= curve_date:
        return True

    spec = INFLATION_INDICES.get(trade["index"] or "")
    levels = (index_levels or {}).get(trade["index"] or "")

    if spec is None or not levels:
        return False

    return (
        index_ratio(
            levels,
            trade["effective_date"],
            curve_date,
            spec["lag_months"],
            spec["interpolate"],
        )
        is not None
    )


def _priceable_by_family(
    record: dict,
    day_records: Iterable[dict],
    day: str,
    today: dateType,
    fx_records: Iterable[dict] | None,
    memo: dict,
    index_levels: dict[str, dict] | None,
) -> bool:
    """Dispatch a print to the gate its own trade-type family is valued through."""
    from openbb_cftc.utils.swap import (
        extract_spread_trade,
        parse_trade_record,
        reference_spread,
    )

    family = record.get("trade_type")

    if family == "inflation":
        return _inflation_priceable(record, day_records, day, today, memo, index_levels)

    if family in ("basis", "cross_currency"):
        trade = extract_spread_trade(record, today)

        if trade is None or not _curve_ok(day_records, trade["currency"], day, memo):
            return False

        if family == "cross_currency":
            return _curve_ok(
                day_records, trade["other_currency"], day, memo
            ) and _spot_ok(
                fx_records, trade["other_currency"], trade["currency"], day, memo
            )

        spread_key = (
            f"spread:{trade['underlier']}:{trade['trade_type']}:{trade['spread_leg']}"
        )

        if spread_key not in memo:
            memo[spread_key] = reference_spread(
                day_records,
                trade["underlier"],
                trade["trade_type"],
                trade["spread_leg"],
                dateType.fromisoformat(day),
                1,
            )

        return memo[spread_key] is not None

    if parse_trade_record(record, today) is None:
        return False

    currency = (record.get("Notional currency-Leg 1") or "").strip()

    return _curve_ok(day_records, currency, day, memo)


async def _keep_priceable(
    filtered: list[dict],
    day_records: Iterable[dict],
    day: str,
    query: "CftcSwapTradesQueryParams",
) -> list[dict]:
    """Keep the rates rows the swap valuation endpoints can actually price."""
    from openbb_cftc.utils.dtcc import get_slice

    if query.asset_class == "forex":
        return await _keep_priceable_forex(filtered, day_records, day, query)

    fx_records: Iterable[dict] | None = None

    if any(r.get("trade_type") == "cross_currency" for r in filtered):
        try:
            fx_records = await get_slice("forex", day, use_cache=query.use_cache)
        except OpenBBError:
            fx_records = []

    index_levels = await _inflation_levels(filtered, query.use_cache)
    today = datetime.now(UTC).date()
    memo: dict = {}

    return [
        record
        for record in filtered
        if _priceable(record, day_records, day, today, fx_records, memo, index_levels)
    ]


async def _keep_priceable_forex(
    filtered: list[dict],
    day_records: Iterable[dict],
    day: str,
    query: "CftcSwapTradesQueryParams",
) -> list[dict]:
    """Keep the forex rows the swap valuation endpoints can actually price."""
    from openbb_cftc.utils.cfets import cny_curve_records, mentions_cny
    from openbb_cftc.utils.dtcc import get_slice
    from openbb_cftc.utils.fx_valuation import value_fx_trade
    from openbb_cftc.utils.store import RecordChain

    try:
        rates = await get_slice("rates", day, use_cache=query.use_cache)
    except OpenBBError:
        return []

    curve_date = dateType.fromisoformat(day)

    if any(mentions_cny(record) for record in filtered):
        extra = await cny_curve_records(curve_date, use_cache=query.use_cache)

        if extra:
            rates = RecordChain(rates, extra)

    memo: dict = {}

    return [
        record
        for record in filtered
        if value_fx_trade(
            record,
            day_records,
            rates,
            curve_date,
            min_notional=query.min_notional or 0.0,
            memo=memo,
        )
        is not None
    ]


async def _inflation_levels(filtered: list[dict], use_cache: bool) -> dict[str, dict]:
    """Return the published levels for each index the day's inflation prints use."""
    from openbb_cftc.utils.inflation import (
        get_inflation_index,
        index_for_inflation_underlier,
    )

    wanted = {
        index
        for record in filtered
        if record.get("trade_type") == "inflation"
        and (index := index_for_inflation_underlier(record.get("UPI Underlier Name")))
    }
    levels: dict[str, dict] = {}

    for index in sorted(wanted):
        try:
            levels[index] = await get_inflation_index(index, use_cache=use_cache)
        except OpenBBError:
            continue

    return levels


def _apply_filters(
    records: Iterable[dict], query: CftcSwapTradesQueryParams
) -> list[dict]:
    """Narrow a report date's transactions to those matching the query."""
    from datetime import datetime

    from openbb_cftc.utils.curve import parse_notional

    today = datetime.now(UTC).date()
    results: list[dict] = []

    for record in records:
        output_record = record

        if query.asset_class == "rates":
            category = _classify_rates_swap(record, today)

            if category is None:
                continue

            if query.trade_type and category != query.trade_type:
                continue

            output_record = {**record, "trade_type": category}

        if (
            query.currency
            and (record.get("Notional currency-Leg 1") or "").strip().upper()
            != query.currency.strip().upper()
        ):
            continue

        if (
            query.underlier
            and query.underlier.strip().upper()
            not in (record.get("UPI Underlier Name") or "").upper()
        ):
            continue

        if (
            query.upi_fisn
            and query.upi_fisn.strip().upper()
            not in (record.get("UPI FISN") or "").upper()
        ):
            continue

        if (
            query.ticker
            and query.ticker.strip().upper()
            != (record.get("Unique Product Identifier") or "").strip().upper()
        ):
            continue

        if (
            query.action_type
            and (record.get("Action type") or "").strip().upper()
            != query.action_type.strip().upper()
        ):
            continue

        if query.cleared is not None:
            is_cleared = (record.get("Cleared") or "").strip().upper() in ("Y", "I")

            if is_cleared != query.cleared:
                continue

        if query.min_notional is not None or query.max_notional is not None:
            notional, _ = parse_notional(record.get("Notional amount-Leg 1"))

            if notional is None:
                continue

            if query.min_notional is not None and notional < query.min_notional:
                continue

            if query.max_notional is not None and notional > query.max_notional:
                continue

        results.append(output_record)

        if query.limit and len(results) >= query.limit:
            break

    return results


class CftcSwapTradesFetcher(
    Fetcher[CftcSwapTradesQueryParams, list[CftcSwapTradesData]]
):
    """DTCC Public Price Dissemination Swap Trades Fetcher."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> CftcSwapTradesQueryParams:
        """Transform the query params."""
        return CftcSwapTradesQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: CftcSwapTradesQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict]:
        """Fetch the report-date window's transactions and apply the query filters."""
        import asyncio
        from datetime import timedelta

        from openbb_cftc.utils.dtcc import (
            MAX_LOOKBACK_DAYS,
            get_latest_viable_slice,
            get_rates_slice_for,
            get_slice,
        )

        anchor = query.end_date or query.start_date

        if query.ticker:
            from openbb_cftc.utils.search import search_trades
            from openbb_cftc.utils.swap import record_disseminated_day

            today = datetime.now(UTC).date()
            search_end = anchor or today
            search_start = query.start_date or (
                search_end
                if anchor
                else search_end - timedelta(days=MAX_LOOKBACK_DAYS - 1)
            )

            if search_start > search_end:
                raise OpenBBError(
                    f"The report-date window ends before it starts:"
                    f" {search_start} to {search_end}."
                )

            records = await search_trades(
                query.asset_class,
                search_start,
                search_end,
                currency=query.currency,
                upi=query.ticker.strip().upper(),
                use_cache=query.use_cache,
            )

            if anchor is None and records:
                latest = max(record_disseminated_day(r) or "" for r in records)
                records = [
                    r for r in records if (record_disseminated_day(r) or "") == latest
                ]

            filtered = _apply_filters(records, query)

            if not filtered:
                raise EmptyDataError(
                    f"No {query.asset_class} transactions matched the query between"
                    f" {search_start} and {search_end}."
                )

            if query.asset_class != "rates":
                return filtered

            rates, rates_date = await get_rates_slice_for(
                today.isoformat(), ["USD"], use_cache=query.use_cache
            )

            return await _keep_priceable(filtered, rates, rates_date, query)

        if anchor is None:
            records, viable_date = await get_latest_viable_slice(
                query.asset_class,
                lambda recs, _date: bool(_apply_filters(recs, query)),
                use_cache=query.use_cache,
            )

            return await _keep_priceable(
                _apply_filters(records, query), records, viable_date, query
            )

        end_date = query.end_date or anchor
        start_date = query.start_date or anchor

        if start_date > end_date:
            raise OpenBBError(
                f"The report-date window ends before it starts: {start_date} to {end_date}."
            )

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
        days = [
            start_date + timedelta(days=offset)
            for offset in range((end_date - start_date).days + 1)
        ]

        async def _one(report_date: dateType) -> list[dict]:
            async with semaphore:
                try:
                    records = await get_slice(
                        query.asset_class,
                        report_date.isoformat(),
                        use_cache=query.use_cache,
                    )
                except EmptyDataError:
                    return []

                return await _keep_priceable(
                    _apply_filters(records, query),
                    records,
                    report_date.isoformat(),
                    query,
                )

        results = [
            record
            for day in await asyncio.gather(*[_one(d) for d in days])
            for record in day
        ]

        if not results:
            raise EmptyDataError(
                f"No {query.asset_class} transactions matched the query between"
                f" {start_date} and {end_date}."
            )

        return results[: query.limit] if query.limit else results

    @staticmethod
    def transform_data(
        query: CftcSwapTradesQueryParams,
        data: list[dict],
        **kwargs: Any,
    ) -> list[CftcSwapTradesData]:
        """Transform the data."""
        return [CftcSwapTradesData.model_validate(d) for d in data]
