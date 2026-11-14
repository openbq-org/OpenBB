"""Tests for the USDA ERS Farm Household Income and Characteristics utils and model."""

import asyncio
import csv
from io import StringIO

import pytest
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.utils.errors import EmptyDataError

from openbb_government_us.usda.models.farm_household_income_and_characteristics import (
    FarmHouseholdIncomeAndCharacteristicsData,
    FarmHouseholdIncomeAndCharacteristicsFetcher,
    FarmHouseholdIncomeAndCharacteristicsQueryParams,
)
from openbb_government_us.usda.utils import (
    ers_farm_household_income_and_characteristics as util,
)
from openbb_government_us.usda.utils.ers_farm_household_income_and_characteristics import (
    DEFAULT_TABLE,
    PRODUCT_PAGE,
    TABLE_CONFIG,
    TABLE_LABELS,
    YEAR_TABLES,
    afetch_table,
    clean_column,
    clean_label,
    parse_table,
    parse_value,
    parse_year,
    year_sort_key,
)


def _csv(header, rows):
    """Serialize a header and rows to CSV text."""
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    for row in rows:
        writer.writerow(row)
    return buffer.getvalue()


YEAR_CSV = _csv(
    ["Item", "Year", "Value", "Source", "Date"],
    [
        ["Number of family farms", "2023", "100", "src", "d"],
        ["Number of family farms", "2024", "110", "src", "d"],
        ["Number of family farms", "2025F", "NA", "src", "d"],
        ["Off-farm income", "2023", "50.5", "src", "d"],
        ["Off-farm income", "2024", "60", "src", "d"],
        ["Off-farm income", "2025F", "70", "src", "d"],
    ],
)

CATEGORY_CSV = _csv(
    ["Item", "FarmType", "Value", "Source", "Date"],
    [
        ["Number of family farms", "Residence_Farms", "900", "src", "d"],
        ["Number of family farms", "Commercial_Farms", "200", "src", "d"],
        ["Number of family farms", "All_Farms", "1100", "src", "d"],
        ["Farm income", "Residence_Farms", "10", "src", "d"],
        ["Farm income", "Commercial_Farms", "20", "src", "d"],
        ["Farm income", "All_Farms", "15", "src", "d"],
    ],
)

OCCUPATION_CSV = _csv(
    ["Item", "Occupation", "Value", "Source", "Date"],
    [
        [
            "Number of family farms",
            "Major occupation of principal operator: Farm or ranch work",
            "973966",
            "src",
            "d",
        ],
        [
            "Number of family farms",
            "Major occupation of principal operator: All farm operator households",
            "1819554",
            "src",
            "d",
        ],
    ],
)

COMBINED_CSV = _csv(
    ["Combined_Label", "Value", "Source"],
    [
        ["Less than 35 years old: Number of family farm households", "52366", "src"],
        ["Less than 35 years old: Total operators            \xa0", "83753", "src"],
        ["All family farms: Number of family farm households", "1819554", "src"],
        ["All family farms: Total operators ", "2912610", "src"],
        ["NoSeparatorLabel", "5", "src"],
        ["Male: ", "9", "src"],
    ],
)

BLANK_ITEM_CSV = _csv(
    ["Item", "Year", "Value", "Source", "Date"],
    [
        ["", "2024", "5", "src", "d"],
        ["Real item", "2024", "6", "src", "d"],
    ],
)


