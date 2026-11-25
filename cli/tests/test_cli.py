"""Tests for openbb_cli.cli — entry-point routing and end-to-end dispatch.

End-to-end tests drive ``cli.main`` against the real generated ``obb``
namespace via ``run_in_obb``; routing-only tests still inject test doubles
at the dispatcher boundary because routing is independent of obb.
"""

import json
from unittest.mock import MagicMock, patch

from openbb_cli import cli


def test_build_dispatcher_local_when_no_server():
    with patch("openbb_cli.dispatchers.LocalDispatcher") as ld:
        ld.return_value = MagicMock(name="local")
        d = cli._build_dispatcher(None)
    assert d is ld.return_value


def test_build_dispatcher_http_when_server():
    """``--server URL`` builds via ``http_dispatcher_from_server`` (which fetches openapi)."""
    with patch("openbb_cli.dispatchers.http.http_dispatcher_from_server") as factory:
        factory.return_value = MagicMock(name="http")
        d = cli._build_dispatcher("http://api.local")
    factory.assert_called_once_with(
        "http://api.local", headers=None, query_params=None, auth_hook=None
    )
    assert d is factory.return_value


def test_main_dispatches_one_shot_when_command_given():
    with (
        patch("openbb_cli.cli._build_dispatcher") as bd,
        patch("openbb_cli.dispatchers.runtime.run_argv", return_value=0) as ra,
        patch("openbb_cli.dispatchers.runtime.run_batch") as rb,
    ):
        # Local backend has no _spec_doc attribute, so main() falls through
        # to run_argv instead of the spec-aware dispatch path.
        dispatcher = MagicMock(name="dispatcher", spec=["dispatch", "aclose"])
        bd.return_value = dispatcher
        rc = cli.main(["economy.gdp", "--provider=oecd"])
    assert rc == 0
    ra.assert_called_once()
    rb.assert_not_called()


def test_main_routes_to_batch_when_flag_set():
    with (
        patch("openbb_cli.cli._build_dispatcher") as bd,
        patch("openbb_cli.dispatchers.runtime.run_batch", return_value=0) as rb,
        patch("openbb_cli.dispatchers.runtime.run_argv") as ra,
    ):
        bd.return_value = MagicMock(name="dispatcher")
        rc = cli.main(["--batch"])
    assert rc == 0
    rb.assert_called_once()
    ra.assert_not_called()


def test_main_launches_repl_when_interactive():
    with patch("openbb_cli.cli._launch_repl", return_value=0) as repl:
        rc = cli.main(["-i"])
    assert rc == 0
    repl.assert_called_once()


def test_main_help_exit_when_no_command(capsys):
    """Default mode with no positional command exits with code 2."""
    with patch("openbb_cli.cli._build_dispatcher") as bd:
        bd.return_value = MagicMock(name="dispatcher")
        rc = cli.main([])
    assert rc == 2
    err = capsys.readouterr().err
    assert "usage" in err.lower()


def test_main_generate_spec_accepts_positional_output_path():
    """``openbb --server X --generate-spec out.spec`` (no --output) writes to ``out.spec``."""
    with patch("openbb_cli.cli._generate_spec", return_value=0) as gen:
        rc = cli.main(["--server", "http://x", "--generate-spec", "/tmp/out.spec"])
    assert rc == 0
    args, _ = gen.call_args
    assert args[1] == "/tmp/out.spec"


def test_main_generate_spec_uses_explicit_output_flag():
    """``--output`` is honored when no positional output path is supplied."""
    with patch("openbb_cli.cli._generate_spec", return_value=0) as gen:
        cli.main(
            ["--server", "http://x", "--generate-spec", "--output", "/explicit.spec"]
        )
    args, _ = gen.call_args
    assert args[1] == "/explicit.spec"


def test_main_generate_spec_errors_when_positional_added_to_explicit_output(capsys):
    """``--output`` already-set + a positional path -> error, no silent override."""
    with patch("openbb_cli.cli._generate_spec") as gen:
        rc = cli.main(
            [
                "--server",
                "http://x",
                "--generate-spec",
                "--output",
                "/explicit.spec",
                "/extra.spec",
            ]
        )
    assert rc == 2
    gen.assert_not_called()
    err = capsys.readouterr().err
    assert "no extra positional" in err
    assert "/extra.spec" in err


def test_main_generate_spec_errors_on_extra_positionals(capsys):
    """Anything beyond a single positional output path triggers a clean error."""
    with patch("openbb_cli.cli._generate_spec") as gen:
        rc = cli.main(
            ["--server", "http://x", "--generate-spec", "/tmp/a.spec", "/tmp/b.spec"]
        )
    assert rc == 2
    gen.assert_not_called()
    err = capsys.readouterr().err
    assert "no extra positional" in err
    assert "/tmp/b.spec" in err


def test_main_socrata_story_materializes_spec_for_interactive_mode(tmp_path):
    """``-i --socrata-story <url>`` materializes the spec to a temp file
    and feeds it to the REPL as an unnamed ``--spec`` entry — same UX as
    pre-generating with ``--generate-spec`` and then loading."""
    materialized = tmp_path / "stub.spec"
    materialized.write_text("{}")
    with (
        patch(
            "openbb_cli.cli._materialize_socrata_spec",
            return_value=str(materialized),
        ) as mat,
        patch("openbb_cli.cli._launch_repl", return_value=0) as repl,
    ):
        rc = cli.main(["-i", "--socrata-story", "https://x/stories/s/abcd-1234"])
    assert rc == 0
    mat.assert_called_once_with("https://x/stories/s/abcd-1234")
    # spec_entries (3rd positional arg to _launch_repl) carries the
    # materialized spec as a single unnamed entry.
    args, _ = repl.call_args
    assert args[2] == [(None, str(materialized))]


