"""USDA ERS Farm Household Income and Characteristics catalog, fetch, and parser."""

import csv
from io import StringIO

PRODUCT_PAGE = "data-products/farm-household-income-and-characteristics"

DEFAULT_TABLE = "finances_2021_26f"

TABLE_CONFIG: dict[str, dict] = {
    "finances_2021_26f": {
        "media_path": "/media/7005/principal-us-farm-operator-household-finances-2021-26f.csv",
        "shape": "year",
        "item_col": "Item",
        "dim_col": "Year",
        "label": "Principal U.S. farm operator household finances, 2021-26F",
    },
    "mean_median_income": {
        "media_path": "/media/7001/mean-and-median-us-farm-operator-household-income-and-ratio-of-farm-household-to-us-household-income-1960-2024.csv",
        "shape": "year",
        "item_col": "IncomeMeasure",
        "dim_col": "Year",
        "label": "Mean and median U.S. farm operator household income and ratio of"
        " farm household to U.S. household income, 1960-2024",
    },
    "farm_size_class": {
        "media_path": "/media/6999/all-farms-and-family-farms-by-farm-size-class-gross-sales-1996-2024.csv",
        "shape": "year",
        "item_col": "FarmType",
        "dim_col": "Year",
        "label": "All farms and family farms, by farm size class (gross sales),"
        " 1996-2024",
    },
    "by_farm_type_2024": {
        "media_path": "/media/6995/principal-farm-operator-household-finances-by-farm-type-2024.csv",
        "shape": "category",
        "item_col": "Item",
        "dim_col": "FarmType",
        "dim_deunderscore": True,
        "label": "Principal farm operator household finances, by farm type, 2024",
    },
    "by_occupation_2024": {
        "media_path": "/media/6997/finances-and-characteristics-of-principal-farm-operator-households-by-major-occupation-2024.csv",
        "shape": "category",
        "item_col": "Item",
        "dim_col": "Occupation",
        "dim_prefix": "Major occupation of principal operator: ",
        "label": "Finances and characteristics of principal farm operator"
        " households, by major occupation, 2024",
    },
    "by_age_2024": {
        "media_path": "/media/20794/characteristics-of-principal-farm-operator-households-by-age-of-principal-operators-2024.csv",
        "shape": "combined",
        "label": "Characteristics of principal farm operator households, by age of"
        " principal operators, 2024",
    },
    "by_experience_2024": {
        "media_path": "/media/20796/characteristics-of-principal-farm-operator-households-by-experience-of-operators-2024.csv",
        "shape": "combined",
        "label": "Characteristics of principal farm operator households, by"
        " experience of operators, 2024",
    },
    "by_management_team_2024": {
        "media_path": "/media/20798/characteristics-of-principal-farm-operator-households-by-type-of-management-team-2024.csv",
        "shape": "combined",
        "label": "Characteristics of principal farm operator households, by type of"
        " management team, 2024",
    },
    "by_limited_resource_2024": {
        "media_path": "/media/20800/characteristics-of-principal-farm-operator-households-by-limited-resource-farm-status-2024.csv",
        "shape": "combined",
        "label": "Characteristics of principal farm operator households, by"
        " limited-resource farm status, 2024",
    },
    "by_sex_2024": {
        "media_path": "/media/20802/characteristics-of-principal-farm-operator-households-by-sex-of-principal-operator-2024.csv",
        "shape": "combined",
        "label": "Characteristics of principal farm operator households, by sex of"
        " principal operator, 2024",
    },
}

TABLE_LABELS: dict[str, str] = {
    key: config["label"] for key, config in TABLE_CONFIG.items()
}

YEAR_TABLES: frozenset[str] = frozenset(
    key for key, config in TABLE_CONFIG.items() if config["shape"] == "year"
)


def clean_label(value: str | None) -> str:
    """Strip no-break spaces and surrounding whitespace from a label.

    Parameters
    ----------
    value : str | None
        Raw item or category label.

    Returns
    -------
    str
        The label with no-break-space bytes removed and ends stripped.
    """
    return (value or "").replace("\xa0", "").strip()


def clean_column(config: dict, raw: str | None) -> str:
    """Normalize a cross-tab category value into its wide-column header.

    Parameters
    ----------
    config : dict
        The table's TABLE_CONFIG entry.
    raw : str | None
        Raw dimension value, e.g. 'Residence_Farms' or a prefixed occupation.

    Returns
    -------
    str
        The category with any configured prefix removed and underscores
        replaced by spaces, ends stripped.
    """
    value = raw or ""
    prefix = config.get("dim_prefix")
    if prefix and value.startswith(prefix):
        value = value[len(prefix) :]
    if config.get("dim_deunderscore"):
        value = value.replace("_", " ")
    return value.strip()


def parse_value(raw: str | None) -> int | float | None:
    """Parse a raw Value cell into a number, keeping full precision.

    Parameters
    ----------
    raw : str | None
        Raw Value cell, which may be 'NA' or blank where a value is absent.

    Returns
    -------
    int | float | None
        The integer or float value, or None when the cell is blank or a
        non-numeric placeholder such as 'NA'.
    """
    text = (raw or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return None


def parse_year(column: str) -> int:
    """Return the integer year of a year-column header, forecast suffix dropped.

    Parameters
    ----------
    column : str
        Year header, e.g. '2024' or the forecast '2025F'.

    Returns
    -------
    int
        The four-digit year as an integer.
    """
    return int(column.rstrip("FP"))


def year_sort_key(column: str) -> tuple[int, bool]:
    """Return a chronological sort key that keeps forecast years last.

    Parameters
    ----------
    column : str
        Year header, e.g. '2024' or the forecast '2025F'.

    Returns
    -------
    tuple[int, bool]
        The integer year and whether the header is a forecast, so a forecast
        year sorts after a non-forecast year of the same value.
    """
    return (parse_year(column), column.endswith(("F", "P")))


def parse_table(text: str, table: str) -> list[dict]:
    """Parse a table's CSV into long records of item, column, and value.

    Parameters
    ----------
    text : str
        Decoded CSV text of the table file.
    table : str
        Table key from TABLE_CONFIG.

    Returns
    -------
    list[dict]
        Records with item, column, and value keys, in source row order. The
        column is the year for the time-series tables and the category for the
        cross-tab tables.
    """
    config = TABLE_CONFIG[table]
    shape = config["shape"]
    records: list[dict] = []
    for row in csv.DictReader(StringIO(text)):
        if shape == "combined":
            category, separator, item = (row.get("Combined_Label") or "").partition(
                ": "
            )
            if not separator:
                continue
            column = clean_label(category)
            item = clean_label(item)
        else:
            item = clean_label(row.get(config["item_col"]))
            column = clean_column(config, row.get(config["dim_col"]))
        if not item or not column:
            continue
        records.append(
            {"item": item, "column": column, "value": parse_value(row.get("Value"))}
        )
    return records


async def afetch_table(table: str) -> list[dict]:
    """Download and parse one table's CSV through the ERS disk cache.

    Parameters
    ----------
    table : str
        Table key from TABLE_CONFIG.

    Returns
    -------
    list[dict]
        Long records from parse_table for the selected table.
    """
    from openbb_government_us.usda.utils.ers_client import afetch_ers_file

    content = await afetch_ers_file(
        TABLE_CONFIG[table]["media_path"], product=PRODUCT_PAGE
    )
    return parse_table(content.decode("utf-8-sig", errors="replace"), table)
