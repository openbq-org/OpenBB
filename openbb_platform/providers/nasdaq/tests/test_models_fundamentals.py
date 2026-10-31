"""Tests for the Nasdaq fundamentals, estimates, and ownership models."""

import asyncio
from datetime import date

import pytest
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.utils.errors import EmptyDataError

from openbb_nasdaq.models.balance_sheet import NasdaqBalanceSheetFetcher
from openbb_nasdaq.models.cash_flow import NasdaqCashFlowStatementFetcher
from openbb_nasdaq.models.financial_ratios import NasdaqFinancialRatiosFetcher
from openbb_nasdaq.models.historical_dividends import (
    NasdaqHistoricalDividendsFetcher,
)
from openbb_nasdaq.models.historical_eps import NasdaqHistoricalEpsFetcher
from openbb_nasdaq.models.income_statement import NasdaqIncomeStatementFetcher
from openbb_nasdaq.models.insider_trading import NasdaqInsiderTradingFetcher
from openbb_nasdaq.models.institutional_ownership import (
    NasdaqInstitutionalOwnershipFetcher,
)
from openbb_nasdaq.models.price_target import NasdaqPriceTargetFetcher
from openbb_nasdaq.models.price_target_consensus import (
    NasdaqPriceTargetConsensusFetcher,
)

from .conftest import patch_asset_class, patch_data


def statement(table: str, label: str, value: str) -> dict:
    """Build a one-period statement payload."""
    return {
        table: {
            "headers": {"value1": "Period Ending:", "value2": "12/31/2025"},
            "rows": [{"value1": label, "value2": value}],
        }
    }


class TestStatements:
    """Cover the four statement models."""

    @pytest.mark.parametrize(
        ("fetcher", "table", "label", "field"),
        [
            (
                NasdaqBalanceSheetFetcher,
                "balanceSheetTable",
                "Total Assets",
                "total_assets",
            ),
            (
                NasdaqIncomeStatementFetcher,
                "incomeStatementTable",
                "Total Revenue",
                "revenue",
            ),
            (
                NasdaqCashFlowStatementFetcher,
                "cashFlowTable",
                "Net Income",
                "net_income",
            ),
        ],
        ids=["balance", "income", "cash"],
    )
    def test_transforms_a_period(self, fetcher, table, label, field):
        """Each statement pivots into one record per period."""
        query = fetcher.transform_query({"symbol": "AAPL"})
        rows = fetcher.transform_data(query, statement(table, label, "$1,000"))

        assert rows[0].symbol == "AAPL"
        assert rows[0].period_ending == date(2025, 12, 31)
        assert getattr(rows[0], field) == pytest.approx(1000)

    @pytest.mark.parametrize(
        ("fetcher", "message"),
        [
            (NasdaqBalanceSheetFetcher, "No balance sheet"),
            (NasdaqIncomeStatementFetcher, "No income statement"),
            (NasdaqCashFlowStatementFetcher, "No cash flow"),
            (NasdaqFinancialRatiosFetcher, "No financial ratios"),
        ],
        ids=["balance", "income", "cash", "ratios"],
    )
    def test_empty_raises(self, fetcher, message):
        """A symbol with no statement is reported."""
        query = fetcher.transform_query({"symbol": "AAPL"})

        with pytest.raises(EmptyDataError, match=message):
            fetcher.transform_data(query, {})

    @pytest.mark.parametrize(
        "fetcher",
        [
            NasdaqBalanceSheetFetcher,
            NasdaqIncomeStatementFetcher,
            NasdaqCashFlowStatementFetcher,
            NasdaqFinancialRatiosFetcher,
        ],
        ids=["balance", "income", "cash", "ratios"],
    )
    def test_delegates_to_the_financials_endpoint(self, fetcher, monkeypatch):
        """Each statement is read from the shared financials payload."""
        seen: list[tuple] = []

        async def _financials(symbol, period):
            seen.append((symbol, period))

            return {}

        monkeypatch.setattr(
            "openbb_nasdaq.utils.financials.get_financials", _financials
        )
        query = fetcher.transform_query({"symbol": "AAPL", "period": "quarter"})
        asyncio.run(fetcher.aextract_data(query, None))

        assert seen == [("AAPL", "quarter")]

    def test_ratios_normalize_percentages(self):
        """Ratio percentages are normalized."""
        query = NasdaqFinancialRatiosFetcher.transform_query({"symbol": "AAPL"})
        rows = NasdaqFinancialRatiosFetcher.transform_data(
            query, statement("financialRatiosTable", "Profit Margin", "10.00 %")
        )

        assert rows[0].net_profit_margin == pytest.approx(0.1)

    def test_limit_truncates(self):
        """The limit caps the number of periods returned."""
        payload = {
            "balanceSheetTable": {
                "headers": {
                    "value1": "Period Ending:",
                    "value2": "12/31/2025",
                    "value3": "12/31/2024",
                },
                "rows": [{"value1": "Total Assets", "value2": "$2", "value3": "$1"}],
            }
        }
        query = NasdaqBalanceSheetFetcher.transform_query(
            {"symbol": "AAPL", "limit": 1}
        )

        assert len(NasdaqBalanceSheetFetcher.transform_data(query, payload)) == 1

    def test_as_of_date_filters_periods(self):
        """as_of_date excludes periods ending after the cutoff."""
        payload = {
            "incomeStatementTable": {
                "headers": {
                    "value1": "Period Ending:",
                    "value2": "12/31/2025",
                    "value3": "12/31/2024",
                },
                "rows": [
                    {"value1": "Total Revenue", "value2": "$200", "value3": "$100"}
                ],
            }
        }
        query = NasdaqIncomeStatementFetcher.transform_query(
            {"symbol": "AAPL", "as_of_date": "2025-06-15"}
        )
        rows = NasdaqIncomeStatementFetcher.transform_data(query, payload)
        assert len(rows) == 1
        assert rows[0].period_ending == date(2024, 12, 31)


