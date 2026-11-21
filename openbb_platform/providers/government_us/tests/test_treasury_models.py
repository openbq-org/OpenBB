"""Tests for the US Treasury models."""

import asyncio
import warnings
from datetime import date, timedelta

import pytest
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.utils import helpers as core_helpers
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import ValidationError

from openbb_government_us.treasury.models import (
    auction_results,
    bill_offerings,
    daily_treasury_statement,
    debt_to_penny,
    treasury_auctions,
    treasury_prices,
    upcoming_auctions,
    usaspending_award,
)
from openbb_government_us.treasury.utils import usaspending


def _capture_fetch(monkeypatch, rows):
    """Patch get_fiscal_data to record its arguments and return canned rows."""
    captured: dict = {}

    async def _fake(endpoint, filters=None, sort=None, **kwargs):
        captured["endpoint"] = endpoint
        captured["filters"] = filters
        captured["sort"] = sort
        return rows

    monkeypatch.setattr(
        "openbb_government_us.treasury.utils.fiscal_data.get_fiscal_data", _fake
    )
    return captured


class TestDebtToPenny:
    """Tests for the DebtToPenny fetcher."""

    def test_transform_query_defaults(self):
        """Default query has no date bounds."""
        query = debt_to_penny.DebtToPennyFetcher.transform_query({})
        assert query.start_date is None
        assert query.end_date is None

    def test_transform_query_coerces_dates(self):
        """ISO date strings coerce to date objects."""
        query = debt_to_penny.DebtToPennyFetcher.transform_query(
            {"start_date": "2025-01-01", "end_date": "2025-06-30"}
        )
        assert query.start_date == date(2025, 1, 1)
        assert query.end_date == date(2025, 6, 30)

    def test_extract_data_builds_date_filters(self, monkeypatch):
        """Date bounds become record_date gte/lte filters sorted by record_date."""
        captured = _capture_fetch(monkeypatch, [{"record_date": "2025-01-02"}])
        query = debt_to_penny.DebtToPennyFetcher.transform_query(
            {"start_date": "2025-01-01", "end_date": "2025-06-30"}
        )
        rows = asyncio.run(debt_to_penny.DebtToPennyFetcher.aextract_data(query, None))
        assert rows == [{"record_date": "2025-01-02"}]
        assert captured["endpoint"] == "v2/accounting/od/debt_to_penny"
        assert captured["filters"] == (
            "record_date:gte:2025-01-01,record_date:lte:2025-06-30"
        )
        assert captured["sort"] == "record_date"

    def test_extract_data_defaults_to_trailing_window(self, monkeypatch):
        """No start date defaults to a bounded trailing-365-day record filter."""
        captured = _capture_fetch(monkeypatch, [{"record_date": "2025-01-02"}])
        query = debt_to_penny.DebtToPennyFetcher.transform_query({})
        asyncio.run(debt_to_penny.DebtToPennyFetcher.aextract_data(query, None))
        expected = date.today() - timedelta(days=365)
        assert captured["filters"] == f"record_date:gte:{expected}"

    def test_transform_data_whitelists_and_parses(self):
        """Only model fields survive, string amounts parse, newest row leads."""
        rows = [
            {
                "record_date": "2025-01-02",
                "debt_held_public_amt": "28831964741779.76",
                "intragov_hold_amt": "7337992876980.45",
                "tot_pub_debt_out_amt": "36169957618760.21",
                "src_line_nbr": "1",
                "record_fiscal_year": "2025",
            },
            {
                "record_date": "2004-12-31",
                "debt_held_public_amt": None,
                "intragov_hold_amt": None,
                "tot_pub_debt_out_amt": "7596142802424.14",
            },
        ]
        query = debt_to_penny.DebtToPennyFetcher.transform_query({})
        result = debt_to_penny.DebtToPennyFetcher.transform_data(query, rows)
        assert result[0].date == date(2025, 1, 2)
        assert result[0].debt_held_public == 28831964741779.76
        assert result[0].intragovernmental_holdings == 7337992876980.45
        assert result[0].total_public_debt_outstanding == 36169957618760.21
        assert "src_line_nbr" not in result[0].model_dump()
        assert "record_fiscal_year" not in result[0].model_dump()
        assert "record_date" not in result[0].model_dump()
        assert result[1].debt_held_public is None
        assert result[1].intragovernmental_holdings is None

    def test_transform_data_sorts_newest_first(self):
        """The most recent business day leads the series."""
        rows = [
            {"record_date": "2004-12-31", "tot_pub_debt_out_amt": "1"},
            {"record_date": "2025-01-02", "tot_pub_debt_out_amt": "2"},
            {"record_date": "2015-06-30", "tot_pub_debt_out_amt": "3"},
        ]
        query = debt_to_penny.DebtToPennyFetcher.transform_query({})
        result = debt_to_penny.DebtToPennyFetcher.transform_data(query, rows)
        assert [str(item.date) for item in result] == [
            "2025-01-02",
            "2015-06-30",
            "2004-12-31",
        ]

    def test_date_leads_the_columns(self):
        """The observation date is the first, pinned column."""
        fields = list(debt_to_penny.DebtToPennyData.model_fields)
        assert fields[0] == "date"
        assert debt_to_penny.DebtToPennyData.model_fields["date"].json_schema_extra == {
            "x-widget_config": {"pinned": "left"}
        }


def _dts_row(table: str, **overrides) -> dict:
    """Build a synthetic source row covering every mapped key of a DTS table."""
    row = {
        "record_date": "2025-07-11",
        "table_nbr": "I",
        "table_nm": "Table Name",
        "src_line_nbr": "1",
    }
    for source, target in daily_treasury_statement.FIELD_MAP[table].items():
        if source in row:
            continue
        if target in daily_treasury_statement.AMOUNT_FIELDS:
            row[source] = "2.5"
        else:
            row[source] = f"{source}_value"
    row["extra_key"] = "ignored"
    row.update(overrides)
    return row


def _dts_label(table: str) -> str:
    """Build the pivoted column label of a synthetic row of a DTS table."""
    inverse = {
        target: source
        for source, target in daily_treasury_statement.FIELD_MAP[table].items()
    }
    return " - ".join(
        f"{inverse[dimension]}_value"
        for dimension in daily_treasury_statement.PIVOT_DIMS[table]
    )


def _dts_values(table: str) -> list[str]:
    """List the amount fields a DTS table reports, in published order."""
    return [
        target
        for target in daily_treasury_statement.FIELD_MAP[table].values()
        if target in daily_treasury_statement.AMOUNT_FIELDS
    ]


class TestDailyTreasuryStatement:
    """Tests for the DailyTreasuryStatement fetcher."""

    def test_transform_query_defaults(self):
        """The default table is operating_cash_balance with no date bounds."""
        fetcher = daily_treasury_statement.DailyTreasuryStatementFetcher
        query = fetcher.transform_query({})
        assert query.table == "operating_cash_balance"
        assert query.start_date is None
        assert query.end_date is None

    def test_transform_query_rejects_unknown_table(self):
        """An unknown table name fails validation."""
        fetcher = daily_treasury_statement.DailyTreasuryStatementFetcher
        with pytest.raises(ValidationError):
            fetcher.transform_query({"table": "not_a_table"})

    def test_extract_data_appends_table_to_endpoint(self, monkeypatch):
        """The table name extends the endpoint and dates become filters."""
        captured = _capture_fetch(monkeypatch, [{"record_date": "2025-06-02"}])
        fetcher = daily_treasury_statement.DailyTreasuryStatementFetcher
        query = fetcher.transform_query(
            {
                "table": "public_debt_transactions",
                "start_date": "2025-06-01",
                "end_date": "2025-06-30",
            }
        )
        asyncio.run(fetcher.aextract_data(query, None))
        assert captured["endpoint"] == "v1/accounting/dts/public_debt_transactions"
        assert captured["filters"] == (
            "record_date:gte:2025-06-01,record_date:lte:2025-06-30"
        )
        assert captured["sort"] == "record_date"

    @pytest.mark.parametrize("table", sorted(daily_treasury_statement.FIELD_MAP))
    def test_transform_data_per_table(self, table):
        """Each table pivots to one row per date, with expanded amounts."""
        fetcher = daily_treasury_statement.DailyTreasuryStatementFetcher
        mapping = daily_treasury_statement.FIELD_MAP[table]
        amount_fields = daily_treasury_statement.AMOUNT_FIELDS
        values = _dts_values(table)
        row = _dts_row(table)
        none_source = next(
            source
            for source, target in sorted(mapping.items())
            if target in amount_fields
        )
        row[none_source] = None
        query = fetcher.transform_query(
            {"table": table, "sub_table": "all", "amount_basis": "all"}
        )
        result = fetcher.transform_data(query, [row])
        item = result[0]
        dumped = item.model_dump()
        label = _dts_label(table)
        assert item.date == date(2025, 7, 11)
        assert "extra_key" not in dumped
        assert list(dumped)[0] == "date"
        for target in mapping.values():
            if target != "date":
                assert target not in dumped
        for target in values:
            column = f"{label} ({daily_treasury_statement.VALUE_LABELS[target]})"
            if target == mapping[none_source]:
                assert column not in dumped
            else:
                assert dumped[column] == 2500000.0

    def test_transform_data_one_row_per_date(self):
        """Line items become columns and each date collapses to one row."""
        fetcher = daily_treasury_statement.DailyTreasuryStatementFetcher
        query = fetcher.transform_query({"table": "operating_cash_balance"})
        rows = [
            _dts_row("operating_cash_balance", account_type="Opening Balance"),
            _dts_row("operating_cash_balance", account_type="Closing Balance"),
            _dts_row(
                "operating_cash_balance",
                record_date="2025-07-10",
                account_type="Opening Balance",
                open_today_bal="1.5",
            ),
        ]
        result = fetcher.transform_data(query, rows)
        assert len(result) == 2
        assert [str(item.date) for item in result] == ["2025-07-11", "2025-07-10"]
        latest = result[0].model_dump()
        assert latest["Opening Balance (Open Today)"] == 2500000.0
        assert latest["Closing Balance (Open Today)"] == 2500000.0
        assert result[1].model_dump()["Opening Balance (Open Today)"] == 1500000.0

    def test_transform_data_drops_constant_dimensions(self):
        """A dimension with a single value is left out of the column label."""
        fetcher = daily_treasury_statement.DailyTreasuryStatementFetcher
        query = fetcher.transform_query({"table": "operating_cash_balance"})
        rows = [
            _dts_row(
                "operating_cash_balance",
                sub_table_name="Cash Balance Details",
                account_type=name,
            )
            for name in ("Opening Balance", "Closing Balance")
        ]
        dumped = fetcher.transform_data(query, rows)[0].model_dump()
        assert "Opening Balance (Open Today)" in dumped
        assert "Cash Balance Details" not in str(list(dumped))

    def test_transform_data_skips_missing_source_keys(self):
        """A mapped key absent from the row serves no column for it."""
        fetcher = daily_treasury_statement.DailyTreasuryStatementFetcher
        row = _dts_row("operating_cash_balance")
        del row["close_today_bal"]
        query = fetcher.transform_query({"table": "operating_cash_balance"})
        dumped = fetcher.transform_data(query, [row])[0].model_dump()
        label = _dts_label("operating_cash_balance")
        assert f"{label} (Close Today)" not in dumped
        assert dumped[f"{label} (Open Today)"] == 2500000.0


