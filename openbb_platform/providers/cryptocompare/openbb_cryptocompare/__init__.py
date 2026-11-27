"""CryptoCompare provider module."""

from openbb_core.provider.abstract.provider import Provider
from openbb_cryptocompare.models.crypto_historical import (
    CryptoCompareCryptoHistoricalFetcher,
)

cryptocompare_provider = Provider(
    name="cryptocompare",
    website="https://www.cryptocompare.com",
    description=(
        "CryptoCompare delivers consolidated cryptocurrency market data, offering"
        " historical and real-time candles for thousands of trading pairs across"
        " major exchanges."
    ),
    credentials=["api_key"],
    fetcher_dict={
        "CryptoHistorical": CryptoCompareCryptoHistoricalFetcher,
    },
    repr_name="CryptoCompare",
    deprecated_credentials={"CRYPTOCOMPARE_API_KEY": "cryptocompare_api_key"},
    instructions=(
        "1. Navigate to https://min-api.cryptocompare.com/pricing and create a free account.\n"
        "2. From the dashboard, open the 'API Keys' section and copy your key.\n"
        "3. In OpenBB, save it as 'cryptocompare_api_key' via the credentials manager."
    ),
)
