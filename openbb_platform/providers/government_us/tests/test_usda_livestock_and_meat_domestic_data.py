"""Tests for the USDA ERS livestock and meat domestic data utils and model."""

import asyncio
import zipfile
from io import BytesIO

import pytest
from openbb_core.app.model.abstract.error import OpenBBError

from openbb_government_us.usda.models.livestock_and_meat_domestic_data import (
    DEFAULT_TABLE,
    LivestockAndMeatDomesticData,
    LivestockAndMeatDomesticDataFetcher,
    LivestockAndMeatDomesticDataQueryParams,
)
from openbb_government_us.usda.utils import ers_livestock_and_meat_domestic_data
from openbb_government_us.usda.utils.ers_livestock_and_meat_domestic_data import (
    LIVESTOCK_AND_MEAT_FILES,
    PRODUCT_PAGE,
    ZIP_DIR,
    ZIP_MEDIA,
    _amount,
    column_label,
    parse_table,
)

PRODUCTION_CSV = (
    "commodity_desc,attribute_desc,table_name,unit_desc,year_id,"
    "timeperiod_id,timeperiod_desc,amount\n"
    "Beef,Federally inspected production,Red meat and poultry production,"
    "million pounds,2025,5,May-2025,2092.2\n"
    "Beef,Commercial production,Red meat and poultry production,"
    "million pounds,2025,5,May-2025,2122.9\n"
    "Beef,Federally inspected production,Red meat and poultry production,"
    "million pounds,2025,4,Apr-2025,2000.0\n"
    "Beef,Federally inspected production,Red meat and poultry production,"
    "million pounds,2025,101,Jan-May-2025,9000.0\n"
    "Beef,Federally inspected production,Red meat and poultry production,"
    "million pounds,2025,17,Annual,111.0\n"
    "Broilers,Federally inspected production,Red meat and poultry production,"
    "million pounds,2025,5,May-2025,3991.252\n"
    "Cattle,Federally inspected slaughter,Livestock and poultry slaughter,"
    "thousand head,2025,5,May-2025,2717.2\n"
    "Beef,Federally inspected production,Red meat and poultry production,"
    "million pounds,,5,May-,50.0\n"
    "Beef,Commercial production,Red meat and poultry production,"
    "million pounds,2025,5,May-2025,NA\n"
)

MEATSD_CSV = (
    "commodity_desc,attribute_desc,unit_desc,year_id,"
    "timeperiod_id,timeperiod_desc,amount\n"
    "Beef,Total Production,Million pounds,2024,17,Yr Jan-Dec,27049.5\n"
    'Beef,Disappearance Per Capita,"Retail weight, pounds",2024,17,Yr Jan-Dec,59.0988\n'
    'Beef,Disappearance Per Capita,"Carcass-weight-equivalent, pounds",'
    "2024,17,Yr Jan-Dec,84.4269\n"
    "Beef,Total Production,Million pounds,2025,17,Yr Jan-Dec,26071.0\n"
    "Eggs and egg products,Total Production,Million Dozens,2024,17,Yr Jan-Dec,9300.0\n"
)

LIVESTOCK_PRICES_CSV = (
    "commodity_desc,geography_desc,attribute_desc,unit_desc,"
    "year_id,month_id,month_desc,amount\n"
    "Cattle,National,Steers 35-65 percent Choice,Dollars per hundredweight,"
    "2025,1,January,200.39\n"
    "Cattle,National,Steers 35-65 percent Choice,Dollars per hundredweight,"
    "2025,2,February,202.83\n"
    'Hay,National,"Alfalfa hay, U.S. average",Dollars per ton,2025,1,January,150.0\n'
)

FEEDER_CSV = (
    "attribute_desc,unit_desc,year_id,amount\n"
    'On feed Jan 1: Total,"1,000 head",2025,"14,657.7"\n'
    "On feed Jan 1: Total,Percent change from previous year,2025,-1.5\n"
)

HEIFERS_CSV = (
    "commodity_desc,table_name,attribute_desc,unit_desc,year_id,amount\n"
    "Cattle,Total heifers entering cow herd,Percent entering Jan-June,Percent,"
    "2017,38.26\n"
    'Cattle,January 1 cattle inventory,Cattle and calves,"1,000 head",'
    "2017,93600.0\n"
)