def _deposits_row(category: str, amount: str, **overrides) -> dict:
    """Build a Table II source row for one line item."""
    fields = {
        "account_type": "Treasury General Account (TGA)",
        "transaction_type": "Deposits",
        "transaction_catg": category,
        "transaction_catg_desc": None,
        "transaction_today_amt": amount,
        "transaction_mtd_amt": amount,
        "transaction_fytd_amt": amount,
    }
    fields.update(overrides)
    return _dts_row("deposits_withdrawals_operating_cash", **fields)


class TestDailyTreasuryStatementSubTable:
    """Tests for the DTS sub-table selector and column budget."""

    def test_every_table_declares_a_sub_table_field(self):
        """A table with no sub-table dimension has no dropdown to offer."""
        assert set(daily_treasury_statement.SUB_TABLE_FIELD) == set(
            daily_treasury_statement.FIELD_MAP
        )
        for table, field in daily_treasury_statement.SUB_TABLE_FIELD.items():
            assert field in daily_treasury_statement.PIVOT_DIMS[table]
            assert field in daily_treasury_statement.FIELD_MAP[table].values()

    def test_resolve_sub_table_prefers_the_request(self):
        """An explicit selection wins over the table's default."""
        resolve = daily_treasury_statement.resolve_sub_table
        assert resolve("deposits_withdrawals_operating_cash", "Withdrawals") == (
            "Withdrawals"
        )
        assert resolve("deposits_withdrawals_operating_cash", None) == "Deposits"
        assert resolve("public_debt_transactions", None) == "Issues"
        assert resolve("operating_cash_balance", None) == "all"

    def test_blank_sub_table_falls_back_to_the_default(self):
        """A blank selection is the same as none at all."""
        fetcher = daily_treasury_statement.DailyTreasuryStatementFetcher
        query = fetcher.transform_query(
            {"table": "deposits_withdrawals_operating_cash", "sub_table": "  "}
        )
        assert query.sub_table is None

    def test_default_sub_table_filters_the_records(self):
        """Only the default sub-table's line items become columns."""
        fetcher = daily_treasury_statement.DailyTreasuryStatementFetcher
        query = fetcher.transform_query(
            {"table": "deposits_withdrawals_operating_cash"}
        )
        rows = [
            _deposits_row("Taxes - Corporate Income", "1"),
            _deposits_row(
                "Interest on Treasury Securities", "2", transaction_type="Withdrawals"
            ),
        ]
        dumped = fetcher.transform_data(query, rows)[0].model_dump()
        served = "Treasury General Account (TGA) - Taxes - Corporate Income"
        assert served in dumped
        assert "Interest on Treasury Securities" not in str(list(dumped))

    def test_selected_sub_table_drops_out_of_the_labels(self):
        """A sub-table filtered to one value stops repeating in every column."""
        fetcher = daily_treasury_statement.DailyTreasuryStatementFetcher
        query = fetcher.transform_query(
            {
                "table": "deposits_withdrawals_operating_cash",
                "sub_table": "Withdrawals",
            }
        )
        rows = [
            _deposits_row("Taxes - Corporate Income", "1"),
            _deposits_row(
                "Interest on Treasury Securities", "2", transaction_type="Withdrawals"
            ),
        ]
        dumped = fetcher.transform_data(query, rows)[0].model_dump()
        served = "Treasury General Account (TGA) - Interest on Treasury Securities"
        assert served in dumped
        assert "Withdrawals" not in str(list(dumped))

    def test_all_sub_tables_keeps_every_record(self):
        """The 'all' selection restores the combined view."""
        fetcher = daily_treasury_statement.DailyTreasuryStatementFetcher
        query = fetcher.transform_query(
            {"table": "deposits_withdrawals_operating_cash", "sub_table": "all"}
        )
        rows = [
            _deposits_row("Taxes - Corporate Income", "1"),
            _deposits_row(
                "Interest on Treasury Securities", "2", transaction_type="Withdrawals"
            ),
        ]
        dumped = fetcher.transform_data(query, rows)[0].model_dump()
        assert "Deposits - Taxes - Corporate Income" in dumped
        assert "Withdrawals - Interest on Treasury Securities" in dumped

    def test_unknown_sub_table_names_the_available_ones(self):
        """A selection the table never publishes fails with the real choices."""
        fetcher = daily_treasury_statement.DailyTreasuryStatementFetcher
        query = fetcher.transform_query(
            {"table": "deposits_withdrawals_operating_cash", "sub_table": "Issues"}
        )
        with pytest.raises(EmptyDataError, match="Deposits, Withdrawals"):
            fetcher.transform_data(
                query,
                [
                    _deposits_row("Taxes - Corporate Income", "1"),
                    _deposits_row("Unclassified", "2", transaction_type="Withdrawals"),
                ],
            )

    def test_budget_that_fits_raises_no_warning(self):
        """A selection inside the budget is served whole and quietly."""
        fetcher = daily_treasury_statement.DailyTreasuryStatementFetcher
        query = fetcher.transform_query({"table": "operating_cash_balance"})
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            dumped = fetcher.transform_data(
                query, [_dts_row("operating_cash_balance")]
            )[0].model_dump()
        assert len(dumped) == 5

    def test_sub_table_options_put_the_default_first(self, monkeypatch):
        """The dropdown leads with the selection the fetcher applies."""
        _capture_fetch(
            monkeypatch,
            [
                _deposits_row("Taxes - Corporate Income", "1"),
                _deposits_row("Unclassified", "2", transaction_type="Withdrawals"),
            ],
        )
        options = asyncio.run(
            daily_treasury_statement.sub_table_options(
                "deposits_withdrawals_operating_cash"
            )
        )
        assert options == [
            {"label": "Deposits", "value": "Deposits"},
            {"label": "Withdrawals", "value": "Withdrawals"},
            {"label": "All Sub-Tables", "value": "all"},
        ]

    def test_sub_table_options_anchor_discontinued_tables(self, monkeypatch):
        """A frozen table lists its sub-tables from its final publication."""
        captured = _capture_fetch(
            monkeypatch, [_dts_row("federal_tax_deposits", sub_table_name="Class")]
        )
        options = asyncio.run(
            daily_treasury_statement.sub_table_options("federal_tax_deposits")
        )
        assert captured["endpoint"] == "v1/accounting/dts/federal_tax_deposits"
        assert captured["filters"] == (
            "record_date:gte:2023-01-14,record_date:lte:2023-02-13"
        )
        assert options == [
            {"label": "All Sub-Tables", "value": "all"},
            {"label": "Class", "value": "Class"},
        ]

    def test_sub_table_options_reject_an_unknown_table(self):
        """An unknown table has no sub-tables to list."""
        assert asyncio.run(daily_treasury_statement.sub_table_options("nope")) == []


def _upcoming_row(**overrides) -> dict:
    """Build an upcoming-auctions source row with optional overrides."""
    row = {
        "record_date": "2024-03-08",
        "security_type": "Bill",
        "security_term": "8-Week",
        "reopening": "Yes",
        "cusip": "912797JW8",
        "offering_amt": "90000000000",
        "announcemt_date": "2024-03-12",
        "auction_date": "2024-03-14",
        "issue_date": "2024-03-19",
    }
    row.update(overrides)
    return row


class TestUpcomingTreasuryAuctions:
    """Tests for the UpcomingTreasuryAuctions fetcher."""

    def test_transform_query_defaults(self):
        """The default query does not filter by security type."""
        fetcher = upcoming_auctions.UpcomingTreasuryAuctionsFetcher
        assert fetcher.transform_query({}).security_type is None

    def test_transform_query_rejects_unknown_type(self):
        """An unknown security type fails validation."""
        fetcher = upcoming_auctions.UpcomingTreasuryAuctionsFetcher
        with pytest.raises(ValidationError):
            fetcher.transform_query({"security_type": "swap"})

    def test_extract_data_uses_bare_endpoint(self, monkeypatch):
        """The full table is requested with no filters or sort."""
        captured = _capture_fetch(monkeypatch, [_upcoming_row()])
        fetcher = upcoming_auctions.UpcomingTreasuryAuctionsFetcher
        query = fetcher.transform_query({"security_type": "bill"})
        rows = asyncio.run(fetcher.aextract_data(query, None))
        assert rows == [_upcoming_row()]
        assert captured["endpoint"] == "v1/accounting/od/upcoming_auctions"
        assert captured["filters"] is None
        assert captured["sort"] is None

    def test_transform_data_keeps_latest_snapshot(self):
        """Only rows from the latest record_date survive, sorted by dates."""
        fetcher = upcoming_auctions.UpcomingTreasuryAuctionsFetcher
        rows = [
            _upcoming_row(record_date="2024-03-01", cusip="OLD"),
            _upcoming_row(
                cusip="LATER",
                auction_date="2024-03-15",
                reopening="No",
                offering_amt=None,
            ),
            _upcoming_row(cusip="SOONER", auction_date="2024-03-13"),
        ]
        result = fetcher.transform_data(fetcher.transform_query({}), rows)
        assert [item.cusip for item in result] == ["SOONER", "LATER"]
        assert result[0].as_of_date == date(2024, 3, 8)
        assert result[0].reopening is True
        assert result[0].offering_amount == 90000000000.0
        assert result[0].announcement_date == date(2024, 3, 12)
        assert result[1].reopening is False
        assert result[1].offering_amount is None

    @pytest.mark.parametrize(
        ("security_type", "label"),
        [
            ("bill", "Bill"),
            ("note", "Note"),
            ("bond", "Bond"),
            ("cmb", "CMB"),
            ("frn", "FRN Note"),
            ("tips", "TIPS Note"),
        ],
    )
    def test_transform_data_security_type_filter(self, security_type, label):
        """Each security_type value maps to its published label."""
        fetcher = upcoming_auctions.UpcomingTreasuryAuctionsFetcher
        rows = [
            _upcoming_row(security_type=name, cusip=name)
            for name in upcoming_auctions.SECURITY_TYPE_MAP.values()
        ]
        query = fetcher.transform_query({"security_type": security_type})
        result = fetcher.transform_data(query, rows)
        assert [item.security_type for item in result] == [label]

    def test_transform_data_empty_filter_raises(self):
        """A filter that empties the latest snapshot raises EmptyDataError."""
        from openbb_core.provider.utils.errors import EmptyDataError

        fetcher = upcoming_auctions.UpcomingTreasuryAuctionsFetcher
        query = fetcher.transform_query({"security_type": "bond"})
        with pytest.raises(EmptyDataError, match="bond"):
            fetcher.transform_data(query, [_upcoming_row()])

    def test_auction_date_leads_the_columns(self):
        """The auction date leads, and the constant snapshot date trails."""
        fields = list(upcoming_auctions.UpcomingTreasuryAuctionsData.model_fields)
        assert fields[0] == "auction_date"
        assert fields[-1] == "as_of_date"

    def test_snapshot_date_is_hidden_not_served(self):
        """The constant snapshot date is renamed and hidden from the grid."""
        fields = upcoming_auctions.UpcomingTreasuryAuctionsData.model_fields
        assert "record_date" not in fields
        extra = fields["as_of_date"].json_schema_extra
        assert extra["x-widget_config"]["hide"] is True

    def test_no_other_column_is_constant(self):
        """Every column other than the hidden snapshot date varies across rows."""
        fetcher = upcoming_auctions.UpcomingTreasuryAuctionsFetcher
        rows = [
            _upcoming_row(),
            _upcoming_row(
                security_type="Note",
                security_term="2-Year",
                cusip="91282CRB9",
                offering_amt=None,
                reopening="No",
                announcemt_date="2024-03-13",
                auction_date="2024-03-15",
                issue_date="2024-03-20",
            ),
        ]
        dumped = [
            item.model_dump()
            for item in fetcher.transform_data(fetcher.transform_query({}), rows)
        ]
        constant = [
            column
            for column in dumped[0]
            if len({str(item[column]) for item in dumped}) == 1
        ]
        assert constant == ["as_of_date"]

    def test_served_columns_carry_no_source_slugs(self):
        """The source's abbreviated keys do not reach the served columns."""
        fetcher = upcoming_auctions.UpcomingTreasuryAuctionsFetcher
        dumped = fetcher.transform_data(fetcher.transform_query({}), [_upcoming_row()])[
            0
        ].model_dump(by_alias=True)
        assert "announcemt_date" not in dumped
        assert "offering_amt" not in dumped
        assert dumped["announcement_date"] == date(2024, 3, 12)
        assert dumped["offering_amount"] == 90000000000.0


