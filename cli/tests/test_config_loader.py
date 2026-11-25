"""Tests for openbb_cli.config.loader — layered TOML resolution + env injection."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from openbb_cli.config import loader


def _write(path: Path, contents: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents)
    return path


# --- load_config layering ---


def test_load_config_returns_empty_when_no_sources(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENBB_CLI_CONFIG", raising=False)
    monkeypatch.setattr(loader, "_user_global_toml", lambda: None)
    assert loader.load_config(start=tmp_path) == {}


def test_load_config_normalizes_kebab_to_snake(tmp_path, monkeypatch):
    _write(tmp_path / "openbb.toml", "batch-concurrency = 4\n")
    monkeypatch.delenv("OPENBB_CLI_CONFIG", raising=False)
    monkeypatch.setattr(loader, "_user_global_toml", lambda: None)
    out = loader.load_config(start=tmp_path)
    assert out["batch_concurrency"] == 4


def test_load_config_explicit_path_wins(tmp_path, monkeypatch):
    _write(tmp_path / "openbb.toml", 'server = "from-local"\n')
    explicit = _write(tmp_path / "explicit.toml", 'server = "from-explicit"\n')
    monkeypatch.delenv("OPENBB_CLI_CONFIG", raising=False)
    monkeypatch.setattr(loader, "_user_global_toml", lambda: None)
    out = loader.load_config(explicit_path=str(explicit), start=tmp_path)
    assert out["server"] == "from-explicit"


def test_load_config_env_var_picks_up_path(tmp_path, monkeypatch):
    explicit = _write(tmp_path / "viaenv.toml", 'server = "from-env"\n')
    monkeypatch.setenv("OPENBB_CLI_CONFIG", str(explicit))
    monkeypatch.setattr(loader, "_user_global_toml", lambda: None)
    out = loader.load_config(start=tmp_path)
    assert out["server"] == "from-env"


def test_load_config_pyproject_section_loaded(tmp_path, monkeypatch):
    _write(
        tmp_path / "pyproject.toml",
        '[tool.openbb-cli]\nserver = "https://from-pyproject"\n',
    )
    monkeypatch.delenv("OPENBB_CLI_CONFIG", raising=False)
    monkeypatch.setattr(loader, "_user_global_toml", lambda: None)
    out = loader.load_config(start=tmp_path)
    assert out["server"] == "https://from-pyproject"


def test_load_config_project_local_overrides_pyproject(tmp_path, monkeypatch):
    _write(
        tmp_path / "pyproject.toml",
        '[tool.openbb-cli]\nserver = "from-pyproject"\n',
    )
    _write(tmp_path / "openbb.toml", 'server = "from-local"\n')
    monkeypatch.delenv("OPENBB_CLI_CONFIG", raising=False)
    monkeypatch.setattr(loader, "_user_global_toml", lambda: None)
    out = loader.load_config(start=tmp_path)
    assert out["server"] == "from-local"


def test_load_config_deep_merges_nested_tables(tmp_path, monkeypatch):
    """Nested ``[headers]`` / ``[query]`` tables merge per-key, not whole-table."""
    _write(
        tmp_path / "pyproject.toml",
        '[tool.openbb-cli.headers]\nA = "1"\nB = "from-pyproject"\n',
    )
    _write(tmp_path / "openbb.toml", '[headers]\nB = "overridden"\nC = "3"\n')
    monkeypatch.delenv("OPENBB_CLI_CONFIG", raising=False)
    monkeypatch.setattr(loader, "_user_global_toml", lambda: None)
    out = loader.load_config(start=tmp_path)
    assert out["headers"] == {"A": "1", "B": "overridden", "C": "3"}


def test_read_toml_returns_empty_on_invalid_content(tmp_path):
    """A malformed TOML file is treated as an empty layer, not raised."""
    bad = _write(tmp_path / "bad.toml", "this is not toml = =\n")
    assert loader._read_toml(bad) == {}


def test_find_first_walks_up_to_ancestor(tmp_path):
    """Discovery walks up from a nested directory until it finds the file."""
    _write(tmp_path / "openbb.toml", 'server = "x"\n')
    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    found = loader._find_first(nested, ("openbb.toml", ".openbb.toml"))
    assert found == tmp_path / "openbb.toml"


def test_find_first_returns_none_when_no_match(tmp_path):
    assert loader._find_first(tmp_path, ("nonsense.toml",)) is None


# --- apply_settings_to_env ---


def test_apply_settings_to_env_handles_none_or_empty():
    assert loader.apply_settings_to_env(None) == []
    assert loader.apply_settings_to_env({}) == []


def test_apply_settings_to_env_translates_kebab_keys(monkeypatch):
    monkeypatch.delenv("OPENBB_ALLOWED_NUMBER_OF_ROWS", raising=False)
    try:
        applied = loader.apply_settings_to_env(
            {"settings": {"allowed-number-of-rows": 50}}
        )
        assert "OPENBB_ALLOWED_NUMBER_OF_ROWS" in applied
        assert os.environ["OPENBB_ALLOWED_NUMBER_OF_ROWS"] == "50"
    finally:
        # `apply_settings_to_env` writes straight to the real `os.environ`,
        # which `monkeypatch.delenv` above never registered for auto-cleanup
        # (nothing existed yet to revert). `monkeypatch.delenv` again here
        # would be wrong too — once the key exists, it records "50" as the
        # value to *restore* on teardown, re-leaking it. A direct pop is the
        # only way to guarantee it doesn't leak into later tests that
        # construct a real ``Settings()`` and read ``os.environ``.
        os.environ.pop("OPENBB_ALLOWED_NUMBER_OF_ROWS", None)


def test_apply_settings_to_env_serializes_booleans_capitalized(monkeypatch):
    monkeypatch.delenv("OPENBB_USE_PROMPT_TOOLKIT", raising=False)
    try:
        loader.apply_settings_to_env({"settings": {"use-prompt-toolkit": True}})
        assert os.environ["OPENBB_USE_PROMPT_TOOLKIT"] == "True"
    finally:
        os.environ.pop("OPENBB_USE_PROMPT_TOOLKIT", None)


def test_apply_settings_to_env_settings_table_does_not_clobber_existing(monkeypatch):
    """Values from the ``[settings]`` table use ``setdefault`` semantics."""
    monkeypatch.setenv("OPENBB_ALLOWED_NUMBER_OF_ROWS", "999")
    loader.apply_settings_to_env({"settings": {"allowed-number-of-rows": 50}})
    assert os.environ["OPENBB_ALLOWED_NUMBER_OF_ROWS"] == "999"


def test_apply_settings_to_env_top_level_overrides_settings_table(monkeypatch):
    """Top-level promoted keys (snake_case after normalization) override [settings]."""
    monkeypatch.delenv("OPENBB_OUTPUT_MODE", raising=False)
    try:
        # Mimic what `load_config()` produces: top-level keys arrive snake_cased
        loader.apply_settings_to_env(
            {
                "output_mode": "rich",
                "settings": {"output-mode": "tsv"},
            }
        )
        assert os.environ["OPENBB_OUTPUT_MODE"] == "rich"
    finally:
        os.environ.pop("OPENBB_OUTPUT_MODE", None)


# --- load_env_files ---


def test_load_env_files_loads_explicit_path(tmp_path, monkeypatch):
    env = _write(tmp_path / ".env", "OPENBB_FROM_DOTENV=hello\n")
    monkeypatch.delenv("OPENBB_FROM_DOTENV", raising=False)
    # Block discovery of the user-global .env so this test stays hermetic
    monkeypatch.setattr(loader, "USER_OPENBB_DIR", tmp_path / "no-such-dir")
    try:
        loaded = loader.load_env_files(str(env))
        assert env in loaded
        assert os.environ["OPENBB_FROM_DOTENV"] == "hello"
    finally:
        os.environ.pop("OPENBB_FROM_DOTENV", None)


def test_load_env_files_does_not_override_existing(tmp_path, monkeypatch):
    env = _write(tmp_path / ".env", "OPENBB_KEEP_EXISTING=from-dotenv\n")
    monkeypatch.setenv("OPENBB_KEEP_EXISTING", "from-shell")
    monkeypatch.setattr(loader, "USER_OPENBB_DIR", tmp_path / "no-such-dir")
    loader.load_env_files(str(env))
    assert os.environ["OPENBB_KEEP_EXISTING"] == "from-shell"


def test_load_env_files_silently_skips_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(loader, "USER_OPENBB_DIR", tmp_path / "no-such-dir")
    assert loader.load_env_files("/nonexistent/path/.env") == []


def test_load_env_files_uses_env_var_when_no_explicit(tmp_path, monkeypatch):
    env = _write(tmp_path / ".env", "OPENBB_FROM_ENV_VAR=yes\n")
    monkeypatch.delenv("OPENBB_FROM_ENV_VAR", raising=False)
    monkeypatch.setenv(loader.EXPLICIT_ENV_FILE_ENV, str(env))
    monkeypatch.setattr(loader, "USER_OPENBB_DIR", tmp_path / "no-such-dir")
    try:
        loader.load_env_files()
        assert os.environ["OPENBB_FROM_ENV_VAR"] == "yes"
    finally:
        os.environ.pop("OPENBB_FROM_ENV_VAR", None)


# --- render_config_template ---


def test_render_config_template_returns_valid_toml():
    """The template must round-trip through tomllib when nothing's been set."""
    rendered = loader.render_config_template()
    # Strip the all-comment lines so tomllib has something to parse — even
    # an empty result is fine; the assertion is "no parse error".
    import tomllib

    tomllib.loads(rendered)


