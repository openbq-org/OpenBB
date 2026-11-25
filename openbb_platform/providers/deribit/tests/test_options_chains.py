"""Tests for the Deribit options chain."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
import time_machine
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.utils.errors import EmptyDataError

from openbb_deribit.models.options_chains import DeribitOptionsChainsFetcher

# The XRP_USDC contracts quoted in the fixtures expire at 2026-09-21 08:00 UTC.
EXPIRING = "2026-09-21"
UTC = ZoneInfo("UTC")


@pytest.fixture
def chain(monkeypatch, responder, load):
    """Answer the instrument listing and the subscription from fixtures."""

    def install(root, messages=(), tickers=None):
        responder({"get_instruments": load("instruments_option")})
        stored = load("option_tickers") if tickers is None else tickers
        wanted = {
            name: ticker
            for name, ticker in stored.items()
            if name.startswith(f"{root}-")
        }

        async def _subscribe(symbols, collected):
            collected.update(messages)

            return {name: wanted[name] for name in symbols if name in wanted}

        monkeypatch.setattr(
            "openbb_deribit.utils.websocket.subscribe_tickers", _subscribe
        )

        return wanted

    return install


class TestChain:
    """A chain carries one row per contract, with greeks."""

    @pytest.mark.asyncio
    async def test_rows(self, chain):
        """Each contract quoted lands on the chain, sorted."""
        quoted = chain("XRP_USDC")
        result = await DeribitOptionsChainsFetcher.fetch_data(
            {"symbol": "XRP_USDC"}, {}
        )
        rows = result.model_dump()

        assert len(rows) == len(quoted)
        assert [
            (row["expiration"], row["strike"], row["option_type"]) for row in rows
        ] == sorted(
            (row["expiration"], row["strike"], row["option_type"]) for row in rows
        )
        assert all(row["delta"] is not None for row in rows)

    @pytest.mark.asyncio
    async def test_percentages_stay_in_percent_units(self, chain):
        """A volatility is kept as the exchange publishes it."""
        chain("XRP_USDC")
        result = await DeribitOptionsChainsFetcher.fetch_data(
            {"symbol": "XRP_USDC"}, {}
        )
        quoted = [
            row["implied_volatility"]
            for row in result.model_dump()
            if row["implied_volatility"]
        ]

        assert quoted
        assert all(value > 1 for value in quoted)

    @pytest.mark.asyncio
    async def test_linear_prices_are_left_alone(self, chain):
        """A USDC-quoted contract keeps the price the exchange published."""
        quoted = chain("XRP_USDC")
        result = await DeribitOptionsChainsFetcher.fetch_data(
            {"symbol": "XRP_USDC"}, {}
        )
        rows = {row["contract_symbol"]: row for row in result.model_dump()}
        name = next(iter(quoted))

        assert rows[name]["mark"] == quoted[name]["mark_price"]

    @pytest.mark.asyncio
    async def test_inverse_prices_are_carried_to_usd(self, chain):
        """A BTC-quoted contract's premium is carried at the index level."""
        quoted = chain("BTC")
        result = await DeribitOptionsChainsFetcher.fetch_data({"symbol": "BTC"}, {})
        rows = {row["contract_symbol"]: row for row in result.model_dump()}
        name = next(iter(quoted))
        published = quoted[name]

        assert rows[name]["mark"] == (
            published["mark_price"] * published["index_price"]
        )

    @pytest.mark.asyncio
    async def test_no_rounding(self, chain):
        """The carried premium keeps every digit the arithmetic produced."""
        quoted = chain("BTC")
        result = await DeribitOptionsChainsFetcher.fetch_data({"symbol": "BTC"}, {})
        rows = {row["contract_symbol"]: row for row in result.model_dump()}
        carried = [
            rows[name]["mark"] for name in quoted if rows[name]["mark"] is not None
        ]

        assert any(round(value, 2) != value for value in carried)

    @pytest.mark.asyncio
    async def test_decimal_strikes(self, chain):
        """A strike the exchange spells with a ``d`` reads as a decimal."""
        chain("XRP_USDC")
        result = await DeribitOptionsChainsFetcher.fetch_data(
            {"symbol": "XRP_USDC"}, {}
        )

        assert any(row["strike"] % 1 for row in result.model_dump())

    @pytest.mark.asyncio
    async def test_warns_but_returns(self, chain):
        """A partial subscription warns and returns what did arrive."""
        chain("XRP_USDC", messages=("half the chain timed out",))

        with pytest.warns(UserWarning, match="timed out"):
            result = await DeribitOptionsChainsFetcher.fetch_data(
                {"symbol": "XRP_USDC"}, {}
            )

        assert result.model_dump()

    @pytest.mark.asyncio
    async def test_raises_when_everything_failed(self, chain):
        """A subscription that returned nothing at all raises its reason."""
        chain("XRP_USDC", messages=("the subscription failed",), tickers={})

        with pytest.raises(OpenBBError, match="subscription failed"):
            await DeribitOptionsChainsFetcher.fetch_data({"symbol": "XRP_USDC"}, {})

    @pytest.mark.asyncio
    async def test_empty_without_a_reason(self, chain):
        """A silent empty subscription is an empty-data error."""
        chain("XRP_USDC", tickers={})

        with pytest.raises(EmptyDataError):
            await DeribitOptionsChainsFetcher.fetch_data({"symbol": "XRP_USDC"}, {})

    @pytest.mark.asyncio
    async def test_a_failed_expiration_is_skipped(self, monkeypatch, responder, load):
        """An expiration whose subscription raised is left out, not fatal."""
        responder({"get_instruments": load("instruments_option")})
        stored = load("option_tickers")
        calls: list = []

        async def _subscribe(symbols, collected):
            calls.append(symbols)

            if not any(name in stored for name in symbols):
                raise RuntimeError("the socket went away")

            return {name: stored[name] for name in symbols if name in stored}

        monkeypatch.setattr(
            "openbb_deribit.utils.websocket.subscribe_tickers", _subscribe
        )
        result = await DeribitOptionsChainsFetcher.fetch_data(
            {"symbol": "XRP_USDC"}, {}
        )

        assert result.model_dump()

    @pytest.mark.asyncio
    async def test_unlisted_underlying(self, responder, load):
        """An underlying with no options names the ones that have them."""
        responder({"get_instruments": load("instruments_option")})

        with pytest.raises(OpenBBError, match="XRP_USDC"):
            await DeribitOptionsChainsFetcher.fetch_data({"symbol": "DOGE"}, {})

    @pytest.mark.asyncio
    async def test_index_underlying_is_named(self, chain, load):
        """A contract priced off the index names the index, not a placeholder."""
        stored = load("option_tickers")

        for ticker in stored.values():
            ticker["underlying_index"] = "index_price"

        chain("XRP_USDC", tickers=stored)
        result = await DeribitOptionsChainsFetcher.fetch_data(
            {"symbol": "XRP_USDC"}, {}
        )

        assert {row["underlying_symbol"] for row in result.model_dump()} == {"XRP-USDC"}


