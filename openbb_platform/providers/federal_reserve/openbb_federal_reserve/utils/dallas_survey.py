"""Shared decoding for the Dallas Fed outlook-survey workbooks."""

from __future__ import annotations

from datetime import date as dateType
from typing import Any

MANUFACTURING_INDICATORS: dict[str, str] = {
    "prod": "Production",
    "capu": "Capacity Utilization",
    "vnwo": "Volume of New Orders",
    "gro": "Growth Rate of Orders",
    "ufil": "Unfilled Orders",
    "vshp": "Volume of Shipments",
    "dtm": "Delivery Time",
    "fgi": "Finished Goods Inventories",
    "prm": "Prices Paid for Raw Materials",
    "pfg": "Prices Received for Finished Goods",
    "wgs": "Wages and Benefits",
    "nemp": "Number of Employees",
    "avgwk": "Hours Worked",
    "cexp": "Capital Expenditures",
    "colk": "Company Outlook",
    "bact": "General Business Activity",
    "uncr": "Outlook Uncertainty",
}

SERVICE_INDICATORS: dict[str, str] = {
    "rev": "Revenue",
    "emp": "Employment",
    "pemp": "Part-Time Employment",
    "avgwk": "Hours Worked",
    "wgs": "Wages and Benefits",
    "inp": "Input Prices",
    "sell": "Selling Prices",
    "cexp": "Capital Expenditures",
    "inv": "Inventories",
    "colk": "Company Outlook",
    "bact": "General Business Activity",
    "uncr": "Outlook Uncertainty",
}


RETAIL_INDICATORS: dict[str, str] = {
    "rev": "Retail Sales",
    "trev": "Companywide Sales",
    "intrev": "Internet Sales",
    "emp": "Employment",
    "pemp": "Part-Time Employment",
    "avgwk": "Hours Worked",
    "wgs": "Wages and Benefits",
    "inp": "Input Prices",
    "sell": "Selling Prices",
    "cexp": "Capital Expenditures",
    "inv": "Inventories",
    "colk": "Company Outlook",
    "bact": "General Business Activity",
    "uncr": "Outlook Uncertainty",
}

ENERGY_INDICATORS: dict[str, str] = {
    "qbac": "Business Activity",
    "qoprd": "Oil Production",
    "qgprd": "Natural Gas Production",
    "qcexp": "Capital Expenditures",
    "qfexp": "Capital Expenditures (Next Year, Expected)",
    "qdvcst": "Finding and Development Costs",
    "qlsexp": "Lease Operating Expenses",
    "qsdtm": "Supplier Delivery Time",
    "qeqput": "Equipment Utilization",
    "qlgtm": "Lag Time in Turnaround of Activity",
    "qinp": "Input Costs",
    "qsell": "Prices Received for Services",
    "qopmgn": "Operating Margins",
    "qemp": "Employment",
    "qemphr": "Employee Hours",
    "qwgs": "Wages and Benefits",
    "qolk": "Company Outlook",
    "quncr": "Outlook Uncertainty",
}

BANKING_INDICATORS: dict[str, tuple[str, str]] = {
    "lvol": ("Total Loan Volume", "current"),
    "ldem": ("Loan Demand", "current"),
    "lnon": ("Nonperforming Loans", "current"),
    "lprice": ("Loan Pricing", "current"),
    "lstds": ("Credit Standards", "current"),
    "civol": ("Commercial & Industrial Loan Volume", "current"),
    "cinp": ("Commercial & Industrial Nonperforming Loans", "current"),
    "cistds": ("Commercial & Industrial Credit Standards", "current"),
    "crevol": ("Commercial Real Estate Loan Volume", "current"),
    "crenp": ("Commercial Real Estate Nonperforming Loans", "current"),
    "crestds": ("Commercial Real Estate Credit Standards", "current"),
    "rrevol": ("Residential Real Estate Loan Volume", "current"),
    "rrenp": ("Residential Real Estate Nonperforming Loans", "current"),
    "rrestds": ("Residential Real Estate Credit Standards", "current"),
    "cvol": ("Consumer Loan Volume", "current"),
    "cnp": ("Consumer Nonperforming Loans", "current"),
    "cstds": ("Consumer Credit Standards", "current"),
    "colkdem": ("Loan Demand", "future"),
    "colknp": ("Nonperforming Loans", "future"),
    "bact": ("General Business Activity", "current"),
    "fbact": ("General Business Activity", "future"),
    "ocorvol": ("Core Deposit Volume", "current"),
    "ocstfds": ("Cost of Funds", "current"),
    "onintmar": ("Net Interest Margin", "current"),
    "onintinc": ("Noninterest Income", "current"),
}