def _auction_result_row(**overrides) -> dict:
    """Build an auction-results source row with optional overrides."""
    row = {
        "record_date": "2026-01-08",
        "cusip": "912797SL2",
        "security_type": "Bill",
        "security_term": "13-Week",
        "auction_date": "2026-01-05",
        "issue_date": "2026-01-08",
        "maturity_date": "2026-04-09",
        "announcemt_date": "2025-12-31",
        "price_per100": "99.105167",
        "allocation_pctage": "77.130000",
        "allocation_pctage_decimals": "2",
        "auction_format": "Single-Price",
        "avg_med_discnt_rate": "3.515000",
        "avg_med_yield": None,
        "bid_to_cover_ratio": "2.840000",
        "cash_management_bill_cmb": "No",
        "comp_accepted": "81948440600",
        "comp_tenders_accepted": "Yes",
        "floating_rate": "No",
        "high_discnt_rate": "3.540000",
        "high_investment_rate": "3.622000",
        "high_price": "99.105167",
        "int_rate": None,
        "low_discnt_rate": "3.440000",
        "offering_amt": "86000000000",
        "reopening": "Yes",
        "inflation_index_security": "No",
        "spread": None,
        "total_accepted": "90430132400",
        "total_tendered": "248267933200",
    }
    row.update(overrides)
    return row


class TestTreasuryAuctionResults:
    """Tests for the TreasuryAuctionResults fetcher."""

    def test_transform_query_defaults(self):
        """The default query has no filters at all."""
        fetcher = auction_results.TreasuryAuctionResultsFetcher
        query = fetcher.transform_query({})
        assert query.start_date is None
        assert query.end_date is None
        assert query.security_type is None
        assert query.cusip is None

    def test_transform_query_rejects_unknown_type(self):
        """An unknown security type fails validation."""
        fetcher = auction_results.TreasuryAuctionResultsFetcher
        with pytest.raises(ValidationError):
            fetcher.transform_query({"security_type": "tips"})

    def test_extract_data_defaults_to_trailing_window(self, monkeypatch):
        """No dates or CUSIP defaults to a bounded trailing-365-day auction filter."""
        captured = _capture_fetch(monkeypatch, [_auction_result_row()])
        fetcher = auction_results.TreasuryAuctionResultsFetcher
        asyncio.run(fetcher.aextract_data(fetcher.transform_query({}), None))
        assert captured["endpoint"] == "v1/accounting/od/auctions_query"
        expected = date.today() - timedelta(days=365)
        assert captured["filters"] == f"auction_date:gte:{expected}"
        assert captured["sort"] == "auction_date"

    def test_extract_data_cusip_reaches_full_history(self, monkeypatch):
        """A CUSIP query skips the trailing default so its full history returns."""
        captured = _capture_fetch(monkeypatch, [_auction_result_row()])
        fetcher = auction_results.TreasuryAuctionResultsFetcher
        query = fetcher.transform_query({"cusip": "912797SL2"})
        asyncio.run(fetcher.aextract_data(query, None))
        assert captured["filters"] == "cusip:eq:912797SL2"

    def test_extract_data_single_cusip_uses_eq(self, monkeypatch):
        """One CUSIP builds an eq condition."""
        captured = _capture_fetch(monkeypatch, [_auction_result_row()])
        fetcher = auction_results.TreasuryAuctionResultsFetcher
        query = fetcher.transform_query({"cusip": "912797SL2"})
        asyncio.run(fetcher.aextract_data(query, None))
        assert captured["filters"] == "cusip:eq:912797SL2"

    def test_extract_data_cusip_list_uses_in(self, monkeypatch):
        """A comma-separated CUSIP list is stripped and wrapped as an in list."""
        captured = _capture_fetch(monkeypatch, [_auction_result_row()])
        fetcher = auction_results.TreasuryAuctionResultsFetcher
        query = fetcher.transform_query({"cusip": "912797SL2, 912796YT4"})
        asyncio.run(fetcher.aextract_data(query, None))
        assert captured["filters"] == "cusip:in:(912797SL2,912796YT4)"

    def test_extract_data_dates_and_capitalized_type(self, monkeypatch):
        """Date bounds filter auction_date and security_type is capitalized."""
        captured = _capture_fetch(monkeypatch, [_auction_result_row()])
        fetcher = auction_results.TreasuryAuctionResultsFetcher
        query = fetcher.transform_query(
            {
                "start_date": "2020-01-01",
                "end_date": "2020-12-31",
                "security_type": "bond",
            }
        )
        asyncio.run(fetcher.aextract_data(query, None))
        assert captured["filters"] == (
            "auction_date:gte:2020-01-01,auction_date:lte:2020-12-31,"
            "security_type:eq:Bond"
        )

    def test_transform_data_normalizes_percent_fields(self):
        """Percent fields divide by 100 while other numerics pass through."""
        fetcher = auction_results.TreasuryAuctionResultsFetcher
        query = fetcher.transform_query({})
        item = fetcher.transform_data(query, [_auction_result_row()])[0]
        assert item.high_discount_rate == 3.54 / 100
        assert item.high_investment_rate == 3.622 / 100
        assert item.low_discount_rate == 3.44 / 100
        assert item.avg_median_discount_rate == 3.515 / 100
        assert item.allocation_percentage == 77.13 / 100
        assert item.interest_rate is None
        assert item.spread is None
        assert item.avg_median_yield is None
        assert item.high_price == 99.105167
        assert item.price_per_100 == 99.105167
        assert item.bid_to_cover_ratio == 2.84
        assert item.total_accepted == 90430132400.0

    def test_transform_data_normalizes_single_price(self):
        """The legacy 'Single Price' label becomes 'Single-Price'."""
        fetcher = auction_results.TreasuryAuctionResultsFetcher
        query = fetcher.transform_query({})
        rows = [
            _auction_result_row(auction_format="Single Price"),
            _auction_result_row(auction_format="Multi-Price"),
        ]
        result = fetcher.transform_data(query, rows)
        assert result[0].auction_format == "Single-Price"
        assert result[1].auction_format == "Multi-Price"

    def test_transform_data_sorts_newest_auction_first(self):
        """The most recent auction leads the series."""
        fetcher = auction_results.TreasuryAuctionResultsFetcher
        query = fetcher.transform_query({})
        rows = [
            _auction_result_row(auction_date="2026-01-05"),
            _auction_result_row(auction_date="2026-02-09"),
            _auction_result_row(auction_date="2025-12-01"),
        ]
        result = fetcher.transform_data(query, rows)
        assert [str(item.auction_date) for item in result] == [
            "2026-02-09",
            "2026-01-05",
            "2025-12-01",
        ]

    def test_auction_date_leads_the_columns(self):
        """The auction date is the first, pinned column."""
        fields = list(auction_results.TreasuryAuctionResultsData.model_fields)
        assert fields[0] == "auction_date"
        assert auction_results.TreasuryAuctionResultsData.model_fields[
            "auction_date"
        ].json_schema_extra == {"x-widget_config": {"pinned": "left"}}

    def test_served_columns_carry_no_source_slugs(self):
        """Abbreviated source keys are validation aliases, not served columns."""
        fetcher = auction_results.TreasuryAuctionResultsFetcher
        query = fetcher.transform_query({})
        dumped = fetcher.transform_data(query, [_auction_result_row()])[0].model_dump(
            by_alias=True
        )
        for slug in ("price_per100", "allocation_pctage", "announcemt_date"):
            assert slug not in dumped
        assert dumped["price_per_100"] == 99.105167
        assert dumped["announcement_date"] == date(2025, 12, 31)

    def test_discontinued_columns_are_hidden(self):
        """Columns the source stopped publishing are not shown by default."""
        fields = auction_results.TreasuryAuctionResultsData.model_fields
        for name in ("avg_median_price", "low_price", "call_date", "called_date"):
            assert fields[name].json_schema_extra == {"x-widget_config": {"hide": True}}

    def test_transform_data_whitelists_and_coerces(self):
        """Non-model keys drop and Yes/No strings coerce to booleans."""
        fetcher = auction_results.TreasuryAuctionResultsFetcher
        query = fetcher.transform_query({})
        item = fetcher.transform_data(query, [_auction_result_row()])[0]
        dumped = item.model_dump()
        assert "record_date" not in dumped
        assert item.reopening is True
        assert item.cash_management_bill is False
        assert item.floating_rate is False
        assert item.inflation_index_security is False
        assert item.competitive_tenders_accepted is True
        assert item.allocation_percentage_decimals == 2
        assert item.announcement_date == date(2025, 12, 31)