def test_render_config_template_uncomments_active_values():
    """When ``active`` resolves a value, the line is emitted uncommented."""
    rendered = loader.render_config_template({"server": "https://api.example.com"})
    # The server line should NOT be commented out
    server_lines = [
        line for line in rendered.splitlines() if line.strip().startswith("server =")
    ]
    assert server_lines
    assert not server_lines[0].lstrip().startswith("#")
    assert "api.example.com" in server_lines[0]


def test_render_config_template_includes_headers_and_query_sections():
    rendered = loader.render_config_template()
    assert "[headers]" in rendered
    assert "[query]" in rendered
    assert "[settings]" in rendered


@pytest.mark.parametrize(
    "value,expected",
    [
        (True, "true"),
        (False, "false"),
        (42, "42"),
        ("plain", '"plain"'),
        ('with "quote"', '"with \\"quote\\""'),
    ],
)
def test_toml_quote_serializes_basic_types(value, expected):
    assert loader._toml_quote(value) == expected


def test_normalize_keys_kebab_to_snake_top_level_only():
    """Top-level keys are kebab→snake; nested header/query keys keep casing."""
    out = loader._normalize_keys(
        {"batch-concurrency": 8, "headers": {"X-API-Key": "v"}}
    )
    assert "batch_concurrency" in out
    # Nested header keys preserved as-is — they're literal HTTP header names
    assert "X-API-Key" in out["headers"]


