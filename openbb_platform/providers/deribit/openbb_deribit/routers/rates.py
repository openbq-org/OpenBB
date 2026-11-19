"""Deribit Rates sub-router."""

from datetime import UTC
from typing import Annotated

from fastapi import Query as FastAPIQuery
from openbb_core.app.model.command_context import CommandContext
from openbb_core.app.model.example import APIEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.provider_interface import (
    ExtraParams,
    ProviderChoices,
    StandardParams,
)
from openbb_core.app.query import Query as OBBQuery
from openbb_core.app.router import Router

router = Router(prefix="/rates", description="Deribit funding and yield data.")


@router.command(
    model="DeribitFundingRateHistory",
    widget_config={
        "name": "Deribit Funding Rate History",
        "description": "The hourly funding a perpetual has paid.",
        "category": "Crypto",
        "subCategory": "Rates",
        "source": ["Deribit"],
        "gridData": {"w": 40, "h": 14},
        "params": [{"paramName": "symbol", "value": "BTC-PERPETUAL"}],
        "data": {
            "table": {
                "chartView": {"enabled": True, "chartType": "line"},
            }
        },
    },
    examples=[
        APIEx(
            description="The funding the BTC perpetual has paid over the last week.",
            parameters={"symbol": "BTC-PERPETUAL", "provider": "deribit"},
        )
    ],
)
async def funding_history(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get the hourly funding a Deribit perpetual has paid."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="DeribitFundingChart",
    widget_config={"exclude": True},
    examples=[
        APIEx(
            description="The funding the BTC perpetual has accrued over eight hours.",
            parameters={"symbol": "BTC-PERPETUAL", "provider": "deribit"},
        )
    ],
)
async def funding_chart(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get the funding a Deribit perpetual has accrued over the current window."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="DeribitAprHistory",
    widget_config={
        "name": "Deribit Yield History",
        "description": "The daily yield a yield-bearing currency has earned.",
        "category": "Crypto",
        "subCategory": "Rates",
        "source": ["Deribit"],
        "gridData": {"w": 40, "h": 14},
        "data": {
            "table": {
                "chartView": {"enabled": True, "chartType": "line"},
            }
        },
    },
    examples=[
        APIEx(
            description="The yield USDe has earned.",
            parameters={"currency": "usde", "provider": "deribit"},
        )
    ],
)
async def apr_history(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get the daily yield a Deribit yield-bearing currency has earned."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    methods=["GET"],
    widget_config={"exclude": True},
    examples=[
        APIEx(
            description="Read the funding one perpetual paid over a span.",
            parameters={
                "symbol": "BTC-PERPETUAL",
                "start_date": "2026-09-01",
                "end_date": "2026-09-08",
            },
        )
    ],
)
async def funding_value(
    symbol: Annotated[
        str, FastAPIQuery(description="The perpetual instrument name.")
    ] = "BTC-PERPETUAL",
    start_date: Annotated[
        str | None, FastAPIQuery(description="The first date of the span.")
    ] = None,
    end_date: Annotated[
        str | None, FastAPIQuery(description="The last date of the span.")
    ] = None,
) -> float:
    """Get the funding one perpetual paid over a span, as a single rate."""
    from datetime import datetime, timedelta

    from openbb_deribit.utils.client import request
    from openbb_deribit.utils.helpers import get_perpetual_symbols, to_timestamp

    now = datetime.now(UTC)
    perpetuals = await get_perpetual_symbols()

    return await request(
        "get_funding_rate_value",
        {
            "instrument_name": perpetuals.get(symbol.upper(), symbol),
            "start_timestamp": to_timestamp(start_date or now - timedelta(days=7)),
            "end_timestamp": to_timestamp(end_date or now),
        },
    )