SHARED_SERIES_CSV = (
    "commodity_desc,attribute_desc,unit_desc,year_id,"
    "timeperiod_id,timeperiod_desc,amount\n"
    "Beef,Total Production,Million pounds,2024,17,Yr Jan-Dec,27049.5\n"
    "Beef,Total Supply,Million pounds,2024,17,Yr Jan-Dec,30000.0\n"
    "Beef,Imports,Million pounds,2024,17,Yr Jan-Dec,4000.0\n"
    "Beef,Exports,Million pounds,2024,17,Yr Jan-Dec,3000.0\n"
    "Pork,Total Production,Million pounds,2024,17,Yr Jan-Dec,27700.0\n"
    "Pork,Total Supply,Million pounds,2024,17,Yr Jan-Dec,29000.0\n"
    "Pork,Imports,Million pounds,2024,17,Yr Jan-Dec,1200.0\n"
    "Pork,Exports,Million pounds,2024,17,Yr Jan-Dec,7000.0\n"
)

HIGH_PLAINS_CSV = (
    "commodity_desc,geography_desc,attribute_desc,unit_desc,"
    "timeperiod_desc,year_id,month_id,amount\n"
    "Cattle,High Plains,Marketing,dollars per head,Feb-25 to Jun-25,2025,2,f.o.b.\n"
    "Cattle,High Plains,Expenses: Total expenses,dollars per head,"
    "Feb-25 to Jun-25,2025,2,2501.3\n"
    "Cattle,OK City,Prices: Choice feeder steer 750-800 pounds,"
    "dollars per hundredweight,Feb-25 to Jun-25,2025,2,280.0\n"
)