def _bill_offering_row(**overrides) -> dict:
    """Build a PDO-1 source row with optional overrides."""
    row = {
        "record_date": "2026-06-01",
        "issue_date": "2026-03-03",
        "maturity_date": "2026-03-31",
        "days_to_maturity": "28",
        "bids_tendered_mil_amt": "304637.3",
        "bids_acc_total_mil_amt": "106808.4",
        "bids_acc_comp_basis_mil_amt": "97061.5",
        "bids_acc_noncomp_basis_mil_amt": "5938.8",
        "high_price_per_hundred": "99.718056",
        "high_discount_rate": "3.625",
        "high_investment_rate": "3.686",
        "src_line_nbr": "52",
        "record_fiscal_year": "2026",
    }
    row.update(overrides)
    return row


class TestTreasuryBillOfferings:
    """Tests for the TreasuryBillOfferings fetcher."""

    def test_transform_query_defaults(self):
        """The default query has no date bounds."""
        fetcher = bill_offerings.TreasuryBillOfferingsFetcher
        query = fetcher.transform_query({})
        assert query.start_date is None
        assert query.end_date is None

    def test_extract_data_builds_issue_date_filters(self, monkeypatch):
        """Date bounds filter issue_date, sorted by issue date and line."""
        captured = _capture_fetch(monkeypatch, [{"record_date": "2026-06-01"}])
        fetcher = bill_offerings.TreasuryBillOfferingsFetcher
        query = fetcher.transform_query(
            {"start_date": "2026-03-01", "end_date": "2026-03-31"}
        )
        asyncio.run(fetcher.aextract_data(query, None))
        assert captured["endpoint"] == (
            "v1/accounting/tb/pdo1_offerings_regular_weekly_treasury_bills"
        )
        assert captured["filters"] == (
            "issue_date:gte:2026-03-01,issue_date:lte:2026-03-31"
        )
        assert captured["sort"] == "issue_date,src_line_nbr"

    def test_extract_data_defaults_to_trailing_window(self, monkeypatch):
        """No start date defaults to a bounded trailing-365-day issue filter."""
        captured = _capture_fetch(monkeypatch, [{"record_date": "2026-06-01"}])
        fetcher = bill_offerings.TreasuryBillOfferingsFetcher
        asyncio.run(fetcher.aextract_data(fetcher.transform_query({}), None))
        expected = date.today() - timedelta(days=365)
        assert captured["filters"] == f"issue_date:gte:{expected}"

    def test_transform_data_expands_and_normalizes(self):
        """Million amounts expand to dollars, rates divide by 100, extras drop."""
        fetcher = bill_offerings.TreasuryBillOfferingsFetcher
        item = fetcher.transform_data(
            fetcher.transform_query({}), [_bill_offering_row()]
        )[0]
        assert item.record_date == date(2026, 6, 1)
        assert item.issue_date == date(2026, 3, 3)
        assert item.maturity_date == date(2026, 3, 31)
        assert item.days_to_maturity == 28
        assert item.bids_tendered == 304637.3 * 1_000_000
        assert item.bids_accepted_total == 106808.4 * 1_000_000
        assert item.bids_accepted_competitive == 97061.5 * 1_000_000
        assert item.bids_accepted_noncompetitive == 5938.8 * 1_000_000
        assert item.high_price_per_hundred == 99.718056
        assert item.high_discount_rate == 3.625 / 100
        assert item.high_investment_rate == 3.686 / 100
        dumped = item.model_dump()
        assert "src_line_nbr" not in dumped
        assert "record_fiscal_year" not in dumped

    def test_issue_date_leads_and_sorts_newest_first(self):
        """The issue date leads the columns and the newest issue leads the rows."""
        fetcher = bill_offerings.TreasuryBillOfferingsFetcher
        fields = list(bill_offerings.TreasuryBillOfferingsData.model_fields)
        assert fields[0] == "issue_date"
        assert fields[-1] == "record_date"
        rows = [
            _bill_offering_row(issue_date="2026-03-03"),
            _bill_offering_row(issue_date="2026-03-17"),
            _bill_offering_row(issue_date="2026-02-24"),
        ]
        result = fetcher.transform_data(fetcher.transform_query({}), rows)
        assert [str(item.issue_date) for item in result] == [
            "2026-03-17",
            "2026-03-03",
            "2026-02-24",
        ]

    def test_served_columns_carry_no_source_slugs(self):
        """The source's 'mil_amt' keys do not reach the served columns."""
        fetcher = bill_offerings.TreasuryBillOfferingsFetcher
        dumped = fetcher.transform_data(
            fetcher.transform_query({}), [_bill_offering_row()]
        )[0].model_dump(by_alias=True)
        assert "bids_tendered_mil_amt" not in dumped
        assert dumped["bids_tendered"] == 304637.3 * 1_000_000


class TestUsSpendingAwardColumns:
    """Each award section serves only the columns it reports."""

    @staticmethod
    def _subawards() -> list[dict]:
        """Build source-shaped subaward rows."""
        return [
            {
                "id": 9850548,
                "subaward_number": "WS-16-C-0001",
                "description": "REIMBURSEMENT METHODOLOGY CHANGES",
                "action_date": "2025-03-07",
                "amount": 258312.0,
                "recipient_name": "WISCONSIN PHYSICIANS SERVICE INSURANCE CORP.",
                usaspending_award.SUBJECT_KEY: "CONT_AWD_HT940216C0001_9700",
            }
        ]

    @staticmethod
    def _funding(**overrides) -> dict:
        """Build a source-shaped funding row with optional overrides."""
        row = {
            "transaction_obligated_amount": 1000.0,
            "gross_outlay_amount": None,
            "disaster_emergency_fund_code": "Q",
            "federal_account": "075-0512",
            "account_title": "Defense Health Program",
            "funding_agency_name": "Department of Defense",
            "awarding_agency_name": "Department of Defense",
            "object_class": "25.1",
            "object_class_name": "Advisory and assistance services",
            "program_activity_code": "0001",
            "program_activity_name": "Private Sector Care",
            "reporting_fiscal_year": 2025,
            "reporting_fiscal_quarter": 2,
            "reporting_fiscal_month": 5,
            "is_quarterly_submission": False,
            usaspending_award.SUBJECT_KEY: "CONT_AWD_HT940216C0001_9700",
        }
        row.update(overrides)
        return row

    @staticmethod
    def _query(section: str):
        """Build a query for one section of the reference award."""
        return usaspending_award.UsSpendingAwardFetcher.transform_query(
            {"award_id": "CONT_AWD_HT940216C0001_9700", "section": section}
        )

    def test_unreported_fields_are_dropped(self):
        """The fields belonging to the other sections are not served."""
        fetcher = usaspending_award.UsSpendingAwardFetcher
        dumped = fetcher.transform_data(self._query("subawards"), self._subawards())[
            0
        ].model_dump()
        assert set(dumped) == {
            "action_date",
            "award_id",
            "subaward_id",
            "subaward_number",
            "amount",
            "recipient_name",
            "description",
        }

    def test_row_label_leads_and_description_trails(self):
        """The action date leads the columns and the long text trails."""
        fetcher = usaspending_award.UsSpendingAwardFetcher
        columns = list(
            fetcher.transform_data(self._query("subawards"), self._subawards())[
                0
            ].model_dump()
        )
        assert columns[0] == "action_date"
        assert columns[-1] == "description"

    def test_the_request_echo_is_not_served_as_a_column(self):
        """The requested section is constant on every row, so it is not a column."""
        fetcher = usaspending_award.UsSpendingAwardFetcher
        dumped = fetcher.transform_data(self._query("subawards"), self._subawards())[
            0
        ].model_dump()
        assert "section" not in dumped
        assert "section" not in usaspending_award.UsSpendingAwardData.model_fields

    def test_every_row_of_a_section_serves_one_key_set(self):
        """A field absent from one row is still served on it, as None."""
        fetcher = usaspending_award.UsSpendingAwardFetcher
        rows = [
            self._funding(),
            self._funding(program_activity_code=None, program_activity_name=None),
            self._funding(transaction_obligated_amount=None, gross_outlay_amount=-25.5),
        ]
        dumped = [
            item.model_dump()
            for item in fetcher.transform_data(self._query("funding"), rows)
        ]
        assert len({tuple(item) for item in dumped}) == 1
        assert dumped[1]["program_activity_code"] is None
        assert dumped[0]["program_activity_code"] == "0001"
        assert dumped[2]["gross_outlay_amount"] == -25.5
        assert dumped[0]["gross_outlay_amount"] is None

    def test_a_field_no_row_reports_is_not_served(self):
        """A field null on every row of the result is dropped from all of them."""
        fetcher = usaspending_award.UsSpendingAwardFetcher
        rows = [
            self._funding(disaster_emergency_fund_code=None),
            self._funding(disaster_emergency_fund_code=""),
        ]
        dumped = [
            item.model_dump()
            for item in fetcher.transform_data(self._query("funding"), rows)
        ]
        assert all("disaster_emergency_fund_code" not in item for item in dumped)
        assert all("federal_account" in item for item in dumped)

    def test_a_section_serves_only_its_declared_fields(self):
        """No section serves a column outside its FIELD_MAP, bar the award id."""
        fetcher = usaspending_award.UsSpendingAwardFetcher
        dumped = fetcher.transform_data(self._query("funding"), [self._funding()])[
            0
        ].model_dump()
        allowed = set(usaspending_award.FIELD_MAP["funding"].values()) | {"award_id"}
        assert set(dumped) <= allowed
        assert set(dumped) == allowed - {"gross_outlay_amount"}

    def test_an_empty_section_transforms_to_no_rows(self):
        """No source rows yields no records, and no served columns to order."""
        fetcher = usaspending_award.UsSpendingAwardFetcher
        assert fetcher.transform_data(self._query("funding"), []) == []