def test_main_socrata_story_appends_named_entry_when_other_specs_present(tmp_path):
    """Mixed with other ``--spec`` entries, the socrata one becomes a
    named entry (``socrata``) so the resolver doesn't reject the mix of
    unnamed + named."""
    materialized = tmp_path / "stub.spec"
    materialized.write_text("{}")
    with (
        patch(
            "openbb_cli.cli._materialize_socrata_spec",
            return_value=str(materialized),
        ),
        patch("openbb_cli.cli._launch_repl", return_value=0) as repl,
    ):
        cli.main(
            [
                "-i",
                "--spec",
                "other=/tmp/other.spec",
                "--socrata-story",
                "https://x/stories/s/abcd-1234",
            ]
        )
    args, _ = repl.call_args
    assert args[2] == [
        ("other", "/tmp/other.spec"),
        ("socrata", str(materialized)),
    ]


def test_main_socrata_story_passes_through_to_generate_spec_when_set(capsys):
    """``--generate-spec --socrata-story`` keeps the file-output behavior;
    the in-memory materialization branch is skipped."""
    with (
        patch("openbb_cli.cli._generate_spec", return_value=0) as gen,
        patch("openbb_cli.cli._materialize_socrata_spec") as mat,
    ):
        rc = cli.main(
            [
                "--generate-spec",
                "--socrata-story",
                "https://x/stories/s/abcd-1234",
                "--output",
                "/tmp/out.spec",
            ]
        )
    assert rc == 0
    # File-mode generation path used; in-memory materializer not invoked.
    mat.assert_not_called()
    _args, kwargs = gen.call_args
    assert kwargs["socrata_story"] == "https://x/stories/s/abcd-1234"


