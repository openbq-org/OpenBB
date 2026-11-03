"""Unit tests for the six SEC financial-statement ``transform_data`` paths.

The BLK fixture suite exercises the happy path (non-empty, no limit, no
diagnostics). These tests drive ``transform_data`` directly with synthetic
``StandardizedStatements``-shaped data to cover the empty-result, ``limit``,
validation-diagnostics, and NaN-serializer branches shared by all six models.
"""

from math import isnan, nan
from types import SimpleNamespace

import pytest
from openbb_core.provider.utils.errors import EmptyDataError

from openbb_sec.models.balance_sheet import (
    SecBalanceSheetData,
    SecBalanceSheetFetcher,
)
from openbb_sec.models.balance_sheet_growth import (
    SecBalanceSheetGrowthData,
    SecBalanceSheetGrowthFetcher,
)
from openbb_sec.models.cash_flow import (
    SecCashFlowStatementData,
    SecCashFlowStatementFetcher,
)
from openbb_sec.models.cash_flow_growth import (
    SecCashFlowStatementGrowthData,
    SecCashFlowStatementGrowthFetcher,
)
from openbb_sec.models.income_statement import (
    SecIncomeStatementData,
    SecIncomeStatementFetcher,
)
from openbb_sec.models.income_statement_growth import (
    SecIncomeStatementGrowthData,
    SecIncomeStatementGrowthFetcher,
)

# (Fetcher, Data class, statement attribute, a real tag on the base statement)
CASES = [
    (SecBalanceSheetFetcher, SecBalanceSheetData, "balance_sheet", "total_assets"),
    (
        SecCashFlowStatementFetcher,
        SecCashFlowStatementData,
        "cash_flow",
        "net_income",
    ),
    (
        SecIncomeStatementFetcher,
        SecIncomeStatementData,
        "income_statement",
        "revenue",
    ),
    (
        SecBalanceSheetGrowthFetcher,
        SecBalanceSheetGrowthData,
        "balance_sheet",
        "total_assets",
    ),
    (
        SecCashFlowStatementGrowthFetcher,
        SecCashFlowStatementGrowthData,
        "cash_flow",
        "net_income",
    ),
    (
        SecIncomeStatementGrowthFetcher,
        SecIncomeStatementGrowthData,
        "income_statement",
        "revenue",
    ),
]

_IDS = [c[2] + ("_growth" if "Growth" in c[0].__name__ else "") for c in CASES]


def _record(period_ending, fiscal_year, tag, value, source="10-K"):
    return {
        "period_ending": period_ending,
        "fiscal_period": "FY",
        "fiscal_year": fiscal_year,
        "currency": "USD",
        "tag": tag,
        "value": value,
        "source": source,
        "label": tag.replace("_", " ").title(),
        "description": "synthetic",
        "parent": None,
        "sequence": 1,
        "factor": "+",
        "balance": "debit",
        "unit": "monetary",
    }


def _result(statement, records, diagnostics):
    ns = SimpleNamespace(
        entity_name="Synthetic Corp",
        cik="0000000001",
        company_type="operating",
        diagnostics=diagnostics,
    )
    setattr(ns, statement, records)
    return ns


def _diagnostic():
    return SimpleNamespace(
        date="2023-12-31",
        tag="total_assets",
        expected=100.0,
        actual=110.0,
        formula="a == b + c",
        identity="balance",
    )


@pytest.mark.parametrize("fetcher, data_cls, statement, tag", CASES, ids=_IDS)
def test_transform_data_empty_raises(fetcher, data_cls, statement, tag):
    """An empty statement list raises EmptyDataError."""
    data = {"result": _result(statement, [], []), "statement": statement}
    with pytest.raises(EmptyDataError):
        fetcher.transform_data(SimpleNamespace(limit=None), data)


@pytest.mark.parametrize("fetcher, data_cls, statement, tag", CASES, ids=_IDS)
def test_transform_data_diagnostics_and_serializer(fetcher, data_cls, statement, tag):
    """Diagnostics surface validation_warnings; NaN values serialize to None."""
    records = [
        _record("2023-12-31", 2023, tag, 100.0, source="10-K"),
        _record("2022-12-31", 2022, tag, nan, source=""),
    ]
    data = {
        "result": _result(statement, records, [_diagnostic()]),
        "statement": statement,
    }

    with pytest.warns(Warning):
        result = fetcher.transform_data(SimpleNamespace(limit=None), data)

    assert len(result.result) == 2
    assert "validation_warnings" in result.metadata
    assert result.metadata["entity_name"] == "Synthetic Corp"

    # Serializer (model_dump wrap) turns NaN floats into None.
    dumped = [row.model_dump() for row in result.result]
    assert all(
        not (isinstance(v, float) and isnan(v)) for row in dumped for v in row.values()
    )


@pytest.mark.parametrize("fetcher, data_cls, statement, tag", CASES, ids=_IDS)
def test_transform_data_limit(fetcher, data_cls, statement, tag):
    """The limit parameter truncates to the most recent N periods."""
    records = [
        _record("2023-12-31", 2023, tag, 100.0),
        _record("2022-12-31", 2022, tag, 90.0),
        _record("2021-12-31", 2021, tag, 80.0),
    ]
    data = {"result": _result(statement, records, []), "statement": statement}
    result = fetcher.transform_data(SimpleNamespace(limit=1), data)
    assert len(result.result) == 1
    assert str(result.result[0].period_ending) == "2023-12-31"


@pytest.mark.parametrize("fetcher, data_cls, statement, tag", CASES, ids=_IDS)
def test_transform_data_pit_metadata(fetcher, data_cls, statement, tag):
    """PIT fields (filing_date, is_restated) and metadata['periods'] / as_of_date populate."""
    rec = _record("2023-12-31", 2023, tag, 100.0)
    rec["filing_date"] = "2024-02-15"
    rec["original_filing_date"] = "2024-02-15"
    rec["latest_filing_date"] = "2025-02-15"
    rec["is_restated"] = True
    res_obj = _result(statement, [rec], [])
    res_obj.schema_version = "1.0"
    data = {"result": res_obj, "statement": statement}
    query = fetcher.transform_query({"symbol": "AAPL", "as_of_date": "2025-06-15"})
    out = fetcher.transform_data(query, data)
    assert str(out.result[0].filing_date) == "2024-02-15"
    assert out.result[0].is_restated is True
    assert out.metadata["as_of_date"] == "2025-06-15"
    assert out.metadata["periods"]["2023-12-31"]["is_restated"] is True
    assert out.metadata["periods"]["2023-12-31"]["filing_date"] == "2024-02-15"
