"""Tests for the USDA ERS vegetables and pulses utils and model."""

import asyncio
import zipfile
from io import BytesIO

import pytest
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.utils.errors import EmptyDataError

from openbb_government_us.usda.models.vegetables_and_pulses import (
    VegetablesAndPulsesData,
    VegetablesAndPulsesFetcher,
    VegetablesAndPulsesQueryParams,
)
from openbb_government_us.usda.utils import ers_vegetables_and_pulses
from openbb_government_us.usda.utils.ers_vegetables_and_pulses import (
    CSV_MEMBERS,
    DATA_ZIP,
    DEFAULT_TABLE,
    PRODUCT_PAGE,
    TABLE_LABELS,
    parse_rows,
)

HEADER = (
    "Table,Decade,Year,Item,Commodity,EndUse,PublishValue,Unit,Category,"
    "GeographicalLevel,Location\n"
)

SAMPLE_CSV = HEADER + (
    "Table33_Potatoes,1970,1970,Production,Potatoes,Fresh,97.4,Million pounds,"
    "Supply,Country,United States\n"
    "Table33_Potatoes,1970,1970,Total supply,Potatoes,Fresh,100.5,"
    "Million pounds,Supply,Country,United States\n"
    "Table33_Potatoes,1970,1971,Production,Potatoes,Fresh,85.8,Million pounds,"
    "Supply,Country,United States\n"
    "Table33_Potatoes,1970,1971,Total supply,Potatoes,Fresh,90.2,"
    "Million pounds,Supply,Country,United States\n"
    "Table33_Potatoes,1970,1971,Per capita availability,Potatoes,Fresh,"
    "0.441931803,Pounds,Availability,Country,United States\n"
    "Table33_Potatoes,1970,1971,Current dollars,Potatoes,Fresh,29.2,"
    "U.S. dollars per hundredweight,Season average price,Country,United States\n"
    "Table33_Potatoes,1970,,Production,Potatoes,Fresh,12.0,Million pounds,"
    "Supply,Country,United States\n"
    "Table33_Potatoes,1970,abcd,Production,Potatoes,Fresh,13.0,Million pounds,"
    "Supply,Country,United States\n"
    "Table33_Potatoes,1970,1972,Production,Potatoes,Fresh,,Million pounds,"
    "Supply,Country,United States\n"
    "Table33_Potatoes,1970,1972,Production,Potatoes,Fresh,NA,Million pounds,"
    "Supply,Country,United States\n"
    "Table09_WorldVegProduction,2000,2005,Production,Artichokes,All uses,"
    "10.36117,Million hundredweight,Supply,Country,Italy\n"
    "Table09_WorldVegProduction,2000,2005,Production,Green peas ,All uses,"
    "4.41222,Million hundredweight,Supply,Country,Spain\n"
    "Table10_CashReceipts,2000,2000,Current dollars,"
    "Vegetables excluding mushrooms,All uses,6580599,Thousand dollars,"
    "Cash receipts,State,California  \n"
)

NONE_FIELDS_CSV = HEADER + (
    "Table33_Potatoes,1970,1973,Production,,,50.0,Million pounds,Supply,,\n"
)


