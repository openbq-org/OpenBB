"""Widgets whose unfiltered default exceeds MAX_AUTO_ROWS open on the newest page."""

import pytest

PREFIX = "/api/v1/eia/"

NEWEST_PAGE = {
    PREFIX + path
    for path in (
        "aeo",
        "ieo",
        "international",
        "seds",
        "electricity/electric_power_operations",
        "electricity/electric_power_operations_for_individual_power_plants",
        "electricity/inventory_of_operable_generators",
        "electricity_grid/demand",
        "electricity_grid/demand_by_subregion",
        "electricity_grid/generation_by_fuel",
        "electricity_grid/interchange",
        "nuclear_outages/facility_level_nuclear_outages",
        "nuclear_outages/generator_level_nuclear_outages",
        "petroleum/consumption_sales/prime_supplier_sales_volumes",
        "petroleum/consumption_sales/refiner_motor_gasoline_sales_volumes",
        "petroleum/consumption_sales/refiner_sales_volumes_of_other_petroleum_products",
        "petroleum/imports_exports_and_movements/exports_by_destination",
        "petroleum/imports_exports_and_movements/pad_district_exports_by_destination",
        "petroleum/imports_exports_and_movements/pad_district_imports_by_country_of_origin",
        "petroleum/prices/gasoline_prices_by_formulation_grade_sales_type",
        "petroleum/refining_and_processing/refinery_blender_net_production",
        "petroleum/stocks/stocks_by_type",
        "petroleum/summary/prices_sales_volumes_stocks_by_state",
        "petroleum/summary/supply_and_disposition",
        "petroleum/summary/weekly_supply_estimates",
    )
}


@pytest.fixture(scope="module")
def eia_paths():
    """Map every EIA GET path to its OpenAPI operation."""
    from openbb_core.api.rest_api import app

    return {
        path: item["get"]
        for path, item in app.openapi()["paths"].items()
        if path.startswith(PREFIX) and "get" in item
    }


def _paging_params(operation) -> dict:
    params = (operation.get("widget_config") or {}).get("params", [])
    return {p["paramName"]: p for p in params if p["paramName"] in ("limit", "sort")}


def test_listed_widgets_open_on_the_newest_5000_rows(eia_paths):
    assert len(NEWEST_PAGE) == 25
    for path in sorted(NEWEST_PAGE):
        params = _paging_params(eia_paths[path])
        assert params["limit"]["value"] == 5000, path
        assert params["sort"]["value"] == "desc", path
        assert params["sort"]["show"] is False, path


def test_other_widgets_keep_their_defaults(eia_paths):
    others = {path: op for path, op in eia_paths.items() if path not in NEWEST_PAGE}
    assert others
    assert {path for path, op in others.items() if _paging_params(op)} == set()


def test_api_defaults_are_unchanged(eia_paths):
    """Only the widget changes: the API still paginates fully, oldest first."""
    for path in NEWEST_PAGE:
        defaults = {
            p["name"]: p["schema"].get("default") for p in eia_paths[path]["parameters"]
        }
        assert "limit" in defaults, path
        assert defaults["limit"] is None, path
        assert defaults["sort"] == "asc", path
