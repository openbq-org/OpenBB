"""Tests for openbb_famafrench.utils.helpers."""

import asyncio
import io
import zipfile

import pytest

from openbb_famafrench.utils import helpers


def _make_zip(filename: str, content: bytes) -> bytes:
    """Build an in-memory zip archive holding a single file."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(filename, content)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# get_factor_choices  (async, pure - no network)
# ---------------------------------------------------------------------------


def test_get_factor_choices_region_only():
    """Region supplied, no factor: returns the factor list for that region."""
    result = asyncio.run(helpers.get_factor_choices(region="america"))

    assert isinstance(result, list)
    assert result
    values = {d["value"] for d in result}
    assert "3_Factors" in values
    # Title-casing keeps ST/LT upper-cased.
    labels = {d["label"] for d in result}
    assert any("ST" in label for label in labels)
    assert any("LT" in label for label in labels)


def test_get_factor_choices_region_and_factor():
    """Region + factor: returns interval choices for that factor."""
    result = asyncio.run(
        helpers.get_factor_choices(region="america", factor="3_Factors")
    )

    assert isinstance(result, list)
    assert {d["value"] for d in result} >= {"daily", "monthly"}


def test_get_factor_choices_no_args():
    """No arguments: returns all regions."""
    result = asyncio.run(helpers.get_factor_choices())

    assert isinstance(result, list)
    values = {d["value"] for d in result}
    assert "america" in values
    assert "europe" in values


def test_get_factor_choices_portfolio_america():
    """is_portfolio + america region: returns US portfolio choices."""
    result = asyncio.run(
        helpers.get_factor_choices(region="america", is_portfolio=True)
    )

    assert isinstance(result, list)
    assert result
    # America portfolios must not start with a regional prefix.
    assert all(not d["value"].startswith("Europe") for d in result)
    # The "ex_" filter removes ex-US datasets from a non-"ex_" region.
    assert all("ex_" not in d["value"] for d in result)
    # daily datasets are excluded.
    assert all("daily" not in d["value"].lower() for d in result)


def test_get_factor_choices_portfolio_europe():
    """is_portfolio + non-america region: regional prefix stripped from labels."""
    result = asyncio.run(helpers.get_factor_choices(region="europe", is_portfolio=True))

    assert isinstance(result, list)
    assert result
    assert all(d["value"].startswith("Europe") for d in result)
    # Label has the mapped region stripped out.
    assert all("Europe" not in d["label"] for d in result)


def test_get_factor_choices_portfolio_developed_ex_us():
    """is_portfolio + an 'ex_' region keeps the ex_ datasets."""
    result = asyncio.run(
        helpers.get_factor_choices(region="developed_ex_us", is_portfolio=True)
    )

    assert isinstance(result, list)
    assert result
    assert all(d["value"].startswith("Developed_ex_US") for d in result)


def test_get_factor_choices_portfolio_with_portfolio_monthly():
    """is_portfolio + region + portfolio: returns frequency choices."""
    result = asyncio.run(
        helpers.get_factor_choices(
            region="europe",
            is_portfolio=True,
            portfolio="6_Portfolios_ME_BE-ME",
        )
    )

    assert isinstance(result, list)
    values = {d["value"] for d in result}
    assert "monthly" in values
    assert "annual" in values


def test_get_factor_choices_portfolio_with_portfolio_daily():
    """A portfolio substring that also matches daily datasets adds 'daily'."""
    result = asyncio.run(
        helpers.get_factor_choices(
            region="america",
            is_portfolio=True,
            portfolio="Portfolios_Formed_on_ME",
        )
    )

    values = {d["value"] for d in result}
    assert "daily" in values
    assert "monthly" in values


def test_get_factor_choices_portfolio_no_args():
    """is_portfolio with no region/portfolio falls through to the default."""
    result = asyncio.run(helpers.get_factor_choices(is_portfolio=True))

    assert result == [
        {"label": "No choices found. Try a new parameter.", "value": None}
    ]


# ---------------------------------------------------------------------------
# apply_date  (pure - no network)
# ---------------------------------------------------------------------------


def test_apply_date_len_six():
    """A 6-digit YYYYMM string becomes a month-start date string."""
    assert helpers.apply_date("202001") == "2020-01-01"


def test_apply_date_len_eight():
    """An 8-digit YYYYMMDD string becomes a dashed date string."""
    assert helpers.apply_date("20200115") == "2020-01-15"


def test_apply_date_len_four():
    """A 4-digit year becomes a year-end date string."""
    assert helpers.apply_date("2020") == "2020-12-31"


# ---------------------------------------------------------------------------
# download_file  (validation - no network)
# ---------------------------------------------------------------------------


def test_download_file_invalid_dataset():
    """An unknown dataset raises ValueError before any request."""
    with pytest.raises(ValueError, match="not found in available datasets"):
        helpers.download_file("not_a_real_dataset")


# ---------------------------------------------------------------------------
# get_international_portfolio_data  (validation - no network)
# ---------------------------------------------------------------------------


def test_get_international_portfolio_data_no_index_no_country():
    """Neither index nor country raises ValueError."""
    with pytest.raises(ValueError, match="either an index or a country"):
        helpers.get_international_portfolio_data()


def test_get_international_portfolio_data_both_index_and_country():
    """Both index and country raises ValueError."""
    with pytest.raises(ValueError, match="not both"):
        helpers.get_international_portfolio_data(index="all", country="japan")


def test_get_international_portfolio_data_invalid_index():
    """An invalid index raises ValueError."""
    with pytest.raises(ValueError, match="not found in available indexes"):
        helpers.get_international_portfolio_data(index="not_an_index")


def test_get_international_portfolio_data_invalid_country():
    """An invalid country raises ValueError."""
    with pytest.raises(ValueError, match="not found in available countries"):
        helpers.get_international_portfolio_data(country="not_a_country")


# ---------------------------------------------------------------------------
# get_portfolio_data  (validation - no network)
# ---------------------------------------------------------------------------


def test_get_portfolio_data_invalid_frequency():
    """An invalid frequency raises ValueError before download."""
    with pytest.raises(ValueError, match="Frequency .* not supported"):
        helpers.get_portfolio_data("Portfolios Formed on ME", frequency="hourly")


def test_get_portfolio_data_invalid_measure():
    """An invalid measure raises ValueError before download."""
    with pytest.raises(ValueError, match="Measure .* not supported"):
        helpers.get_portfolio_data("Portfolios Formed on ME", measure="bogus")


def test_get_portfolio_data_number_of_firms_annual():
    """number_of_firms with annual frequency raises ValueError."""
    with pytest.raises(ValueError, match="only available for monthly"):
        helpers.get_portfolio_data(
            "Portfolios Formed on ME",
            frequency="annual",
            measure="number_of_firms",
        )


# ---------------------------------------------------------------------------
# Data-dependent paths  (real HTTP, recorded to cassettes)
# ---------------------------------------------------------------------------


@pytest.mark.record_http
def test_get_portfolio_data_portfolio_measures():
    """A portfolio dataset across all four measures."""
    for measure in ("value", "equal", "number_of_firms", "firm_size"):
        dfs, metadata = helpers.get_portfolio_data(
            "Portfolios_Formed_on_ME_CSV.zip",
            frequency="monthly",
            measure=measure,
        )
        assert isinstance(dfs, list)
        assert isinstance(metadata, list)
        assert dfs
        assert metadata


@pytest.mark.record_http
def test_get_portfolio_data_daily_dataset():
    """A daily portfolio dataset is parsed without a frequency filter."""
    dfs, metadata = helpers.get_portfolio_data(
        "Portfolios_Formed_on_ME_Daily_CSV.zip",
        measure="value",
    )
    assert isinstance(dfs, list)
    assert dfs


@pytest.mark.record_http
def test_get_portfolio_data_factor_dataset():
    """A Factor dataset clears the measure and returns the factor table."""
    dfs, metadata = helpers.get_portfolio_data(
        "F-F_Research_Data_Factors_CSV.zip",
        frequency="monthly",
        measure="value",
    )
    assert isinstance(dfs, list)
    assert dfs


@pytest.mark.record_http
def test_get_breakpoint_data_non_ratio():
    """A non-ratio breakpoint type ('me')."""
    dfs, metadata = helpers.get_breakpoint_data("me")

    assert isinstance(dfs, list)
    assert isinstance(metadata, list)
    assert "date" in dfs[0].columns


@pytest.mark.record_http
def test_get_breakpoint_data_ratio():
    """A ratio breakpoint type ('be-me') uses the ratio column names."""
    dfs, metadata = helpers.get_breakpoint_data("be-me")

    assert isinstance(dfs, list)
    assert "num_firms_less_than_0" in dfs[0].columns


@pytest.mark.record_http
def test_get_international_portfolio_measures():
    """An international index across measures and all_data_items_required."""
    for measure in ("usd", "local", "ratios"):
        dfs, metadata = helpers.get_international_portfolio(
            index="europe_ex_uk",
            measure=measure,
            frequency="annual",
            dividends=True,
        )
        assert isinstance(dfs, list)
        assert isinstance(metadata, list)
        assert dfs

    for required in (True, False):
        dfs, metadata = helpers.get_international_portfolio(
            index="europe_ex_uk",
            measure="usd",
            frequency="annual",
            dividends=True,
            all_data_items_required=required,
        )
        assert isinstance(dfs, list)
        assert dfs

    # No frequency filter exercises the frequency-None branch.
    dfs, metadata = helpers.get_international_portfolio(
        index="europe_ex_uk",
        measure="usd",
        dividends=True,
    )
    assert isinstance(dfs, list)
    assert dfs


# ---------------------------------------------------------------------------
# read_csv_file  (pure parser - crafted input, no network)
# ---------------------------------------------------------------------------

# A multi-table CSV that exercises: the initial-metadata extraction, the
# standalone "--" metadata line, scanning back across blank lines for a
# table's metadata, and the trailing-blank-line break.
_CSV_TEXT = "\n".join(
    [
        "Some general description of the file",
        "Average Value Weighted Returns -- Monthly",
        ",Lo 30,Med 40,Hi 30",
        "192607,1.0,2.0,3.0",
        "192608,4.0,5.0,6.0,7.0",
        "",
        "  Average Value Weighted Returns -- Annual Returns",
        "",
        ",Lo 30,Med 40,Hi 30",
        "1927,8.0,9.0,10.0",
        "",
        "",
    ]
)


def test_read_csv_file_multi_table():
    """read_csv_file parses multiple tables, metadata, and trailing blanks."""
    tables, general_desc = helpers.read_csv_file(_CSV_TEXT)

    assert len(tables) == 2
    assert "general description" in general_desc
    assert tables[0]["is_annual"] is False
    assert tables[1]["is_annual"] is True
    # The ragged data row keeps all five values.
    assert any(len(row) == 5 for row in tables[0]["rows"])


def test_process_csv_tables_ragged_headers():
    """process_csv_tables pads headers when a data row has extra columns."""
    tables, general_desc = helpers.read_csv_file(_CSV_TEXT)
    dataframes, metadata = helpers.process_csv_tables(tables, general_desc)

    assert len(dataframes) == 2
    # The first table gained a generated column for the ragged row.
    assert any(col.startswith("Column_") for col in dataframes[0].columns)
    assert metadata[0]["frequency"] == "monthly"
    assert metadata[1]["frequency"] == "annual"


def test_process_csv_tables_skips_empty_rows_table():
    """A table whose rows list is empty is skipped."""
    dataframes, metadata = helpers.process_csv_tables(
        [{"meta": "Empty", "headers": ["Date", "A"], "rows": [], "is_annual": False}]
    )

    assert dataframes == []
    assert metadata == []


def test_process_csv_tables_skips_empty_dataframe():
    """A table whose only row is empty produces an empty frame and is skipped."""
    dataframes, metadata = helpers.process_csv_tables(
        [{"meta": "Empty", "headers": ["Date"], "rows": [[]], "is_annual": False}]
    )

    assert dataframes == []
    assert metadata == []


def test_process_csv_tables_bad_dates_fallback():
    """Unparsable dates fall back to string conversion with a warning."""
    table = {
        "meta": "Average Value Weighted Returns -- Monthly",
        "headers": ["Date", "A"],
        "rows": [["9X9X9X", "1.0"], ["8Y8Y8Y", "2.0"]],
        "is_annual": False,
    }
    with pytest.warns(UserWarning, match="Error parsing dates"):
        dataframes, metadata = helpers.process_csv_tables([table])

    assert len(dataframes) == 1
    assert metadata[0]["frequency"] == "monthly"


# ---------------------------------------------------------------------------
# read_dat_file  (pure parser - crafted input, no network)
# ---------------------------------------------------------------------------

# A synthetic .dat payload exercising the comma separator skip, a "Firms"
# table that falls back to default headers (its metadata mentions "Firms" but
# the header row is missing), and a malformed table that is skipped because it
# has neither a usable header row nor "Firms" metadata.
_DAT_TEXT = "\n".join(
    [
        "  Value-Weight Dollar Returns      All 4 Data Items Required",
        "              -- BE/ME --   --- E/P ---",
        "        Mkt   High    Low   High    Low",
        "197501  23.52  22.05  23.43  26.41  24.34",
        "197502  -4.67  -1.35  -7.10   3.73 -10.52",
        "  ,",
        "  Firms-related B/M Section Block",
        "  -- BE/ME --",
        "197501   100   200",
        "197502   110   210",
        "  ,",
        "  Number of Firms in B/M",
        "197501   100   200",
        "197502   110   210",
        "  ,",
        "  Plain Metadata Header Block",
        "  -- BE/ME --",
        "197501   1.0   2.0",
        "197502   3.0   4.0",
    ]
)


def test_read_dat_file_separator_firms_and_malformed():
    """read_dat_file handles separators, Firms tables, and a malformed table."""
    tables = helpers.read_dat_file(_DAT_TEXT)

    # The regular table and both Firms tables are kept; the malformed one is not.
    assert len(tables) == 3
    assert tables[0]["spanners"].strip().startswith("--")
    # The metadata-only Firms table falls back to default headers.
    assert tables[1]["headers"] == ["Date", "Firms", "B/M", "E/P", "CE/P", "Yld"]
    # The "Firms" header-row table has no spanner line.
    assert tables[2]["spanners"] == ""
    assert "Firms" in tables[2]["headers"]


# ---------------------------------------------------------------------------
# process_international_portfolio_data  (pure - crafted input, no network)
# ---------------------------------------------------------------------------


def test_process_international_portfolio_data_skips_empty_table():
    """A table without rows produces an empty frame and is skipped."""
    dataframes, metadata = helpers.process_international_portfolio_data(
        [{"meta": "Empty", "spanners": "", "headers": ["Date"], "rows": []}]
    )

    assert dataframes == []
    assert metadata == []


def test_process_international_portfolio_data_bad_dates_and_ex_dividends():
    """Unparsable dates fall back to strings and ex-dividend metadata is set."""
    table = {
        "meta": "Value-Weight Dollar Returns",
        "spanners": "-- BE/ME --",
        "headers": ["Date", "High", "Low"],
        "rows": [["9X9X9X", "1.0", "2.0"], ["8Y8Y8Y", "3.0", "4.0"]],
    }
    with pytest.warns(UserWarning, match="Error parsing dates"):
        dataframes, metadata = helpers.process_international_portfolio_data(
            [table], dividends=False
        )

    assert len(dataframes) == 1
    assert metadata[0]["description"].endswith("Ex-Dividends")


# ---------------------------------------------------------------------------
# download_file  (latin-1 fallback - monkeypatched network)
# ---------------------------------------------------------------------------


def test_download_file_latin1_fallback(monkeypatch):
    """download_file decodes latin-1 content when utf-8 decoding fails."""

    class _Response:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            """No-op status check."""

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url):
            """Return the prepared latin-1 archive."""
            return _Response(_make_zip("data.csv", "café returns".encode("latin-1")))

    monkeypatch.setattr(
        "openbb_core.provider.utils.helpers.get_requests_session",
        _Session,
    )

    result = helpers.download_file("Portfolios_Formed_on_ME_CSV.zip")

    assert "café" in result
    assert "returns" in result


# ---------------------------------------------------------------------------
# get_international_portfolio_data  (monkeypatched network)
# ---------------------------------------------------------------------------


class _IntlResponse:
    """Stand-in for a requests Response wrapping zip bytes."""

    def __init__(self, content):
        self.content = content


def test_get_international_portfolio_data_country_ex_dividends(monkeypatch):
    """A country lookup with dividends disabled reads from the ex-dividend zip."""
    monkeypatch.setattr(
        helpers,
        "download_international_portfolios",
        lambda url: _IntlResponse(_make_zip("Japan.Dat", b"some japan data")),
    )

    result = helpers.get_international_portfolio_data(country="japan", dividends=False)

    assert result == "some japan data"


def test_get_international_portfolio_data_latin1_fallback(monkeypatch):
    """A non-utf-8 .dat member is decoded using latin-1."""
    monkeypatch.setattr(
        helpers,
        "download_international_portfolios",
        lambda url: _IntlResponse(_make_zip("Japan.Dat", "café".encode("latin-1"))),
    )

    result = helpers.get_international_portfolio_data(country="japan")

    assert result == "café"


def test_get_international_portfolio_data_index_missing_in_zip(monkeypatch):
    """A mapped index that is absent from the archive raises ValueError."""
    monkeypatch.setattr(
        helpers,
        "download_international_portfolios",
        lambda url: _IntlResponse(_make_zip("Other.Dat", b"data")),
    )

    with pytest.raises(ValueError, match="not found in available indexes"):
        helpers.get_international_portfolio_data(index="all")


# The members of F-F_International_Countries.zip and its _Wout_Div twin.
_COUNTRY_ZIP_MEMBERS = {
    "Austria.Dat",
    "Austrlia.Dat",
    "Belgium.Dat",
    "Canada.Dat",
    "Denmark.Dat",
    "Finland.Dat",
    "France.Dat",
    "Germany.Dat",
    "HongKong.Dat",
    "Ireland.Dat",
    "Italy.Dat",
    "Japan.Dat",
    "Malaysia.Dat",
    "Nethrlnd.Dat",
    "NewZland.Dat",
    "Norway.Dat",
    "Singapor.Dat",
    "Spain.Dat",
    "Sweden.Dat",
    "Swtzrlnd.Dat",
    "UK.Dat",
}


def test_every_country_maps_to_a_zip_member():
    """Each country names a member of the archive; Australia's is Austrlia.Dat."""
    missing = {
        country: member
        for country, member in helpers.COUNTRY_PORTFOLIO_FILES.items()
        if member not in _COUNTRY_ZIP_MEMBERS
    }
    assert missing == {}


