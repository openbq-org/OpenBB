"""Tests for openbb_cli.codegen.test_gen — per-provider unit-test emission."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field

from openbb_cli.codegen import test_gen as tg


@dataclass
class _Fetcher:
    module_name: str
    fetcher_class: str
    model_name: str = ""
    credentials_used: dict[str, dict[str, str]] = field(default_factory=dict)


def _spec_with_choices_and_default():
    return {
        "equity.search": {
            "parameters": [
                {
                    "name": "scope",
                    "type": "string",
                    "required": True,
                    "choices": ["all", "active"],
                },
                {
                    "name": "format",
                    "type": "string",
                    "required": True,
                    "default": "json",
                    "choices": ["json", "xml"],
                },
            ],
        },
    }


# --- _spec_supplied_value ---


def test_spec_supplied_value_prefers_example_over_everything():
    assert (
        tg._spec_supplied_value(
            {
                "example": "AMZN",
                "default": "GOOG",
                "choices": ["GOOG", "AMZN"],
            }
        )
        == "AMZN"
    )
    assert tg._spec_supplied_value({"example": "AAPL", "default": "MSFT"}) == "AAPL"


def test_spec_supplied_value_skips_example_and_default_outside_choices():
    assert (
        tg._spec_supplied_value(
            {
                "example": "AAPL",
                "default": "MSFT",
                "choices": ["GOOG", "AMZN"],
            }
        )
        == "GOOG"
    )
    assert (
        tg._spec_supplied_value(
            {"example": "AAPL", "default": "AMZN", "choices": ["GOOG", "AMZN"]}
        )
        == "AMZN"
    )


def test_spec_supplied_value_skips_quoted_example_outside_choices():
    """Binance's klines spec gives ``interval`` the example ``'"1m"'``."""
    assert (
        tg._spec_supplied_value({"example": '"1m"', "choices": ["1s", "1m", "1h"]})
        == "1s"
    )


def test_spec_supplied_value_prefers_default_over_choices():
    assert (
        tg._spec_supplied_value({"default": "json", "choices": ["xml", "json"]})
        == "json"
    )


def test_spec_supplied_value_falls_back_to_first_choice():
    assert tg._spec_supplied_value({"choices": ["all", "active"]}) == "all"


def test_spec_supplied_value_returns_none_when_no_default_or_choices():
    assert tg._spec_supplied_value({"type": "string"}) is None
    assert tg._spec_supplied_value({}) is None


def test_spec_supplied_value_treats_empty_choices_as_no_choices():
    assert tg._spec_supplied_value({"choices": []}) is None


def test_normalize_to_module_matches_fetcher_module_naming_with_spaces():
    """Dotted names with spaces collapse the same way fetcher module names do."""
    assert tg._normalize_to_module("soma.agency.wam.agency debts.asof") == (
        "soma_agency_wam_agency_debts_asof"
    )


def test_normalize_to_module_handles_leading_digit_and_empty():
    assert tg._normalize_to_module("3legged.path") == "_3legged_path"
    assert tg._normalize_to_module("___") == "command"


# --- _derive_test_params ---


def test_derive_test_params_returns_empty_when_no_required_params():
    cmd = {"parameters": [{"name": "x", "type": "string"}]}
    assert tg._derive_test_params(cmd, "fmp") == {}


def test_derive_test_params_includes_only_required_with_known_value():
    cmd = {
        "parameters": [
            {
                "name": "scope",
                "type": "string",
                "required": True,
                "choices": ["all"],
            },
            {"name": "limit", "type": "integer", "default": 10},
        ]
    }
    out = tg._derive_test_params(cmd, "fmp")
    assert out == {"scope": "all"}


def test_derive_test_params_returns_none_when_required_param_has_no_supplied_value():
    cmd = {
        "parameters": [
            {"name": "cusip", "type": "string", "required": True},
        ]
    }
    assert tg._derive_test_params(cmd, "fmp") is None


def _grouped(alternatives, combinator="oneOf", required=True, params=None):
    members = sorted({name for alt in alternatives for name in alt})
    return {
        "parameters": params
        or [
            {"name": "symbol", "example": "BNBUSDT"},
            {"name": "symbols", "example": '["BTCUSDT"]'},
            {"name": "windowSize"},
        ],
        "required_groups": [
            {
                "combinator": combinator,
                "alternatives": alternatives,
                "members": members,
                "required": required,
            }
        ],
    }