class TestHistoricalEps:
    """Cover the earnings surprise model."""

    def test_transforms_and_sorts(self, monkeypatch):
        """Undated rows drop and the rest sort newest first."""
        patch_data(
            monkeypatch,
            {
                "earningsSurpriseTable": {
                    "rows": [
                        {
                            "dateReported": "05/01/2026",
                            "eps": "$1.50",
                            "consensusForecast": "$1.40",
                            "percentageSurprise": "7.14",
                            "fiscalQtrEnd": "Mar 2026",
                        },
                        {
                            "dateReported": "08/01/2026",
                            "eps": "$2.00",
                            "consensusForecast": "$1.90",
                            "percentageSurprise": "5.26",
                            "fiscalQtrEnd": "Jun 2026",
                        },
                        {"dateReported": "N/A"},
                    ]
                }
            },
        )
        query = NasdaqHistoricalEpsFetcher.transform_query({"symbol": "aapl"})
        raw = asyncio.run(NasdaqHistoricalEpsFetcher.aextract_data(query, None))
        rows = NasdaqHistoricalEpsFetcher.transform_data(query, raw)

        assert [r.date.isoformat() for r in rows] == ["2026-08-01", "2026-05-01"]
        assert rows[0].eps_actual == pytest.approx(2.0)
        assert rows[0].surprise_percent == pytest.approx(0.0526)

    def test_empty_raises(self, monkeypatch):
        """A symbol with no earnings history is reported."""
        patch_data(monkeypatch, {})
        query = NasdaqHistoricalEpsFetcher.transform_query({"symbol": "AAPL"})

        with pytest.raises(EmptyDataError, match="No earnings history"):
            asyncio.run(NasdaqHistoricalEpsFetcher.aextract_data(query, None))


