"""Crypto Price Router."""

from openbb_core.app.model.command_context import CommandContext
from openbb_core.app.model.example import APIEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.provider_interface import (
    ExtraParams,
    ProviderChoices,
    StandardParams,
)
from openbb_core.app.query import Query
from openbb_core.app.router import Router

router = Router(prefix="/price")


@router.command(
    model="CryptoHistorical",
    examples=[
        APIEx(parameters={"symbol": "BTCUSD", "provider": "fmp"}),
        APIEx(
            parameters={
                "symbol": "BTCUSD",
                "start_date": "2024-01-01",
                "end_date": "2024-01-31",
                "provider": "fmp",
            },
        ),
        APIEx(
            description="Get monthly historical prices from Yahoo Finance for Ethereum.",
            parameters={
                "symbol": "ETH-USD",
                "interval": "1m",
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
                "provider": "yfinance",
            },
        ),
    ],
)
async def historical(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get historical price data for cryptocurrency pair(s) within a provider."""
    return await OBBject.from_query(Query(**locals()))


@router.command(
    model="CryptoPrice",
    examples=[
        APIEx(parameters={"symbol": "bitcoin", "provider": "coingecko"}),
        APIEx(parameters={"symbol": "bitcoin,ethereum", "vs_currency": "eur", "provider": "coingecko"}),
        APIEx(
            description="Get real-time prices for multiple cryptocurrencies with market data.",
            parameters={
                "symbol": "bitcoin,ethereum,cardano",
                "vs_currency": "usd",
                "include_market_cap": True,
                "include_24hr_vol": True,
                "include_24hr_change": True,
                "provider": "coingecko",
            },
        ),
    ],
)
async def quote(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Get real-time price data for cryptocurrency(s) from CoinGecko."""
    return await OBBject.from_query(Query(**locals()))
