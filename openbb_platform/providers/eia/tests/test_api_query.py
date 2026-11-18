"""Tests for the shared EIA APIv2 query, pagination, and transform machinery."""

from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest
from openbb_core.provider.utils.errors import EmptyDataError

from openbb_us_eia.models.crude_oil_imports import EiaCrudeOilImportsQueryParams
from openbb_us_eia.models.ieo import EiaIeoQueryParams
from openbb_us_eia.models.registry import DATASET_FETCHERS
from openbb_us_eia.utils import catalog
from openbb_us_eia.utils.api_query import (
    MAX_AUTO_ROWS,
    empty_result_message,
    maybe_float,
    paginate,
    to_float,
    transform_rows,
)
from openbb_us_eia.utils.helpers import build_data_url

CoalReceiptsQueryParams = DATASET_FETCHERS["EiaCoalReceipts"].query_params_type


class TestQueryParamProperties:
    """Dataset resolution and facet collection on the base query params."""

    def test_dataset_key_from_dataset_class_attribute(self):
        query = CoalReceiptsQueryParams()
        assert query.dataset_key == "receipts"

    def test_dataset_key_from_release_field(self):
        query = EiaIeoQueryParams(release="2021")
        assert query.dataset_key == "2021"

    def test_dataset_key_single_dataset_group(self):
        query = EiaCrudeOilImportsQueryParams()
        assert query.dataset_key == "crude_oil_imports"

    def test_dataset_key_falls_back_to_first_of_group(self):
        from openbb_us_eia.utils.api_query import EiaApiQueryParams

        class BareSedsQuery(EiaApiQueryParams):
            """Synthetic query with neither __dataset__ nor a release field."""

            __group__ = "seds"

        assert BareSedsQuery().dataset_key == "seds"

    def test_facet_values_exclude_standard_fields(self):
        query = CoalReceiptsQueryParams(coal_rank="MET", limit=10, sort="desc")
        facets = query.facet_values
        assert facets["coal_rank"] == "MET"
        assert "limit" not in facets
        assert "sort" not in facets
        assert "dataset" not in facets


class TestBuildDataUrl:
    """URL rendering for one page of an EIA data request."""

    def test_full_request(self):
        request = {
            "path": "coal/receipts",
            "api_key": "KEY",
            "frequency": "quarterly",
            "data_columns": ["quantity", "price"],
            "facets": {"coalRankId": ["MET", "STM"]},
            "start": "2020-Q1",
            "end": "2021-Q4",
            "sort": "asc",
        }
        url = build_data_url(request, offset=5000, length=2500)
        parsed = urlparse(url)
        assert parsed.path == "/v2/coal/receipts/data/"
        params = parse_qs(parsed.query)
        assert params["api_key"] == ["KEY"]
        assert params["frequency"] == ["quarterly"]
        assert params["data[0]"] == ["quantity"]
        assert params["data[1]"] == ["price"]
        assert params["facets[coalRankId][]"] == ["MET", "STM"]
        assert params["start"] == ["2020-Q1"]
        assert params["end"] == ["2021-Q4"]
        assert params["sort[0][column]"] == ["period"]
        assert params["sort[0][direction]"] == ["asc"]
        assert params["offset"] == ["5000"]
        assert params["length"] == ["2500"]

    def test_optional_parts_omitted(self):
        request = {"path": "steo", "api_key": "KEY"}
        params = parse_qs(urlparse(build_data_url(request, 0, 5000)).query)
        assert "frequency" not in params
        assert "start" not in params
        assert "end" not in params
        assert params["sort[0][direction]"] == ["desc"]


def _page(rows, total, date_format="YYYY"):
    return {"response": {"data": rows, "total": str(total), "dateFormat": date_format}}


def _stub_http(pages):
    """Build amake_request/amake_requests stubs serving canned pages by offset."""
    calls = {"urls": []}

    async def amake_request(url, response_callback=None, **kwargs):
        calls["urls"].append(url)
        offset = int(parse_qs(urlparse(url).query)["offset"][0])
        return pages[offset]

    async def amake_requests(urls, response_callback=None, **kwargs):
        calls["urls"].extend(urls)
        return [pages[int(parse_qs(urlparse(url).query)["offset"][0])] for url in urls]

    return amake_request, amake_requests, calls


async def _noop_callback(response, session):
    return {}


