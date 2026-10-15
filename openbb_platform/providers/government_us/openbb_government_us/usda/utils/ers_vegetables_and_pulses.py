"""USDA ERS Vegetables and Pulses Yearbook file catalog and long-format parser."""

import csv
import zipfile
from io import BytesIO, StringIO

BASE_URL = "https://www.ers.usda.gov"
PRODUCT_PAGE = (
    "data-products/vegetables-and-pulses-data/vegetables-and-pulses-yearbook-tables"
)
DATA_ZIP = "/media/5018/vegetables-and-pulses-machine-readable-data.zip"
CSV_MEMBERS = ("vegetables-pulses-data.csv", "Vegetables_Pulses.csv")

DEFAULT_TABLE = "Table33_Potatoes"

TABLE_LABELS: dict[str, str] = {
    "Table09_WorldVegProduction": "Selected vegetable production in leading"
    " countries and the world",
    "Table10_CashReceipts": "Vegetables and pulse crops: U.S. farm cash receipts",
    "Table11_TotalFresh": "U.S. fresh market vegetables: supply, availability,"
    " and farm weight",
    "Table12_Artichokes": "U.S. artichokes, all uses: supply, availability,"
    " price, and farm weight",
    "Table13_Asparagus": "U.S. fresh asparagus: supply, availability, price,"
    " and farm weight",
    "Table14_Broccoli": "U.S. fresh broccoli: supply, availability, price,"
    " and farm weight",
    "Table15_BrusselsSprouts": "U.S. brussels sprouts, all uses: supply,"
    " availability, price, and farm weight",
    "Table16_Cabbage": "U.S. cabbage: supply, availability, price, and farm weight",
    "Table17_Carrots": "U.S. fresh carrots: supply, availability, price,"
    " and farm weight",
    "Table18_Cauliflower": "U.S. fresh cauliflower: supply, availability,"
    " price, and farm weight",
    "Table19_Celery": "U.S. celery, all uses: supply, availability, price,"
    " and farm weight",
    "Table20_CollardGreens": "U.S. collard greens, all uses: supply,"
    " availability, price, and farm weight",
    "Table21_Cucumbers": "U.S. fresh cucumbers: supply, availability, price,"
    " and farm weight",
    "Table22_Eggplant": "U.S. eggplant, all uses: supply, availability, price,"
    " and farm weight",
    "Table23_EscaroleandEndive": "U.S. escarole and endive, all uses: supply,"
    " availability, price, and farm weight",
    "Table24_Garlic": "U.S. garlic, all uses: supply, availability, price,"
    " and farm weight",
    "Table25_HeadLettuce": "U.S. fresh head lettuce: supply, availability,"
    " price, and farm weight",
    "Table26_LeafandRomaine": "U.S. leaf and romaine lettuce: supply,"
    " availability, price, and farm weight",
    "Table27_Kale": "U.S. kale, all uses: supply, availability, price, and farm weight",
    "Table28_Mushrooms": "U.S. fresh mushrooms: supply, availability, price,"
    " and farm weight",
    "Table29_MustardGreens": "U.S. mustard greens, all uses: supply,"
    " availability, price, and farm weight",
    "Table30_Okra": "U.S. okra, all uses: supply, availability, and farm weight",
    "Table31_Onions": "U.S. fresh onions: supply, availability, price, and farm weight",
    "Table32_PeppersBell": "U.S. bell peppers, all uses: supply, availability,"
    " price, and farm weight",
    "Table33_Potatoes": "U.S. fresh potatoes: supply, availability, price,"
    " and farm weight",
    "Table34_Pumpkins": "U.S. pumpkins, all uses: supply, availability,"
    " and farm weight",
    "Table35_Radishes": "U.S. radishes, all uses: supply, availability,"
    " and farm weight",
    "Table36_SnapBeans": "U.S. fresh snap beans: supply, availability, price,"
    " and farm weight",
    "Table37_Spinach": "U.S. fresh spinach: supply, availability, price,"
    " and farm weight",
    "Table38_Squash": "U.S. squash, all uses: supply, availability, price,"
    " and farm weight",
    "Table39_SweetCorn": "U.S. fresh sweet corn: supply, availability, price,"
    " and farm weight",
    "Table40_SweetPotatoes": "U.S. sweet potatoes, all uses: supply,"
    " availability, price, and farm weight",
    "Table41_Tomatoes": "U.S. fresh tomatoes: supply, availability, price,"
    " and farm weight",
    "Table42_TurnipGreens": "U.S. turnip greens, all: supply, availability,"
    " price, and farm weight",
    "Table43_TotalVeg_Pr": "U.S. vegetables for processing (excluding potatoes):"
    " supply, availability, and farm weight",
    "Table44a_Asparagus_Pr": "U.S. asparagus for processing: supply,"
    " availability, price, and farm weight",
    "Table44b_Asparagus_Cn": "U.S. asparagus for canning: supply, availability,"
    " price, and farm weight",
    "Table44c_Asparagus_Fz": "U.S. asparagus for freezing: supply,"
    " availability, price, and farm weight",
    "Table45_Broccoli_Pr": "U.S. broccoli for processing: supply, availability,"
    " price, and farm weight",
    "Table46_Cabbage_Pr": "U.S. cabbage for sauerkraut: supply, availability,"
    " price, and farm weight",
    "Table47a_Carrots_Pr": "U.S. carrots for processing: supply, availability,"
    " price, and farm weight",
    "Table47b_Carrots_Fz": "U.S. carrots for freezing: supply, availability,"
    " price, and farm weight",
    "Table47c_Carrots_Cn": "U.S. carrots for canning: supply, availability,"
    " price, and farm weight",
    "Table48_Cauliflower_Pr": "U.S. cauliflower for processing: supply,"
    " availability, price, and farm weight",
    "Table49_Cucumbers_Pr": "U.S. cucumbers for processing (largely pickling):"
    " supply, availability, price, and farm weight",
    "Table50a_GreenLimaBeans_Pr": "U.S. green lima beans for processing:"
    " supply, availability, price, and farm weight",
    "Table50b_GreenLimaBeans_Cn": "U.S. green lima beans for canning: supply,"
    " availability, price, and farm weight",
    "Table50c_GreenLimaBeans_Fz": "U.S. green lima beans for freezing: supply,"
    " availability, price, and farm weight",
    "Table51_Mushrooms_Pr": "U.S. mushrooms for processing: supply,"
    " availability, price, and farm weight",
    "Table52_Onions_Dehy": "U.S. onions for dehydrating: supply, availability,"
    " price, and farm weight",
    "Table53a_GreenPeas_Pr": "U.S. peas (green) for processing: supply,"
    " availability, price, and farm weight",
    "Table53b_GreenPeas_Cn": "U.S. peas (green) for canning: supply,"
    " availability, price, and farm weight",
    "Table53c_GreenPeas_Fz": "U.S. peas (green) for freezing: supply,"
    " availability, price, and farm weight",
    "Table54_ChiliPeppers_Pr": "U.S. chili peppers, all uses: supply,"
    " availability, and price, farm weight",
    "Table55a_Potatoes_Cn": "U.S. potatoes for canning: supply, availability,"
    " price, and farm weight",
    "Table55b_Potatoes_Chip": "U.S. potatoes for chips and shoestrings: supply,"
    " availability, price, and farm weight",
    "Table55c_Potatoes_Dehy": "U.S. potatoes for dehydration: supply,"
    " availability, price, and farm weight",
    "Table55d_Potatoes_Fz": "U.S. potatoes for freezing: Supply and availability",
    "Table56a_SnapBeans_Pr": "U.S. snap beans for processing: supply,"
    " availability, price, and farm weight",
    "Table56b_SnapBeans_Cn": "U.S. snap beans for canning: supply,"
    " availability, price, and farm weight",
    "Table56c_SnapBeans_Fz": "U.S. snap beans for freezing: supply,"
    " availability, price, and farm weight",
    "Table57a_Spinach_Pr": "U.S. spinach for processing: supply, availability,"
    " price, and farm weight",
    "Table57b_Spinach_Cn": "U.S. spinach for canning: supply, availability,"
    " price, and farm weight",
    "Table57c_Spinach_Fz": "U.S. spinach for freezing: supply, availability,"
    " price, and farm weight",
    "Table58a_SweetCorn_Pr": "U.S. sweet corn for processing: supply,"
    " availability, price, and farm weight",
    "Table58b_SweetCorn_Cn": "U.S. sweet corn for canning: supply,"
    " availability, price, and farm weight",
    "Table58c_SweetCorn_Fz": "U.S. sweet corn for freezing: supply,"
    " availability, price, and farm weight",
    "Table59_Tomatoes_Pr": "U.S. tomatoes for processing: supply, availability,"
    " price, and farm weight",
    "Table60_AllDryBeans": "U.S. dry edible beans: supply, availability,"
    " and price, farm weight",
    "Table61_Pinto": "U.S. pinto beans, dry: supply, availability, and price,"
    " farm weight",
    "Table62_Navy": "U.S. navy beans, dry: supply, availability, and price,"
    " farm weight",
    "Table63_GreatNorthern": "U.S. great northern beans, dry: supply,"
    " availability, and price, farm weight",
    "Table64_Black": "U.S. black beans, dry: supply, availability, and price,"
    " farm weight",
    "Table65_Lima": "U.S. lima beans, dry: supply, availability, and price,"
    " farm weight",
    "Table66_RedKidney": "U.S. all red kidney beans, dry: supply, availability,"
    " and price, farm weight",
    "Table67_Blackeye": "U.S. blackeye beans, dry: supply, availability,"
    " and price, farm weight",
    "Table68_Garbanzo": "U.S. garbanzo beans, dry: supply, availability,"
    " and price, farm weight",
    "Table69_SmallWhite": "U.S. small white beans, dry: supply, availability,"
    " and price, farm weight",
    "Table70_SmallRed": "U.S. small red beans, dry: supply, availability,"
    " and price, farm weight",
    "Table71_Pink": "U.S. pink beans, dry: supply, availability, and price,"
    " farm weight",
    "Table72_Other": "U.S. cranberry and other beans, dry: supply,"
    " availability, and price, farm weight",
}