def test_derive_test_params_fills_first_fillable_alternative():
    spec = _grouped([["symbol"], ["symbols"]])
    assert tg._derive_test_params(spec, "binance") == {"symbol": "BNBUSDT"}
    spec = _grouped([["windowSize"], ["symbols"]], combinator="anyOf")
    assert tg._derive_test_params(spec, "binance") == {"symbols": '["BTCUSDT"]'}


def test_derive_test_params_skips_test_when_no_alternative_is_fillable():
    spec = _grouped([["windowSize"], ["missing"]])
    assert tg._derive_test_params(spec, "binance") is None


def test_derive_test_params_leaves_absent_optional_group_alone():
    spec = _grouped([["symbol"], ["symbols"]], required=False)
    assert tg._derive_test_params(spec, "binance") == {}


def test_derive_test_params_keeps_exactly_one_one_of_alternative():
    """The date heuristic fills both dates; oneOf keeps only the first."""
    params = [{"name": "startDate"}, {"name": "endDate"}]
    spec = _grouped([["startDate"], ["endDate"]], params=params)
    out = tg._derive_test_params(spec, "binance")
    assert list(out) == ["start_date"]
    spec = _grouped([["startDate"], ["endDate"]], combinator="anyOf", params=params)
    assert list(tg._derive_test_params(spec, "binance")) == ["start_date", "end_date"]


def test_derive_test_params_one_of_with_nested_alternatives():
    params = [{"name": "a", "example": "A"}, {"name": "b", "example": "B"}]
    spec = _grouped([["a", "b"], ["a"]], params=params)
    assert tg._derive_test_params(spec, "binance") == {"a": "A"}


def test_derive_test_params_never_drops_a_required_param():
    params = [
        {"name": "symbol", "required": True, "example": "BTCUSDT"},
        {"name": "date"},
    ]
    spec = _grouped([["date"], ["symbol"]], params=params)
    assert tg._derive_test_params(spec, "binance") == {"symbol": "BTCUSDT"}
    params = [
        {"name": "symbol", "required": True, "example": "BTCUSDT"},
        {"name": "symbols", "required": True, "example": "X"},
    ]
    spec = _grouped([["symbol"], ["symbols"]], params=params)
    assert tg._derive_test_params(spec, "binance") is None


def test_derive_test_params_solves_groups_together():
    """oneOf [a|b] plus anyOf [b|c]: {b} meets both, though filling a first does not."""
    params = [
        {"name": "a", "example": "A"},
        {"name": "b", "example": "B"},
        {"name": "c"},
    ]
    spec = _grouped([["a"], ["b"]], params=params)
    spec["required_groups"].append(
        {
            "combinator": "anyOf",
            "alternatives": [["b"], ["c"]],
            "members": ["b", "c"],
            "required": True,
        }
    )
    assert tg._derive_test_params(spec, "binance") == {"b": "B"}


def test_derive_test_params_skips_test_when_groups_truly_conflict():
    params = [{"name": "a", "example": "A"}, {"name": "b", "example": "B"}]
    spec = _grouped([["a"], ["b"]], params=params)
    spec["required_groups"].append(
        {
            "combinator": "anyOf",
            "alternatives": [["a", "b"]],
            "members": ["a", "b"],
            "required": True,
        }
    )
    assert tg._derive_test_params(spec, "binance") is None


def test_derive_test_params_fills_a_merged_url_when_none_fits():
    """No URL is free of placeholders, so the test fills the first it can."""
    cmd = {
        "url_path": "/orders/{orderId}",
        "url_templates": ["/orders/{orderId}", "/{account}/orders"],
        "template_query_params": {"/orders/{orderId}": [], "/{account}/orders": []},
        "parameters": [
            {"name": "orderId", "in": "path", "required": False},
            {"name": "account", "in": "path", "required": False, "example": "acct"},
        ],
    }
    assert tg._derive_test_params(cmd, "prov") == {"account": "acct"}
    cmd["parameters"][1].pop("example")
    assert tg._derive_test_params(cmd, "prov") is None