def test_get_international_portfolio_data_australia(monkeypatch):
    """Australia reads the archive's eight-character member name."""
    monkeypatch.setattr(
        helpers,
        "download_international_portfolios",
        lambda url: _IntlResponse(_make_zip("Austrlia.Dat", b"australia data")),
    )

    result = helpers.get_international_portfolio_data(country="australia")

    assert result == "australia data"


def test_get_international_portfolio_data_unresolved_country_index(monkeypatch):
    monkeypatch.setitem(helpers.COUNTRY_PORTFOLIO_FILES, "Japan", None)
    monkeypatch.setattr(
        helpers,
        "download_international_portfolios",
        lambda url: _IntlResponse(_make_zip("Other.Dat", b"data")),
    )

    with pytest.raises(ValueError, match="Could not resolve portfolio index"):
        helpers.get_international_portfolio_data(country="japan")


# ---------------------------------------------------------------------------
# get_international_portfolio  (measure validation - monkeypatched network)
# ---------------------------------------------------------------------------


def test_get_international_portfolio_invalid_measure(monkeypatch):
    """An unsupported measure raises ValueError after the data is read."""
    monkeypatch.setattr(helpers, "get_international_portfolio_data", lambda *a, **k: "")
    monkeypatch.setattr(helpers, "read_dat_file", lambda data: [])
    monkeypatch.setattr(
        helpers, "process_international_portfolio_data", lambda *a, **k: ([], [])
    )

    with pytest.raises(ValueError, match="Measure .* not supported"):
        helpers.get_international_portfolio(country="japan", measure="bogus")


def test_get_international_portfolio_ratios_monthly(monkeypatch):
    """The 'ratios' measure with monthly frequency raises ValueError."""
    monkeypatch.setattr(helpers, "get_international_portfolio_data", lambda *a, **k: "")
    monkeypatch.setattr(helpers, "read_dat_file", lambda data: [])
    monkeypatch.setattr(
        helpers, "process_international_portfolio_data", lambda *a, **k: ([], [])
    )

    with pytest.raises(ValueError, match="Only annual frequency"):
        helpers.get_international_portfolio(
            country="japan", measure="ratios", frequency="monthly"
        )
