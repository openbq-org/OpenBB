"""USDA ERS Livestock and Meat Domestic Data file catalog and parsers."""

import csv
import zipfile
from io import BytesIO, StringIO

from openbb_government_us.utils.serializers import is_null_token

BASE_URL = "https://www.ers.usda.gov"
PRODUCT_PAGE = "data-products/livestock-and-meat-domestic-data"

ZIP_MEDIA = "/media/5539/livestock-domestic-data-machine-readable-files.zip"
ZIP_DIR = "livestock-data-machine-readable-files"

LIVESTOCK_AND_MEAT_FILES: dict[str, dict] = {
    "supply_and_disappearance": {
        "label": "Meat supply and disappearance",
        "member": ("Meat-Supply-Disappearance.csv", "MeatSD.csv"),
        "table_name": None,
        "fold_dims": (("commodity_desc", "commodity"),),
        "col_dims": ("attribute_desc",),
        "multi_unit": True,
        "period": "timeperiod_desc",
        "period_sort": "timeperiod_id",
    },
    "slaughter": {
        "label": "Livestock and poultry slaughter",
        "member": ("Meat-Statistics.csv", "MeatStats.csv"),
        "table_name": "Livestock and poultry slaughter",
        "fold_dims": (("commodity_desc", "commodity"),),
        "col_dims": ("attribute_desc",),
        "multi_unit": False,
        "period": "month_year_strip",
        "period_sort": "timeperiod_id",
    },
    "production": {
        "label": "Red meat and poultry production",
        "member": ("Meat-Statistics.csv", "MeatStats.csv"),
        "table_name": "Red meat and poultry production",
        "fold_dims": (("commodity_desc", "commodity"),),
        "col_dims": ("attribute_desc",),
        "multi_unit": False,
        "period": "month_year_strip",
        "period_sort": "timeperiod_id",
    },
    "live_and_dressed_weights": {
        "label": "Livestock and poultry live and dressed weights",
        "member": ("Meat-Statistics.csv", "MeatStats.csv"),
        "table_name": "Livestock and poultry live and dressed weights",
        "fold_dims": (("commodity_desc", "commodity"),),
        "col_dims": ("attribute_desc",),
        "multi_unit": False,
        "period": "month_year_strip",
        "period_sort": "timeperiod_id",
    },
    "cold_storage": {
        "label": "Red meat and poultry cold storage stocks",
        "member": ("Meat-Statistics.csv", "MeatStats.csv"),
        "table_name": "Red meat and poultry beginning cold storage stocks",
        "fold_dims": (("commodity_desc", "commodity"),),
        "col_dims": ("attribute_desc",),
        "multi_unit": False,
        "period": "month_year_strip",
        "period_sort": "timeperiod_id",
    },
    "livestock_prices": {
        "label": "Livestock prices",
        "member": "LivestockPrices.csv",
        "table_name": None,
        "fold_dims": (),
        "col_dims": ("attribute_desc",),
        "multi_unit": True,
        "period": "month_desc",
        "period_sort": "month_id",
    },
    "wholesale_prices": {
        "label": "Wholesale prices",
        "member": "WholesalePrices.csv",
        "table_name": None,
        "fold_dims": (),
        "col_dims": ("commodity_desc", "geography_desc", "attribute_desc"),
        "multi_unit": True,
        "period": "month_desc",
        "period_sort": "month_id",
    },
    "feeder_cattle_outside_feedlots": {
        "label": "Feeder cattle supplies outside feedlots",
        "member": "FeederCattleSuppliesOutsideFeedlots.csv",
        "table_name": None,
        "fold_dims": (),
        "col_dims": ("attribute_desc",),
        "multi_unit": True,
        "period": None,
        "period_sort": None,
    },
    "heifers_entering_the_herd": {
        "label": "Heifers entering the herd",
        "member": "heifersenteringherd.csv",
        "table_name": None,
        "fold_dims": (("table_name", "table_name"),),
        "col_dims": ("attribute_desc",),
        "multi_unit": True,
        "period": None,
        "period_sort": None,
    },
    "high_plains_cattle_feeding_simulator": {
        "label": "High Plains cattle feeding simulator",
        "member": "highplainscattlefeedingsimulator.csv",
        "table_name": None,
        "fold_dims": (),
        "col_dims": ("geography_desc", "attribute_desc"),
        "multi_unit": True,
        "period": "timeperiod_desc",
        "period_sort": "month_id",
    },
}

FOLD_DIM_FIELDS = ("commodity", "table_name", "geography")