def test_derive_test_params_date_heuristic_skips_any_url_placeholder():
    """The merged ``date`` kept its query copy, but another URL uses it as a segment."""
    cmd = {
        "url_path": "/obs/{station}",
        "url_templates": ["/obs/{station}", "/obs/{date}"],
        "template_query_params": {"/obs/{station}": ["date"], "/obs/{date}": []},
        "parameters": [
            {"name": "station", "in": "path", "required": False, "example": "KPHX"},
            {"name": "date", "in": "query", "required": False},
        ],
    }
    out = tg._derive_test_params(cmd, "prov")
    assert "date" not in out


def test_derive_test_params_disarms_optional_group_set_off_by_heuristic_dates():
    params = [{"name": "startDate"}, {"name": "symbol"}]
    spec = _grouped([["symbol"]], combinator="anyOf", required=False, params=params)
    spec["required_groups"][0]["members"] = ["startDate", "symbol"]
    assert tg._derive_test_params(spec, "binance") == {}


def test_derive_test_params_reuses_heuristic_value_inside_an_alternative():
    params = [{"name": "symbol", "example": "BTCUSDT"}, {"name": "date"}]
    spec = _grouped([["symbol", "date"]], combinator="anyOf", params=params)
    out = tg._derive_test_params(spec, "binance")
    assert set(out) == {"symbol", "date"}
    assert out["symbol"] == "BTCUSDT"


def test_derive_test_params_keys_are_query_params_field_names():
    """``Fetcher.test`` reads each key back with ``getattr`` on the query."""
    from openbb_cli.codegen.fetcher_gen import _query_params_schema
    from openbb_cli.codegen.pydantic_gen import generate_class, render_module

    cmd = {
        "parameters": [
            {
                "name": "operationType",
                "type": "string",
                "required": True,
                "example": "all",
            },
            {"name": "cwsu-id", "type": "string", "required": True, "example": "ZAB"},
            {"name": "startDate", "type": "string"},
        ]
    }
    out = tg._derive_test_params(cmd, "prov")
    assert set(out) == {"operation_type", "cwsu_id", "start_date"}
    cls = generate_class(
        _query_params_schema(cmd, "prov"), class_name="Q", base_class="QueryParams"
    )
    namespace: dict = {}
    exec(  # noqa: S102
        "from openbb_core.provider.abstract.query_params import QueryParams\n"
        + render_module(cls),
        namespace,
    )
    query = namespace["Q"](**out)
    assert all(getattr(query, key) == value for key, value in out.items())


def test_derive_test_params_date_heuristic_skips_params_with_choices():
    """``date_type`` (trade | maturity) is not a date; filling it fails validation."""
    cmd = {
        "parameters": [
            {"name": "date_type", "type": "string", "choices": ["trade", "maturity"]},
            {"name": "startDate", "type": "string"},
        ]
    }
    assert set(tg._derive_test_params(cmd, "prov")) == {"start_date"}


def test_derive_test_params_date_heuristic_skips_path_params():
    """A merged command's optional ``{date}`` belongs to another URL, not this test."""
    cmd = {
        "parameters": [
            {"name": "cwsuId", "in": "path", "required": True, "example": "ZAB"},
            {"name": "date", "in": "path", "required": False},
            {"name": "startDate", "in": "query"},
        ]
    }
    assert set(tg._derive_test_params(cmd, "prov")) == {"cwsu_id", "start_date"}


def test_spec_supplied_value_joins_list_example_for_list_query_param():
    param = {"name": "symbols", "in": "query", "is_list": True, "example": ["A", "B"]}
    assert tg._spec_supplied_value(param) == "A,B"
    assert tg._spec_supplied_value({**param, "is_list": False}) == ["A", "B"]


def test_derive_test_params_skips_provider_discriminator():
    cmd = {
        "parameters": [
            {"name": "provider", "type": "string", "required": True},
            {
                "name": "scope",
                "type": "string",
                "required": True,
                "choices": ["all"],
            },
        ]
    }
    assert tg._derive_test_params(cmd, "fmp") == {"scope": "all"}


def test_derive_test_params_skips_unnamed_or_non_dict_entries():
    cmd = {
        "parameters": [
            "not a dict",
            {"type": "string", "required": True},
            {
                "name": "scope",
                "type": "string",
                "required": True,
                "choices": ["all"],
            },
        ]
    }
    assert tg._derive_test_params(cmd, "fmp") == {"scope": "all"}