def test_main_socrata_story_surfaces_materialization_errors(capsys):
    """A network / parse failure from ``_materialize_socrata_spec`` exits
    with a clean ``--socrata-story`` error message."""
    with patch(
        "openbb_cli.cli._materialize_socrata_spec",
        side_effect=OSError("DNS failed"),
    ):
        rc = cli.main(["-i", "--socrata-story", "https://nope/stories/s/x-y"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--socrata-story" in err
    assert "DNS failed" in err


def test_main_passes_dev_debug_to_repl():
    with patch("openbb_cli.cli._launch_repl", return_value=0) as repl:
        cli.main(["-i", "--dev", "--debug"])
    # Positional args: dev, debug, spec_entries, server, headers, query_params,
    # per_ns_headers, per_ns_query — followed by keyword global/per-ns hooks
    # and initial_command. spec_entries is an empty list when no --spec given.
    repl.assert_called_once_with(
        True,
        True,
        [],
        None,
        None,
        None,
        {},
        {},
        global_auth_hook=None,
        per_ns_auth_hooks={},
        initial_command=[],
    )


def test_launch_repl_calls_run_cli_with_no_queue_when_no_initial_command(capsys):
    """``openbb -i`` (no extra args) goes straight to ``run_cli(None, backend=None)``,
    bypassing the legacy ``parse_args_and_run`` argv re-parser that would
    otherwise reject our outer ``-i`` flag with a usage error."""
    with (
        patch("openbb_cli.config.setup.bootstrap") as bs,
        patch("openbb_cli.controllers.cli_controller.run_cli") as run_cli_,
    ):
        rc = cli._launch_repl(False, False)
    assert rc == 0
    assert "Loading..." in capsys.readouterr().out
    bs.assert_called_once()
    run_cli_.assert_called_once_with(None, backend=None)


def test_launch_repl_forwards_initial_command_to_run_cli():
    """``openbb -i bill actions --congress 117`` enqueues the joined command
    so the REPL runs it before prompting."""
    with (
        patch("openbb_cli.config.setup.bootstrap"),
        patch("openbb_cli.controllers.cli_controller.run_cli") as run_cli_,
    ):
        cli._launch_repl(
            False, False, initial_command=["bill", "actions", "--congress", "117"]
        )
    run_cli_.assert_called_once_with(["bill actions --congress 117"], backend=None)


def test_launch_repl_forces_rich_interactive_defaults():
    """Even if the user's env file left ``OPENBB_TEST_MODE=True`` or
    ``OUTPUT_MODE=tsv``, ``-i`` flips them so colors render and the
    interactive DataFrame viewer is enabled."""
    from openbb_cli.controllers.cli_controller import session

    session.settings.OUTPUT_MODE = "tsv"
    session.settings.USE_INTERACTIVE_DF = False
    session.settings.TEST_MODE = True

    with (
        patch("openbb_cli.config.setup.bootstrap"),
        patch("openbb_cli.controllers.cli_controller.run_cli"),
    ):
        cli._launch_repl(False, False)

    assert session.settings.OUTPUT_MODE == "rich"
    assert session.settings.USE_INTERACTIVE_DF is True
    assert session.settings.TEST_MODE is False


def test_apply_interactive_defaults_overrides_each_field():
    """Direct unit test for the helper, independent of the REPL launch path."""
    from types import SimpleNamespace

    settings = SimpleNamespace(
        OUTPUT_MODE="tsv", USE_INTERACTIVE_DF=False, TEST_MODE=True
    )
    cli._apply_interactive_defaults(settings)
    assert settings.OUTPUT_MODE == "rich"
    assert settings.USE_INTERACTIVE_DF is True
    assert settings.TEST_MODE is False


def test_parse_header_kv_equals_form():
    from openbb_cli.cli import _parse_header_kv

    assert _parse_header_kv("X-API-Key=abc123") == ("X-API-Key", "abc123")


def test_parse_header_kv_colon_form():
    from openbb_cli.cli import _parse_header_kv

    assert _parse_header_kv("Authorization: Bearer xyz") == (
        "Authorization",
        "Bearer xyz",
    )


def test_parse_header_kv_equals_wins_when_first():
    """``KEY=VALUE: with embedded colon`` keeps the colon in the value."""
    from openbb_cli.cli import _parse_header_kv

    assert _parse_header_kv("X-Trace=foo:bar:baz") == ("X-Trace", "foo:bar:baz")


def test_parse_header_kv_colon_wins_when_first():
    """``KEY: VALUE with embedded =`` keeps the equals in the value."""
    from openbb_cli.cli import _parse_header_kv

    assert _parse_header_kv("Authorization: Bearer x=y=z") == (
        "Authorization",
        "Bearer x=y=z",
    )


def test_parse_header_kv_rejects_no_separator():
    import pytest

    from openbb_cli.cli import _parse_header_kv

    with pytest.raises(ValueError, match="must be"):
        _parse_header_kv("nokeyvalue")


def test_resolve_headers_merges_file_and_cli(tmp_path):
    from openbb_cli.cli import _resolve_headers

    header_file = tmp_path / "h.json"
    header_file.write_text('{"X-API-Key": "from-file", "X-Tenant": "shared"}')
    out = _resolve_headers(["X-API-Key=from-cli", "X-Trace=tid"], str(header_file))
    assert out == {
        "X-API-Key": "from-cli",
        "X-Tenant": "shared",
        "X-Trace": "tid",
    }


def test_resolve_headers_returns_none_when_empty():
    from openbb_cli.cli import _resolve_headers

    assert _resolve_headers([], None) is None
    assert _resolve_headers(None, None) is None


def test_resolve_headers_rejects_non_object_file(tmp_path, capsys):
    from openbb_cli.cli import _resolve_headers

    bad = tmp_path / "h.json"
    bad.write_text("[1, 2]")
    out = _resolve_headers([], str(bad))
    assert out is None
    err = capsys.readouterr().err
    assert "must contain a JSON object" in err


def test_resolve_headers_rejects_invalid_json(tmp_path, capsys):
    from openbb_cli.cli import _resolve_headers

    bad = tmp_path / "h.json"
    bad.write_text("not-json")
    assert _resolve_headers([], str(bad)) is None
    assert "Expecting" in capsys.readouterr().err


def test_main_threads_headers_to_one_shot(tmp_path):
    """``-H KEY=VALUE`` flows from main into ``_run_spec_one_shot``."""
    import json

    from openbb_cli.dispatchers.spec import SPEC_VERSION

    spec_file = tmp_path / "h.spec"
    spec_file.write_text(
        json.dumps(
            {
                "version": SPEC_VERSION,
                "base_url": "http://h",
                "api_prefix": "/api",
                "commands": {},
                "routers": {},
                "reference": {"paths": {}, "routers": {}},
            }
        )
    )
    with patch("openbb_cli.cli._run_spec_one_shot", return_value=0) as one_shot:
        cli.main(
            [
                "--spec",
                str(spec_file),
                "-H",
                "Authorization: Bearer xyz",
                "fxs.list.counterparties",
                "--format",
                "json",
            ]
        )
    one_shot.assert_called_once()
    args = one_shot.call_args.args
    # spec_entries is now [(name, path)] — single unnamed → [(None, str(path))]
    assert args[0] == [(None, str(spec_file))]
    assert args[1] == [
        "fxs.list.counterparties",
        "--format",
        "json",
    ]
    assert args[2] == {"Authorization": "Bearer xyz"}


def test_launch_repl_with_spec_uses_spec_backend(tmp_path):
    """``--spec PATH`` builds a ``SpecBackend`` and threads it into ``run_cli``."""
    import json

    from openbb_cli.dispatchers.spec import SPEC_VERSION

    spec_file = tmp_path / "fake.spec"
    spec_file.write_text(
        json.dumps(
            {
                "version": SPEC_VERSION,
                "base_url": "http://h",
                "api_prefix": "/api",
                "commands": {},
                "routers": {},
                "reference": {"paths": {}, "routers": {}},
            }
        )
    )
    with (
        patch("openbb_cli.config.setup.bootstrap"),
        patch("openbb_cli.controllers.cli_controller.run_cli") as run_cli_,
    ):
        cli._launch_repl(False, False, [(None, str(spec_file))], None)
    backend_arg = run_cli_.call_args[1]["backend"]
    assert backend_arg is not None
    assert backend_arg.routers == {}


def test_e2e_dispatches_real_command_to_stdout(run_in_obb):
    """``openbb cli_test.echo --value=hello`` resolves through real obb."""
    result = run_in_obb("""
        import io, sys
        from openbb_cli.cli import main

        captured = io.StringIO()
        sys.stdout = captured
        try:
            rc = main(["cli_test.echo", "--value=hello"])
        finally:
            sys.stdout = sys.__stdout__
        RESULT = {"rc": rc, "out": captured.getvalue()}
    """)
    assert result["rc"] == 0
    payload = json.loads(result["out"].strip())
    assert payload["ok"] is True
    assert payload["result"]["results"] == {"echo": "hello"}


def test_e2e_dispatch_failure_returns_nonzero(run_in_obb):
    """``openbb cli_test.bomb`` returns rc=1 with structured error in stdout."""
    result = run_in_obb("""
        import io, sys
        from openbb_cli.cli import main

        captured = io.StringIO()
        sys.stdout = captured
        try:
            rc = main(["cli_test.bomb"])
        finally:
            sys.stdout = sys.__stdout__
        RESULT = {"rc": rc, "out": captured.getvalue()}
    """)
    assert result["rc"] == 1
    payload = json.loads(result["out"].strip())
    assert payload["ok"] is False
    assert payload["error"]["type"] == "OpenBBError"


def test_e2e_batch_protocol_round_trip(run_in_obb):
    """NDJSON in → NDJSON out across multiple commands."""
    result = run_in_obb("""
        import io, json, sys
        from openbb_cli.dispatchers import LocalDispatcher
        from openbb_cli.dispatchers.runtime import run_batch

        reader = io.StringIO(
            json.dumps({"id": "a", "command": "cli_test.echo", "params": {"value": "x"}})
            + "\\n"
            + json.dumps({"id": "b", "command": "cli_test.bomb"})
            + "\\n"
        )
        writer = io.StringIO()
        rc = run_batch(LocalDispatcher(), reader=reader, writer=writer, concurrency=2)
        RESULT = {"rc": rc, "lines": [
            json.loads(line) for line in writer.getvalue().splitlines() if line
        ]}
    """)
    assert result["rc"] == 1
    by_id = {line["id"]: line for line in result["lines"]}
    assert by_id["a"]["ok"] is True
    assert by_id["a"]["result"]["results"] == {"echo": "x"}
    assert by_id["b"]["ok"] is False
    assert by_id["b"]["error"]["type"] == "OpenBBError"


# --- Multi-spec resolution ---


def test_parse_spec_arg_named():
    assert cli._parse_spec_arg("congress=path.spec") == ("congress", "path.spec")


def test_parse_spec_arg_unnamed():
    assert cli._parse_spec_arg("path.spec") == (None, "path.spec")


def test_parse_spec_arg_strips_whitespace():
    assert cli._parse_spec_arg("  congress = path.spec  ") == ("congress", "path.spec")


def test_parse_spec_arg_rejects_empty_name():
    import pytest

    with pytest.raises(ValueError, match="malformed"):
        cli._parse_spec_arg("=path")


def test_parse_spec_arg_rejects_empty_path():
    import pytest

    with pytest.raises(ValueError, match="malformed"):
        cli._parse_spec_arg("name=")


def test_resolve_spec_entries_cli_overrides_config(monkeypatch):
    monkeypatch.delenv("OPENBB_SPEC_PATH", raising=False)
    out = cli._resolve_spec_entries(
        ["a=foo.spec"],
        config_specs={"b": {"path": "bar.spec"}},
    )
    assert out == [("a", "foo.spec")]


def test_resolve_spec_entries_uses_toml_specs_table_when_no_cli(monkeypatch):
    monkeypatch.delenv("OPENBB_SPEC_PATH", raising=False)
    out = cli._resolve_spec_entries(
        [],
        config_specs={"alpha": {"path": "a"}, "beta": "b"},
    )
    assert sorted(out) == [("alpha", "a"), ("beta", "b")]


def test_resolve_spec_entries_falls_back_to_legacy_single_spec(monkeypatch):
    monkeypatch.delenv("OPENBB_SPEC_PATH", raising=False)
    out = cli._resolve_spec_entries(
        [], config_specs=None, config_single_spec="legacy.spec"
    )
    assert out == [(None, "legacy.spec")]


def test_resolve_spec_entries_env_var_last_resort(monkeypatch):
    monkeypatch.setenv("OPENBB_SPEC_PATH", "env.spec")
    out = cli._resolve_spec_entries([], config_specs=None)
    assert out == [(None, "env.spec")]


def test_resolve_spec_entries_returns_empty_when_no_source(monkeypatch):
    monkeypatch.delenv("OPENBB_SPEC_PATH", raising=False)
    assert cli._resolve_spec_entries([], config_specs=None) == []


def test_resolve_spec_entries_rejects_missing_path_key():
    import pytest

    with pytest.raises(ValueError, match="missing required 'path'"):
        cli._resolve_spec_entries([], config_specs={"x": {"headers": {}}})


def test_resolve_spec_entries_rejects_mixed_named_and_unnamed():
    import pytest

    with pytest.raises(ValueError, match="every one must be NAME=PATH"):
        cli._resolve_spec_entries(["bare.spec", "named=other.spec"], config_specs=None)


# --- Per-namespace token splitting ---


def test_split_scoped_token_recognizes_declared_namespace():
    assert cli._split_scoped_token("congress:Authorization=Bearer x", {"congress"}) == (
        "congress",
        "Authorization=Bearer x",
    )


def test_split_scoped_token_returns_global_for_undeclared_prefix():
    """``Authorization: Bearer xxx`` must NOT be misread as a namespace prefix."""
    assert cli._split_scoped_token(
        "Authorization: Bearer xxx", {"congress", "nyfed"}
    ) == (None, "Authorization: Bearer xxx")


def test_split_scoped_token_handles_no_colon():
    assert cli._split_scoped_token("KEY=VAL", {"ns"}) == (None, "KEY=VAL")


def test_split_per_namespace_partitions_correctly():
    global_, per_ns = cli._split_per_namespace(
        [
            "Authorization=global",
            "congress:api_key=cg",
            "nyfed:X-Header=nf",
            "another_global=x",
        ],
        {"congress", "nyfed"},
    )
    assert global_ == ["Authorization=global", "another_global=x"]
    assert per_ns["congress"] == ["api_key=cg"]
    assert per_ns["nyfed"] == ["X-Header=nf"]


def test_merge_dicts_right_biased():
    out = cli._merge_dicts({"a": "1", "b": "2"}, {"b": "X", "c": "3"})
    assert out == {"a": "1", "b": "X", "c": "3"}


def test_merge_dicts_returns_none_when_all_empty():
    assert cli._merge_dicts(None, None) is None
    assert cli._merge_dicts({}, None) is None


# --- Per-namespace auth resolver ---


def test_resolve_per_ns_auth_merges_toml_and_cli_tokens():
    per_h, per_q = cli._resolve_per_ns_auth(
        per_ns_h_tokens={"congress": ["Authorization=cli-bearer"]},
        per_ns_q_tokens={"congress": ["api_key=cli-key"]},
        namespaces={"congress"},
        config_specs={
            "congress": {
                "headers": {"X-Tenant": "toml-tenant"},
                "query": {"format": "json"},
            }
        },
    )
    assert per_h == {
        "congress": {"X-Tenant": "toml-tenant", "Authorization": "cli-bearer"}
    }
    assert per_q == {"congress": {"format": "json", "api_key": "cli-key"}}


def test_resolve_per_ns_auth_rejects_malformed_query_token(capsys):
    per_h, per_q = cli._resolve_per_ns_auth(
        per_ns_h_tokens={},
        per_ns_q_tokens={"congress": ["no_equals_here"]},
        namespaces={"congress"},
        config_specs=None,
    )
    assert per_h is None and per_q is None
    err = capsys.readouterr().err
    assert "must be 'KEY=VALUE'" in err


# --- Auth-hook resolver ---


def test_resolve_auth_hooks_loads_global_and_per_ns(monkeypatch):
    import sys
    import types

    mod = types.ModuleType("openbb_cli_test_hooks_mod")

    def global_hook(ctx):
        return None

    def congress_hook(ctx):
        return None

    mod.global_hook = global_hook
    mod.congress_hook = congress_hook
    monkeypatch.setitem(sys.modules, "openbb_cli_test_hooks_mod", mod)

    config = {
        "auth-hook": "openbb_cli_test_hooks_mod:global_hook",
        "specs": {
            "congress": {
                "path": "/x.spec",
                "auth-hook": "openbb_cli_test_hooks_mod:congress_hook",
            },
            "nyfed": {"path": "/y.spec"},  # no per-ns hook → global applies
        },
    }
    g, per_ns = cli._resolve_auth_hooks(config, namespaces={"congress", "nyfed"})
    assert g is global_hook
    assert per_ns == {"congress": congress_hook}


def test_resolve_auth_hooks_returns_none_when_unconfigured():
    g, per_ns = cli._resolve_auth_hooks({}, namespaces=set())
    assert g is None
    assert per_ns == {}


def test_resolve_auth_hooks_underscore_alias_works(monkeypatch):
    """Both ``auth-hook`` and ``auth_hook`` keys are honored."""
    import sys
    import types

    mod = types.ModuleType("openbb_cli_test_hooks_underscore")

    def hook(ctx):
        return None

    mod.hook = hook
    monkeypatch.setitem(sys.modules, "openbb_cli_test_hooks_underscore", mod)
    g, _ = cli._resolve_auth_hooks(
        {"auth_hook": "openbb_cli_test_hooks_underscore:hook"}, namespaces=set()
    )
    assert g is hook


# --- Multi-spec dispatcher building ---


def test_build_spec_dispatcher_single_unnamed_returns_http_dispatcher(tmp_path):
    """Backward compat: one unnamed spec → flat HttpDispatcher, no namespacing."""
    from openbb_cli.dispatchers.http import HttpDispatcher
    from openbb_cli.dispatchers.spec import SPEC_VERSION, write_spec

    spec_path = tmp_path / "single.spec"
    write_spec(
        spec_path,
        {
            "version": SPEC_VERSION,
            "base_url": "http://upstream",
            "api_prefix": "/api/v1",
            "commands": {"x": {"url_path": "/api/v1/x", "method": "get"}},
        },
    )
    d = cli._build_spec_dispatcher([(None, str(spec_path))], None, None)
    assert isinstance(d, HttpDispatcher)


def test_build_spec_dispatcher_multi_returns_multi_spec(tmp_path):
    """Multiple named specs → MultiSpecDispatcher with per-namespace HTTP dispatchers."""
    from openbb_cli.dispatchers.multi import MultiSpecDispatcher
    from openbb_cli.dispatchers.spec import SPEC_VERSION, write_spec

    a = tmp_path / "a.spec"
    b = tmp_path / "b.spec"
    for path in (a, b):
        write_spec(
            path,
            {
                "version": SPEC_VERSION,
                "base_url": "http://x",
                "api_prefix": "/api/v1",
                "commands": {"foo": {"url_path": "/api/v1/foo", "method": "get"}},
            },
        )
    d = cli._build_spec_dispatcher([("alpha", str(a)), ("beta", str(b))], None, None)
    assert isinstance(d, MultiSpecDispatcher)
    assert set(d._dispatchers) == {"alpha", "beta"}


def test_build_spec_dispatcher_passes_per_ns_auth(tmp_path):
    """Per-namespace headers/query and hooks land on the matching dispatcher."""
    from openbb_cli.dispatchers.spec import SPEC_VERSION, write_spec

    spec = tmp_path / "x.spec"
    write_spec(
        spec,
        {
            "version": SPEC_VERSION,
            "base_url": "http://x",
            "api_prefix": "/api/v1",
            "commands": {"foo": {"url_path": "/api/v1/foo", "method": "get"}},
        },
    )

    def hook_a(ctx):
        return None

    def hook_b(ctx):
        return None

    d = cli._build_spec_dispatcher(
        [("a", str(spec)), ("b", str(spec))],
        headers={"X-Global": "g"},
        query_params={"q": "g"},
        per_ns_headers={"a": {"X-A": "a"}},
        per_ns_query={"b": {"qb": "v"}},
        global_auth_hook=hook_a,
        per_ns_auth_hooks={"b": hook_b},
    )
    a = d._dispatchers["a"]
    b = d._dispatchers["b"]
    # Per-ns headers merged with global; namespace passed through
    assert a._headers == {"X-Global": "g", "X-A": "a"}
    assert a._namespace == "a"
    # Per-ns query merged with global on b
    assert b._query_params == {"q": "g", "qb": "v"}
    # Hook overridden per-ns; a falls back to global
    assert a._auth_hook is hook_a
    assert b._auth_hook is hook_b


def test_build_spec_dispatcher_multi_rejects_unnamed_entry(tmp_path):
    """Defensive: passing an unnamed entry into the multi branch is a programmer error."""
    import pytest

    from openbb_cli.dispatchers.spec import SPEC_VERSION, write_spec

    spec = tmp_path / "x.spec"
    write_spec(
        spec,
        {
            "version": SPEC_VERSION,
            "base_url": "http://x",
            "api_prefix": "/api/v1",
            "commands": {},
        },
    )
    with pytest.raises(ValueError, match="missing namespace"):
        cli._build_spec_dispatcher([("a", str(spec)), (None, str(spec))], None, None)


# --- _filter_spec_commands: --include / --exclude ---


def _stub_spec(*names: str) -> dict:
    """Build a minimal spec_doc with the named dotted commands."""
    return {
        "base_url": "http://x",
        "api_prefix": "/api/v1",
        "commands": {n: {"method": "get"} for n in names},
    }


def test_filter_spec_commands_passthrough_when_neither_supplied():
    """Without ``include`` or ``exclude`` the spec is returned untouched."""
    spec = _stub_spec("a.b", "c.d")
    out = cli._filter_spec_commands(spec, include=None, exclude=None)
    assert out is spec


def test_filter_spec_commands_include_keeps_only_matching():
    """``--include 'equity.*'`` keeps every command under the equity
    namespace and drops the rest."""
    spec = _stub_spec(
        "equity.price.historical",
        "equity.fundamentals.balance",
        "fixedincome.rate",
        "shipping.disruptions",
    )
    out = cli._filter_spec_commands(spec, include=["equity.*"], exclude=None)
    kept = sorted(out["commands"])
    assert kept == ["equity.fundamentals.balance", "equity.price.historical"]


def test_filter_spec_commands_include_supports_multiple_patterns():
    """Multiple ``--include`` patterns OR together — a command kept if it
    matches any one of them."""
    spec = _stub_spec("equity.price", "fixedincome.rate", "shipping.x")
    out = cli._filter_spec_commands(
        spec, include=["equity.*", "shipping.*"], exclude=None
    )
    assert sorted(out["commands"]) == ["equity.price", "shipping.x"]


def test_filter_spec_commands_exclude_drops_matching():
    """``--exclude 'equity.fundamentals.*'`` drops the fundamentals
    subtree and keeps everything else."""
    spec = _stub_spec(
        "equity.price.historical",
        "equity.fundamentals.balance",
        "fixedincome.rate",
    )
    out = cli._filter_spec_commands(
        spec, include=None, exclude=["equity.fundamentals.*"]
    )
    assert sorted(out["commands"]) == ["equity.price.historical", "fixedincome.rate"]


def test_filter_spec_commands_include_takes_priority_over_exclude():
    """When both are supplied, ``--include`` wins — ``--exclude`` is
    ignored entirely (per the documented priority rule). Only commands
    matching include are kept; exclude doesn't get to subtract from the
    whitelist.
    """
    spec = _stub_spec(
        "equity.price",
        "equity.fundamentals.balance",
        "shipping.x",
    )
    out = cli._filter_spec_commands(
        spec,
        include=["equity.*"],
        exclude=["equity.fundamentals.*"],
    )
    # Both ``equity.*`` matches survive — exclude was ignored.
    assert sorted(out["commands"]) == [
        "equity.fundamentals.balance",
        "equity.price",
    ]


def test_filter_spec_commands_does_not_mutate_original():
    """The original ``spec_doc.commands`` is preserved; the filter
    returns a new dict so callers can keep the unfiltered version."""
    spec = _stub_spec("a", "b", "c")
    original_commands = spec["commands"]
    cli._filter_spec_commands(spec, include=["a"], exclude=None)
    assert sorted(original_commands) == ["a", "b", "c"]


def _stub_command_spec() -> dict:
    """A minimum-viable command entry that satisfies SpecDocument validation."""
    return {"method": "get", "url_path": "/x", "parameters": []}


def test_generate_extension_aborts_when_filter_matches_nothing(tmp_path, capsys):
    """Empty filter result is a user error — exit 2 with a stderr message
    rather than emitting an empty extension package."""
    from openbb_cli.dispatchers.spec import SPEC_VERSION, write_spec

    spec_path = tmp_path / "x.spec"
    write_spec(
        spec_path,
        {
            "version": SPEC_VERSION,
            "base_url": "http://x",
            "api_prefix": "/api/v1",
            "commands": {"equity.price": _stub_command_spec()},
        },
    )
    rc = cli._generate_extension(
        [(None, str(spec_path))],
        str(tmp_path / "out"),
        provider_name=None,
        project_name=None,
        package_name=None,
        router_name=None,
        include=["nope.*"],
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "matched no commands" in err


def test_generate_spec_errors_when_zero_commands(tmp_path, capsys):
    """A source that maps to no commands is a loud error, not a skeleton spec."""
    with patch(
        "openbb_cli.dispatchers.openapi_schema.fetch_openapi",
        return_value={
            "openapi": "3.1.0",
            "paths": {"/x": {"$ref": "./paths/x.yaml#/~1x"}},
        },
    ):
        rc = cli._generate_spec(
            "http://localhost:8000",
            str(tmp_path / "x.spec"),
            "/openapi.yaml",
        )
    assert rc == 2
    err = capsys.readouterr().err
    assert "0 commands" in err
    assert "external $refs" in err
    assert not (tmp_path / "x.spec").exists()


def test_main_generate_spec_passes_api_prefix_and_overlays():
    with patch("openbb_cli.cli._generate_spec", return_value=0) as gen:
        rc = cli.main(
            [
                "--server",
                "http://x",
                "--generate-spec",
                "--api-prefix",
                "/api/v3",
                "--overlay",
                "a.yaml",
                "--overlay",
                "b.yaml",
            ]
        )
    assert rc == 0
    _, kwargs = gen.call_args
    assert kwargs["api_prefix"] == "/api/v3"
    assert kwargs["overlays"] == ["a.yaml", "b.yaml"]


_PREFIXED_OPENAPI = {
    "openapi": "3.0.2",
    "paths": {
        "/api/v3/aggTrades": {
            "get": {
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "array",
                                    "items": {"$ref": "#/components/schemas/aggTrade"},
                                }
                            }
                        }
                    }
                }
            }
        },
        "/sapi/v1/system/status": {"get": {"responses": {}}},
    },
    "components": {
        "schemas": {
            "aggTrade": {
                "type": "object",
                "properties": {"T": {"type": "boolean"}},
            }
        }
    },
}