_RESPONSES = {"i": "increase", "n": "no change", "d": "decrease"}

_ENERGY_STEMS = {code[1:]: label for code, label in ENERGY_INDICATORS.items()}
_PRICE_PRODUCTS = {
    "oprc": "WTI Oil Price",
    "ngprc": "Henry Hub Natural Gas Price",
}
_PRICE_STATS = {
    "ref": "Reference",
    "avg": "Average",
    "med": "Median",
    "max": "Maximum",
    "min": "Minimum",
    "sd": "Standard Deviation",
    "nof": "Number of Responses",
}
_PRICE_SHARES = {
    "d": "% Expecting Decrease",
    "i": "% Expecting Increase",
    "n": "% Expecting No Change",
    "dk": "% Responding Don't Know",
}


def decode_energy_code(code: str) -> str:
    """Decode a Dallas Fed Energy Survey column code into a readable label."""
    text = str(code).strip()
    lower = text.lower()
    if not lower or lower == "date":
        return text

    if lower[0] in ("q", "y"):
        stem = lower[1:]
        if stem in _ENERGY_STEMS:
            return _ENERGY_STEMS[stem]
        if stem[-1:] in _RESPONSES and stem[:-1] in _ENERGY_STEMS:
            share = _RESPONSES[stem[-1]]
            return f"{_ENERGY_STEMS[stem[:-1]]} (% Reporting {share.title()})"

    for product, name in _PRICE_PRODUCTS.items():
        position = lower.find(product)
        if position < 0:
            continue
        head = lower[:position]
        tail = lower[position + len(product) :]
        if head in _PRICE_STATS and not tail:
            return f"{name} ({_PRICE_STATS[head]})"
        if head == "f" and (not tail or tail in _PRICE_SHARES):
            suffix = "Expected" if not tail else _PRICE_SHARES[tail]
            return f"{name} ({suffix})"

    return text


def parse_energy_long(
    content: bytes,
    sheet: str,
    start_date=None,
    end_date=None,
) -> list[dict]:
    """Melt every value column of an Energy Survey sheet into long records."""
    from io import BytesIO

    from pandas import isna, read_excel, to_datetime, to_numeric

    frame = read_excel(BytesIO(content), sheet_name=sheet)
    frame = frame.rename(columns={frame.columns[0]: "date"})
    frame["date"] = to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date"])
    frame["date"] = frame["date"].dt.date

    value_columns = [column for column in frame.columns if column != "date"]
    for column in value_columns:
        frame[column] = to_numeric(frame[column], errors="coerce")
    melted = frame[["date", *value_columns]].melt(
        id_vars=["date"], var_name="_code", value_name="value"
    )
    melted["indicator"] = melted["_code"].map(decode_energy_code)

    if start_date:
        melted = melted[melted["date"] >= start_date]
    if end_date:
        melted = melted[melted["date"] <= end_date]

    return [
        {
            "date": row["date"],
            "indicator": row["indicator"],
            "value": None if isna(row["value"]) else float(row["value"]),
        }
        for row in melted.sort_values(["date", "indicator"]).to_dict(orient="records")
    ]


def _decode_retail(code: str) -> tuple[str, str, str] | None:
    """Decode a retail code into ``(indicator, horizon, response)``."""
    lowered = code.strip().lower()
    bases = sorted(RETAIL_INDICATORS, key=len, reverse=True)
    for prefix, horizon in (("f", "future"), ("", "current")):
        if prefix and not lowered.startswith(prefix):
            continue
        rest = lowered[len(prefix) :]
        for base in bases:
            if rest == base:
                return RETAIL_INDICATORS[base], horizon, "net"
            for suffix, response in _RESPONSES.items():
                if rest == base + suffix:
                    return RETAIL_INDICATORS[base], horizon, response
    return None


def _decode(code: str, indicators: dict[str, str]) -> tuple[str, str] | None:
    """Decode a column code into an ``(indicator label, horizon)`` pair."""
    lowered = code.strip().lower()
    if lowered in indicators:
        return indicators[lowered], "current"
    if lowered.startswith("f") and lowered[1:] in indicators:
        return indicators[lowered[1:]], "future"
    return None


def _read_dated(
    content: bytes,
    sheet: str,
    date_format: str | None,
    start_date: dateType | None,
    end_date: dateType | None,
):
    """Read a survey sheet, parse its first column as the date, and filter."""
    from io import BytesIO

    from pandas import read_excel, to_datetime

    frame = read_excel(BytesIO(content), engine="openpyxl", sheet_name=sheet)
    frame = frame.rename(columns={frame.columns[0]: "date"})
    frame["date"] = to_datetime(
        frame["date"].astype(str).str.strip(),
        format=date_format or "mixed",
        errors="coerce",
    )
    frame = frame.dropna(subset=["date"])
    frame["date"] = frame["date"].dt.date
    if start_date:
        frame = frame[frame["date"] >= start_date]
    if end_date:
        frame = frame[frame["date"] <= end_date]
    return frame