def parse_rows(text: str, table: str) -> list[dict]:
    """Parse the yearbook CSV text into long-format records for one table.

    Parameters
    ----------
    text : str
        Decoded CSV text of the Vegetables_Pulses.csv member.
    table : str
        Table key from TABLE_LABELS to keep; other tables are skipped.

    Returns
    -------
    list[dict]
        One record per kept observation, carrying the integer year, the
        commodity, end use, location, geographical level, item (the series
        that becomes a wide column), unit, category, and the numeric value.
        Rows for other tables, or whose year or value is blank or
        non-numeric, are skipped.
    """
    records: list[dict] = []
    for row in csv.DictReader(StringIO(text)):
        if (row.get("Table") or "").strip() != table:
            continue
        raw_value = (row.get("PublishValue") or "").strip()
        try:
            value = float(raw_value)
        except ValueError:
            continue
        year_label = (row.get("Year") or "").strip()
        if not year_label[:4].isdigit():
            continue
        records.append(
            {
                "table": table,
                "year": int(year_label[:4]),
                "commodity": (row.get("Commodity") or "").strip() or None,
                "end_use": (row.get("EndUse") or "").strip() or None,
                "location": (row.get("Location") or "").strip() or None,
                "geographical_level": (row.get("GeographicalLevel") or "").strip()
                or None,
                "item": (row.get("Item") or "").strip(),
                "unit": (row.get("Unit") or "").strip() or None,
                "category": (row.get("Category") or "").strip() or None,
                "value": value,
            }
        )
    return records


async def afetch_table(table: str, **kwargs) -> list[dict]:
    """Download the yearbook zip through the ERS cache and parse one table.

    Parameters
    ----------
    table : str
        Table key from TABLE_LABELS.

    Returns
    -------
    list[dict]
        Long-format records from parse_rows for the selected table.
    """
    from openbb_government_us.usda.utils.ers_client import afetch_ers_file

    content = await afetch_ers_file(DATA_ZIP, product=PRODUCT_PAGE)
    with zipfile.ZipFile(BytesIO(content)) as archive:
        names = {name.lower(): name for name in archive.namelist()}
        member = next(
            (names[m.lower()] for m in CSV_MEMBERS if m.lower() in names),
            CSV_MEMBERS[0],
        )
        raw = archive.read(member)
    return parse_rows(raw.decode("utf-8-sig", errors="replace"), table)