class TestUsSpendingAwardPaths:
    """Tests for the award source-path resolver and date truncation."""

    def test_walks_nested_objects(self):
        """A dotted path resolves through nested objects."""
        row = {"recipient": {"location": {"state_code": "KY"}}}
        assert usaspending_award._get_path(row, "recipient.location.state_code") == "KY"

    def test_indexes_a_list_segment(self):
        """A digit segment indexes into a list."""
        row = {"cfda_info": [{"cfda_number": "93.778"}, {"cfda_number": "93.779"}]}
        assert usaspending_award._get_path(row, "cfda_info.1.cfda_number") == "93.779"

    def test_an_index_past_the_end_is_missing(self):
        """Indexing past the end of a list yields MISSING, not an error."""
        row = {"cfda_info": []}
        assert (
            usaspending_award._get_path(row, "cfda_info.0.cfda_number")
            is usaspending_award.MISSING
        )

    def test_a_named_segment_against_a_list_is_missing(self):
        """A non-numeric segment cannot address a list, so it resolves to MISSING."""
        row = {"cfda_info": [{"cfda_number": "93.778"}]}
        assert (
            usaspending_award._get_path(row, "cfda_info.cfda_number")
            is usaspending_award.MISSING
        )

    def test_an_absent_key_is_missing(self):
        """A key the source omits yields MISSING, which is distinct from None."""
        assert (
            usaspending_award._get_path({"piid": None}, "fain")
            is usaspending_award.MISSING
        )
        assert usaspending_award._get_path({"piid": None}, "piid") is None

    def test_descending_into_a_scalar_is_missing(self):
        """A path that continues past a scalar yields MISSING."""
        assert (
            usaspending_award._get_path({"piid": "HT9402"}, "piid.value")
            is usaspending_award.MISSING
        )

    def test_truncates_a_timestamp_to_its_date(self):
        """Both the space and T separated timestamps keep only the date."""
        assert usaspending_award._to_date("2016-08-01 00:00:00") == "2016-08-01"
        assert usaspending_award._to_date("2016-08-01T12:30:45Z") == "2016-08-01"
        assert usaspending_award._to_date("2016-08-01") == "2016-08-01"

    def test_passes_a_non_string_through(self):
        """A value that is not a string is returned unchanged."""
        assert usaspending_award._to_date(None) is None
        assert usaspending_award._to_date(date(2016, 8, 1)) == date(2016, 8, 1)


class TestUsSpendingAwardQueryLimits:
    """Tests for the per-section limit cap."""

    def test_rejects_a_limit_above_the_section_cap(self):
        """A limit the source would reject is refused with the real maximum."""
        with pytest.raises(
            OpenBBError, match="maximum limit for section 'subawards' is 100"
        ):
            usaspending_award.UsSpendingAwardFetcher.transform_query(
                {"award_id": "CONT_AWD_X", "section": "subawards", "limit": 101}
            )

    def test_allows_the_larger_transactions_cap(self):
        """Transactions accept the 5000 the source allows them."""
        query = usaspending_award.UsSpendingAwardFetcher.transform_query(
            {"award_id": "CONT_AWD_X", "section": "transactions", "limit": 5000}
        )
        assert query.limit == 5000
        with pytest.raises(
            OpenBBError, match="maximum limit for section 'transactions' is 5000"
        ):
            usaspending_award.UsSpendingAwardFetcher.transform_query(
                {"award_id": "CONT_AWD_X", "section": "transactions", "limit": 5001}
            )

    def test_the_detail_section_is_uncapped(self):
        """The unpaginated detail section ignores the limit rather than capping it."""
        query = usaspending_award.UsSpendingAwardFetcher.transform_query(
            {"award_id": "CONT_AWD_X", "section": "detail", "limit": 100000}
        )
        assert query.limit == 100000
        assert query.section == "detail"


AWARD_ID = "CONT_AWD_HT940216C0001_9700"

IDV_ID = "CONT_IDV_15F06724A0000314_1549"


class TestUsSpendingAwardExtract:
    """Tests for the award section requests."""

    @staticmethod
    def _patch(monkeypatch, detail=None, response=None):
        """Patch the award GET and the section POST, recording both calls."""
        captured: dict = {}

        async def _fake_get(path, **kwargs):
            captured["get_path"] = path
            return detail or {}

        async def _fake_post(path, payload, **kwargs):
            captured["post_path"] = path
            captured["payload"] = payload
            return response or {}

        monkeypatch.setattr(usaspending, "get_usaspending", _fake_get)
        monkeypatch.setattr(usaspending, "post_usaspending", _fake_post)
        return captured

    def test_detail_returns_the_award_payload_verbatim(self, monkeypatch):
        """The detail section is one GET and yields a single row."""
        detail = {"generated_unique_award_id": AWARD_ID, "category": "contract"}
        captured = self._patch(monkeypatch, detail=detail)
        query = usaspending_award.UsSpendingAwardFetcher.transform_query(
            {"award_id": AWARD_ID}
        )
        rows = asyncio.run(
            usaspending_award.UsSpendingAwardFetcher.aextract_data(query, None)
        )
        assert captured["get_path"] == f"awards/{AWARD_ID}/"
        assert rows == [detail]
        assert "post_path" not in captured

    def test_detail_escapes_the_award_id(self, monkeypatch):
        """An id with a path separator is escaped rather than changing the route."""
        captured = self._patch(monkeypatch, detail={})
        query = usaspending_award.UsSpendingAwardFetcher.transform_query(
            {"award_id": "CONT_AWD_A/B"}
        )
        asyncio.run(usaspending_award.UsSpendingAwardFetcher.aextract_data(query, None))
        assert captured["get_path"] == "awards/CONT_AWD_A%2FB/"

    @pytest.mark.parametrize(
        ("section", "path"),
        [
            ("transactions", "transactions/"),
            ("subawards", "subawards/"),
            ("federal_accounts", "awards/accounts/"),
            ("funding", "awards/funding/"),
        ],
    )
    def test_each_paged_section_posts_to_its_endpoint(self, monkeypatch, section, path):
        """Every paged section is fetched from the endpoint it belongs to."""
        captured = self._patch(monkeypatch, response={"results": [{"a": 1}]})
        query = usaspending_award.UsSpendingAwardFetcher.transform_query(
            {"award_id": AWARD_ID, "section": section}
        )
        asyncio.run(usaspending_award.UsSpendingAwardFetcher.aextract_data(query, None))
        assert captured["post_path"] == path
        assert "get_path" not in captured

    def test_paged_section_sends_the_page_and_limit(self, monkeypatch):
        """The requested page and limit are forwarded and the subject stamped on."""
        captured = self._patch(monkeypatch, response={"results": [{"id": "CONT_TX_1"}]})
        query = usaspending_award.UsSpendingAwardFetcher.transform_query(
            {
                "award_id": AWARD_ID,
                "section": "transactions",
                "page": 3,
                "limit": 50,
            }
        )
        rows = asyncio.run(
            usaspending_award.UsSpendingAwardFetcher.aextract_data(query, None)
        )
        assert captured["payload"] == {
            "award_id": AWARD_ID,
            "page": 3,
            "limit": 50,
        }
        assert rows == [{"id": "CONT_TX_1", usaspending_award.SUBJECT_KEY: AWARD_ID}]

    def test_an_empty_section_raises(self, monkeypatch):
        """A section with no rows names the section, the award, and the page."""
        self._patch(monkeypatch, response={"results": []})
        query = usaspending_award.UsSpendingAwardFetcher.transform_query(
            {"award_id": AWARD_ID, "section": "funding", "page": 4}
        )
        with pytest.raises(EmptyDataError, match="No 'funding' rows"):
            asyncio.run(
                usaspending_award.UsSpendingAwardFetcher.aextract_data(query, None)
            )

    def test_a_missing_results_key_raises(self, monkeypatch):
        """A response with no results key is treated as empty, not as an error."""
        self._patch(monkeypatch, response={})
        query = usaspending_award.UsSpendingAwardFetcher.transform_query(
            {"award_id": AWARD_ID, "section": "subawards"}
        )
        with pytest.raises(EmptyDataError, match=f"award '{AWARD_ID}' at page 1"):
            asyncio.run(
                usaspending_award.UsSpendingAwardFetcher.aextract_data(query, None)
            )

    def test_idv_children_rejects_a_non_idv_award(self, monkeypatch):
        """A contract has no children, which the source hides behind an empty list."""
        captured = self._patch(
            monkeypatch, detail={"category": "contract"}, response={"results": []}
        )
        query = usaspending_award.UsSpendingAwardFetcher.transform_query(
            {"award_id": AWARD_ID, "section": "idv_children"}
        )
        with pytest.raises(OpenBBError, match="has category 'contract', not 'idv'"):
            asyncio.run(
                usaspending_award.UsSpendingAwardFetcher.aextract_data(query, None)
            )
        assert "post_path" not in captured

    def test_idv_children_sends_the_relation_type(self, monkeypatch):
        """An IDV posts the requested relation and stamps the resolved award id."""
        captured = self._patch(
            monkeypatch,
            detail={"category": "idv", "generated_unique_award_id": IDV_ID},
            response={"results": [{"generated_unique_award_id": "CONT_AWD_CHILD"}]},
        )
        query = usaspending_award.UsSpendingAwardFetcher.transform_query(
            {
                "award_id": "1549",
                "section": "idv_children",
                "idv_children_type": "child_idvs",
            }
        )
        rows = asyncio.run(
            usaspending_award.UsSpendingAwardFetcher.aextract_data(query, None)
        )
        assert captured["get_path"] == "awards/1549/"
        assert captured["post_path"] == "idvs/awards/"
        assert captured["payload"] == {
            "award_id": "1549",
            "type": "child_idvs",
            "page": 1,
            "limit": 100,
        }
        assert rows[0][usaspending_award.SUBJECT_KEY] == IDV_ID

    def test_idv_children_falls_back_to_the_requested_id(self, monkeypatch):
        """A detail payload without a generated id keeps the requested id."""
        self._patch(
            monkeypatch,
            detail={"category": "idv"},
            response={"results": [{"piid": "HT0011"}]},
        )
        query = usaspending_award.UsSpendingAwardFetcher.transform_query(
            {"award_id": IDV_ID, "section": "idv_children"}
        )
        rows = asyncio.run(
            usaspending_award.UsSpendingAwardFetcher.aextract_data(query, None)
        )
        assert rows[0][usaspending_award.SUBJECT_KEY] == IDV_ID


