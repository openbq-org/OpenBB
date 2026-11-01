"""Tests for openbb_cli.codegen.router_gen — router module emission."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from openbb_cli.codegen import (
    namespace_tree as nt,
    router_gen as rg,
)


@dataclass
class _Fetcher:
    module_name: str
    fetcher_class: str
    model_name: str
    is_streaming: bool = False


@dataclass
class _PostCommand:
    module_name: str
    function_name: str


# --- _safe_segment / _module_name_for / _model_name_for ---


def test_safe_segment_handles_special_chars_and_empty():
    assert rg._safe_segment("Equity Price") == "equity_price"
    assert rg._safe_segment("___") == "ns"
    assert rg._safe_segment("Fixed-Income") == "fixed_income"


def test_module_name_for_joins_dotted_path():
    assert rg._module_name_for("equity") == "equity"
    assert rg._module_name_for("equity.price") == "equity_price"
    assert rg._module_name_for("equity.price.historical") == "equity_price_historical"


def test_model_name_for_camelcases_dotted_path():
    assert rg._model_name_for("equity.price.historical") == "EquityPriceHistorical"
    assert rg._model_name_for("equity.search") == "EquitySearch"
    assert rg._model_name_for("commodity.psd_report") == "CommodityPsdReport"


# --- _format_docstring ---


def test_format_docstring_single_line_appends_period():
    out = rg._format_docstring("Get historical data")
    assert out == '    """Get historical data."""'


def test_format_docstring_blank_text_renders_period_only():
    out = rg._format_docstring("   ")
    assert out == '    """."""'


def test_format_docstring_keeps_existing_terminator():
    out = rg._format_docstring("What is X?")
    assert out == '    """What is X?"""'


def test_format_docstring_multiline_uses_block_layout():
    out = rg._format_docstring("First line.\nSecond line.\n\nThird line.")
    assert out.startswith('    """First line.')
    assert out.endswith('    """')
    # Continuation lines are indented to four spaces; blank lines stay blank.
    assert "\n    Second line." in out
    assert "\n    Third line." in out


# --- generate_routers (full pipeline) ---


def test_generate_routers_emits_top_router_with_get_command():
    tree = nt.build_namespace_tree(
        {"equity.search": {"providers": ["fmp"], "description": "Search equities"}}
    )
    fetchers = {
        "equity.search": _Fetcher(
            module_name="equity_search",
            fetcher_class="EquitySearchFetcher",
            model_name="EquitySearch",
        )
    }
    out = rg.generate_routers(
        tree,
        package_name="openbb_codegen",
        provider_name="fmp",
        fetchers_by_command=fetchers,
        post_commands_by_command={},
    )

    assert isinstance(out, rg.GeneratedRouters)
    assert len(out.routers) == 1
    router = out.routers[0]
    assert router.module_name == "equity"
    assert router.entry_point_name == "equity"

    src = router.source
    assert 'router = Router(prefix="")' in src
    assert '@router.command(model="EquitySearch")' in src
    assert "async def search(" in src
    assert '"""Search equities."""' in src
    # Module parses
    ast.parse(src)


def test_generate_routers_emits_stream_command_for_streaming_fetcher():
    tree = nt.build_namespace_tree(
        {"crypto.feed": {"providers": ["wargame"], "description": "Live feed"}}
    )
    fetchers = {
        "crypto.feed": _Fetcher(
            module_name="crypto_feed",
            fetcher_class="CryptoFeedFetcher",
            model_name="CryptoFeed",
            is_streaming=True,
        )
    }
    out = rg.generate_routers(
        tree,
        package_name="openbb_codegen",
        provider_name="wargame",
        fetchers_by_command=fetchers,
        post_commands_by_command={},
    )

    src = out.routers[0].source
    assert "from openbb_core.app.model.stream import OBBStream" in src
    assert '@router.command(model="CryptoFeed")' in src
    assert "OBBStream" in src
    ast.parse(src)