def test_generate_spec_applies_overlay_and_api_prefix(tmp_path):
    from openbb_cli.dispatchers.spec import load_spec

    overlay = tmp_path / "fix.overlay.yaml"
    overlay.write_text(
        "overlay: 1.0.0\n"
        "info: {title: fix, version: '1'}\n"
        "actions:\n"
        "  - target: $.components.schemas.aggTrade.properties.T\n"
        "    update: {type: integer}\n"
    )
    out = tmp_path / "x.spec"
    with patch(
        "openbb_cli.dispatchers.openapi_schema.fetch_openapi",
        return_value=_PREFIXED_OPENAPI,
    ):
        rc = cli._generate_spec(
            "http://localhost:8000",
            str(out),
            "/openapi.yaml",
            api_prefix="/api/v3",
            overlays=[str(overlay)],
        )
    assert rc == 0
    spec = load_spec(out)
    assert set(spec["commands"]) == {"aggTrades", "sapi.v1.system.status"}
    row = spec["commands"]["aggTrades"]["response_schema"]["items"]
    assert row["properties"]["T"]["type"] == "integer"


def test_generate_spec_warns_on_overlay_target_that_matches_nothing(tmp_path, capsys):
    overlay = tmp_path / "fix.overlay.yaml"
    overlay.write_text(
        "overlay: 1.0.0\nactions:\n  - target: $.components.nope\n    update: {}\n"
    )
    with patch(
        "openbb_cli.dispatchers.openapi_schema.fetch_openapi",
        return_value=_PREFIXED_OPENAPI,
    ):
        rc = cli._generate_spec(
            "http://localhost:8000",
            str(tmp_path / "x.spec"),
            "/openapi.yaml",
            overlays=[str(overlay)],
        )
    assert rc == 0
    assert "target matched nothing: $.components.nope" in capsys.readouterr().err