# --- _user_global_toml + load_env_files ---


def test_user_global_toml_finds_file_when_dir_exists(tmp_path, monkeypatch):
    """``_user_global_toml`` returns the path when the user dir + file both exist."""
    monkeypatch.setattr(loader, "USER_OPENBB_DIR", tmp_path)
    expected = tmp_path / "openbb.toml"
    expected.write_text("server = 'x'\n")
    assert loader._user_global_toml() == expected


def test_user_global_toml_returns_none_when_dir_exists_no_file(tmp_path, monkeypatch):
    """Directory exists but no openbb.toml inside → None."""
    monkeypatch.setattr(loader, "USER_OPENBB_DIR", tmp_path)
    assert loader._user_global_toml() is None


def test_load_config_includes_user_global_layer(tmp_path, monkeypatch):
    """The user-global TOML layer is merged below project-local."""
    user_toml = tmp_path / "openbb.toml"
    user_toml.write_text('server = "from-user-global"\n')
    monkeypatch.setattr(loader, "_user_global_toml", lambda: user_toml)
    monkeypatch.delenv("OPENBB_CLI_CONFIG", raising=False)
    out = loader.load_config(start=tmp_path / "no-such-dir")
    assert out["server"] == "from-user-global"


def test_load_env_files_imports_dotenv_values(tmp_path, monkeypatch):
    """Real ``.env`` parsing path: values land in os.environ via setdefault."""
    env = tmp_path / ".env"
    env.write_text("OPENBB_LOADER_REAL=yes\nNULL_VALUE\n")
    monkeypatch.setattr(loader, "USER_OPENBB_DIR", tmp_path / "no-user")
    monkeypatch.delenv("OPENBB_LOADER_REAL", raising=False)
    monkeypatch.delenv("NULL_VALUE", raising=False)
    try:
        loader.load_env_files(str(env))
        assert os.environ["OPENBB_LOADER_REAL"] == "yes"
        # Bare ``NULL_VALUE`` (no equals) parses as None and is skipped, not set
        assert "NULL_VALUE" not in os.environ
    finally:
        os.environ.pop("OPENBB_LOADER_REAL", None)


