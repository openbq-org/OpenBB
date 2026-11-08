"""Shape as-filed SEC statement tables for Workspace widgets."""

from types import SimpleNamespace


async def get_as_filed_widget_rows(
    symbol: str,
    statement_type: str,
    calendar_year: str | None = None,
    calendar_period: str | None = None,
    use_cache: bool = True,
) -> list[dict]:
    """Return as-filed statement rows from the standard statement pipeline."""
    from pandas import isna

    from openbb_sec.models.sec_financials import (
        FinancialStatements,
        resolve_section_url,
    )

    query = SimpleNamespace(
        symbol=symbol,
        url=None,
        calendar_year=calendar_year,
        calendar_period=calendar_period,
        use_cache=use_cache,
    )
    url = await resolve_section_url(query, annual_default=False)
    if not url:
        return []

    statements = FinancialStatements.from_url(url, use_cache)
    data, _ = statements.get_statement(statement_type)
    if data is None or data.empty:
        return []

    if {"label", "period_ending", "value"}.issubset(data.columns):
        id_columns = ["order", "label"]
        if "unit" in data.columns:
            id_columns.append("unit")
        data = data[
            ~(
                data["label"].isna()
                & data.groupby("order")["value"].transform(lambda s: s.isna().all())
            )
        ]
        period_order = list(dict.fromkeys(data["period_ending"].astype(str).tolist()))
        data = data.drop_duplicates(
            subset=[*id_columns, "period_ending"],
            keep="first",
        )
        data = data.pivot(
            index=id_columns,
            columns="period_ending",
            values="value",
        ).reset_index()
        ordered_periods = [p for p in period_order if p in data.columns]
        data = data[[*id_columns, *ordered_periods]]
        data = data.astype(object).where(data.notna(), "--")
    else:
        drop_columns = {
            "tag",
            "parent_tag",
            "preferred_label",
            "balance",
            "weight",
            "decimals",
            "context_ref",
            "period_beginning",
            "period_ending",
            "value",
            "taxonomy",
            "data_type",
            "period_type",
            "description",
            "name",
        }
        keep_columns = [c for c in data.columns if str(c) not in drop_columns]
        data = data[keep_columns]

    source_columns = list(data.columns)
    if not source_columns:
        return []

    label_column = "label" if "label" in source_columns else source_columns[0]
    rows: list[dict] = []

    for idx, row in enumerate(data.itertuples(index=False), start=1):
        values = list(row)
        output: dict = {"order": idx}
        for column_name, value in zip(source_columns, values):
            if str(column_name) == "order":
                output["order"] = value
                continue
            key = "label" if column_name == label_column else str(column_name)
            if value == "--":
                output[key] = "--"
            else:
                output[key] = None if isna(value) else value
        rows.append(output)

    return rows
