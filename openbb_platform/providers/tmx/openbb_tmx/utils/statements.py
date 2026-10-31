"""Financial statements shaped one line item per row, one period per column."""

STATEMENTS = {
    "income": "TmxIncomeStatementFetcher",
    "balance": "TmxBalanceSheetFetcher",
    "cash": "TmxCashFlowStatementFetcher",
}

MODULES = {
    "income": "income_statement",
    "balance": "balance_sheet",
    "cash": "cash_flow",
}

ITEM_COLUMN = "Item"

SKIPPED_FIELDS = (
    "period_ending",
    "fiscal_period",
    "fiscal_year",
    "filing_date",
    "is_restated",
)

PERIOD_FIELD = "period_ending"


def _fetcher(statement: str):
    """Return the fetcher that reads one statement."""
    from importlib import import_module

    module = import_module(f"openbb_tmx.models.{MODULES[statement]}")

    return getattr(module, STATEMENTS[statement])


def _label(field: str) -> str:
    """Return the row label for one model field."""
    return field.replace("_", " ").title()


async def statement_table(
    statement: str = "income",
    symbol: str = "AC",
    period: str = "annual",
    limit: int | None = None,
    use_cache: bool = True,
) -> list[dict]:
    """Read one statement with every reported period beside it.

    Parameters
    ----------
    statement : str
        One of 'income', 'balance', or 'cash'.
    symbol : str
        The company symbol.
    period : str
        Either 'annual' or 'quarter'.
    limit : int or None
        The number of periods to return, newest first.
    use_cache : bool
        Whether to read and write the on-disk cache.

    Returns
    -------
    list[dict]
        One row per line item, carrying a column per reported period.

    Raises
    ------
    OpenBBError
        If the statement is not one this provider publishes.
    """
    from openbb_core.app.model.abstract.error import OpenBBError

    if statement not in STATEMENTS:
        raise OpenBBError(f"Unknown statement '{statement}'.")

    fetcher = _fetcher(statement)
    reports = await fetcher.fetch_data(
        {"symbol": symbol, "period": period, "use_cache": use_cache}, {}
    )

    if limit:
        reports = reports[: int(limit)]

    columns = [str(getattr(r, PERIOD_FIELD)) for r in reports]
    dumped = [r.model_dump(mode="json") for r in reports]
    rows: list[dict] = []

    for field in type(reports[0]).model_fields:
        if field in SKIPPED_FIELDS:
            continue

        values = [report.get(field) for report in dumped]

        if all(value is None for value in values):
            continue

        rows.append({ITEM_COLUMN: _label(field)} | dict(zip(columns, values)))

    return rows