def test_derive_test_params_skips_param_outside_provider_whitelist():
    cmd = {
        "parameters": [
            {
                "name": "use_cache",
                "type": "boolean",
                "required": True,
                "providers": ["cboe"],
            },
        ]
    }
    # ``use_cache`` is cboe-only — fmp's QueryParams class doesn't have it,
    # so it's skipped instead of failing the whole test.
    assert tg._derive_test_params(cmd, "fmp") == {}


def test_derive_test_params_skips_optional_choices_to_avoid_over_constraining():
    """Optional ``choices`` over-constrain queries (rp_results_search empty
    when method=multiple+term=overnight added). Better to omit and let the
    upstream choose its own defaults."""
    cmd = {
        "parameters": [
            {
                "name": "scope",
                "type": "string",
                "required": True,
                "choices": ["all"],
            },
            {
                "name": "operationTypes",
                "type": "string",
                "required": False,
                "choices": ["Repo", "Reverse Repo"],
            },
        ]
    }
    out = tg._derive_test_params(cmd, "fmp")
    assert out == {"scope": "all"}
    assert "operationTypes" not in out


def test_derive_test_params_includes_optional_date_params_with_current_date():
    """Search endpoints typically need a date range to return data."""
    cmd = {
        "parameters": [
            {
                "name": "scope",
                "type": "string",
                "required": True,
                "choices": ["all"],
            },
            {"name": "startDate", "type": "string", "required": False},
            {"name": "endDate", "type": "string", "required": False},
        ]
    }
    out = tg._derive_test_params(cmd, "fmp")
    from datetime import date, timedelta

    assert out["scope"] == "all"
    assert out["start_date"] == str(date.today() - timedelta(days=30))
    assert out["end_date"] == str(date.today())


def test_derive_test_params_skips_optional_param_without_date_shape_or_required():
    cmd = {
        "parameters": [
            {
                "name": "scope",
                "type": "string",
                "required": True,
                "choices": ["all"],
            },
            {"name": "extra", "type": "string", "required": False},
            {
                "name": "cusip",
                "type": "string",
                "required": False,
                "example": "01234ABCD",
            },
        ]
    }
    out = tg._derive_test_params(cmd, "fmp")
    assert out == {"scope": "all"}


def test_is_date_param_recognizes_canonical_names():
    assert tg._is_date_param("startDate")
    assert tg._is_date_param("endDate")
    assert tg._is_date_param("date")
    assert tg._is_date_param("fromDate")
    assert tg._is_date_param("toDate")
    assert tg._is_date_param("from")
    assert tg._is_date_param("to")
    assert tg._is_date_param("operationDate")  # contains "date"
    assert not tg._is_date_param("symbol")
    assert not tg._is_date_param("limit")


# --- _refresh_date_shape ---


def test_refresh_date_shape_replaces_yyyy_mm_dd_example_with_today():
    out = tg._refresh_date_shape("endDate", "2021-01-01")
    from datetime import date

    assert out == str(date.today())


def test_refresh_date_shape_uses_thirty_days_ago_for_start_date():
    out = tg._refresh_date_shape("startDate", "2021-01-01")
    from datetime import date, timedelta

    assert out == str(date.today() - timedelta(days=30))


def test_refresh_date_shape_treats_from_as_start_alias():
    out = tg._refresh_date_shape("from", "2021-01-01")
    from datetime import date, timedelta

    assert out == str(date.today() - timedelta(days=30))


def test_refresh_date_shape_handles_iso_timestamps():
    """ISO-8601 timestamps refresh to today's UTC timestamp."""
    out = tg._refresh_date_shape("toDateTime", "2021-01-01T00:00:00Z")
    assert out.endswith("Z")
    assert "T" in out
    # It's an actual parseable iso datetime
    from datetime import datetime

    parsed = datetime.fromisoformat(out.replace("Z", "+00:00"))
    assert parsed.year >= 2024


def test_refresh_date_shape_passes_through_non_date_strings():
    assert tg._refresh_date_shape("symbol", "AAPL") == "AAPL"


def test_refresh_date_shape_passes_through_non_strings():
    assert tg._refresh_date_shape("limit", 5) == 5
    assert tg._refresh_date_shape("flag", True) is True


def test_spec_supplied_value_returns_none_for_open_ended_param():
    """Param with no example, default, or choices yields None — caller skips test."""
    assert tg._spec_supplied_value({"name": "cusip", "type": "string"}) is None


# --- generate_provider_tests ---