class TestErsVegetablesAndPulsesUtils:
    """Tests for the ers_vegetables_and_pulses utils module."""

    def test_catalog_contents(self):
        """The catalog holds all 81 yearbook tables and the single source."""
        assert len(TABLE_LABELS) == 81
        assert DEFAULT_TABLE in TABLE_LABELS
        assert DATA_ZIP == "/media/5018/vegetables-and-pulses-machine-readable-data.zip"
        assert CSV_MEMBERS == ("vegetables-pulses-data.csv", "Vegetables_Pulses.csv")
        assert PRODUCT_PAGE.endswith("vegetables-and-pulses-yearbook-tables")
        assert all(label for label in TABLE_LABELS.values())

    def test_parse_rows_filters_to_table(self):
        """Only rows matching the requested table are parsed."""
        records = parse_rows(SAMPLE_CSV, "Table33_Potatoes")
        assert {record["table"] for record in records} == {"Table33_Potatoes"}
        assert {record["item"] for record in records} == {
            "Production",
            "Total supply",
            "Per capita availability",
            "Current dollars",
        }

    def test_parse_rows_first_record_full_precision(self):
        """The first parsed record carries every field at full precision."""
        records = parse_rows(SAMPLE_CSV, "Table33_Potatoes")
        assert records[0] == {
            "table": "Table33_Potatoes",
            "year": 1970,
            "commodity": "Potatoes",
            "end_use": "Fresh",
            "location": "United States",
            "geographical_level": "Country",
            "item": "Production",
            "unit": "Million pounds",
            "category": "Supply",
            "value": 97.4,
        }
        per_capita = next(r for r in records if r["item"] == "Per capita availability")
        assert per_capita["value"] == 0.441931803

    def test_parse_rows_skips_blank_and_nonnumeric_value(self):
        """Rows with a blank or non-numeric PublishValue are dropped."""
        records = parse_rows(SAMPLE_CSV, "Table33_Potatoes")
        assert 1972 not in {record["year"] for record in records}

    def test_parse_rows_skips_blank_and_nonnumeric_year(self):
        """Rows with a blank or non-numeric Year label are dropped."""
        records = parse_rows(SAMPLE_CSV, "Table33_Potatoes")
        assert {record["year"] for record in records} == {1970, 1971}
        assert 12.0 not in {record["value"] for record in records}
        assert 13.0 not in {record["value"] for record in records}

    def test_parse_rows_strips_location_and_commodity_whitespace(self):
        """Trailing whitespace on Location and Commodity is stripped."""
        cash = parse_rows(SAMPLE_CSV, "Table10_CashReceipts")
        assert cash[0]["location"] == "California"
        assert cash[0]["geographical_level"] == "State"
        world = parse_rows(SAMPLE_CSV, "Table09_WorldVegProduction")
        assert {record["commodity"] for record in world} == {
            "Artichokes",
            "Green peas",
        }

    def test_parse_rows_empty_dimensions_become_none(self):
        """Empty dimension cells become None while the value is kept."""
        records = parse_rows(NONE_FIELDS_CSV, "Table33_Potatoes")
        assert len(records) == 1
        assert records[0]["commodity"] is None
        assert records[0]["end_use"] is None
        assert records[0]["location"] is None
        assert records[0]["geographical_level"] is None
        assert records[0]["value"] == 50.0

    @pytest.mark.parametrize(
        "member", ["vegetables-pulses-data.csv", "Vegetables_Pulses.csv"]
    )
    def test_afetch_table(self, monkeypatch, member):
        """afetch_table reads the renamed member, or the old one."""
        calls = []
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(member, SAMPLE_CSV)
            archive.writestr("readme.txt", "notes")
        content = buffer.getvalue()

        async def fake_afetch_ers_file(media_path, product=None, ttl=None):
            calls.append((media_path, product))
            return content

        monkeypatch.setattr(
            "openbb_government_us.usda.utils.ers_client.afetch_ers_file",
            fake_afetch_ers_file,
        )
        records = asyncio.run(
            ers_vegetables_and_pulses.afetch_table("Table33_Potatoes")
        )
        assert calls == [(DATA_ZIP, PRODUCT_PAGE)]
        assert {record["item"] for record in records} == {
            "Production",
            "Total supply",
            "Per capita availability",
            "Current dollars",
        }


