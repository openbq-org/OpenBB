"""Fama-French Factors Fetcher Model."""

from datetime import date as dateType
from typing import Any, Literal

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.app.service.system_service import SystemService
from openbb_core.provider.abstract.annotated_result import AnnotatedResult
from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import Field, model_validator

from openbb_famafrench.utils.constants import (
    FACTOR_REGION_MAP,
    PERCENT_UNIT,
    REGIONS_MAP,
)

api_prefix = SystemService().system_settings.api_settings.prefix
factors_dict = {
    "5_factors": "5_Factors",
    "3_factors": "3_Factors",
    "momentum": "Momentum",
    "st_reversal": "ST_Reversal",
    "lt_reversal": "LT_Reversal",
}


class FamaFrenchFactorsQueryParams(QueryParams):
    """Query parameters for Fama-French factors.

    Source: https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html
    """

    region: Literal[
        "america",
        "north_america",
        "europe",
        "japan",
        "asia_pacific_ex_japan",
        "developed",
        "developed_ex_us",
        "emerging",
    ] = Field(
        description="Region of focus. Default is America.",
        default="america",
        json_schema_extra={
            "x-widget_config": {
                "options": [
                    {"label": k.replace("_", " ").title(), "value": v}
                    for k, v in REGIONS_MAP.items()
                ]
            }
        },
    )
    factor: Literal[
        "5_factors", "3_factors", "momentum", "st_reversal", "lt_reversal"
    ] = Field(
        default="3_factors",
        description="Factor to fetch. "
        + "Default is the 3-Factor Model."
        + "Short/long-term reversals are available only for America.",
        json_schema_extra={
            "x-widget_config": {
                "type": "endpoint",
                "optionsEndpoint": f"{api_prefix}/famafrench/factor_choices",
                "optionsParams": {"region": "$region", "is_portfolio": False},
            },
        },
    )
    frequency: Literal[
        "daily",
        "weekly",
        "monthly",
        "annual",
    ] = Field(
        default="monthly",
        description="Frequency of the factor data."
        + "Not all are available for all regions, "
        + "and intervals depend on the factor selected."
        + " Weekly is only available for the US 3-Factor Model.",
        json_schema_extra={
            "x-widget_config": {
                "type": "endpoint",
                "optionsEndpoint": f"{api_prefix}/famafrench/get_factor_choices",
                "optionsParams": {
                    "region": "$region",
                    "factor": "$factor",
                    "is_portfolio": False,
                },
            },
        },
    )
    start_date: dateType | None = Field(
        default=None,
        description="Start date of the data. Defaults to the complete data range.",
        json_schema_extra={
            "x-widget_config": {
                "value": "$currentDate-5y",
                "description": "Start date of the factor data.",
            }
        },
    )
    end_date: dateType | None = Field(
        default=None,
        description="End date of the data. Defaults to the complete data range.",
        json_schema_extra={
            "x-widget_config": {
                "value": "$currentDate",
                "description": "End date of the factor data.",
            }
        },
    )

    @model_validator(mode="before")
    @classmethod
    def validate_region_and_factor(cls, values):
        """Validate region and factor combination."""
        region = values.get("region", "america")
        factor = factors_dict.get(values.get("factor", "3_factors"), "")
        frequency = values.get("frequency", "")

        if (  # pragma: no cover
            factor and factor in ["st_reversal", "lt_reversal"] and region != "america"
        ):
            raise ValueError(
                f"Invalid region, '{region}', for factor '{factor}'. Only 'america' is supported."
            )

        if region and region not in list(FACTOR_REGION_MAP):
            raise ValueError(
                f"Invalid region: '{region}'. "
                + "Valid regions are: "
                + ", ".join(FACTOR_REGION_MAP.keys())
            )

        regional_factors = FACTOR_REGION_MAP[region]

        if factor not in regional_factors.get("factors", {}):
            raise ValueError(
                f"Invalid factor: '{factor}' for region: '{region}'. "
                + "Valid factors are: "
                + ", ".join(regional_factors.get("factors", {}).keys())
            )

        if frequency:
            intervals = regional_factors.get("intervals", {}).get(factor, {})
            if frequency not in list(intervals):
                raise ValueError(
                    f"Invalid frequency: '{frequency}' for factor: '{factor}'"
                    + f" in region: '{region}'. "
                    + "Valid frequencies are: "
                    + ", ".join(intervals.keys())
                )

        return values


