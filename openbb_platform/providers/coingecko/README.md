# OpenBB CoinGecko Provider

This extension integrates the [CoinGecko](https://www.coingecko.com) data provider into the OpenBB Platform, providing comprehensive real-time and historical cryptocurrency data.

## Installation

To install the extension:

```bash
pip install openbb-coingecko
```

## Coverage

The following endpoints are covered by this extension:

- `obb.crypto.price.historical` - Historical cryptocurrency price data
- `obb.crypto.price.quote` - Real-time cryptocurrency prices
- `obb.crypto.search` - Search for cryptocurrencies

## Features

### Real-time Data
- Current cryptocurrency prices
- Market capitalization data
- 24-hour trading volume
- 24-hour price changes
- Last updated timestamps

### Historical Data
- Historical price charts
- Market cap history
- Volume data over time
- Flexible date ranges
- Multiple interval options

### Search Functionality
- Search cryptocurrencies by name or symbol
- Get comprehensive coin information
- Access to CoinGecko coin IDs for API calls

## API Key Setup

While CoinGecko offers a free tier, we recommend using an API key for production use:

1. Visit [CoinGecko API Pricing](https://www.coingecko.com/en/api/pricing)
2. Sign up for a Pro API plan
3. Visit your [Developer Dashboard](https://www.coingecko.com/en/developers/dashboard)
4. Copy your API key
5. Add it to your OpenBB credentials as `coingecko_api_key`

## Usage Examples

### Real-time Prices

```python
from openbb import obb

# Get current Bitcoin price
result = obb.crypto.price.quote(symbol="bitcoin", provider="coingecko")

# Get multiple cryptocurrencies with market data
result = obb.crypto.price.quote(
    symbol="bitcoin,ethereum,cardano",
    vs_currency="usd",
    include_market_cap=True,
    include_24hr_vol=True,
    include_24hr_change=True,
    provider="coingecko"
)
```

### Historical Data

```python
# Get Bitcoin historical data for the last 30 days
result = obb.crypto.price.historical(
    symbol="bitcoin",
    interval="30d",
    vs_currency="usd",
    provider="coingecko"
)

# Get historical data with specific date range
result = obb.crypto.price.historical(
    symbol="ethereum",
    start_date="2024-01-01",
    end_date="2024-01-31",
    vs_currency="eur",
    provider="coingecko"
)
```

### Search Cryptocurrencies

```python
# Search for cryptocurrencies
result = obb.crypto.search(query="bitcoin", provider="coingecko")

# Get all available cryptocurrencies
result = obb.crypto.search(provider="coingecko")
```

## Supported Currencies

The provider supports pricing in multiple fiat and cryptocurrency currencies:

**Fiat:** USD, EUR, JPY, GBP, AUD, CAD, CHF, CNY, HKD, INR, KRW, MXN, NOK, NZD, PHP, PLN, RUB, SEK, SGD, THB, TRY, TWD, ZAR

**Crypto:** BTC, ETH, LTC, BCH, BNB, EOS, XRP, XLM, LINK, DOT, YFI

## Rate Limits

- **Free API:** 10-50 calls/minute
- **Pro API:** 500+ calls/minute (depending on plan)

For production use, we recommend upgrading to a Pro plan to avoid rate limiting.

## Data Sources

CoinGecko aggregates data from over 400+ exchanges worldwide, providing comprehensive and reliable cryptocurrency market data. The platform tracks 10,000+ different crypto-assets and is one of the most trusted sources in the cryptocurrency space.

## Support

For issues related to this provider, please visit the [OpenBB Platform repository](https://github.com/OpenBB-finance/OpenBB).

For CoinGecko API-specific questions, refer to the [CoinGecko API Documentation](https://docs.coingecko.com/reference/introduction).