class TestPriceTarget:
    """Cover the ratings actions model."""

    def test_transforms_an_action(self, monkeypatch):
        """A rating change resolves under either field naming."""
        patch_data(
            monkeypatch,
            {
                "upgradesDowngrades": [
                    {
                        "date": "07/24/2026",
                        "company": "Morgan Stanley",
                        "toRating": "Overweight",
                        "fromRating": "Equal Weight",
                        "action": "Upgrade",
                        "toPT": "$400",
                        "fromPT": "$350",
                    },
                    {
                        "date": "07/20/2026",
                        "firm": "UBS",
                        "rating": "Buy",
                        "priceTarget": "$380",
                    },
                ]
            },
        )
        query = NasdaqPriceTargetFetcher.transform_query({"symbol": "aapl"})
        raw = asyncio.run(NasdaqPriceTargetFetcher.aextract_data(query, None))
        rows = NasdaqPriceTargetFetcher.transform_data(query, raw)

        assert rows[0].analyst_firm == "Morgan Stanley"
        assert rows[0].price_target == pytest.approx(400)
        assert rows[0].rating_previous == "Equal Weight"
        assert rows[1].analyst_firm == "UBS"

    def test_warns_and_raises_when_empty(self, monkeypatch):
        """A symbol with no published actions warns and reports."""

        async def _data(path, **kwargs):
            raise OpenBBError("no ratings")

        monkeypatch.setattr("openbb_nasdaq.utils.helpers.get_nasdaq_data", _data)
        query = NasdaqPriceTargetFetcher.transform_query({"symbol": "NOPE"})

        with (
            pytest.warns(UserWarning, match="NOPE"),
            pytest.raises(EmptyDataError, match="No rating changes"),
        ):
            asyncio.run(NasdaqPriceTargetFetcher.aextract_data(query, None))


class TestPriceTargetConsensus:
    """Cover the analyst consensus model."""

    def test_merges_target_and_ratings(self, monkeypatch):
        """The consensus overview and rating counts are merged."""

        async def _data(path, **kwargs):
            if "targetprice" in path:
                return {
                    "consensusOverview": {
                        "highPriceTarget": "$400",
                        "lowPriceTarget": "$200",
                        "priceTarget": "$300",
                        "buy": "20",
                    }
                }

            return {"ratings": {}}

        monkeypatch.setattr("openbb_nasdaq.utils.helpers.get_nasdaq_data", _data)
        query = NasdaqPriceTargetConsensusFetcher.transform_query({"symbol": "aapl"})
        raw = asyncio.run(NasdaqPriceTargetConsensusFetcher.aextract_data(query, None))
        rows = NasdaqPriceTargetConsensusFetcher.transform_data(query, raw)

        assert rows[0].target_high == pytest.approx(400)
        assert rows[0].target_consensus == pytest.approx(300)

    def test_warns_without_a_target(self, monkeypatch):
        """A symbol with no consensus warns and reports."""

        async def _data(path, **kwargs):
            return None

        monkeypatch.setattr("openbb_nasdaq.utils.helpers.get_nasdaq_data", _data)
        query = NasdaqPriceTargetConsensusFetcher.transform_query({"symbol": "NOPE"})

        with pytest.warns(UserWarning, match="NOPE"), pytest.raises(EmptyDataError):
            asyncio.run(NasdaqPriceTargetConsensusFetcher.aextract_data(query, None))

    def test_tolerates_a_failing_ratings_call(self, monkeypatch):
        """The consensus is still returned when the ratings call fails."""

        async def _data(path, **kwargs):
            if "ratings" in path:
                raise OpenBBError("no ratings")

            return {"consensusOverview": {"priceTarget": "$300"}}

        monkeypatch.setattr("openbb_nasdaq.utils.helpers.get_nasdaq_data", _data)
        query = NasdaqPriceTargetConsensusFetcher.transform_query({"symbol": "AAPL"})
        raw = asyncio.run(NasdaqPriceTargetConsensusFetcher.aextract_data(query, None))

        assert raw[0]["ratings"] == {}