def _days_left(result) -> set:
    """Return the DTE of every contract in the result that expires on EXPIRING."""
    return {
        row["dte"] for row in result.model_dump() if str(row["expiration"]) == EXPIRING
    }


class TestDaysToExpiration:
    """DTE is the whole days left before the exchange expires the contract."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("zone", ["UTC", "Asia/Tokyo", "America/Los_Angeles"])
    async def test_the_local_timezone_does_not_change_it(self, chain, zone):
        """Five hours before it expires a contract is at zero days, anywhere."""
        chain("XRP_USDC")
        instant = datetime(2026, 9, 21, 3, tzinfo=UTC).astimezone(ZoneInfo(zone))

        # A ZoneInfo destination also sets the local timezone, where tzset exists.
        with time_machine.travel(instant, tick=False):
            result = await DeribitOptionsChainsFetcher.fetch_data(
                {"symbol": "XRP_USDC"}, {}
            )

        assert _days_left(result) == {0}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("hour", "days"), [(7, 1), (9, 0)])
    async def test_without_a_timestamp_it_expires_at_eight_utc(
        self, chain, responder, load, hour, days
    ):
        """A contract listed with no timestamp expires at 08:00 UTC on its date."""
        chain("XRP_USDC")
        responder(
            {
                "get_instruments": [
                    {k: v for k, v in spec.items() if k != "expiration_timestamp"}
                    for spec in load("instruments_option")
                ]
            }
        )

        with time_machine.travel(datetime(2026, 9, 20, hour, tzinfo=UTC), tick=False):
            result = await DeribitOptionsChainsFetcher.fetch_data(
                {"symbol": "XRP_USDC"}, {}
            )

        assert _days_left(result) == {days}
