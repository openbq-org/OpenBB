"""Interactive Brokers OpenBB Platform Provider."""

from openbb_core.provider.abstract.provider import Provider
from openbb_ibkr.models.equity_historical import IBKREquityHistoricalFetcher

# mypy: disable-error-code="list-item"

provider = Provider(
    name="ibkr",
    website="https://www.interactivebrokers.com",
    description=(
        "Interactive Brokers provider via TWS or IB Gateway (ib_insync). "
        "Requires TWS or IB Gateway running locally before use. "
        "Default port: 4002 (IB Gateway paper trading)."
    ),
    credentials=["host", "port", "client_id"],
    fetcher_dict={
        "EquityHistorical": IBKREquityHistoricalFetcher,
    },
    repr_name="Interactive Brokers",
)