def test_generate_routers_nests_sub_routers_via_include_router():
    tree = nt.build_namespace_tree(
        {
            "equity.price.historical": {
                "providers": ["fmp"],
                "description": "OHLCV.",
            }
        }
    )
    fetchers = {
        "equity.price.historical": _Fetcher(
            module_name="equity_price_historical",
            fetcher_class="EquityPriceHistoricalFetcher",
            model_name="EquityPriceHistorical",
        )
    }
    out = rg.generate_routers(
        tree,
        package_name="openbb_codegen",
        provider_name="fmp",
        fetchers_by_command=fetchers,
        post_commands_by_command={},
    )

    by_module = {r.module_name: r for r in out.routers}
    # Both top-level (equity) and nested (equity_price) modules emitted
    assert {"equity", "equity_price"} <= set(by_module)
    # Only the top-level router gets an entry point
    assert by_module["equity"].entry_point_name == "equity"
    assert by_module["equity_price"].entry_point_name is None
    # Top-level router includes the nested one with the correct prefix
    assert (
        "from openbb_codegen.routers.equity_price import router as _price_router"
        in by_module["equity"].source
    )
    assert (
        'router.include_router(_price_router, prefix="/price")'
        in by_module["equity"].source
    )
    # The nested router defines the actual command
    assert "async def historical(" in by_module["equity_price"].source


def test_generate_routers_emits_post_command_re_decoration():
    tree = nt.build_namespace_tree(
        {"econometrics.regression": {"providers": [], "description": "Linear fit."}}
    )
    posts = {
        "econometrics.regression": _PostCommand(
            module_name="econometrics_regression",
            function_name="regression",
        )
    }
    out = rg.generate_routers(
        tree,
        package_name="openbb_codegen",
        provider_name="tools",
        fetchers_by_command={},
        post_commands_by_command=posts,
    )

    src = out.routers[0].source
    assert (
        "from openbb_codegen.providers.tools.models.econometrics_regression "
        "import regression as _regression"
    ) in src
    assert 'router.command(methods=["POST"])(_regression)' in src
    ast.parse(src)


def test_generate_routers_falls_back_to_model_name_when_description_missing():
    tree = nt.build_namespace_tree(
        {"equity.search": {"providers": ["fmp"]}},  # no description
    )
    fetchers = {
        "equity.search": _Fetcher(
            module_name="equity_search",
            fetcher_class="EquitySearchFetcher",
            model_name="EquitySearch",
        )
    }
    out = rg.generate_routers(
        tree,
        package_name="openbb_codegen",
        provider_name="fmp",
        fetchers_by_command=fetchers,
        post_commands_by_command={},
    )
    assert '"""EquitySearch command."""' in out.routers[0].source


def test_generate_routers_skips_command_without_matching_fetcher_or_post():
    tree = nt.build_namespace_tree(
        {"equity.search": {"providers": ["fmp"], "description": "Search."}}
    )
    out = rg.generate_routers(
        tree,
        package_name="openbb_codegen",
        provider_name="fmp",
        fetchers_by_command={},  # no fetcher registered
        post_commands_by_command={},  # no post command either
    )
    src = out.routers[0].source
    # No command body emitted; only the router declaration remains
    assert "async def" not in src
    assert "router.command" not in src
    ast.parse(src)


# --- top-level leaf commands land on the root router ---


def test_generate_routers_top_level_command_becomes_root_command():
    tree = nt.build_namespace_tree(
        {"eod": {"providers": ["eodhd"], "description": "End of day."}}
    )
    fetchers = {
        "eod": _Fetcher(
            module_name="eod",
            fetcher_class="EodFetcher",
            model_name="Eod",
        )
    }
    out = rg.generate_routers(
        tree,
        package_name="openbb_codegen",
        provider_name="eodhd",
        fetchers_by_command=fetchers,
        post_commands_by_command={},
    )
    # No dedicated router module for a pure top-level command
    assert out.routers == []
    assert len(out.root_commands) == 1
    block = out.root_commands[0]
    assert '@router.command(model="Eod")' in block
    assert "async def eod(" in block
    assert out.root_has_stream is False


def test_generate_routers_top_level_stream_command_sets_flag():
    tree = nt.build_namespace_tree(
        {"feed": {"providers": ["wargame"], "description": "Live feed."}}
    )
    fetchers = {
        "feed": _Fetcher(
            module_name="feed",
            fetcher_class="FeedFetcher",
            model_name="Feed",
            is_streaming=True,
        )
    }
    out = rg.generate_routers(
        tree,
        package_name="openbb_codegen",
        provider_name="wargame",
        fetchers_by_command=fetchers,
        post_commands_by_command={},
    )
    assert out.root_has_stream is True
    assert "OBBStream" in out.root_commands[0]


def test_generate_routers_top_level_post_command_records_import():
    tree = nt.build_namespace_tree(
        {"regression": {"providers": [], "description": "Linear fit."}}
    )
    posts = {
        "regression": _PostCommand(
            module_name="regression",
            function_name="regression",
        )
    }
    out = rg.generate_routers(
        tree,
        package_name="openbb_codegen",
        provider_name="tools",
        fetchers_by_command={},
        post_commands_by_command=posts,
    )
    assert out.root_post_imports == [
        ("openbb_codegen.providers.tools.models.regression", "regression")
    ]
    assert 'router.command(methods=["POST"])(_regression)' in out.root_commands[0]