class TestErsLivestockAndMeatDomesticDataUtils:
    """Tests for the ers_livestock_and_meat_domestic_data utils module."""

    def test_catalog_contents(self):
        """The catalog holds the ten tables mapped to the seven zip members."""
        assert len(LIVESTOCK_AND_MEAT_FILES) == 10
        assert DEFAULT_TABLE in LIVESTOCK_AND_MEAT_FILES
        members = {config["member"] for config in LIVESTOCK_AND_MEAT_FILES.values()}
        assert len(members) == 7
        meatstats = [
            key
            for key, config in LIVESTOCK_AND_MEAT_FILES.items()
            if config["member"] == ("Meat-Statistics.csv", "MeatStats.csv")
        ]
        assert len(meatstats) == 4
        for config in LIVESTOCK_AND_MEAT_FILES.values():
            assert config["label"]
            assert config["col_dims"]

    def test_amount_parses_number_text_and_null(self):
        """Amounts parse to floats, keep text, and coerce null tokens to None."""
        assert _amount("14,657.7") == 14657.7
        assert _amount("2501.3") == 2501.3
        assert _amount("f.o.b.") == "f.o.b."
        assert _amount("NA") is None
        assert _amount("") is None
        assert _amount(None) is None

    def test_column_label_folds_unit_when_mixed(self):
        """A mixed-unit table folds the unit into the column label."""
        row = {
            "commodity_desc": "Broilers",
            "geography_desc": "National",
            "attribute_desc": "Breast, boneless",
            "unit_desc": "Cents per pound",
        }
        config = LIVESTOCK_AND_MEAT_FILES["wholesale_prices"]
        assert (
            column_label(config, row)
            == "Broilers National Breast, boneless (Cents per pound)"
        )

    def test_column_label_omits_unit_when_single(self):
        """A single-unit table omits the unit from the column label."""
        row = {"attribute_desc": "Commercial production", "unit_desc": "million pounds"}
        config = LIVESTOCK_AND_MEAT_FILES["production"]
        assert column_label(config, row) == "Commercial production"

    def test_parse_production_filters_table_name_and_bad_rows(self):
        """The MeatStats production table filters other tables, blanks, and NA."""
        records = parse_table(PRODUCTION_CSV, "production")
        assert len(records) == 6
        assert all(record["table"] == "production" for record in records)
        assert all(record["commodity"] in ("Beef", "Broilers") for record in records)
        assert all(record["unit"] == "million pounds" for record in records)
        assert all(record["table_name"] is None for record in records)

    def test_parse_production_strips_month_year_period(self):
        """The month-year period keeps the month, and a plain label passes through."""
        records = parse_table(PRODUCTION_CSV, "production")
        may = next(r for r in records if r["period_sort"] == 5)
        assert may["period"] == "May"
        ytd = next(r for r in records if r["period_sort"] == 101)
        assert ytd["period"] == "Jan-May"
        annual = next(r for r in records if r["period_sort"] == 17)
        assert annual["period"] == "Annual"

    def test_parse_production_column_and_amount(self):
        """The production column omits the unit and keeps the raw amount."""
        records = parse_table(PRODUCTION_CSV, "production")
        fed = next(
            r
            for r in records
            if r["commodity"] == "Beef"
            and r["period"] == "May"
            and r["column"] == "Federally inspected production"
        )
        assert fed["amount"] == 2092.2

    def test_parse_meatsd_folds_unit_into_columns(self):
        """The MeatSD table folds units and disambiguates per-capita columns."""
        records = parse_table(MEATSD_CSV, "supply_and_disappearance")
        columns = {r["column"] for r in records}
        assert "Total Production (Million pounds)" in columns
        assert "Total Production (Million Dozens)" in columns
        assert "Disappearance Per Capita (Retail weight, pounds)" in columns
        assert "Disappearance Per Capita (Carcass-weight-equivalent, pounds)" in columns
        assert all(r["unit"] is None for r in records)
        assert all(r["period"] == "Yr Jan-Dec" for r in records)

    def test_parse_livestock_prices_month_period_no_fold_dims(self):
        """Livestock prices use the month period and carry no folding dims."""
        records = parse_table(LIVESTOCK_PRICES_CSV, "livestock_prices")
        assert len(records) == 3
        assert {r["period"] for r in records} == {"January", "February"}
        assert all(r["commodity"] is None for r in records)
        assert any(
            r["column"] == "Alfalfa hay, U.S. average (Dollars per ton)"
            for r in records
        )

    def test_parse_feeder_has_no_period_and_parses_comma(self):
        """Feeder cattle rows carry no period and parse comma thousands."""
        records = parse_table(FEEDER_CSV, "feeder_cattle_outside_feedlots")
        assert all(r["period"] is None for r in records)
        assert all(r["period_sort"] == 0 for r in records)
        level = next(r for r in records if r["column"].endswith("(1,000 head)"))
        assert level["amount"] == 14657.7

    def test_parse_heifers_uses_table_name_fold_dim(self):
        """Heifers rows carry the sub-table as a folding dimension."""
        records = parse_table(HEIFERS_CSV, "heifers_entering_the_herd")
        assert {r["table_name"] for r in records} == {
            "Total heifers entering cow herd",
            "January 1 cattle inventory",
        }
        assert all(r["commodity"] is None for r in records)

    def test_parse_high_plains_keeps_textual_value(self):
        """A textual amount such as 'f.o.b.' is preserved, not dropped."""
        records = parse_table(HIGH_PLAINS_CSV, "high_plains_cattle_feeding_simulator")
        marketing = next(r for r in records if "Marketing" in r["column"])
        assert marketing["amount"] == "f.o.b."
        assert marketing["period"] == "Feb-25 to Jun-25"
        assert marketing["period_sort"] == 2
        assert any(r["column"].startswith("OK City ") for r in records)

    @pytest.mark.parametrize("member", ["Meat-Supply-Disappearance.csv", "MeatSD.csv"])
    def test_afetch_table(self, monkeypatch, member):
        """afetch_table reads the renamed member, or the old one."""
        calls = []
        buffer = BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr(f"{ZIP_DIR}/{member}", MEATSD_CSV)
            archive.writestr(f"{ZIP_DIR}/_Read_Me.txt", "readme")
        content = buffer.getvalue()

        async def fake_afetch_ers_file(media_path, product=None, ttl=None):
            calls.append((media_path, product))
            return content

        monkeypatch.setattr(
            "openbb_government_us.usda.utils.ers_client.afetch_ers_file",
            fake_afetch_ers_file,
        )
        records = asyncio.run(
            ers_livestock_and_meat_domestic_data.afetch_table(
                "supply_and_disappearance"
            )
        )
        assert calls == [(ZIP_MEDIA, PRODUCT_PAGE)]
        assert any(r["column"] == "Total Production (Million pounds)" for r in records)