def test_generate_spec_rejects_invalid_overlay(tmp_path, capsys):
    overlay = tmp_path / "not-an-overlay.yaml"
    overlay.write_text("openapi: 3.0.0\n")
    with patch(
        "openbb_cli.dispatchers.openapi_schema.fetch_openapi",
        return_value=_PREFIXED_OPENAPI,
    ):
        rc = cli._generate_spec(
            "http://localhost:8000",
            str(tmp_path / "x.spec"),
            "/openapi.yaml",
            overlays=[str(overlay), str(tmp_path / "missing.yaml")],
        )
    assert rc == 2
    assert "missing 'overlay' field" in capsys.readouterr().err
    assert not (tmp_path / "x.spec").exists()


def test_generate_spec_applies_overlay_before_type_arrays_are_rewritten(tmp_path):
    from openbb_cli.dispatchers.spec import load_spec

    openapi = {
        "openapi": "3.1.0",
        "paths": {
            "/x": {
                "get": {
                    "parameters": [
                        {
                            "name": "limit",
                            "in": "query",
                            "schema": {"type": ["string", "null"]},
                        }
                    ],
                    "responses": {},
                }
            }
        },
    }
    overlay = tmp_path / "fix.overlay.yaml"
    overlay.write_text(
        "overlay: 1.0.0\n"
        "actions:\n"
        "  - target: $.paths['/x'].get.parameters[0].schema\n"
        "    update: {type: [integer, 'null']}\n"
    )
    out = tmp_path / "x.spec"
    with patch(
        "openbb_cli.dispatchers.openapi_schema.fetch_openapi", return_value=openapi
    ) as fetch:
        rc = cli._generate_spec(
            "http://localhost:8000", str(out), "/openapi.json", overlays=[str(overlay)]
        )
    assert rc == 0
    assert fetch.call_args.kwargs["normalize"] is False
    (param,) = load_spec(out)["commands"]["x"]["parameters"]
    assert param["type"] == "integer"