class TestInsiderTrading:
    """Cover the insider trading model."""

    def test_transforms_a_trade(self, monkeypatch):
        """The insider, relation, and URL all resolve."""
        patch_data(
            monkeypatch,
            {
                "transactionTable": {
                    "rows": [
                        {
                            "insider": "COOK TIMOTHY D",
                            "relation": "Chief Executive Officer",
                            "lastDate": "07/24/2026",
                            "transactionType": "Sale",
                            "ownType": "Direct",
                            "sharesTraded": "100,000",
                            "lastPrice": "$333.02",
                            "sharesHeld": "3,000,000",
                            "url": "/market-activity/insiders/x",
                        }
                    ]
                }
            },
        )
        query = NasdaqInsiderTradingFetcher.transform_query({"symbol": "aapl"})
        raw = asyncio.run(NasdaqInsiderTradingFetcher.aextract_data(query, None))
        rows = NasdaqInsiderTradingFetcher.transform_data(query, raw)

        assert rows[0].owner_name == "COOK TIMOTHY D"
        assert rows[0].securities_transacted == pytest.approx(100000)
        assert rows[0].url.startswith("https://www.nasdaq.com/market-activity")

    def test_without_a_url(self):
        """A row without a link carries none."""
        query = NasdaqInsiderTradingFetcher.transform_query({"symbol": "AAPL"})
        rows = NasdaqInsiderTradingFetcher.transform_data(
            query, [{"symbol": "AAPL", "lastDate": "07/24/2026"}]
        )

        assert rows[0].url is None

    def test_empty_raises(self, monkeypatch):
        """A symbol with no insider activity is reported."""
        patch_data(monkeypatch, {})
        query = NasdaqInsiderTradingFetcher.transform_query({"symbol": "AAPL"})

        with pytest.raises(EmptyDataError):
            asyncio.run(NasdaqInsiderTradingFetcher.aextract_data(query, None))


class TestInstitutionalOwnership:
    """Cover the institutional holders model."""

    def test_sends_the_type_and_sort(self, monkeypatch):
        """The holder type and sort column are both sent."""
        seen: list[str] = []
        patch_data(
            monkeypatch,
            {"holdingsTransactions": {"table": {"rows": [{"ownerName": "Citadel"}]}}},
            seen,
        )
        query = NasdaqInstitutionalOwnershipFetcher.transform_query(
            {"symbol": "stak", "holder_type": "sold_out", "sort_by": "shares_held"}
        )
        asyncio.run(NasdaqInstitutionalOwnershipFetcher.aextract_data(query, None))

        assert "type=SOLDOUT" in seen[0]
        assert "sortColumn=sharesHeld" in seen[0]

    def test_transforms_a_holder(self):
        """The holder, change, and portfolio link resolve."""
        query = NasdaqInstitutionalOwnershipFetcher.transform_query({"symbol": "STAK"})
        rows = NasdaqInstitutionalOwnershipFetcher.transform_data(
            query,
            [
                {
                    "symbol": "STAK",
                    "ownerName": "Citadel Advisors Llc",
                    "date": "03/31/2026",
                    "sharesHeld": "0",
                    "sharesChange": "-54,125",
                    "sharesChangePCT": "-100%",
                    "marketValue": "",
                    "url": "/market-activity/institutional-portfolio/citadel",
                }
            ],
        )

        assert rows[0].owner_name == "Citadel Advisors Llc"
        assert rows[0].shares_change == pytest.approx(-54125)
        assert rows[0].shares_change_percent == pytest.approx(-1.0)
        assert rows[0].market_value is None
        assert rows[0].url.startswith("https://www.nasdaq.com")

    def test_empty_raises(self, monkeypatch):
        """A symbol with no holders of that type is reported."""
        patch_data(monkeypatch, {})
        query = NasdaqInstitutionalOwnershipFetcher.transform_query({"symbol": "STAK"})

        with pytest.raises(EmptyDataError, match="institutional holders"):
            asyncio.run(NasdaqInstitutionalOwnershipFetcher.aextract_data(query, None))