class TestVegetablesAndPulses:
    """Tests for the VegetablesAndPulses model."""

    def test_transform_query_default_table(self):
        """transform_query defaults the table and keeps year filters."""
        query = VegetablesAndPulsesFetcher.transform_query({"start_year": 2000})
        assert isinstance(query, VegetablesAndPulsesQueryParams)
        assert query.table == DEFAULT_TABLE
        assert query.start_year == 2000

    def test_table_blank_returns_default(self):
        """A blank or None table normalizes to the default table."""
        assert VegetablesAndPulsesQueryParams(table=None).table == DEFAULT_TABLE
        assert VegetablesAndPulsesQueryParams(table="").table == DEFAULT_TABLE

    def test_table_strips_whitespace(self):
        """A padded table value is stripped before validation."""
        query = VegetablesAndPulsesQueryParams(table="  Table13_Asparagus  ")
        assert query.table == "Table13_Asparagus"

    def test_table_accepts_list_value(self):
        """A list-wrapped table value uses its first element."""
        query = VegetablesAndPulsesQueryParams(table=["Table09_WorldVegProduction"])
        assert query.table == "Table09_WorldVegProduction"

    def test_unknown_table_raises(self):
        """An unknown table raises OpenBBError listing valid choices."""
        with pytest.raises(OpenBBError, match="Invalid table: bogus"):
            VegetablesAndPulsesQueryParams(table="bogus")

    def test_aextract_data_fetches_selected_table(self, monkeypatch):
        """aextract_data fetches only the selected table's rows."""
        fetched = []

        async def fake_afetch_table(table, **kwargs):
            fetched.append(table)
            return [{"table": table}]

        monkeypatch.setattr(
            ers_vegetables_and_pulses, "afetch_table", fake_afetch_table
        )
        query = VegetablesAndPulsesFetcher.transform_query(
            {"table": "Table09_WorldVegProduction"}
        )
        records = asyncio.run(VegetablesAndPulsesFetcher.aextract_data(query, None))
        assert fetched == ["Table09_WorldVegProduction"]
        assert records == [{"table": "Table09_WorldVegProduction"}]

    def test_transform_data_pivots_item_into_columns(self):
        """Each item becomes its own column, one row per year."""
        records = parse_rows(SAMPLE_CSV, "Table33_Potatoes")
        query = VegetablesAndPulsesFetcher.transform_query({})
        data = VegetablesAndPulsesFetcher.transform_data(query, records)
        dumped = [row.model_dump() for row in data]
        row_1971 = next(row for row in dumped if row["year"] == 1971)
        assert row_1971["Production"] == 85.8
        assert row_1971["Total supply"] == 90.2
        assert row_1971["Per capita availability"] == 0.441931803
        assert row_1971["Current dollars"] == 29.2
        assert row_1971["commodity"] == "Potatoes"
        assert row_1971["location"] == "United States"

    def test_transform_data_sparse_item_absent(self):
        """An item absent in a year is omitted from that year's row."""
        records = parse_rows(SAMPLE_CSV, "Table33_Potatoes")
        query = VegetablesAndPulsesFetcher.transform_query({})
        data = VegetablesAndPulsesFetcher.transform_data(query, records)
        row_1970 = next(row for row in data if row.year == 1970)
        assert "Current dollars" not in row_1970.model_dump()

    def test_transform_data_year_rows_chronological(self):
        """Rows for one series are emitted in ascending year order."""
        records = parse_rows(SAMPLE_CSV, "Table33_Potatoes")
        query = VegetablesAndPulsesFetcher.transform_query({})
        data = VegetablesAndPulsesFetcher.transform_data(query, records)
        assert [row.year for row in data] == [1970, 1971]

    def test_transform_data_multi_location_groups(self):
        """The world table yields one row per commodity and location."""
        records = parse_rows(SAMPLE_CSV, "Table09_WorldVegProduction")
        query = VegetablesAndPulsesFetcher.transform_query({})
        data = VegetablesAndPulsesFetcher.transform_data(query, records)
        assert len(data) == 2
        by_location = {row.location: row.model_dump() for row in data}
        assert by_location["Italy"]["Production"] == 10.36117
        assert by_location["Spain"]["Production"] == 4.41222
        assert by_location["Italy"]["commodity"] == "Artichokes"

    def test_transform_data_filters_years(self):
        """start_year and end_year filter rows on the integer year."""
        records = parse_rows(SAMPLE_CSV, "Table33_Potatoes")
        start = VegetablesAndPulsesFetcher.transform_data(
            VegetablesAndPulsesFetcher.transform_query({"start_year": 1971}), records
        )
        assert {row.year for row in start} == {1971}
        end = VegetablesAndPulsesFetcher.transform_data(
            VegetablesAndPulsesFetcher.transform_query({"end_year": 1970}), records
        )
        assert {row.year for row in end} == {1970}

    def test_transform_data_empty_raises(self):
        """A filter matching no rows raises EmptyDataError."""
        records = parse_rows(SAMPLE_CSV, "Table33_Potatoes")
        query = VegetablesAndPulsesFetcher.transform_query({"start_year": 3000})
        with pytest.raises(EmptyDataError):
            VegetablesAndPulsesFetcher.transform_data(query, records)

    def test_transform_data_excludes_sort_keys(self):
        """Internal sort keys never leak into the validated records."""
        records = parse_rows(SAMPLE_CSV, "Table09_WorldVegProduction")
        query = VegetablesAndPulsesFetcher.transform_query({})
        data = VegetablesAndPulsesFetcher.transform_data(query, records)
        dumped = data[0].model_dump()
        assert not any(key.startswith("_") for key in dumped)

    def test_data_model_keeps_dynamic_columns_and_precision(self):
        """The Data model preserves dynamic columns at full precision."""
        row = VegetablesAndPulsesData.model_validate(
            {
                "table": "Table33_Potatoes",
                "year": 1971,
                "commodity": "Potatoes",
                "location": "United States",
                "Per capita availability": 0.441931803,
            }
        )
        assert row.model_dump()["Per capita availability"] == 0.441931803

    def test_data_model_widget_config(self):
        """The model carries the whole-widget and per-field widget configs."""
        widget = VegetablesAndPulsesData.model_config["json_schema_extra"][
            "x-widget_config"
        ]
        assert widget["$.category"] == "Economy"
        assert widget["$.subCategory"] == "Agriculture"
        assert widget["$.source"] == ["USDA", "ERS"]
        fields = VegetablesAndPulsesData.model_fields
        assert "table" not in fields
        assert fields["end_use"].json_schema_extra["x-widget_config"]["hide"] is True
        assert fields["year"].json_schema_extra["x-widget_config"]["pinned"] == "left"