def _period(config: dict, row: dict) -> str | None:
    """Derive the row's period label from a CSV row.

    Parameters
    ----------
    config : dict
        Table configuration from LIVESTOCK_AND_MEAT_FILES.
    row : dict
        One decoded CSV row.

    Returns
    -------
    str | None
        The period label, or None for tables without a within-year period.
    """
    kind = config["period"]
    if kind is None:
        return None
    if kind == "month_year_strip":
        desc = (row.get("timeperiod_desc") or "").strip()
        year = (row.get("year_id") or "").strip()
        if year and desc.endswith("-" + year):
            return desc[: -(len(year) + 1)]
        return desc or None
    return (row.get(kind) or "").strip() or None


def _period_sort(config: dict, row: dict) -> int:
    """Derive the row's chronological sort key within a year.

    Parameters
    ----------
    config : dict
        Table configuration from LIVESTOCK_AND_MEAT_FILES.
    row : dict
        One decoded CSV row.

    Returns
    -------
    int
        The numeric period order; zero for tables without a period.
    """
    key = config["period_sort"]
    if key is None:
        return 0
    return int((row.get(key) or "0").strip() or 0)


def _amount(raw: str | None) -> float | str | None:
    """Parse a raw amount cell into a number, a text value, or None.

    Parameters
    ----------
    raw : str | None
        Raw cell text, which may carry comma separators, a null token such as
        'NA', or a textual value such as 'f.o.b.'.

    Returns
    -------
    float | str | None
        The parsed number, the stripped text for non-numeric values, or None
        for empty and null-token cells.
    """
    text = (raw or "").strip()
    if not text or is_null_token(text):
        return None
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return text


def column_label(config: dict, row: dict) -> str:
    """Build the wide column label for a CSV row.

    Parameters
    ----------
    config : dict
        Table configuration from LIVESTOCK_AND_MEAT_FILES.
    row : dict
        One decoded CSV row.

    Returns
    -------
    str
        The column-dimension values joined by a space, with the unit appended
        in parentheses when the table mixes units.
    """
    parts = [(row.get(col) or "").strip() for col in config["col_dims"]]
    label = " ".join(part for part in parts if part)
    if config["multi_unit"]:
        unit = (row.get("unit_desc") or "").strip()
        if unit:
            label = f"{label} ({unit})"
    return label


def parse_table(text: str, table: str) -> list[dict]:
    """Parse one table's CSV text into long-format observation records.

    Parameters
    ----------
    text : str
        Decoded CSV text of the table member.
    table : str
        Table key from LIVESTOCK_AND_MEAT_FILES.

    Returns
    -------
    list[dict]
        Records carrying the table key, the folding-dimension fields, the
        integer year, the period and its sort key, the single-unit table's
        row unit, the wide column label, and the amount. Rows filtered out by
        table name or holding an empty or null-token amount are skipped.
    """
    config = LIVESTOCK_AND_MEAT_FILES[table]
    table_name = config["table_name"]
    fold_dims = config["fold_dims"]
    records: list[dict] = []
    for row in csv.DictReader(StringIO(text)):
        if (
            table_name is not None
            and (row.get("table_name") or "").strip() != table_name
        ):
            continue
        amount = _amount(row.get("amount"))
        if amount is None:
            continue
        year_label = (row.get("year_id") or "").strip()
        if not year_label.isdigit():
            continue
        record: dict = {
            "table": table,
            "commodity": None,
            "table_name": None,
            "geography": None,
            "unit": None,
            "year": int(year_label),
            "period": _period(config, row),
            "period_sort": _period_sort(config, row),
            "column": column_label(config, row),
            "amount": amount,
        }
        for source_col, field in fold_dims:
            record[field] = (row.get(source_col) or "").strip() or None
        if not config["multi_unit"]:
            record["unit"] = (row.get("unit_desc") or "").strip() or None
        records.append(record)
    return records


async def afetch_table(table: str, **kwargs) -> list[dict]:
    """Download and parse one table through the ERS disk cache.

    Parameters
    ----------
    table : str
        Table key from LIVESTOCK_AND_MEAT_FILES.

    Returns
    -------
    list[dict]
        Long-format records from parse_table.
    """
    from openbb_government_us.usda.utils.ers_client import afetch_ers_file

    config = LIVESTOCK_AND_MEAT_FILES[table]
    content = await afetch_ers_file(ZIP_MEDIA, product=PRODUCT_PAGE)
    members = config["member"]
    if isinstance(members, str):
        members = (members,)
    with zipfile.ZipFile(BytesIO(content)) as archive:
        names = {name.lower(): name for name in archive.namelist()}
        member = next(
            (names[key] for m in members if (key := f"{ZIP_DIR}/{m}".lower()) in names),
            f"{ZIP_DIR}/{members[0]}",
        )
        raw = archive.read(member)
    return parse_table(raw.decode("utf-8-sig", errors="replace"), table)