def test_generate_provider_tests_returns_none_when_no_fetchers():
    out = tg.generate_provider_tests(
        package_name="openbb_x",
        provider_name="x",
        fetchers=[],
        commands_by_dotted={},
    )
    assert out is None


def test_generate_provider_tests_emits_runnable_module():
    fetchers = [
        _Fetcher(module_name="equity_search", fetcher_class="EquitySearchFetcher"),
    ]
    out = tg.generate_provider_tests(
        package_name="openbb_x",
        provider_name="x",
        fetchers=fetchers,
        commands_by_dotted=_spec_with_choices_and_default(),
    )
    assert out is not None
    assert out.module_name == "test_x_fetchers"
    src = out.source
    ast.parse(src)
    assert "import pytest" in src
    assert (
        "from openbb_x.providers.x.models.equity_search import EquitySearchFetcher"
    ) in src
    assert "test_credentials = UserService()" in src
    assert "@pytest.fixture" in src
    assert "def vcr_config():" in src
    assert "@pytest.mark.record_http" in src
    assert "def test_equity_search_fetcher(credentials=test_credentials):" in src
    assert "fetcher = EquitySearchFetcher()" in src
    assert "result = fetcher.test(params, credentials)" in src
    assert "assert result is None" in src
    # Required params: scope (choices[0]='all') + format (default='json').
    assert "'scope': 'all'" in src
    assert "'format': 'json'" in src


def test_generate_provider_tests_skips_fetchers_with_unsuppliable_required_params():
    fetchers = [
        _Fetcher(module_name="equity_search", fetcher_class="EquitySearchFetcher"),
        _Fetcher(module_name="x_y", fetcher_class="XYFetcher"),
    ]
    cmds = {
        "equity.search": _spec_with_choices_and_default()["equity.search"],
        # XY requires a free-form ``cusip`` -- can't derive a valid value
        "x.y": {
            "parameters": [
                {"name": "cusip", "type": "string", "required": True},
            ]
        },
    }
    out = tg.generate_provider_tests(
        package_name="openbb_x",
        provider_name="x",
        fetchers=fetchers,
        commands_by_dotted=cmds,
    )
    assert out is not None
    assert "EquitySearchFetcher()" in out.source
    assert "XYFetcher" not in out.source


def test_generate_provider_tests_returns_none_when_every_fetcher_unconfident():
    fetchers = [
        _Fetcher(module_name="x_y", fetcher_class="XYFetcher"),
        _Fetcher(module_name="a_b", fetcher_class="ABFetcher"),
    ]
    cmds = {
        "x.y": {"parameters": [{"name": "cusip", "type": "string", "required": True}]},
        "a.b": {"parameters": [{"name": "raw_id", "type": "string", "required": True}]},
    }
    assert (
        tg.generate_provider_tests(
            package_name="openbb_x",
            provider_name="x",
            fetchers=fetchers,
            commands_by_dotted=cmds,
        )
        is None
    )


def test_generate_provider_tests_handles_unknown_command_dotted_path():
    """Fetcher whose module name doesn't match any dotted command -> empty params."""
    fetchers = [_Fetcher(module_name="orphan", fetcher_class="OrphanFetcher")]
    out = tg.generate_provider_tests(
        package_name="openbb_x",
        provider_name="x",
        fetchers=fetchers,
        commands_by_dotted={"some.other.thing": {"parameters": []}},
    )
    assert out is not None
    assert "params = {}" in out.source


# --- vcr_config redactions ---


def test_generate_provider_tests_emits_query_credential_with_mock_value():
    fetchers = [
        _Fetcher(
            module_name="equity_search",
            fetcher_class="EquitySearchFetcher",
            credentials_used={"api_key": {"name": "apikey", "in": "query"}},
        ),
    ]
    out = tg.generate_provider_tests(
        package_name="openbb_x",
        provider_name="x",
        fetchers=fetchers,
        commands_by_dotted=_spec_with_choices_and_default(),
    )
    assert out is not None
    assert "filter_query_parameters" in out.source
    assert "('apikey', 'MOCK_API_KEY')" in out.source


def test_generate_provider_tests_emits_header_credential_with_bearer_mock():
    fetchers = [
        _Fetcher(
            module_name="equity_search",
            fetcher_class="EquitySearchFetcher",
            credentials_used={
                "authorization": {"name": "Authorization", "in": "header"}
            },
        ),
    ]
    out = tg.generate_provider_tests(
        package_name="openbb_x",
        provider_name="x",
        fetchers=fetchers,
        commands_by_dotted=_spec_with_choices_and_default(),
    )
    assert out is not None
    assert "('Authorization', 'Bearer MOCK_TOKEN')" in out.source