class TestHistoricalDividends:
    """Cover the dividend history model."""

    @staticmethod
    def _payload():
        """Return a two-dividend payload."""
        return {
            "dividends": {
                "rows": [
                    {
                        "exOrEffDate": "08/08/2026",
                        "type": "Cash",
                        "amount": "$0.26",
                        "declarationDate": "07/31/2026",
                        "recordDate": "08/11/2026",
                        "paymentDate": "08/14/2026",
                    },
                    {
                        "exOrEffDate": "05/09/2026",
                        "type": "Cash",
                        "amount": "$0.25",
                        "declarationDate": "05/01/2026",
                        "recordDate": "05/12/2026",
                        "paymentDate": "05/15/2026",
                    },
                ]
            }
        }

    def test_transforms_and_filters(self, monkeypatch):
        """The window narrows the published history."""
        patch_asset_class(monkeypatch, "stocks")
        patch_data(monkeypatch, self._payload())
        query = NasdaqHistoricalDividendsFetcher.transform_query({"symbol": "AAPL"})
        raw = asyncio.run(NasdaqHistoricalDividendsFetcher.aextract_data(query, None))
        rows = NasdaqHistoricalDividendsFetcher.transform_data(query, raw)

        assert len(rows) == 2

        query = NasdaqHistoricalDividendsFetcher.transform_query(
            {"symbol": "AAPL", "start_date": date(2026, 7, 1)}
        )

        assert len(NasdaqHistoricalDividendsFetcher.transform_data(query, raw)) == 1

        query = NasdaqHistoricalDividendsFetcher.transform_query(
            {"symbol": "AAPL", "end_date": date(2026, 6, 1)}
        )

        assert len(NasdaqHistoricalDividendsFetcher.transform_data(query, raw)) == 1

    def test_labels_multiple_symbols(self, monkeypatch):
        """The symbol column appears when more than one is requested."""
        patch_asset_class(monkeypatch, "stocks")
        patch_data(monkeypatch, lambda path: self._payload())
        query = NasdaqHistoricalDividendsFetcher.transform_query(
            {"symbol": "AAPL,MSFT"}
        )
        raw = asyncio.run(NasdaqHistoricalDividendsFetcher.aextract_data(query, None))

        assert {r["symbol"] for r in raw} == {"AAPL", "MSFT"}

    def test_warns_and_raises_when_empty(self, monkeypatch):
        """A symbol with no dividends warns and reports."""
        patch_asset_class(monkeypatch, "stocks")

        async def _data(path, **kwargs):
            raise OpenBBError("no dividends")

        monkeypatch.setattr("openbb_nasdaq.utils.helpers.get_nasdaq_data", _data)
        query = NasdaqHistoricalDividendsFetcher.transform_query({"symbol": "NOPE"})

        with pytest.warns(UserWarning, match="NOPE"), pytest.raises(EmptyDataError):
            asyncio.run(NasdaqHistoricalDividendsFetcher.aextract_data(query, None))


class TestPriceTargetConsensusFailure:
    """Cover the consensus gather failure path."""

    def test_warns_when_the_gather_fails(self, monkeypatch):
        """A failure collecting the payloads warns and skips the symbol."""
        real_gather = asyncio.gather

        async def _gather(*coroutines, **kwargs):
            for coroutine in coroutines:
                coroutine.close()

            raise OSError("connection reset")

        def _patched(*coroutines, **kwargs):
            if kwargs.get("return_exceptions"):
                return _gather(*coroutines, **kwargs)

            return real_gather(*coroutines, **kwargs)

        monkeypatch.setattr(asyncio, "gather", _patched)
        query = NasdaqPriceTargetConsensusFetcher.transform_query({"symbol": "AAPL"})

        with pytest.warns(UserWarning, match="AAPL"), pytest.raises(EmptyDataError):
            asyncio.run(NasdaqPriceTargetConsensusFetcher.aextract_data(query, None))


class TestHistoricalDividendsValidators:
    """Cover the dividend field validators."""

    def test_blank_dates_become_none(self):
        """Nasdaq's blank and placeholder date cells become None."""
        from openbb_nasdaq.models.historical_dividends import (
            NasdaqHistoricalDividendsData,
        )

        row = NasdaqHistoricalDividendsData.model_validate(
            {
                "exOrEffDate": "08/08/2026",
                "type": "Cash",
                "amount": "$0.26",
                "declarationDate": "",
                "recordDate": "N/A",
                "paymentDate": "08/14/2026",
            }
        )

        assert row.amount == pytest.approx(0.26)
        assert row.declaration_date is None
        assert row.record_date is None
        assert row.payment_date == date(2026, 8, 14)