class TestLivestockAndMeatDomesticData:
    """Tests for the LivestockAndMeatDomesticData model."""

    def test_classify_dims_keeps_an_unpopulated_dim_out_of_the_columns(self):
        """A dim no record populates cannot partition the series, so it labels rows."""
        rows = [
            {
                "commodity": None,
                "table_name": "Red meat production",
                "geography": None,
                "column": "Beef",
            },
            {
                "commodity": "",
                "table_name": "Red meat production",
                "geography": None,
                "column": "Pork",
            },
        ]
        assert LivestockAndMeatDomesticDataFetcher._classify_dims(
            rows, ["commodity"]
        ) == ([], ["commodity"])

    def test_transform_query_default_table(self):
        """transform_query defaults the table and keeps year filters."""
        query = LivestockAndMeatDomesticDataFetcher.transform_query(
            {"start_year": 2000}
        )
        assert isinstance(query, LivestockAndMeatDomesticDataQueryParams)
        assert query.table == DEFAULT_TABLE
        assert query.start_year == 2000

    def test_table_blank_returns_default(self):
        """A blank or None table normalizes to the default table."""
        assert (
            LivestockAndMeatDomesticDataQueryParams(table=None).table == DEFAULT_TABLE
        )
        assert LivestockAndMeatDomesticDataQueryParams(table="").table == DEFAULT_TABLE

    def test_table_strips_whitespace(self):
        """A padded table value is stripped before validation."""
        query = LivestockAndMeatDomesticDataQueryParams(table="  livestock_prices  ")
        assert query.table == "livestock_prices"

    def test_unknown_table_raises(self):
        """An unknown table raises OpenBBError listing valid choices."""
        with pytest.raises(OpenBBError, match="Invalid table: bogus"):
            LivestockAndMeatDomesticDataQueryParams(table="bogus")

    def test_non_string_table_raises(self):
        """A non-string, non-empty table value raises OpenBBError."""
        with pytest.raises(OpenBBError, match="Invalid table"):
            LivestockAndMeatDomesticDataQueryParams(table=123)

    def test_aextract_data_fetches_selected_table(self, monkeypatch):
        """aextract_data fetches only the selected table's rows."""
        fetched = []

        async def fake_afetch_table(table, **kwargs):
            fetched.append(table)
            return [{"table": table}]

        monkeypatch.setattr(
            ers_livestock_and_meat_domestic_data, "afetch_table", fake_afetch_table
        )
        query = LivestockAndMeatDomesticDataFetcher.transform_query(
            {"table": "livestock_prices"}
        )
        records = asyncio.run(
            LivestockAndMeatDomesticDataFetcher.aextract_data(query, None)
        )
        assert fetched == ["livestock_prices"]
        assert records == [{"table": "livestock_prices"}]

    def _dump(self, table, records, **params):
        """Run transform_data and return the by-alias dumps."""
        query = LivestockAndMeatDomesticDataFetcher.transform_query(
            {"table": table, **params}
        )
        data = LivestockAndMeatDomesticDataFetcher.transform_data(query, records)
        return [row.model_dump(by_alias=True) for row in data]

    def test_transform_spreads_commodity_into_columns(self):
        """A commodity that splits the series moves into the column header."""
        records = parse_table(PRODUCTION_CSV, "production")
        dumped = self._dump("production", records)
        may = next(row for row in dumped if row["period"] == "2025 May")
        assert may["Beef — Federally inspected production (million pounds)"] == 2092.2
        assert may["Beef — Commercial production (million pounds)"] == 2122.9
        assert (
            may["Broilers — Federally inspected production (million pounds)"]
            == 3991.252
        )
        assert "Broilers — Commercial production (million pounds)" not in may

    def test_transform_groups_columns_by_commodity(self):
        """Column headers group by commodity, then by first-seen series."""
        records = parse_table(PRODUCTION_CSV, "production")
        dumped = self._dump("production", records)
        assert list(dumped[0]) == [
            "period",
            "Beef — Federally inspected production (million pounds)",
            "Beef — Commercial production (million pounds)",
            "Broilers — Federally inspected production (million pounds)",
        ]

    def test_transform_keeps_commodity_in_rows_when_series_are_shared(self):
        """A commodity reporting every series stays folded into the period label."""
        records = parse_table(SHARED_SERIES_CSV, "supply_and_disappearance")
        dumped = self._dump("supply_and_disappearance", records)
        assert [row["period"] for row in dumped] == ["Beef — 2024", "Pork — 2024"]
        assert dumped[0]["Total Production (Million pounds)"] == 27049.5
        assert dumped[1]["Total Production (Million pounds)"] == 27700.0

    def test_transform_sorts_rows_newest_first(self):
        """Rows sort newest first, by year then within-year period order."""
        records = parse_table(PRODUCTION_CSV, "production")
        dumped = self._dump("production", records)
        assert [row["period"] for row in dumped] == [
            "2025 Jan-May",
            "2025 Annual",
            "2025 May",
            "2025 Apr",
        ]

    def test_transform_sorts_untimed_periods_newest_first(self):
        """A table without a within-year period reverses the source order."""
        records = [
            {
                "table": "high_plains_cattle_feeding_simulator",
                "commodity": None,
                "table_name": None,
                "geography": None,
                "unit": None,
                "year": 2025,
                "period": period,
                "period_sort": 0,
                "column": "Marketing (dollars per head)",
                "amount": value,
            }
            for period, value in (
                ("Feb-25 to Jun-25", 1.0),
                ("Mar-25 to Jul-25", 2.0),
                ("Apr-25 to Aug-25", 3.0),
            )
        ]
        dumped = self._dump("high_plains_cattle_feeding_simulator", records)
        assert [row["period"] for row in dumped] == [
            "Apr-25 to Aug-25",
            "Mar-25 to Jul-25",
            "Feb-25 to Jun-25",
        ]

    def test_transform_filters_years(self):
        """start_year and end_year filter rows on the observation year."""
        records = parse_table(MEATSD_CSV, "supply_and_disappearance")
        start = self._dump("supply_and_disappearance", records, start_year=2025)
        assert [row["period"] for row in start] == ["2025"]
        end = self._dump("supply_and_disappearance", records, end_year=2024)
        assert [row["period"] for row in end] == ["2024"]
        assert self._dump("supply_and_disappearance", records, start_year=2100) == []

    def test_transform_multi_unit_columns(self):
        """A multi-unit table folds each series' unit into its column header."""
        records = parse_table(MEATSD_CSV, "supply_and_disappearance")
        dumped = self._dump("supply_and_disappearance", records)
        row = next(row for row in dumped if row["period"] == "2024")
        assert row["Beef — Total Production (Million pounds)"] == 27049.5
        assert row["Beef — Disappearance Per Capita (Retail weight, pounds)"] == 59.0988
        assert (
            row["Eggs and egg products — Total Production (Million Dozens)"] == 9300.0
        )
        assert "Eggs and egg products — Total Production (Million pounds)" not in row

    def test_transform_keeps_textual_cells(self):
        """A textual pivot cell survives model validation as a string."""
        records = parse_table(HIGH_PLAINS_CSV, "high_plains_cattle_feeding_simulator")
        dumped = self._dump("high_plains_cattle_feeding_simulator", records)
        assert dumped[0]["period"] == "Feb-25 to Jun-25"
        marketing = next(k for k in dumped[0] if "Marketing" in k)
        assert dumped[0][marketing] == "f.o.b."

    def test_transform_spreads_table_name_into_columns(self):
        """The heifers sub-table prefixes the column headers, not the period."""
        records = parse_table(HEIFERS_CSV, "heifers_entering_the_herd")
        dumped = self._dump("heifers_entering_the_herd", records)
        assert [row["period"] for row in dumped] == ["2017"]
        assert (
            dumped[0][
                "Total heifers entering cow herd — Percent entering Jan-June (Percent)"
            ]
            == 38.26
        )
        assert (
            dumped[0]["January 1 cattle inventory — Cattle and calves (1,000 head)"]
            == 93600.0
        )

    def test_transform_excludes_sort_keys(self):
        """Internal sort keys never leak into the validated records."""
        records = parse_table(PRODUCTION_CSV, "production")
        dumped = self._dump("production", records)
        for hidden in ("_combo", "_order", "_year", "_period_sort"):
            assert hidden not in dumped[0]

    def test_data_model_only_period_is_static(self):
        """The only static served field is the pinned period label."""
        assert set(LivestockAndMeatDomesticData.model_fields) == {"period"}

    def test_data_model_keeps_dynamic_columns_and_precision(self):
        """The Data model preserves dynamic columns at full precision."""
        row = LivestockAndMeatDomesticData.model_validate(
            {
                "period": "Beef — 2024",
                "Disappearance Per Capita (Carcass-weight-equivalent, pounds)": 84.4269,
            }
        )
        assert (
            row.model_dump()[
                "Disappearance Per Capita (Carcass-weight-equivalent, pounds)"
            ]
            == 84.4269
        )