class TestErsFarmHouseholdIncomeAndCharacteristicsUtils:
    """Tests for the ers_farm_household_income_and_characteristics utils module."""

    def test_catalog_contents(self):
        """The catalog holds the 10 current tables with their pivot config."""
        assert len(TABLE_CONFIG) == 10
        assert DEFAULT_TABLE == "finances_2021_26f"
        assert DEFAULT_TABLE in TABLE_CONFIG
        assert set(TABLE_LABELS) == set(TABLE_CONFIG)
        shapes = {config["shape"] for config in TABLE_CONFIG.values()}
        assert shapes == {"year", "category", "combined"}
        for config in TABLE_CONFIG.values():
            assert config["media_path"].startswith("/media/")
            assert config["media_path"].endswith(".csv")
            assert config["label"]

    def test_year_tables_are_the_three_time_series(self):
        """YEAR_TABLES lists exactly the three time-series tables."""
        assert (
            frozenset({"finances_2021_26f", "mean_median_income", "farm_size_class"})
            == YEAR_TABLES
        )

    def test_clean_label_strips_nbsp_and_whitespace(self):
        """clean_label removes no-break spaces and surrounding whitespace."""
        assert clean_label("Total operators            \xa0") == "Total operators"
        assert clean_label("  spaced  ") == "spaced"
        assert clean_label(None) == ""

    def test_clean_column_deunderscores(self):
        """clean_column replaces underscores when the table configures it."""
        config = {"dim_deunderscore": True}
        assert clean_column(config, "Residence_Farms") == "Residence Farms"

    def test_clean_column_strips_prefix(self):
        """clean_column removes a configured occupation prefix."""
        config = {"dim_prefix": "Major occupation of principal operator: "}
        assert (
            clean_column(config, "Major occupation of principal operator: Farm work")
            == "Farm work"
        )

    def test_clean_column_prefix_not_present(self):
        """clean_column leaves a value that does not start with the prefix."""
        config = {"dim_prefix": "X: "}
        assert clean_column(config, "Y value") == "Y value"

    def test_clean_column_plain(self):
        """clean_column with no transforms just strips whitespace."""
        assert clean_column({}, "  2024  ") == "2024"

    def test_parse_value_integer(self):
        """A pure integer string parses to an int."""
        assert parse_value("1960695") == 1960695
        assert isinstance(parse_value("1960695"), int)

    def test_parse_value_float(self):
        """A decimal string parses to a float, keeping full precision."""
        assert parse_value("149.630228133494") == 149.630228133494

    def test_parse_value_negative(self):
        """A negative integer string parses to a negative int."""
        assert parse_value("-1830") == -1830

    def test_parse_value_blank_and_none(self):
        """A blank cell or None parses to None."""
        assert parse_value("") is None
        assert parse_value("   ") is None
        assert parse_value(None) is None

    def test_parse_value_placeholder(self):
        """A non-numeric placeholder such as 'NA' parses to None."""
        assert parse_value("NA") is None
        assert parse_value("n/a") is None

    def test_parse_year_and_sort_key(self):
        """parse_year drops the forecast suffix; the sort key flags forecasts."""
        assert parse_year("2024") == 2024
        assert parse_year("2025F") == 2025
        assert year_sort_key("2024") == (2024, False)
        assert year_sort_key("2025F") == (2025, True)
        assert sorted(["2025F", "2024", "2026F"], key=year_sort_key) == [
            "2024",
            "2025F",
            "2026F",
        ]

    def test_parse_year_preliminary_suffix(self):
        """A preliminary year such as 2025P parses and sorts like a forecast."""
        assert parse_year("2025P") == 2025
        assert year_sort_key("2025P") == (2025, True)
        assert sorted(["2026F", "2025P", "2025", "2024"], key=year_sort_key) == [
            "2024",
            "2025",
            "2025P",
            "2026F",
        ]

    def test_parse_table_year_shape(self):
        """A time-series table yields item/column/value records with the year."""
        records = parse_table(YEAR_CSV, "finances_2021_26f")
        assert len(records) == 6
        assert records[0] == {
            "item": "Number of family farms",
            "column": "2023",
            "value": 100,
        }
        forecast = next(record for record in records if record["column"] == "2025F")
        assert forecast["value"] is None

    def test_parse_table_category_shape(self):
        """A cross-tab table de-underscores the category into the column."""
        records = parse_table(CATEGORY_CSV, "by_farm_type_2024")
        assert records[0]["column"] == "Residence Farms"
        assert {record["column"] for record in records} == {
            "Residence Farms",
            "Commercial Farms",
            "All Farms",
        }

    def test_parse_table_occupation_prefix_stripped(self):
        """A by-occupation table strips the occupation prefix from the column."""
        records = parse_table(OCCUPATION_CSV, "by_occupation_2024")
        assert {record["column"] for record in records} == {
            "Farm or ranch work",
            "All farm operator households",
        }

    def test_parse_table_combined_shape(self):
        """A combined-label table splits on the first ': ' into category, item."""
        records = parse_table(COMBINED_CSV, "by_age_2024")
        items = {record["item"] for record in records}
        columns = {record["column"] for record in records}
        assert items == {"Number of family farm households", "Total operators"}
        assert columns == {"Less than 35 years old", "All family farms"}

    def test_parse_table_combined_skips_rows_without_separator(self):
        """A combined row lacking ': ' or with an empty item is skipped."""
        records = parse_table(COMBINED_CSV, "by_age_2024")
        assert all(record["item"] for record in records)
        assert "NoSeparatorLabel" not in {record["item"] for record in records}
        assert len(records) == 4

    def test_parse_table_skips_blank_item(self):
        """A non-combined row with a blank item is skipped."""
        records = parse_table(BLANK_ITEM_CSV, "finances_2021_26f")
        assert len(records) == 1
        assert records[0]["item"] == "Real item"

    def test_afetch_table(self, monkeypatch):
        """afetch_table fetches the CSV through the ERS cache and parses it."""
        calls = []

        async def fake_afetch_ers_file(media_path, product=None, ttl=None):
            calls.append((media_path, product))
            return YEAR_CSV.encode("utf-8-sig")

        monkeypatch.setattr(
            "openbb_government_us.usda.utils.ers_client.afetch_ers_file",
            fake_afetch_ers_file,
        )
        records = asyncio.run(afetch_table("finances_2021_26f"))
        assert calls == [
            (TABLE_CONFIG["finances_2021_26f"]["media_path"], PRODUCT_PAGE)
        ]
        assert len(records) == 6