class TestPaginate:
    """Automatic pagination against the response total."""

    @pytest.mark.asyncio
    async def test_single_page(self):
        rows = [{"period": "2020", "value": "1"}]
        amake_request, amake_requests, calls = _stub_http({0: _page(rows, 1)})
        result = await paginate(
            build_data_url,
            {"path": "seds", "api_key": "K"},
            limit=None,
            amake_request=amake_request,
            amake_requests=amake_requests,
            response_callback=_noop_callback,
        )
        assert result["rows"] == rows
        assert result["total"] == 1
        assert result["date_format"] == "YYYY"
        assert len(calls["urls"]) == 1

    @pytest.mark.asyncio
    async def test_multiple_pages(self):
        pages = {
            0: _page([{"period": str(y)} for y in range(5000)], 12000),
            5000: _page([{"period": str(y)} for y in range(5000)], 12000),
            10000: _page([{"period": str(y)} for y in range(2000)], 12000),
        }
        amake_request, amake_requests, calls = _stub_http(pages)
        result = await paginate(
            build_data_url,
            {"path": "seds", "api_key": "K"},
            limit=None,
            amake_request=amake_request,
            amake_requests=amake_requests,
            response_callback=_noop_callback,
        )
        assert len(result["rows"]) == 12000
        assert len(calls["urls"]) == 3

    @pytest.mark.asyncio
    async def test_limit_caps_requests_and_rows(self):
        pages = {
            0: _page([{"period": str(y)} for y in range(5000)], 50000),
            5000: _page([{"period": str(y)} for y in range(2000)], 50000),
        }
        amake_request, amake_requests, calls = _stub_http(pages)
        result = await paginate(
            build_data_url,
            {"path": "seds", "api_key": "K"},
            limit=7000,
            amake_request=amake_request,
            amake_requests=amake_requests,
            response_callback=_noop_callback,
        )
        assert len(result["rows"]) == 7000
        assert len(calls["urls"]) == 2
        last = parse_qs(urlparse(calls["urls"][-1]).query)
        assert last["length"] == ["2000"]

    @pytest.mark.asyncio
    async def test_empty_response_raises(self):
        amake_request, amake_requests, _ = _stub_http({0: _page([], 0)})
        with pytest.raises(EmptyDataError):
            await paginate(
                build_data_url,
                {"path": "seds", "api_key": "K"},
                limit=None,
                amake_request=amake_request,
                amake_requests=amake_requests,
                response_callback=_noop_callback,
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("sort, requests", [("asc", 2), ("desc", 1)])
    async def test_auto_ceiling_returns_newest_page_without_limit(self, sort, requests):
        calls = []

        async def amake_request(url, response_callback=None, **kwargs):
            direction = parse_qs(urlparse(url).query)["sort[0][direction]"][0]
            calls.append(direction)
            period = "2026" if direction == "desc" else "1990"
            return _page([{"period": period}] * 5000, MAX_AUTO_ROWS + 1)

        async def amake_requests(urls, response_callback=None, **kwargs):
            raise AssertionError("no further pages are requested")

        with pytest.warns(UserWarning, match="Returning the newest 5000 rows"):
            result = await paginate(
                build_data_url,
                {"path": "seds", "api_key": "K", "sort": sort},
                limit=None,
                amake_request=amake_request,
                amake_requests=amake_requests,
                response_callback=_noop_callback,
            )
        assert calls == [sort, "desc"][:requests]
        assert result["rows"] == [{"period": "2026"}] * 5000
        assert result["total"] == MAX_AUTO_ROWS + 1

    @pytest.mark.asyncio
    async def test_explicit_limit_bypasses_ceiling(self):
        pages = {0: _page([{"period": "2020"}] * 100, MAX_AUTO_ROWS + 1)}
        amake_request, amake_requests, _ = _stub_http(pages)
        result = await paginate(
            build_data_url,
            {"path": "seds", "api_key": "K"},
            limit=100,
            amake_request=amake_request,
            amake_requests=amake_requests,
            response_callback=_noop_callback,
        )
        assert len(result["rows"]) == 100


class TestEmptyResultMessage:
    """Empty results are explained against the live facet vocabularies."""

    @staticmethod
    def _facet_server(vocabularies):
        async def amake_request(url, response_callback=None, **kwargs):
            facet_id = url.split("/facet/")[1].split("?")[0]
            if vocabularies.get(facet_id) is None:
                raise ValueError("facet endpoint unavailable")
            return {
                "response": {
                    "facets": [
                        {"id": value, "name": label}
                        for value, label in vocabularies[facet_id].items()
                    ]
                }
            }

        return amake_request

    @pytest.mark.asyncio
    async def test_invalid_value_lists_valid_choices(self):
        request = {
            "path": "petroleum/pri/spt",
            "api_key": "K",
            "facets": {"series": ["RWTC"], "process": ["VAM"]},
            "facet_params": {"series": "series", "process": "process"},
        }
        amake_request = self._facet_server(
            {
                "series": {"RWTC": "Cushing, OK WTI Spot Price FOB"},
                "process": {"PF4": "Spot Price FOB"},
            }
        )
        message = await empty_result_message(request, amake_request, _noop_callback)
        assert "process: VAM is not valid for this dataset" in message
        assert "PF4 = Spot Price FOB" in message

    @pytest.mark.asyncio
    async def test_valid_combination_explains_no_intersection(self):
        request = {
            "path": "petroleum/pri/spt",
            "api_key": "K",
            "facets": {"duoarea": ["NUS"], "series": ["RWTC"]},
            "facet_params": {"duoarea": "region", "series": "series"},
            "coverage": ("1986-01-02", "2026-06-30"),
            "start": "2026-01-01",
        }
        amake_request = self._facet_server(
            {
                "duoarea": {"NUS": "U.S."},
                "series": {"RWTC": "Cushing, OK WTI Spot Price FOB"},
            }
        )
        message = await empty_result_message(request, amake_request, _noop_callback)
        assert "combination does not match" in message
        assert "region: NUS (U.S.)" in message
        assert "series: RWTC (Cushing, OK WTI Spot Price FOB)" in message
        assert "The dataset covers 1986-01-02 to 2026-06-30" in message

    @pytest.mark.asyncio
    async def test_facet_endpoint_failure_falls_back_to_codes(self):
        request = {
            "path": "petroleum/pri/spt",
            "api_key": "K",
            "facets": {"series": ["RWTC"]},
            "facet_params": {"series": "series"},
        }
        amake_request = self._facet_server({"series": None})
        message = await empty_result_message(request, amake_request, _noop_callback)
        assert "series: RWTC" in message

    @pytest.mark.asyncio
    async def test_no_facets_reports_date_range(self):
        request = {
            "path": "seds",
            "api_key": "K",
            "facets": {},
            "coverage": ("1960", "2023"),
            "start": "2030",
            "end": "2031",
        }
        message = await empty_result_message(request, None, _noop_callback)
        assert message.startswith("The request returned no data.")
        assert "Requested period: 2030 to 2031" in message
        assert "The dataset covers 1960 to 2023" in message


class TestTransformRows:
    """Row normalization for catalog datasets."""

    def test_facet_and_data_column_renames(self):
        spec = catalog.get_dataset("coal", "exports_imports_quantity_price")
        rows = [
            {
                "period": "2023-Q1",
                "exportImportType": "Exports",
                "coalRankId": "MET",
                "coalRankDescription": "Metallurgical",
                "countryId": "CA",
                "countryDescription": "Canada",
                "quantity": "100.5",
                "price": "not-a-number",
                "quantity-units": "short tons",
            }
        ]
        out = transform_rows(spec, rows, 'YYYY-"Q"Q')
        record = out[0]
        assert record["date"] == date(2023, 1, 1)
        assert record["export_import_type"] == "Exports"
        assert record["coal_rank"] == "MET"
        assert record["coal_rank_name"] == "Metallurgical"
        assert record["country_name"] == "Canada"
        assert record["quantity"] == 100.5
        assert record["price"] is None
        assert "quantity_units" not in record

    def test_unknown_columns_snake_cased(self):
        spec = catalog.get_dataset("seds", "seds")
        rows = [
            {
                "period": "2020",
                "seriesId": "TETPB",
                "seriesDescription": "Total energy",
                "stateId": "TX",
                "stateDescription": "Texas",
                "value": "285.1",
                "unit": "million Btu",
                "surpriseColumn": "x",
            }
        ]
        record = transform_rows(spec, rows, "YYYY")[0]
        assert record["series"] == "TETPB"
        assert record["series_name"] == "Total energy"
        assert record["state"] == "TX"
        assert record["state_name"] == "Texas"
        assert record["value"] == 285.1
        assert record["surprise_column"] == "x"


class TestNumericCasting:
    """Numeric columns are floats; withheld flags become null."""

    def test_to_float_casts_numeric_strings(self):
        assert to_float("1.5") == 1.5

    def test_to_float_nulls_withheld_flags(self):
        assert to_float("W") is None
        assert to_float("NA") is None

    def test_to_float_passes_numbers_and_none(self):
        assert to_float(None) is None
        assert to_float(2) == 2

    def test_maybe_float_for_raw_browser_columns(self):
        assert maybe_float("1.5") == 1.5
        assert maybe_float("W") == "W"
        assert maybe_float(None) is None