def test_generate_spec_reports_invalid_overlay_yaml(tmp_path, capsys):
    overlay = tmp_path / "bad.yaml"
    overlay.write_text("overlay: 1.0.0\nactions: [\n")
    with patch(
        "openbb_cli.dispatchers.openapi_schema.fetch_openapi",
        return_value=_PREFIXED_OPENAPI,
    ):
        rc = cli._generate_spec(
            "http://localhost:8000",
            str(tmp_path / "x.spec"),
            "/openapi.yaml",
            overlays=[str(overlay)],
        )
    assert rc == 2
    assert f"--overlay {overlay}: not valid YAML or JSON" in capsys.readouterr().err


def test_generate_spec_warns_about_paths_the_api_prefix_leaves_unnamed(
    tmp_path, capsys
):
    with patch(
        "openbb_cli.dispatchers.openapi_schema.fetch_openapi",
        return_value=_PREFIXED_OPENAPI,
    ):
        rc = cli._generate_spec(
            "http://localhost:8000",
            str(tmp_path / "x.spec"),
            "/openapi.yaml",
            api_prefix="/api/v3/aggTrades",
        )
    assert rc == 0
    err = capsys.readouterr().err
    assert "--api-prefix /api/v3/aggTrades: no command name is left for" in err
    assert "/api/v3/aggTrades;" in err