class TestFarmHouseholdIncomeAndCharacteristics:
    """Tests for the FarmHouseholdIncomeAndCharacteristics model."""

    def test_transform_query_default_table(self):
        """transform_query defaults the table and keeps year filters."""
        query = FarmHouseholdIncomeAndCharacteristicsFetcher.transform_query(
            {"start_year": 2000}
        )
        assert isinstance(query, FarmHouseholdIncomeAndCharacteristicsQueryParams)
        assert query.table == DEFAULT_TABLE
        assert query.start_year == 2000

    def test_table_blank_returns_default(self):
        """A blank or None table normalizes to the default table."""
        assert (
            FarmHouseholdIncomeAndCharacteristicsQueryParams(table=None).table
            == DEFAULT_TABLE
        )
        assert (
            FarmHouseholdIncomeAndCharacteristicsQueryParams(table="").table
            == DEFAULT_TABLE
        )

    def test_table_list_input_takes_first(self):
        """A list-valued table takes and strips its first element."""
        query = FarmHouseholdIncomeAndCharacteristicsQueryParams(
            table=["  by_sex_2024  "]
        )
        assert query.table == "by_sex_2024"

    def test_unknown_table_raises(self):
        """An unknown table raises OpenBBError listing valid choices."""
        with pytest.raises(OpenBBError, match="Invalid table: bogus"):
            FarmHouseholdIncomeAndCharacteristicsQueryParams(table="bogus")

    def test_non_string_table_raises(self):
        """A non-string, non-empty table value raises OpenBBError."""
        with pytest.raises(OpenBBError, match="Invalid table"):
            FarmHouseholdIncomeAndCharacteristicsQueryParams(table=123)

    def test_aextract_data_fetches_selected_table(self, monkeypatch):
        """aextract_data fetches only the selected table's rows."""
        fetched = []

        async def fake_afetch_table(table, **kwargs):
            fetched.append(table)
            return [{"item": "x", "column": "2024", "value": 1}]

        monkeypatch.setattr(util, "afetch_table", fake_afetch_table)
        query = FarmHouseholdIncomeAndCharacteristicsFetcher.transform_query(
            {"table": "farm_size_class"}
        )
        records = asyncio.run(
            FarmHouseholdIncomeAndCharacteristicsFetcher.aextract_data(query, None)
        )
        assert fetched == ["farm_size_class"]
        assert records == [{"item": "x", "column": "2024", "value": 1}]

    def test_transform_data_year_pivot_chronological(self):
        """Each item's years become columns, forecast years sorted last."""
        records = parse_table(YEAR_CSV, "finances_2021_26f")
        query = FarmHouseholdIncomeAndCharacteristicsFetcher.transform_query(
            {"table": "finances_2021_26f"}
        )
        data = FarmHouseholdIncomeAndCharacteristicsFetcher.transform_data(
            query, records
        )
        assert [row.item for row in data] == [
            "Number of family farms",
            "Off-farm income",
        ]
        first = data[0].model_dump(by_alias=True)
        assert list(first) == ["item", "2023", "2024", "2025F"]
        assert first["2023"] == 100
        assert first["2025F"] is None

    def test_transform_data_preserves_precision(self):
        """Dynamic value columns keep full source precision."""
        records = parse_table(YEAR_CSV, "finances_2021_26f")
        query = FarmHouseholdIncomeAndCharacteristicsFetcher.transform_query(
            {"table": "finances_2021_26f"}
        )
        data = FarmHouseholdIncomeAndCharacteristicsFetcher.transform_data(
            query, records
        )
        off_farm = next(row for row in data if row.item == "Off-farm income")
        assert off_farm.model_dump(by_alias=True)["2023"] == 50.5

    def test_transform_data_filters_years(self):
        """start_year and end_year filter the year columns."""
        records = parse_table(YEAR_CSV, "finances_2021_26f")
        query = FarmHouseholdIncomeAndCharacteristicsFetcher.transform_query(
            {"table": "finances_2021_26f", "start_year": 2024, "end_year": 2024}
        )
        data = FarmHouseholdIncomeAndCharacteristicsFetcher.transform_data(
            query, records
        )
        columns = [k for k in data[0].model_dump(by_alias=True) if k != "item"]
        assert columns == ["2024"]

    def test_transform_data_empty_after_filter_raises(self):
        """A year filter that removes every record raises EmptyDataError."""
        records = parse_table(YEAR_CSV, "finances_2021_26f")
        query = FarmHouseholdIncomeAndCharacteristicsFetcher.transform_query(
            {"table": "finances_2021_26f", "start_year": 3000}
        )
        with pytest.raises(EmptyDataError):
            FarmHouseholdIncomeAndCharacteristicsFetcher.transform_data(query, records)

    def test_transform_data_drops_all_none_column(self):
        """A value column that is null for every item is dropped."""
        query = FarmHouseholdIncomeAndCharacteristicsFetcher.transform_query(
            {"table": "finances_2021_26f"}
        )
        records = [
            {"item": "A", "column": "2023", "value": 1},
            {"item": "A", "column": "2024", "value": None},
            {"item": "B", "column": "2023", "value": 2},
            {"item": "B", "column": "2024", "value": None},
        ]
        data = FarmHouseholdIncomeAndCharacteristicsFetcher.transform_data(
            query, records
        )
        columns = [k for k in data[0].model_dump(by_alias=True) if k != "item"]
        assert columns == ["2023"]

    def test_transform_data_all_none_raises(self):
        """When every value is null the result is empty and raises."""
        query = FarmHouseholdIncomeAndCharacteristicsFetcher.transform_query(
            {"table": "finances_2021_26f"}
        )
        records = [{"item": "A", "column": "2024", "value": None}]
        with pytest.raises(EmptyDataError):
            FarmHouseholdIncomeAndCharacteristicsFetcher.transform_data(query, records)

    def test_transform_data_category_source_order(self):
        """A cross-tab table keeps categories in source order, aggregate last."""
        records = parse_table(CATEGORY_CSV, "by_farm_type_2024")
        query = FarmHouseholdIncomeAndCharacteristicsFetcher.transform_query(
            {"table": "by_farm_type_2024"}
        )
        data = FarmHouseholdIncomeAndCharacteristicsFetcher.transform_data(
            query, records
        )
        columns = [k for k in data[0].model_dump(by_alias=True) if k != "item"]
        assert columns == ["Residence Farms", "Commercial Farms", "All Farms"]
        assert data[0].model_dump(by_alias=True)["All Farms"] == 1100

    def test_transform_data_combined_ignores_year_filter(self):
        """A combined table pivots categories and ignores the year filters."""
        records = parse_table(COMBINED_CSV, "by_age_2024")
        query = FarmHouseholdIncomeAndCharacteristicsFetcher.transform_query(
            {"table": "by_age_2024", "start_year": 2100}
        )
        data = FarmHouseholdIncomeAndCharacteristicsFetcher.transform_data(
            query, records
        )
        columns = [k for k in data[0].model_dump(by_alias=True) if k != "item"]
        assert columns == ["Less than 35 years old", "All family farms"]
        assert [row.item for row in data] == [
            "Number of family farm households",
            "Total operators",
        ]

    def test_null_token_mixin_coerces_dynamic_columns(self):
        """A placeholder token in a dynamic column coerces to None, schema kept."""
        record = FarmHouseholdIncomeAndCharacteristicsData.model_validate(
            {"item": "X", "2020": "--", "2021": 5}
        )
        dumped = record.model_dump(by_alias=True)
        assert dumped["2020"] is None
        assert dumped["2021"] == 5

    def test_query_params_widget_options(self):
        """The table param exposes all 10 tables as a single-select filter."""
        config = FarmHouseholdIncomeAndCharacteristicsQueryParams.__json_schema_extra__[
            "table"
        ]["x-widget_config"]
        assert config["multiSelect"] is False
        assert config["multiple"] is False
        assert config["value"] == DEFAULT_TABLE
        assert len(config["options"]) == 10

    def test_widget_model_config(self):
        """The whole-widget config carries the name, category, and source."""
        config = FarmHouseholdIncomeAndCharacteristicsData.model_config[
            "json_schema_extra"
        ]["x-widget_config"]
        assert config["$.name"] == (
            "USDA ERS Farm Household Income and Characteristics"
        )
        assert config["$.category"] == "Economy"
        assert config["$.subCategory"] == "Agriculture"
        assert config["$.source"] == ["USDA", "ERS"]

    def test_columns_defs_bind_to_served_keys(self):
        """The only declared field binds to a served key; dynamics are extras."""
        records = parse_table(YEAR_CSV, "finances_2021_26f")
        query = FarmHouseholdIncomeAndCharacteristicsFetcher.transform_query(
            {"table": "finances_2021_26f"}
        )
        data = FarmHouseholdIncomeAndCharacteristicsFetcher.transform_data(
            query, records
        )
        served = set(data[0].model_dump(by_alias=True))
        fields = FarmHouseholdIncomeAndCharacteristicsData.model_fields
        for name, field in fields.items():
            extra = (field.json_schema_extra or {}).get("x-widget_config", {})
            if extra.get("exclude"):
                continue
            assert name in served
        dynamic = served - set(fields)
        assert "2023" in dynamic
        assert "item" in served