def test_generate_routers_top_level_command_without_fetcher_is_dropped():
    tree = nt.build_namespace_tree(
        {"orphan": {"providers": ["fmp"], "description": "No fetcher."}}
    )
    out = rg.generate_routers(
        tree,
        package_name="openbb_codegen",
        provider_name="fmp",
        fetchers_by_command={},
        post_commands_by_command={},
    )
    assert out.routers == []
    assert out.root_commands == []


def test_generate_routers_mixes_namespaces_and_root_commands():
    tree = nt.build_namespace_tree(
        {
            "eod": {"providers": ["eodhd"], "description": "End of day."},
            "calendar.ipos": {"providers": ["eodhd"], "description": "IPOs."},
        }
    )
    fetchers = {
        "eod": _Fetcher(
            module_name="eod", fetcher_class="EodFetcher", model_name="Eod"
        ),
        "calendar.ipos": _Fetcher(
            module_name="calendar_ipos",
            fetcher_class="CalendarIposFetcher",
            model_name="CalendarIpos",
        ),
    }
    out = rg.generate_routers(
        tree,
        package_name="openbb_codegen",
        provider_name="eodhd",
        fetchers_by_command=fetchers,
        post_commands_by_command={},
    )
    assert [r.module_name for r in out.routers] == ["calendar"]
    assert "async def ipos(" in out.routers[0].source
    assert len(out.root_commands) == 1
    assert "async def eod(" in out.root_commands[0]


def test_generate_routers_command_that_is_also_a_namespace_lives_in_its_own_router():
    """``/alerts`` (command) with ``/alerts/active`` (child) must not shadow the namespace."""
    tree = nt.build_namespace_tree(
        {
            "alerts": {"providers": ["wx"], "description": "A specific alert."},
            "alerts.active": {"providers": ["wx"], "description": "Active."},
            "alerts.active.count": {"providers": ["wx"], "description": "Count."},
        }
    )
    fetchers = {
        path: _Fetcher(
            module_name=path.replace(".", "_"),
            fetcher_class="F",
            model_name=rg._model_name_for(path),
        )
        for path in ("alerts", "alerts.active", "alerts.active.count")
    }
    out = rg.generate_routers(
        tree,
        package_name="pkg",
        provider_name="wx",
        fetchers_by_command=fetchers,
        post_commands_by_command={},
    )

    by_module = {r.module_name: r for r in out.routers}
    # Not mounted on the root router, where it would shadow ``alerts``.
    assert out.root_commands == []
    # Mounted on its own namespace router alongside the sub-router include.
    assert 'model="Alerts")' in by_module["alerts"].source
    assert "async def alerts(" in by_module["alerts"].source
    assert (
        'include_router(_active_router, prefix="/active")' in by_module["alerts"].source
    )
    # Nested namespace+command follows the same rule and no longer collides with its include.
    assert "async def active(" not in by_module["alerts"].source
    assert "async def active(" in by_module["alerts_active"].source
    assert "async def count(" in by_module["alerts_active"].source
    for r in out.routers:
        ast.parse(r.source)


def test_safe_segment_prefixes_digits_and_suffixes_keywords():
    assert rg._safe_segment("24hr") == "_24hr"
    assert rg._safe_segment("class") == "class_"
    assert rg._safe_segment("Return") == "return_"


def test_generate_routers_digit_and_keyword_commands_are_valid_python():
    tree = nt.build_namespace_tree(
        {
            "ticker.24hr": {"providers": ["fmp"], "description": "24h stats"},
            "ticker.class": {"providers": ["fmp"], "description": "Class"},
            "24hr": {"providers": ["fmp"], "description": "Root 24h"},
        }
    )
    fetchers = {
        key: _Fetcher(
            module_name=key.replace(".", "_"),
            fetcher_class="F",
            model_name="M",
        )
        for key in ("ticker.24hr", "ticker.class", "24hr")
    }
    out = rg.generate_routers(
        tree,
        package_name="openbb_codegen",
        provider_name="fmp",
        fetchers_by_command=fetchers,
        post_commands_by_command={},
    )
    assert out.routers
    for router in out.routers:
        ast.parse(router.source)
    for block in out.root_commands:
        ast.parse(block)
    generated = "".join(r.source for r in out.routers) + "".join(out.root_commands)
    assert "async def _24hr(" in generated
    assert "async def class_(" in generated
