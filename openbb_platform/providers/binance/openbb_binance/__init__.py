"""OpenBB Binance Provider Module."""

from openbb_binance.models.crypto_trades import BinanceCryptoTradesFetcher
from openbb_core.provider.abstract.provider import Provider


binance_provider = Provider(
    name="binance",
    website="https://www.binance.com/",
    description="Public crypto market data from Binance Spot API.",
    credentials=None,
    fetcher_dict={
        "CryptoTrades": BinanceCryptoTradesFetcher,
    },
    repr_name="Binance Public Data",
    instructions="This provider uses public Binance market data endpoints and does not require credentials.",
)
