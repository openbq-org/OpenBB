"""Federal Reserve BHCPR (Bank Holding Company Performance Report) Data Model."""

import re
from datetime import (
    date as dateType,
    datetime,
)
from typing import Any

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.abstract.annotated_result import AnnotatedResult
from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

_NBSP = " "
_UNIT_MARKER = re.compile(r"\s*\((?:\$\s*000s?|in thousands)\)", re.IGNORECASE)
_SUBCOLUMNS = (("amount", ""), ("bhc", "BHC"), ("peer", "Peer #"), ("pct", "Pct"))


def _unit(basis: str | None) -> str:
    """Return the value type a line item's guide basis renders as."""
    text = basis or ""
    if text == "Dollar Amount in Thousands":
        return "USD"
    if "(x" in text.lower():
        return "ratio"
    if text == "Number":
        return "number"
    return "percent"


def _iso_to_display(date: str) -> str:
    """Render an ISO ``YYYY-MM-DD`` period as ``MM/DD/YYYY``."""
    return f"{date[5:7]}/{date[8:10]}/{date[:4]}"


def _quarter_end(year: int, quarter: int) -> str:
    """Return the ``YYYYMMDD`` quarter-end date for a year and quarter."""
    month_day = {1: "0331", 2: "0630", 3: "0930", 4: "1231"}[quarter]
    return f"{year}{month_day}"


def _default_period() -> tuple[int, int]:
    """Return the most recent (year, quarter) whose BHCPR is likely available."""
    today = datetime.now().date()
    year = today.year
    quarter = (today.month - 1) // 3 + 1
    while True:
        available_month = 3 * quarter + 2
        available_year = year + (available_month - 1) // 12
        available_month = (available_month - 1) % 12 + 1
        if (today.year, today.month) >= (available_year, available_month):
            return year, quarter
        quarter -= 1
        if quarter == 0:
            quarter, year = 4, year - 1


def _filed_periods(rssd: str) -> list[str]:
    """Return a firm's filed BHCPR period-ends as ``YYYYMMDD``, newest first."""
    from openbb_federal_reserve.utils.ffiec import fetch_institution_financial_reports

    if not rssd:
        return []
    try:
        reports = fetch_institution_financial_reports(rssd)
    except Exception:  # noqa: BLE001
        return []
    if not isinstance(reports, dict):
        return []
    return [
        _quarter_end(int(period["year"]), int(period["quarter"]))
        for period in reports.get("BHCPR", {}).get("periods", [])
        # NIC lists a quarter before its report is published; its CSV is an error page.
        if period.get("pdf_available", True)
    ]


def _resolve_period(period: str | None, filed: list[str]) -> str:
    """Resolve a ``YYYYMMDD`` period, defaulting to the firm's latest filed period."""
    text = (period or "").strip()
    if text:
        return text
    if filed:
        return filed[0]
    year, quarter = _default_period()
    return _quarter_end(year, quarter)


class FederalReserveBhcprQueryParams(QueryParams):
    """Federal Reserve BHCPR Data Query Parameters."""

    __json_schema_extra__ = {
        "rssd_id": {"x-widget_config": {"group": "rssd_id"}},
        "section": {
            "x-widget_config": {
                "type": "endpoint",
                "optionsEndpoint": "bhcpr_sections",
            }
        },
        "period": {
            "x-widget_config": {
                "type": "endpoint",
                "optionsEndpoint": "bhcpr_periods",
                "optionsParams": {"rssd_id": "$rssd_id"},
            }
        },
    }

    rssd_id: str = Field(
        description="The reporting holding company's RSSD identifier.",
    )
    section: str | None = Field(
        default="Summary Ratios",
        description="The BHCPR report section to return, by its title. When set to"
        " 'All Sections' every section is rendered.",
    )
    period: str | None = Field(
        default=None,
        description="The reporting period to render, as a `YYYYMMDD` quarter-end."
        " Defaults to the latest available. Cascades off `rssd_id`.",
    )


class FederalReserveBhcprData(Data):
    """Federal Reserve BHCPR Data."""

    label: str = Field(
        description="The line item, indented under its section or sub-header.",
    )
    is_header: bool = Field(
        default=False,
        description="Whether the row is a section or sub-header.",
    )
    narrative: str | None = Field(
        default=None,
        description="The BHCPR User's Guide definition of the line item, shown in the"
        " hover card.",
    )
    unit: str | None = Field(
        default=None,
        description="The line item's value type: 'USD' (full dollars), 'percent',"
        " 'ratio' (a multiple), or 'number' (a count).",
    )