def test_generate_extension_aborts_when_spec_has_zero_commands(tmp_path, capsys):
    """An empty spec never reaches codegen — no zero-command skeleton package."""
    from openbb_cli.dispatchers.spec import SPEC_VERSION, write_spec

    spec_path = tmp_path / "empty.spec"
    write_spec(
        spec_path,
        {
            "version": SPEC_VERSION,
            "base_url": "http://x",
            "api_prefix": "/api/v1",
            "commands": {},
        },
    )
    rc = cli._generate_extension(
        [(None, str(spec_path))],
        str(tmp_path / "out"),
        provider_name=None,
        project_name=None,
        package_name=None,
        router_name=None,
    )
    assert rc == 2
    assert "0 commands" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_generate_extension_filters_commands_before_codegen(tmp_path, capsys):
    """``--include`` reaches all the way through to ``generate_packages``:
    the filtered spec is what codegen actually sees, so the emitted
    package only contains the matched commands.
    """
    from openbb_cli.dispatchers.spec import SPEC_VERSION, write_spec

    spec_path = tmp_path / "x.spec"
    write_spec(
        spec_path,
        {
            "version": SPEC_VERSION,
            "base_url": "http://x",
            "api_prefix": "/api/v1",
            "commands": {
                "equity.price": _stub_command_spec(),
                "equity.balance": _stub_command_spec(),
                "shipping.disruptions": _stub_command_spec(),
            },
        },
    )
    captured: dict = {}

    def fake_generate_packages(spec_doc, **kwargs):  # noqa: ARG001
        captured["spec_commands"] = sorted(spec_doc.get("commands") or {})
        package_set = MagicMock()
        package_set.write.return_value = []
        package_set.packages = []
        return package_set

    with patch(
        "openbb_cli.codegen.package_gen.generate_packages",
        side_effect=fake_generate_packages,
    ):
        rc = cli._generate_extension(
            [(None, str(spec_path))],
            str(tmp_path / "out"),
            provider_name=None,
            project_name=None,
            package_name=None,
            router_name=None,
            include=["equity.*"],
        )
    assert rc == 0
    # Codegen received only the equity.* commands.
    assert captured["spec_commands"] == ["equity.balance", "equity.price"]
    out = capsys.readouterr().out
    assert "filter: 2/3 commands kept" in out


