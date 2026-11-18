# OpenBB Binance Provider

This provider adds public Binance crypto market data to OpenBB.

## Usage

```python
from openbb import obb

trades = obb.crypto.price.trades(
    symbol="BTCUSDT",
    provider="binance",
    limit=100,
)
```

## Notes

This provider uses public Binance Spot API market data endpoints and does not require credentials.