class FederalReserveBhcprFetcher(
    Fetcher[
        FederalReserveBhcprQueryParams,
        list[FederalReserveBhcprData],
    ]
):
    """Federal Reserve BHCPR Data Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> FederalReserveBhcprQueryParams:
        """Transform the query params."""
        return FederalReserveBhcprQueryParams(**params)

    @staticmethod
    def extract_data(
        query: FederalReserveBhcprQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Fetch and read the holding company's BHCPR report for the period."""
        from openbb_federal_reserve.utils.ffiec import (
            fetch_bhcpr,
            resolve_bhcpr_holder,
        )

        rssd = resolve_bhcpr_holder(str(query.rssd_id).strip())
        period = _resolve_period(query.period, _filed_periods(rssd))

        data = fetch_bhcpr(rssd, period)
        if not data.get("values"):
            raise EmptyDataError("The request was returned empty.")
        return data

    @staticmethod
    def transform_data(
        query: FederalReserveBhcprQueryParams,
        data: dict[str, Any],
        **kwargs: Any,
    ) -> AnnotatedResult[list[FederalReserveBhcprData]]:
        """Render the selected section's rows from the schema and coded CSV values."""
        from openbb_federal_reserve.utils.bhcpr_csv import PERIOD_SUFFIXES
        from openbb_federal_reserve.utils.bhcpr_schema import load_schema

        schema = load_schema()
        values = data.get("values", {})
        period_by_suffix = data.get("periods", {})
        period_cols: list[tuple[str, str]] = []
        for suffix in PERIOD_SUFFIXES:
            raw = period_by_suffix.get(suffix)
            if raw and len(raw) == 8:
                period_cols.append((suffix, f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"))

        section = (query.section or "").strip()
        select_all = not section or section.lower() == "all sections"
        by_title = {entry["section"].lower(): entry for entry in schema}
        if not select_all and section.lower() not in by_title:
            raise OpenBBError(
                f"Unknown section '{query.section}'. Choose one of:"
                f" {', '.join(entry['section'] for entry in schema)}."
            )
        chosen = schema if select_all else [by_title[section.lower()]]

        raw_rows: list[tuple[str, bool, str | None, str | None, dict[Any, Any]]] = []
        present: set[Any] = set()
        for entry in chosen:
            raw_rows.append((entry["section"], True, None, None, {}))
            for item in entry["entries"]:
                indent = _NBSP * 2 * (item["level"] + 1)
                if item["kind"] == "subheader":
                    raw_rows.append((indent + item["label"], True, None, None, {}))
                    continue
                cells: dict[Any, Any] = {}
                code = item.get("code")
                unit = _unit(item.get("basis")) if code else None
                if code:
                    digits = "".join(
                        character for character in code if character.isdigit()
                    )
                    peer = (
                        values.get(f"PHSR{digits}", {})
                        if code.startswith("BHSR")
                        else {}
                    )
                    pct = (
                        values.get(f"RKSR{digits}", {})
                        if code.startswith("BHSR")
                        else {}
                    )
                    primary = values.get(code, {})
                    scale = 1000 if unit == "USD" else 1
                    for suffix, _date in period_cols:
                        bhc, peer_value = primary.get(suffix), peer.get(suffix)
                        if peer or pct:
                            columns = (
                                ("bhc", bhc * scale if bhc is not None else None),
                                (
                                    "peer",
                                    peer_value * scale
                                    if peer_value is not None
                                    else None,
                                ),
                                ("pct", pct.get(suffix)),
                            )
                        else:
                            columns = (
                                ("amount", bhc * scale if bhc is not None else None),
                            )
                        for sub, value in columns:
                            if value is not None:
                                cells[(suffix, sub)] = value
                                present.add((suffix, sub))
                label = _UNIT_MARKER.sub("", item["label"]).strip()
                raw_rows.append(
                    (">" + indent + label, False, item["definition"], unit, cells)
                )

        columns: list[Any] = []
        for suffix, date in period_cols:
            for sub, _label in _SUBCOLUMNS:
                if (suffix, sub) in present:
                    columns.append((suffix, sub, date))

        labels = {sub: text for sub, text in _SUBCOLUMNS}

        def _name(key: Any) -> str:
            """Render a ``(suffix, sub, date)`` column key as its display header."""
            return f"{_iso_to_display(key[2])} {labels[key[1]]}".strip()

        rows: list[FederalReserveBhcprData] = []
        for label, is_header, narrative, unit, cells in raw_rows:
            row: dict[str, Any] = {
                "label": label,
                "is_header": is_header,
                "narrative": narrative,
                "unit": unit,
            }
            for key in columns:
                row[_name(key)] = cells.get((key[0], key[1]))
            rows.append(FederalReserveBhcprData.model_validate(row))

        identity = data.get("identity", {})
        report_date: dateType | None = None
        if period_cols:
            report_date = datetime.strptime(period_cols[0][1], "%Y-%m-%d").date()

        return AnnotatedResult(
            result=rows,
            metadata={
                key: value
                for key, value in {
                    "rssd_id": identity.get("rssd_id") or str(query.rssd_id).strip(),
                    "name": identity.get("institution_name"),
                    "city_state": identity.get("city_state"),
                    "section": query.section,
                    "reporting_date": report_date.isoformat() if report_date else None,
                }.items()
                if value
            },
        )
