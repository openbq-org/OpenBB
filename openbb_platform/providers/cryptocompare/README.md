# OpenBB CryptoCompare Provider

This extension integrates [CryptoCompare](https://www.cryptocompare.com/) data into the OpenBB Platform.  
It currently supports standardized crypto historical prices with additional datasets planned for upcoming releases.

## Features

- **Crypto Historical Prices** – Pull intraday or end-of-day OHLCV candles for any supported pair (e.g., `BTC-USD`) using the `CryptoHistorical` standard model.  
- Automatic handling of date ranges, interval/aggregation mapping, and optional VWAP estimation.

## Credentials

CryptoCompare allows limited anonymous usage, but obtaining an API key is highly recommended to avoid throttling:

1. Create a free account at [min-api.cryptocompare.com](https://min-api.cryptocompare.com/).
2. Generate an API key from the dashboard.
3. Store it in the OpenBB credentials store as `cryptocompare_api_key`.

## Development

The package follows the same layout as other OpenBB providers:

```
providers/
 └─ cryptocompare/
    ├─ openbb_cryptocompare/
    │   ├─ models/
    │   └─ utils/
    ├─ tests/
    └─ pyproject.toml
```

Add new fetchers in `models/`, hook them into `openbb_cryptocompare/__init__.py`, and record HTTP cassettes under `tests/cassettes/`.
