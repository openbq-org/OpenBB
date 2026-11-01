"""CoinGecko Provider Module."""

from openbb_core.provider.abstract.provider import Provider
from openbb_coingecko.models.crypto_historical import CoinGeckoCryptoHistoricalFetcher
from openbb_coingecko.models.crypto_price import CoinGeckoCryptoPriceFetcher
from openbb_coingecko.models.crypto_search import CoinGeckoCryptoSearchFetcher

coingecko_provider = Provider(
    name="coingecko",
    website="https://www.coingecko.com",
    description=(
        "CoinGecko is the world's largest independent cryptocurrency data aggregator "
        "with over 10,000+ different crypto-assets tracked across more than 400+ "
        "exchanges worldwide. CoinGecko provides real-time pricing, market data, "
        "and comprehensive cryptocurrency information."
    ),
    credentials=["coingecko_api_key"],
    fetcher_dict={
        "CryptoHistorical": CoinGeckoCryptoHistoricalFetcher,
        "CryptoPrice": CoinGeckoCryptoPriceFetcher,
        "CryptoSearch": CoinGeckoCryptoSearchFetcher,
    },
    repr_name="CoinGecko",
    instructions=(
        "To get a CoinGecko API key:\n"
        "1. Visit https://www.coingecko.com/en/api/pricing\n"
        "2. Sign up for a Pro API plan (required for API key access)\n"
        "3. Once subscribed, visit your developer dashboard at "
        "https://www.coingecko.com/en/developers/dashboard\n"
        "4. Copy your API key and add it to your OpenBB credentials as 'coingecko_api_key'\n\n"
        "Note: CoinGecko offers a free tier with limited requests, "
        "but an API key is recommended for production use."
    ),
)