def survey_sheet(content: bytes, names: tuple[str, ...]) -> str:
    """Return the workbook's sheet among ``names``, else its only sheet.

    The Dallas Fed has renamed the data sheet of its survey workbooks.

    Parameters
    ----------
    content : bytes
        The workbook.
    names : tuple[str, ...]
        The names the sheet has been published under, in order of preference.

    Returns
    -------
    str
        The name of the sheet to read.

    Raises
    ------
    OpenBBError
        When no name matches in a workbook of several sheets.
    """
    from io import BytesIO

    from openbb_core.app.model.abstract.error import OpenBBError
    from pandas import ExcelFile

    sheets = ExcelFile(BytesIO(content)).sheet_names

    for name in names:
        if name in sheets:
            return name

    if len(sheets) == 1:
        return str(sheets[0])

    raise OpenBBError(
        f"The Dallas Fed workbook has no sheet named {' or '.join(names)};"
        f" it has {', '.join(map(str, sheets))}."
    )


def parse_survey(
    content: bytes,
    sheet: str,
    indicators: dict[str, str],
    *,
    date_format: str | None = None,
    start_date: dateType | None = None,
    end_date: dateType | None = None,
) -> list[dict[str, Any]]:
    """Decode a survey sheet into long ``(date, indicator, horizon, value)`` records."""
    from pandas import isna, to_numeric

    frame = _read_dated(content, sheet, date_format, start_date, end_date)
    decoded: dict[Any, tuple[str, str]] = {}
    for column in frame.columns:
        if column == "date":
            continue
        result = _decode(str(column), indicators)
        if result is not None:
            decoded[column] = result
    records: list[dict[str, Any]] = []
    for column, (label, horizon) in decoded.items():
        series = to_numeric(frame[column], errors="coerce")
        for observation, value in zip(frame["date"], series):
            records.append(
                {
                    "date": observation,
                    "indicator": label,
                    "horizon": horizon,
                    "value": None if isna(value) else float(value),
                }
            )
    return sorted(records, key=lambda r: (r["date"], r["indicator"], r["horizon"]))


def parse_retail_survey(
    content: bytes,
    sheet: str,
    *,
    date_format: str | None = None,
    start_date: dateType | None = None,
    end_date: dateType | None = None,
) -> list[dict[str, Any]]:
    """Decode a retail sheet into ``(date, indicator, horizon, response, value)``."""
    from pandas import isna, to_numeric

    frame = _read_dated(content, sheet, date_format, start_date, end_date)
    decoded: dict[Any, tuple[str, str, str]] = {}
    for column in frame.columns:
        if column == "date":
            continue
        result = _decode_retail(str(column))
        if result is not None:
            decoded[column] = result
    records: list[dict[str, Any]] = []
    for column, (label, horizon, response) in decoded.items():
        series = to_numeric(frame[column], errors="coerce")
        for observation, value in zip(frame["date"], series):
            records.append(
                {
                    "date": observation,
                    "indicator": label,
                    "horizon": horizon,
                    "response": response,
                    "value": None if isna(value) else float(value),
                }
            )
    return sorted(
        records,
        key=lambda r: (r["date"], r["indicator"], r["horizon"], r["response"]),
    )


def parse_keyed_survey(
    content: bytes,
    sheet: str,
    mapping: dict[str, tuple[str, str]],
    *,
    date_format: str | None = None,
    start_date: dateType | None = None,
    end_date: dateType | None = None,
) -> list[dict[str, Any]]:
    """Decode a sheet whose columns map directly to ``(label, horizon)`` pairs."""
    from pandas import isna, to_numeric

    frame = _read_dated(content, sheet, date_format, start_date, end_date)
    records: list[dict[str, Any]] = []
    for column in frame.columns:
        if column == "date":
            continue
        entry = mapping.get(str(column).strip().lower())
        if not entry:
            continue
        label, horizon = entry
        series = to_numeric(frame[column], errors="coerce")
        for observation, value in zip(frame["date"], series):
            records.append(
                {
                    "date": observation,
                    "indicator": label,
                    "horizon": horizon,
                    "value": None if isna(value) else float(value),
                }
            )
    return sorted(records, key=lambda r: (r["date"], r["indicator"], r["horizon"]))