def test_load_env_files_picks_up_user_global_env(tmp_path, monkeypatch):
    """``USER_OPENBB_DIR/.env`` is added to the candidate list when present —
    the user-global layer is what makes ``~/.openbb_platform/.env`` work
    without any explicit path argument or env var."""
    user_dir = tmp_path / "user"
    user_dir.mkdir()
    (user_dir / loader.USER_OPENBB_ENV_NAME).write_text(
        "OPENBB_LOADER_USER_GLOBAL=present\n"
    )
    monkeypatch.setattr(loader, "USER_OPENBB_DIR", user_dir)
    monkeypatch.delenv("OPENBB_LOADER_USER_GLOBAL", raising=False)
    monkeypatch.delenv(loader.EXPLICIT_ENV_FILE_ENV, raising=False)
    try:
        loader.load_env_files()
        assert os.environ["OPENBB_LOADER_USER_GLOBAL"] == "present"
    finally:
        os.environ.pop("OPENBB_LOADER_USER_GLOBAL", None)


# --- render_config_template with active values ---


def test_render_config_template_renders_active_headers_table():
    rendered = loader.render_config_template(
        {"headers": {"Authorization": "Bearer xyz", "X-Tenant": "acme"}}
    )
    assert '"Authorization" = "Bearer xyz"' in rendered
    assert '"X-Tenant" = "acme"' in rendered


def test_render_config_template_renders_active_query_table():
    rendered = loader.render_config_template({"query": {"api_key": "secret"}})
    assert '"api_key" = "secret"' in rendered


# --- _render_settings_section dev field branch ---


def test_render_settings_section_includes_dev_fields():
    """Dev-mode fields (DEBUG_MODE, TEST_MODE) render in the [settings] section."""
    rendered = loader.render_config_template()
    # DEBUG_MODE / TEST_MODE flagged as dev in _SETTINGS_DEV_FIELDS
    assert "debug-mode" in rendered.lower() or "test-mode" in rendered.lower()


# --- _toml_quote numeric branch ---


@pytest.mark.parametrize("value,expected", [(0, "0"), (1.5, "1.5"), (-3, "-3")])
def test_toml_quote_serializes_numbers(value, expected):
    assert loader._toml_quote(value) == expected


def test_user_global_toml_returns_none_when_dir_missing(tmp_path, monkeypatch):
    """No directory exists at all → None."""
    monkeypatch.setattr(loader, "USER_OPENBB_DIR", tmp_path / "absent")
    assert loader._user_global_toml() is None


def test_render_settings_section_skips_undocumented_internal_field():
    """Fields without ``command`` metadata in ``json_schema_extra`` AND not in
    the dev allowlist are excluded from the rendered template."""
    rendered = loader.render_config_template()
    # ``OPENBB_VERSION`` is internal — must NOT appear in the [settings] block
    assert "version =" not in rendered.lower().replace(" =", "=")


def test_toml_quote_falls_back_to_quoted_repr_for_unknown_type():
    """Anything not bool/int/float/str/list goes through ``str(...)`` and is quoted."""
    assert loader._toml_quote(None) == '"None"'
    assert loader._toml_quote((1, 2)) == '"(1, 2)"'


def test_render_settings_section_skips_undocumented_non_dev_field(monkeypatch):
    """A field that's not internal, not documented (no ``command`` extra),
    and not in the dev allowlist is skipped. Defensive coverage — every
    real Settings field is currently either documented or in the dev
    allowlist; this guards against future regressions if a non-documented
    field gets added without classification.
    """
    from openbb_cli.models.settings import Settings

    class _StubField:
        json_schema_extra = None  # not a dict → not documented
        default = None
        description = "stub"

    monkeypatch.setattr(
        Settings,
        "model_fields",
        {**Settings.model_fields, "STUB_UNDOCUMENTED": _StubField()},
    )
    rendered = loader.render_config_template()
    assert "stub-undocumented" not in rendered.lower()