class TestUsSpendingAwardSectionMapping:
    """Tests for the per-section source-to-schema mapping."""

    @staticmethod
    def _transform(section: str, rows: list[dict], award_id: str = AWARD_ID):
        """Transform source rows of one section into serialized records."""
        query = usaspending_award.UsSpendingAwardFetcher.transform_query(
            {"award_id": award_id, "section": section}
        )
        return [
            row.model_dump()
            for row in usaspending_award.UsSpendingAwardFetcher.transform_data(
                query, rows
            )
        ]

    def test_detail_flattens_the_nested_payload(self):
        """Nested objects and the first assistance listing are flattened out."""
        record = self._transform(
            "detail",
            [
                {
                    "generated_unique_award_id": AWARD_ID,
                    "id": 307885715,
                    "category": "contract",
                    "date_signed": "2016-07-29 00:00:00",
                    "period_of_performance": {
                        "start_date": "2016-08-01",
                        "last_modified_date": "2025-03-07T12:30:45",
                    },
                    "recipient": {
                        "recipient_name": "HUMANA GOVERNMENT BUSINESS INC",
                        "location": {"state_code": "KY", "zip5": "40202"},
                    },
                    "awarding_agency": {"toptier_agency": {"name": "DOD"}},
                    "latest_transaction_contract_data": {"naics": "524114"},
                    "cfda_info": [
                        {"cfda_number": "93.778", "cfda_title": "Medical Assistance"}
                    ],
                }
            ],
        )[0]
        assert record["award_id"] == AWARD_ID
        assert record["internal_id"] == 307885715
        assert record["date_signed"] == date(2016, 7, 29)
        assert record["period_start"] == date(2016, 8, 1)
        assert record["last_modified"] == date(2025, 3, 7)
        assert record["recipient_state"] == "KY"
        assert record["recipient_zip"] == "40202"
        assert record["awarding_agency"] == "DOD"
        assert record["naics"] == "524114"
        assert record["cfda_number"] == "93.778"
        assert record["cfda_title"] == "Medical Assistance"

    def test_transactions_map_to_the_unified_names(self):
        """A transaction row keeps its signed obligation and its truncated date."""
        record = self._transform(
            "transactions",
            [
                {
                    "id": "CONT_TX_9700_1",
                    "type": "C",
                    "type_description": "DELIVERY ORDER",
                    "action_date": "2025-03-07 00:00:00",
                    "action_type": "A",
                    "action_type_description": "ADDITIONAL WORK",
                    "modification_number": "P00012",
                    "description": "MANAGED CARE SUPPORT",
                    "federal_action_obligation": -1913834852.94,
                    "face_value_loan_guarantee": None,
                    "original_loan_subsidy_cost": None,
                    "cfda_number": None,
                    usaspending_award.SUBJECT_KEY: AWARD_ID,
                }
            ],
        )[0]
        assert record["transaction_id"] == "CONT_TX_9700_1"
        assert record["award_type_description"] == "DELIVERY ORDER"
        assert record["action_date"] == date(2025, 3, 7)
        assert record["modification_number"] == "P00012"
        assert record["federal_action_obligation"] == -1913834852.94
        assert "face_value_loan_guarantee" not in record
        assert "cfda_number" not in record

    def test_federal_accounts_map_to_the_unified_names(self):
        """A federal account row serves exactly its mapped fields, zeros included."""
        record = self._transform(
            "federal_accounts",
            [
                {
                    "federal_account": "075-0512",
                    "account_title": "Defense Health Program",
                    "total_transaction_obligated_amount": 0.0,
                    "funding_agency_name": "Department of Defense",
                    "funding_agency_abbreviation": "DOD",
                    usaspending_award.SUBJECT_KEY: AWARD_ID,
                }
            ],
        )[0]
        assert set(record) == set(
            usaspending_award.FIELD_MAP["federal_accounts"].values()
        ) | {"award_id"}
        assert record["total_transaction_obligated_amount"] == 0.0
        assert record["funding_agency"] == "Department of Defense"
        assert record["funding_agency_abbreviation"] == "DOD"

    def test_funding_maps_the_submission_period(self):
        """A funding row keeps the submission period and the quarterly flag."""
        record = self._transform(
            "funding",
            [
                {
                    "transaction_obligated_amount": 1000.0,
                    "gross_outlay_amount": -25.5,
                    "federal_account": "075-0512",
                    "reporting_fiscal_year": 2025,
                    "reporting_fiscal_quarter": 2,
                    "reporting_fiscal_month": 5,
                    "is_quarterly_submission": False,
                    usaspending_award.SUBJECT_KEY: AWARD_ID,
                }
            ],
        )[0]
        assert record["transaction_obligated_amount"] == 1000.0
        assert record["gross_outlay_amount"] == -25.5
        assert record["reporting_fiscal_year"] == 2025
        assert record["reporting_fiscal_month"] == 5
        assert record["is_quarterly_submission"] is False

    def test_idv_children_separate_the_child_from_the_vehicle(self):
        """The child id is its own column and award_id stays the vehicle."""
        record = self._transform(
            "idv_children",
            [
                {
                    "generated_unique_award_id": "CONT_AWD_CHILD_1",
                    "award_id": 123456,
                    "award_type": "DELIVERY ORDER",
                    "description": "TASK ORDER",
                    "piid": "15F06724F0000123",
                    "obligated_amount": 1000.5,
                    "last_date_to_order": "2026-09-30 00:00:00",
                    "period_of_performance_start_date": "2024-10-01",
                    "period_of_performance_current_end_date": "2025-09-30",
                    "funding_agency": "Department of Justice",
                    "awarding_agency": "Department of Justice",
                    usaspending_award.SUBJECT_KEY: IDV_ID,
                }
            ],
            award_id=IDV_ID,
        )[0]
        assert record["award_id"] == IDV_ID
        assert record["child_award_id"] == "CONT_AWD_CHILD_1"
        assert record["internal_id"] == 123456
        assert record["obligated_amount"] == 1000.5
        assert record["last_date_to_order"] == date(2026, 9, 30)
        assert record["period_start"] == date(2024, 10, 1)
        assert record["period_end"] == date(2025, 9, 30)

    def test_an_unstamped_row_falls_back_to_the_requested_award(self):
        """A row carrying no subject is attributed to the requested award."""
        record = self._transform(
            "transactions", [{"id": "CONT_TX_9700_1", "action_type": "A"}]
        )[0]
        assert record["award_id"] == AWARD_ID


class _FakeHTTPResponse:
    """Settable stand-in for a requests.Response."""

    def __init__(
        self, status_code=200, content=b"", encoding="ISO-8859-1", json_data=None
    ):
        self.status_code = status_code
        self.content = content
        self.encoding = encoding
        self._json_data = json_data

    def json(self):
        """Return the canned JSON payload."""
        return self._json_data


def _patch_make_request(monkeypatch, response):
    """Patch make_request to record its call and return the canned response."""
    captured: dict = {}

    def _fake(url=None, method="GET", **kwargs):
        captured["url"] = url
        captured["method"] = method
        captured.update(kwargs)
        return response

    monkeypatch.setattr(core_helpers, "make_request", _fake)
    return captured


def _auction_row(**overrides) -> dict:
    """Build a minimal Treasury Direct auction record with optional overrides."""
    row = {
        "cusip": "912797SL2",
        "issueDate": "2024-01-18",
        "securityType": "Bill",
        "securityTerm": "13-Week",
        "maturityDate": "2024-04-18",
    }
    row.update(overrides)
    return row


class TestUsTreasuryAuctionsUnit:
    """Tests for the UsTreasuryAuctions fetcher."""

    def test_extract_data_builds_query_and_returns_records(self, monkeypatch):
        """A 200 response yields records with empty strings blanked out."""
        rows = [_auction_row(highYield="", somaHoldings=None)]
        captured = _patch_make_request(monkeypatch, _FakeHTTPResponse(json_data=rows))
        fetcher = treasury_auctions.UsTreasuryAuctionsFetcher
        query = fetcher.transform_query(
            {
                "security_type": "bill",
                "start_date": "2024-01-01",
                "end_date": "2024-06-30",
            }
        )
        data = fetcher.extract_data(query, None)
        record = data[0]
        assert record["cusip"] == "912797SL2"
        assert record["somaHoldings"] is None
        assert record["highYield"] is None
        assert "type=Bill" in captured["url"]
        assert "startDate=01/01/2024" in captured["url"]
        assert "endDate=06/30/2024" in captured["url"]
        assert captured["url"].endswith("&format=json")

    def test_extract_data_raises_on_http_error(self, monkeypatch):
        """A non-200 status from Treasury Direct raises OpenBBError."""
        _patch_make_request(monkeypatch, _FakeHTTPResponse(status_code=500))
        fetcher = treasury_auctions.UsTreasuryAuctionsFetcher
        query = fetcher.transform_query({"security_type": "bill"})
        with pytest.raises(OpenBBError, match="500"):
            fetcher.extract_data(query, None)

    def test_normalize_percent_edge_cases(self):
        """Percent keys divide by 100 while Yes/No, empty, and None pass through."""
        row = _auction_row(
            highYield="4.25",
            spread="0.5",
            allocationPercentage="",
            highDiscountMargin=None,
            floatingRate="No",
        )
        item = treasury_auctions.UsTreasuryAuctionsData.model_validate(row)
        assert item.high_yield == 4.25 / 100
        assert item.spread == 0.5 / 100
        assert item.allocation_percentage is None
        assert item.high_discount_margin is None
        assert item.floating_rate == "No"


_PRICES_CSV = (
    "CUSIP,SECURITY TYPE,RATE,MATURITY DATE,CALL DATE,BUY,SELL,END OF DAY\n"
    "912796YT4,MARKET BASED BILL,0.000,04/09/2026,,99.105,99.115,99.110\n"
    "91282CJK8,MARKET BASED NOTE,4.875,11/30/2025,05/15/2025,100.1,100.2,100.15\n"
)


_PRICES_FORM = '<input type="hidden" name="_csrf" value="tok-1" />'


def _patch_prices_requests(monkeypatch, response, form_text=_PRICES_FORM):
    """Serve the price form on GET and the canned response on POST, recording both."""
    calls: list[dict] = []
    session = object()

    def _fake(url=None, method="GET", **kwargs):
        calls.append({"url": url, "method": method, **kwargs})
        if method == "GET":
            form = _FakeHTTPResponse(status_code=response.status_code)
            form.text = form_text
            return form
        return response

    monkeypatch.setattr(core_helpers, "make_request", _fake)
    monkeypatch.setattr(core_helpers, "get_requests_session", lambda **_: session)
    return calls