def test_generate_provider_tests_includes_standard_redaction_baseline():
    """Even without provider-declared credentials, the baseline redactions ship."""
    fetchers = [
        _Fetcher(module_name="equity_search", fetcher_class="EquitySearchFetcher")
    ]
    out = tg.generate_provider_tests(
        package_name="openbb_x",
        provider_name="x",
        fetchers=fetchers,
        commands_by_dotted=_spec_with_choices_and_default(),
    )
    assert out is not None
    assert "('User-Agent', None)" in out.source
    for entry in (
        "('api_key', 'MOCK_API_KEY')",
        "('client_secret', 'MOCK_CLIENT_SECRET')",
        "('access_token', 'MOCK_TOKEN')",
        "('private_key', 'MOCK_SECRET')",
    ):
        assert entry in out.source


# --- _mock_value_for branches ---


def test_mock_value_for_picks_secret_when_name_contains_secret():
    assert tg._mock_value_for("client_secret") == "MOCK_SECRET"
    assert tg._mock_value_for("private_key_secret") == "MOCK_SECRET"


def test_mock_value_for_picks_token_when_name_contains_token():
    assert tg._mock_value_for("auth_token") == "MOCK_TOKEN"
    assert tg._mock_value_for("X-Auth-Token") == "MOCK_TOKEN"


def test_mock_value_for_picks_client_id_for_id_shaped_names():
    assert tg._mock_value_for("client_id") == "MOCK_CLIENT_ID"
    assert tg._mock_value_for("appid") == "MOCK_CLIENT_ID"
    assert tg._mock_value_for("app_id") == "MOCK_CLIENT_ID"


def test_mock_value_for_default_falls_back_to_api_key():
    assert tg._mock_value_for("apikey") == "MOCK_API_KEY"
    assert tg._mock_value_for("subscription_key") == "MOCK_API_KEY"


# --- _merge_redactions edge cases ---


def test_merge_redactions_skips_credentials_without_wire_name():
    fetchers = [
        _Fetcher(
            module_name="x",
            fetcher_class="XFetcher",
            credentials_used={"weird": {"in": "query"}},
        ),
    ]
    headers, queries = tg._merge_redactions(fetchers)
    assert all(name for name, _ in headers)
    assert all(name for name, _ in queries)


def test_merge_redactions_leaves_cookie_credentials_to_cookie_header():
    """A cookie credential gets no filter of its own; ``Cookie`` covers it."""
    fetchers = [
        _Fetcher(
            module_name="x",
            fetcher_class="XFetcher",
            credentials_used={"session": {"name": "sid", "in": "cookie"}},
        ),
    ]
    headers, queries = tg._merge_redactions(fetchers)
    assert "sid" not in dict(headers)
    assert "sid" not in dict(queries)
    assert dict(headers)["Cookie"] == "MOCK_COOKIE"


def test_merge_redactions_picks_up_provider_credential_outside_baseline():
    fetchers = [
        _Fetcher(
            module_name="x",
            fetcher_class="XFetcher",
            credentials_used={"weird_creds": {"name": "X-Weird-Creds", "in": "header"}},
        ),
    ]
    headers, _ = tg._merge_redactions(fetchers)
    assert ("X-Weird-Creds", "MOCK_API_KEY") in headers


# --- _snake ---


def test_snake_handles_multi_word_camelcase():
    assert (
        tg._snake("EquityPriceHistoricalFetcher") == "equity_price_historical_fetcher"
    )
    assert tg._snake("XYZFetcher") == "xyzfetcher"
    assert tg._snake("simple") == "simple"


def test_normalize_to_module_matches_keyword_suffix():
    assert tg._normalize_to_module("class") == "class_"


def test_derive_test_params_keys_renamed_fields_by_their_field_name():
    cmd_spec = {
        "url_path": "/items/{ID}",
        "parameters": [
            {
                "name": "ID",
                "in": "path",
                "type": "string",
                "required": True,
                "example": "A1",
            },
            {"name": "id", "in": "query", "type": "string"},
        ],
    }
    assert tg._derive_test_params(cmd_spec, "prov", "ItemsQueryParams") == {"id_": "A1"}