def test_generate_extension_passes_router_name_to_codegen(tmp_path):
    """``--router-name`` reaches ``generate_packages`` verbatim, distinct
    from ``--provider-name`` — it must not be silently dropped on the way
    from the CLI argument to codegen.
    """
    from openbb_cli.dispatchers.spec import SPEC_VERSION, write_spec

    spec_path = tmp_path / "x.spec"
    write_spec(
        spec_path,
        {
            "version": SPEC_VERSION,
            "base_url": "http://x",
            "api_prefix": "/api/v1",
            "commands": {"equity.price": _stub_command_spec()},
        },
    )
    captured: dict = {}

    def fake_generate_packages(spec_doc, **kwargs):  # noqa: ARG001
        captured["router_name"] = kwargs.get("router_name")
        captured["provider_name"] = kwargs.get("provider_name")
        package_set = MagicMock()
        package_set.write.return_value = []
        package_set.packages = []
        return package_set

    with patch(
        "openbb_cli.codegen.package_gen.generate_packages",
        side_effect=fake_generate_packages,
    ):
        rc = cli._generate_extension(
            [(None, str(spec_path))],
            str(tmp_path / "out"),
            provider_name="myprovider",
            project_name=None,
            package_name=None,
            router_name="custom_router",
        )
    assert rc == 0
    assert captured["router_name"] == "custom_router"
    assert captured["provider_name"] == "myprovider"


def test_apply_config_defaults_applies_output_and_batch_concurrency():
    """TOML ``output``/``batch-concurrency`` reach parsed args when the CLI flag
    isn't passed. Both flags bake a non-empty literal into their argparse
    default, so a naive "is the existing default falsy" check silently
    discards the TOML value for these two keys even though it correctly
    applies for the other ``_CONFIG_SCALAR_KEYS``.
    """
    from openbb_cli.dispatchers.runtime import build_parser

    config = {"output": "from_toml.spec", "batch_concurrency": 42}
    parser = build_parser()
    cli._apply_config_defaults(parser, [], config)
    args = parser.parse_args(["--generate-spec"])
    assert args.output == "from_toml.spec"
    assert args.batch_concurrency == 42


def test_apply_config_defaults_cli_flag_beats_toml():
    """An explicit ``--output`` on the command line still wins over TOML."""
    from openbb_cli.dispatchers.runtime import build_parser

    config = {"output": "from_toml.spec"}
    argv = ["--generate-spec", "--output", "from_cli.spec"]
    parser = build_parser()
    cli._apply_config_defaults(parser, argv, config)
    args = parser.parse_args(argv)
    assert args.output == "from_cli.spec"


def test_apply_config_defaults_env_var_beats_toml(monkeypatch):
    """``OPENBB_CLI_BATCH_CONCURRENCY`` still wins over TOML, per the documented
    precedence (TOML < env vars < CLI flags)."""
    from openbb_cli.dispatchers.runtime import build_parser

    monkeypatch.setenv("OPENBB_CLI_BATCH_CONCURRENCY", "99")
    config = {"batch_concurrency": 42}
    parser = build_parser()
    cli._apply_config_defaults(parser, [], config)
    args = parser.parse_args(["--generate-spec"])
    assert args.batch_concurrency == 99


def test_apply_config_defaults_falls_back_to_hardcoded_default():
    """With no TOML, env, or CLI value, the hardcoded argparse default stands."""
    from openbb_cli.dispatchers.runtime import build_parser

    parser = build_parser()
    cli._apply_config_defaults(parser, [], {})
    args = parser.parse_args(["--generate-spec"])
    assert args.output == "openbb.spec"
    assert args.batch_concurrency == 8