class TestUsTreasuryPricesUnit:
    """Tests for the UsTreasuryPrices fetcher."""

    def test_transform_query_defaults_to_last_business_day(self):
        """A missing date defaults to the last business day."""
        fetcher = treasury_prices.UsTreasuryPricesFetcher
        query = fetcher.transform_query({})
        today = date.today()
        expected = (
            today - timedelta(today.weekday() - 4) if today.weekday() > 4 else today
        )
        assert query.date == expected

    def test_transform_query_keeps_explicit_date(self):
        """An explicit date passes through unchanged."""
        fetcher = treasury_prices.UsTreasuryPricesFetcher
        query = fetcher.transform_query({"date": "2026-04-01"})
        assert query.date == date(2026, 4, 1)

    def test_extract_data_posts_form_payload(self, monkeypatch):
        """The date fields form the POST payload and the body decodes to text."""
        response = _FakeHTTPResponse(content=_PRICES_CSV.encode("utf-8"))
        calls = _patch_prices_requests(monkeypatch, response)
        fetcher = treasury_prices.UsTreasuryPricesFetcher
        query = fetcher.transform_query({"date": "2026-04-01"})
        data = fetcher.extract_data(query, None)
        assert data == _PRICES_CSV
        form, download = calls
        assert form["method"] == "GET"
        assert form["url"].endswith("/selectSecurityPriceDate")
        assert download["method"] == "POST"
        assert download["data"] == (
            "priceDateDay=1&priceDateMonth=4&priceDateYear=2026"
            "&fileType=csv&csv=CSV+FORMAT&_csrf=tok-1"
        )
        assert download["url"].endswith("/securityPriceDetail")
        # The download rides the session that fetched the form, for its cookie.
        assert download["session"] is form["session"]

    def test_extract_data_raises_without_csrf_token(self, monkeypatch):
        """A price form with no CSRF token raises OpenBBError before the download."""
        calls = _patch_prices_requests(monkeypatch, _FakeHTTPResponse(), form_text="")
        fetcher = treasury_prices.UsTreasuryPricesFetcher
        query = fetcher.transform_query({"date": "2026-04-01"})
        with pytest.raises(OpenBBError, match="no CSRF token"):
            fetcher.extract_data(query, None)
        assert len(calls) == 1

    def test_extract_data_raises_on_http_error(self, monkeypatch):
        """A non-200 status raises OpenBBError with the status code."""
        _patch_prices_requests(monkeypatch, _FakeHTTPResponse(status_code=404))
        fetcher = treasury_prices.UsTreasuryPricesFetcher
        query = fetcher.transform_query({"date": "2026-04-01"})
        with pytest.raises(OpenBBError, match="Error with the request: 404"):
            fetcher.extract_data(query, None)

    def test_extract_data_raises_on_unexpected_encoding(self, monkeypatch):
        """A response encoding other than ISO-8859-1 raises OpenBBError."""
        _patch_prices_requests(monkeypatch, _FakeHTTPResponse(encoding="utf-8"))
        fetcher = treasury_prices.UsTreasuryPricesFetcher
        query = fetcher.transform_query({"date": "2026-04-01"})
        with pytest.raises(OpenBBError, match="Expected ISO-8859-1 encoding"):
            fetcher.extract_data(query, None)

    def test_transform_data_parses_csv(self):
        """The CSV parses with renamed columns, ISO dates, and None call dates."""
        fetcher = treasury_prices.UsTreasuryPricesFetcher
        query = fetcher.transform_query({"date": "2026-04-01"})
        result = fetcher.transform_data(query, _PRICES_CSV)
        assert [item.cusip for item in result] == ["912796YT4", "91282CJK8"]
        bill = result[0]
        assert bill.security_type == "MARKET BASED BILL"
        assert bill.rate == 0.0
        assert bill.maturity_date == date(2026, 4, 9)
        assert bill.call_date is None
        assert bill.bid == 99.105
        assert bill.offer == 99.115
        assert bill.eod_price == 99.110
        assert bill.date == date(2026, 4, 1)
        note = result[1]
        assert note.rate == 4.875
        assert note.call_date == date(2025, 5, 15)

    def test_transform_data_empty_raises(self):
        """Empty extracted data raises OpenBBError wrapping EmptyDataError."""
        fetcher = treasury_prices.UsTreasuryPricesFetcher
        query = fetcher.transform_query({"date": "2026-04-01"})
        with pytest.raises(OpenBBError, match="Data not found"):
            fetcher.transform_data(query, "")

    def test_transform_data_filters_security_type(self):
        """The security_type filter matches case-insensitively."""
        fetcher = treasury_prices.UsTreasuryPricesFetcher
        query = fetcher.transform_query({"date": "2026-04-01", "security_type": "note"})
        result = fetcher.transform_data(query, _PRICES_CSV)
        assert [item.cusip for item in result] == ["91282CJK8"]

    def test_transform_data_filters_cusip(self):
        """The cusip filter selects the exact security."""
        fetcher = treasury_prices.UsTreasuryPricesFetcher
        query = fetcher.transform_query({"date": "2026-04-01", "cusip": "912796YT4"})
        result = fetcher.transform_data(query, _PRICES_CSV)
        assert [item.cusip for item in result] == ["912796YT4"]


from openbb_government_us.treasury.models.treasury_bulletin import (  # noqa: E402
    TreasuryBulletinFetcher,
)


class TestTreasuryBulletinPivot:
    """The long bulletin tables are served as wide time series."""

    @staticmethod
    def _records() -> list[dict]:
        """Build long-format ofs2 source rows across two report dates."""
        return [
            {
                "record_date": "2026-06-30",
                "end_of_month": end_of_month,
                "securities_owner": owner,
                "securities_bil_amt": amount,
            }
            for end_of_month, owner, amount in (
                ("2026-03-31", "Total Public Debt", "39065.4"),
                ("2026-03-31", "Mutual Funds", "1710.0"),
                ("2025-12-31", "Total Public Debt", "38514.0"),
                ("2025-12-31", "Mutual Funds", "1680.0"),
            )
        ]

    def test_one_row_per_report_date(self):
        """A long table collapses to one row per observation date."""
        query = TreasuryBulletinFetcher.transform_query({"table": "ofs2"})
        rows = TreasuryBulletinFetcher.transform_data(query, self._records())
        assert len(rows) == 2

    def test_classifications_become_columns(self):
        """Each classification is its own column, not its own row."""
        query = TreasuryBulletinFetcher.transform_query({"table": "ofs2"})
        row = TreasuryBulletinFetcher.transform_data(query, self._records())[
            0
        ].model_dump(exclude_none=True)
        assert row["Total Public Debt"] == 39065400000000.0
        assert row["Mutual Funds"] == 1710000000000.0

    def test_newest_report_date_first(self):
        """Rows read newest first, by the observation date."""
        query = TreasuryBulletinFetcher.transform_query({"table": "ofs2"})
        rows = TreasuryBulletinFetcher.transform_data(query, self._records())
        assert [str(row.report_date) for row in rows] == ["2026-03-31", "2025-12-31"]

    def test_a_row_per_entity_table_is_left_alone(self):
        """A table that already has real columns is not pivoted."""
        query = TreasuryBulletinFetcher.transform_query({"table": "uscc2"})
        rows = TreasuryBulletinFetcher.transform_data(
            query,
            [
                {
                    "record_date": "2026-03-01",
                    "currency_as_of_date": "2025-12-31",
                    "currency_denom": "$1",
                    "total_currency_amt": "15232.270648",
                    "src_line_nbr": "1",
                }
            ],
        )
        assert rows[0].denomination == "$1"

    def test_repeated_label_segments_collapse(self):
        """A dimension repeating its parent's value is not duplicated."""
        query = TreasuryBulletinFetcher.transform_query({"table": "ofs1"})
        row = TreasuryBulletinFetcher.transform_data(
            query,
            [
                {
                    "record_date": "2026-06-30",
                    "end_fiscal_year_or_month": "2026-03-31",
                    "securities_classification": "Agencies securities",
                    "investors_classification": "Total outstanding",
                    "issues_type": "Total outstanding",
                    "securities_mil_amt": "1.0",
                }
            ],
        )[0].model_dump(exclude_none=True)
        assert "Agencies securities - Total outstanding" in row
        assert "Total outstanding - Total outstanding" not in str(list(row))


from openbb_government_us.treasury.models.daily_treasury_statement import (  # noqa: E402
    DailyTreasuryStatementFetcher,
)


class TestDailyTreasuryStatementAmountBasis:
    """The DTS pivot narrows by amount basis rather than dropping line items."""

    @staticmethod
    def _records() -> list[dict]:
        """Build long-format DTS rows for two dates and two line items."""
        return [
            {
                "record_date": date,
                "table_nbr": "II",
                "transaction_type": "Deposits",
                "transaction_catg": item,
                "transaction_today_amt": today,
                "transaction_mtd_amt": "2",
                "transaction_fytd_amt": "3",
            }
            for date, item, today in (
                ("2026-07-20", "Air Transport Security Fees", "1"),
                ("2026-07-20", "Cash FTD's Received", "5"),
                ("2026-07-17", "Air Transport Security Fees", "7"),
                ("2026-07-17", "Cash FTD's Received", "9"),
            )
        ]

    def test_default_serves_every_line_item(self):
        """Narrowing to one basis keeps a column per line item, dropping none."""
        query = DailyTreasuryStatementFetcher.transform_query(
            {"table": "deposits_withdrawals_operating_cash"}
        )
        rows = DailyTreasuryStatementFetcher.transform_data(query, self._records())
        columns = {c for row in rows for c in row.model_dump(exclude_none=True)}
        assert "Air Transport Security Fees" in columns
        assert "Cash FTD's Received" in columns

    def test_every_row_carries_the_same_columns(self):
        """Ragged key sets make the Workspace order columns unpredictably."""
        query = DailyTreasuryStatementFetcher.transform_query(
            {"table": "deposits_withdrawals_operating_cash"}
        )
        rows = DailyTreasuryStatementFetcher.transform_data(query, self._records())
        keysets = {tuple(sorted(row.model_dump(exclude_none=True))) for row in rows}
        assert len(keysets) == 1

    def test_all_bases_widens_rather_than_truncating(self):
        """Asking for every basis serves every basis, suffixed per column."""
        query = DailyTreasuryStatementFetcher.transform_query(
            {"table": "deposits_withdrawals_operating_cash", "amount_basis": "all"}
        )
        rows = DailyTreasuryStatementFetcher.transform_data(query, self._records())
        columns = {c for row in rows for c in row.model_dump(exclude_none=True)}
        assert "Air Transport Security Fees (Today)" in columns
        assert "Air Transport Security Fees (Fiscal Year to Date)" in columns

    def test_an_unknown_basis_is_rejected(self):
        """A basis the table does not publish names the valid ones."""
        query = DailyTreasuryStatementFetcher.transform_query(
            {"table": "deposits_withdrawals_operating_cash", "amount_basis": "Nope"}
        )
        with pytest.raises(OpenBBError, match="Invalid amount_basis"):
            DailyTreasuryStatementFetcher.transform_data(query, self._records())

    def test_balance_tables_keep_every_basis(self):
        """A balance table's bases are its columns, so none is dropped."""
        from openbb_government_us.treasury.models.daily_treasury_statement import (
            resolve_amount_basis,
        )

        assert len(resolve_amount_basis("operating_cash_balance", None)) == 4

    def test_a_named_basis_narrows_to_that_basis(self):
        """A published basis label resolves to just that amount field."""
        from openbb_government_us.treasury.models.daily_treasury_statement import (
            resolve_amount_basis,
        )

        assert resolve_amount_basis(
            "deposits_withdrawals_operating_cash", "Month to Date"
        ) == ["month_to_date_amount"]

    def test_a_named_basis_labels_columns_without_a_suffix(self):
        """One basis serves bare line-item columns, no basis suffix."""
        query = DailyTreasuryStatementFetcher.transform_query(
            {
                "table": "deposits_withdrawals_operating_cash",
                "amount_basis": "Month to Date",
            }
        )
        rows = DailyTreasuryStatementFetcher.transform_data(query, self._records())
        assert rows[0].model_dump(exclude_none=True) == {
            "date": date(2026, 7, 20),
            "Air Transport Security Fees": 2000000.0,
            "Cash FTD's Received": 2000000.0,
        }