class FamaFrenchFactorsData(Data):
    """Fama-French Factors Data.

    Factor definitions:
    https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/f-f_factors.html
    """

    __alias_dict__ = {
        "date": "Date",
        "mkt_rf": "Mkt-RF",
        "smb": "SMB",
        "hml": "HML",
        "rmw": "RMW",
        "cma": "CMA",
        "rf": "RF",
        "mom": "Mom",
        "lt_rev": "LT_Rev",
        "st_rev": "ST_Rev",
        "wml": "WML",
    }

    date: dateType = Field(
        description="Date of the factor data.",
    )
    mkt_rf: float | None = Field(
        default=None,
        description="Market excess return (Rm - Rf), the value-weighted return of all firms,"
        + " minus the one-month Treasury bill rate."
        + " Not returned for momentum or reversal factors."
        + " Values are in percent.",
        json_schema_extra=PERCENT_UNIT,
        title="Mkt-RF",
    )
    smb: float | None = Field(
        default=None,
        description="Small minus big (SMB) factor returns."
        + " Average return of small minus big stock portfolios."
        + " Not returned for momentum or reversal factors."
        + " Values are in percent.",
        json_schema_extra=PERCENT_UNIT,
        title="SMB",
    )
    hml: float | None = Field(
        default=None,
        description="High minus low (HML) factor returns."
        + " Average return on value minus average return on growth portfolios."
        + " Not returned for momentum or reversal factors."
        + " Values are in percent.",
        json_schema_extra=PERCENT_UNIT,
        title="HML",
    )
    rmw: float | None = Field(
        default=None,
        description="Robust minus weak (RMW) factor returns."
        + " Average return on robust operating profitability portfolios,"
        " minus average return on weak operating profitability portfolios."
        + " Only returned when 5 Factor model is selected."
        + " Values are in percent.",
        json_schema_extra=PERCENT_UNIT,
        title="RMW",
    )
    cma: float | None = Field(
        default=None,
        description="Conservative minus aggressive (CMA) factor returns."
        + " Average return on conservative investment portfolios,"
        " minus average return on aggressive investment portfolios."
        + " Only returned when 5 Factor model is selected."
        + " Values are in percent.",
        json_schema_extra=PERCENT_UNIT,
        title="CMA",
    )
    rf: float | None = Field(
        default=None,
        description="Risk-free rate (RF) returns."
        + " The one-month US Treasury bill rate."
        + " Not returned when momentum or reversal factors are selected."
        + " Values are in percent.",
        json_schema_extra=PERCENT_UNIT,
        title="RF",
    )
    mom: float | None = Field(
        default=None,
        description="Momentum (Mom) factor returns."
        + " Returned only when the momentum factor is selected and the region is 'america'."
        + " Values are in percent.",
        json_schema_extra=PERCENT_UNIT,
        title="Mom",
    )
    wml: float | None = Field(
        default=None,
        description="Winners minus losers (WML) factor returns."
        + " Equal-weight average of the returns for the winner portfolios"
        + " minus the average of the returns for the loser portfolios."
        + " Returned only when the momentum factor is selected, and the region is not 'america'."
        + " Values are in percent.",
        json_schema_extra=PERCENT_UNIT,
        title="WML",
    )
    lt_rev: float | None = Field(
        default=None,
        description="Long-term reversal (LT_Rev) factor returns."
        + " Returned only when the long-term reversal factor is selected,"
        + " and the region is 'america'."
        + " Values are in percent.",
        json_schema_extra=PERCENT_UNIT,
        title="LT_Rev",
    )
    st_rev: float | None = Field(
        default=None,
        description="Short-term reversal (ST_Rev) factor returns."
        + " Returned only when the short-term reversal factor is selected,"
        + " and the region is 'america'."
        + " Values are in percent.",
        json_schema_extra=PERCENT_UNIT,
        title="ST_Rev",
    )


class FamaFrenchFactorsFetcher(
    Fetcher[FamaFrenchFactorsQueryParams, list[FamaFrenchFactorsData]]
):
    """Fama-French Factors Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FamaFrenchFactorsQueryParams:
        """Transform query parameters to FamaFrenchFactorsQueryParams."""
        return FamaFrenchFactorsQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: FamaFrenchFactorsQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> tuple:
        """Extract the data from the FTP."""
        from openbb_famafrench.utils.helpers import get_portfolio_data

        factors = FACTOR_REGION_MAP.get(query.region, {})
        factor = factors_dict.get(query.factor, "")
        portfolio = factors.get("factors", {}).get(factor, "")
        interval = factors.get("intervals", {}).get(factor, {}).get(query.frequency, "")
        dataset = portfolio + interval

        if not dataset:
            raise OpenBBError(f"Invalid dataset, {dataset}")

        try:
            return get_portfolio_data(
                dataset=dataset,
                frequency=query.frequency,
            )
        except Exception as e:
            raise OpenBBError(original=e) from e

    @staticmethod
    def transform_data(
        query: FamaFrenchFactorsQueryParams,
        data: tuple,
        **kwargs: Any,
    ) -> AnnotatedResult[list[FamaFrenchFactorsData]]:
        """Transform the raw data and insert metadata."""
        from pandas import to_datetime

        from openbb_famafrench.utils.missing_values import replace_missing_values

        table = data[0][0].reset_index()

        if query.start_date:
            table = table[to_datetime(table.Date) >= to_datetime(query.start_date)]

        if query.end_date:
            table = table[to_datetime(table.Date) <= to_datetime(query.end_date)]

        records = replace_missing_values(table.to_dict(orient="records"))
        metadata = data[1][0]

        return AnnotatedResult(
            result=[FamaFrenchFactorsData(**r) for r in records],
            metadata=metadata,
        )