class TestDailyTreasuryStatementEdgeRows:
    """The DTS pivot drops rows the source cannot place in the wide layout."""

    def test_a_non_text_sub_table_is_left_untouched(self):
        """A None sub-table passes through the strip validator unchanged."""
        query = DailyTreasuryStatementFetcher.transform_query(
            {"table": "deposits_withdrawals_operating_cash", "sub_table": None}
        )
        assert query.sub_table is None

    def test_whitespace_sub_table_is_treated_as_unset(self):
        """A blank sub-table string falls back to the table's default."""
        query = DailyTreasuryStatementFetcher.transform_query(
            {"table": "deposits_withdrawals_operating_cash", "sub_table": "   "}
        )
        assert query.sub_table is None

    def test_a_padded_sub_table_is_stripped(self):
        """Surrounding whitespace is stripped off the sub-table selection."""
        query = DailyTreasuryStatementFetcher.transform_query(
            {"table": "deposits_withdrawals_operating_cash", "sub_table": " Deposits "}
        )
        assert query.sub_table == "Deposits"

    def test_a_row_without_a_record_date_is_dropped(self):
        """A source row carrying no record_date cannot anchor a statement row."""
        query = DailyTreasuryStatementFetcher.transform_query(
            {"table": "deposits_withdrawals_operating_cash"}
        )
        rows = DailyTreasuryStatementFetcher.transform_data(
            query,
            [
                {
                    "record_date": "2026-07-20",
                    "transaction_type": "Deposits",
                    "transaction_catg": "Cash FTD's Received",
                    "transaction_today_amt": "5",
                },
                {
                    "transaction_type": "Deposits",
                    "transaction_catg": "Air Transport Security Fees",
                    "transaction_today_amt": "1",
                },
            ],
        )
        assert [row.model_dump(exclude_none=True) for row in rows] == [
            {"date": date(2026, 7, 20), "Cash FTD's Received": 5000000.0}
        ]

    def test_a_row_with_no_line_item_is_dropped(self):
        """A row whose dimensions are all blank has no column to land in."""
        query = DailyTreasuryStatementFetcher.transform_query(
            {"table": "deposits_withdrawals_operating_cash"}
        )
        rows = DailyTreasuryStatementFetcher.transform_data(
            query,
            [
                {
                    "record_date": "2026-07-20",
                    "transaction_type": "Deposits",
                    "account_type": "Federal Reserve Account",
                    "transaction_catg": "Cash FTD's Received",
                    "transaction_catg_desc": "Withheld Income and Employment Taxes",
                    "transaction_today_amt": "5",
                },
                {
                    "record_date": "2026-07-20",
                    "transaction_type": "Deposits",
                    "account_type": "",
                    "transaction_catg": "",
                    "transaction_catg_desc": "",
                    "transaction_today_amt": "9",
                },
            ],
        )
        assert [row.model_dump(exclude_none=True) for row in rows] == [
            {
                "date": date(2026, 7, 20),
                "Federal Reserve Account - Cash FTD's Received"
                " - Withheld Income and Employment Taxes": 5000000.0,
            }
        ]


class TestTreasuryBulletinRowMapping:
    """Per-table value normalization the bulletin applies before serving."""

    def test_esf2_drops_the_source_reconciliation_rows(self):
        """The ESF-2 check and footnote artifacts are not served as line items."""
        query = TreasuryBulletinFetcher.transform_query({"table": "esf2"})
        rows = TreasuryBulletinFetcher.transform_data(
            query,
            [
                {
                    "record_date": "2026-03-01",
                    "report_date": "2025-12-31",
                    "classification_desc": "Net income",
                    "current_quarter_thous_amt": "10",
                    "fytd_thous_amt": "20",
                    "src_line_nbr": "1",
                },
                {
                    "record_date": "2026-03-01",
                    "report_date": "2025-12-31",
                    "classification_desc": "check",
                    "current_quarter_thous_amt": "0",
                    "fytd_thous_amt": "0",
                    "src_line_nbr": "2",
                },
            ],
        )
        served = rows[0].model_dump(exclude_none=True)
        assert served["Net income (Current Quarter)"] == 10000.0
        assert served["Net income (Fiscal Year to Date)"] == 20000.0
        assert not [key for key in served if key.startswith("check")]

    def test_foreign_currency_amounts_expand_by_the_row_unit(self):
        """FCP rows scale by the denomination the row itself declares."""
        query = TreasuryBulletinFetcher.transform_query({"table": "fcp1"})
        rows = TreasuryBulletinFetcher.transform_data(
            query,
            [
                {
                    "record_date": "2026-03-01",
                    "report_date": "2025-12-31",
                    "foreign_currency_desc": "Euro",
                    "foreign_currency_denom": "Millions",
                    "spot_fwd_future_purch_amt": "2.5",
                    "spot_fwd_future_sold_amt": "1.0",
                    "net_options_positions_amt": "0.5",
                    "exchange_rate": "0.95",
                    "src_line_nbr": "1",
                },
                {
                    "record_date": "2026-03-01",
                    "report_date": "2025-12-31",
                    "foreign_currency_desc": "Yen",
                    "foreign_currency_denom": "Billions",
                    "spot_fwd_future_purch_amt": "3.0",
                    "spot_fwd_future_sold_amt": "1.0",
                    "net_options_positions_amt": "0.0",
                    "exchange_rate": "150.0",
                    "src_line_nbr": "2",
                },
            ],
        )
        by_currency = {row.currency: row for row in rows}
        assert by_currency["Euro"].spot_forward_futures_purchased == 2500000.0
        assert by_currency["Yen"].spot_forward_futures_purchased == 3000000000.0
        assert by_currency["Yen"].exchange_rate == 150.0

    def test_fiscal_year_is_taken_from_the_leading_four_digits(self):
        """A fiscal-year date string is served as the integer year."""
        query = TreasuryBulletinFetcher.transform_query({"table": "ffo6"})
        rows = TreasuryBulletinFetcher.transform_data(
            query,
            [
                {
                    "record_date": "2025-12-01",
                    "collection_fiscal_year": "2024-09-30",
                    "district_nm": "Boston",
                    "port_nm": "Total",
                    "port_cd": None,
                    "collection_amt": "12.5",
                    "src_line_nbr": "1",
                }
            ],
        )
        assert rows[0].fiscal_year == 2024
        assert rows[0].total_collections == 12.5

    def test_rates_are_normalized_to_decimal_fractions(self):
        """Auction rates published as percents are served as fractions."""
        query = TreasuryBulletinFetcher.transform_query({"table": "pdo1"})
        rows = TreasuryBulletinFetcher.transform_data(
            query,
            [
                {
                    "record_date": "2026-03-01",
                    "issue_date": "2026-01-08",
                    "maturity_date": "2026-04-09",
                    "days_to_maturity": "91",
                    "bids_tendered_mil_amt": "100.0",
                    "high_discount_rate": "4.25",
                    "high_investment_rate": "4.37",
                    "src_line_nbr": "1",
                }
            ],
        )
        assert rows[0].high_discount_rate == 0.0425
        assert rows[0].high_investment_rate == 0.0437
        assert rows[0].bids_tendered == 100000000.0


class TestTreasuryBulletinPivotEdges:
    """Rows the bulletin pivot cannot place, and the edition it stamps."""

    def test_a_row_without_a_report_date_is_dropped(self):
        """A row with no observation date has no pivot row to join."""
        query = TreasuryBulletinFetcher.transform_query({"table": "ofs2"})
        rows = TreasuryBulletinFetcher.transform_data(
            query,
            [
                {
                    "record_date": "2026-06-30",
                    "end_of_month": "2026-03-31",
                    "securities_owner": "Mutual Funds",
                    "securities_bil_amt": "1.0",
                },
                {
                    "record_date": "2026-06-30",
                    "securities_owner": "Pension Funds",
                    "securities_bil_amt": "2.0",
                },
            ],
        )
        assert len(rows) == 1
        assert rows[0].model_dump(exclude_none=True) == {
            "table_code": "OFS-2",
            "report_date": date(2026, 3, 31),
            "record_date": date(2026, 6, 30),
            "Mutual Funds": 1000000000.0,
        }

    def test_a_classification_with_no_amount_makes_no_column(self):
        """A classification reported empty gets no column rather than a null one."""
        query = TreasuryBulletinFetcher.transform_query({"table": "ofs2"})
        rows = TreasuryBulletinFetcher.transform_data(
            query,
            [
                {
                    "record_date": "2026-06-30",
                    "end_of_month": "2026-03-31",
                    "securities_owner": "Mutual Funds",
                    "securities_bil_amt": "1.0",
                },
                {
                    "record_date": "2026-06-30",
                    "end_of_month": "2026-03-31",
                    "securities_owner": "State and Local Governments",
                    "securities_bil_amt": None,
                },
            ],
        )
        assert rows[0].model_dump(exclude_none=True) == {
            "table_code": "OFS-2",
            "report_date": date(2026, 3, 31),
            "record_date": date(2026, 6, 30),
            "Mutual Funds": 1000000000.0,
        }

    def test_the_newest_edition_stamps_the_pivoted_row(self):
        """A restated observation carries the latest publication date."""
        query = TreasuryBulletinFetcher.transform_query({"table": "ofs2"})
        rows = TreasuryBulletinFetcher.transform_data(
            query,
            [
                {
                    "record_date": "2026-03-31",
                    "end_of_month": "2026-03-31",
                    "securities_owner": "Mutual Funds",
                    "securities_bil_amt": "1.0",
                },
                {
                    "record_date": "2026-06-30",
                    "end_of_month": "2026-03-31",
                    "securities_owner": "Pension Funds",
                    "securities_bil_amt": "2.0",
                },
            ],
        )
        assert rows[0].record_date == date(2026, 6, 30)

    def test_a_row_with_no_classification_makes_no_column(self):
        """A blank classification would be an unnamed column, so it is dropped."""
        query = TreasuryBulletinFetcher.transform_query({"table": "ofs2"})
        rows = TreasuryBulletinFetcher.transform_data(
            query,
            [
                {
                    "record_date": "2026-06-30",
                    "end_of_month": "2026-03-31",
                    "securities_owner": "Mutual Funds",
                    "securities_bil_amt": "1.0",
                },
                {
                    "record_date": "2026-06-30",
                    "end_of_month": "2026-03-31",
                    "securities_owner": "",
                    "securities_bil_amt": "9.0",
                },
            ],
        )
        assert rows[0].model_dump(exclude_none=True) == {
            "table_code": "OFS-2",
            "report_date": date(2026, 3, 31),
            "record_date": date(2026, 6, 30),
            "Mutual Funds": 1000000000.0,
        }
