"""Emit per-provider unit-test modules for a generated extension."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from typing import TYPE_CHECKING, Any

from openbb_cli.codegen.pydantic_gen import safe_field_name

if TYPE_CHECKING:
    from openbb_cli.codegen.fetcher_gen import GeneratedFetcher


_STANDARD_HEADER_REDACTIONS: tuple[tuple[str, str | None], ...] = (
    ("User-Agent", None),
    ("Authorization", "Bearer MOCK_TOKEN"),
    ("X-API-Key", "MOCK_API_KEY"),
    ("X-Api-Key", "MOCK_API_KEY"),
    ("apikey", "MOCK_API_KEY"),
    ("api-key", "MOCK_API_KEY"),
    ("X-Auth-Token", "MOCK_TOKEN"),
    ("X-Access-Token", "MOCK_TOKEN"),
    ("Cookie", "MOCK_COOKIE"),
    ("Set-Cookie", "MOCK_COOKIE"),
)

_STANDARD_QUERY_REDACTIONS: tuple[tuple[str, str], ...] = (
    ("apikey", "MOCK_API_KEY"),
    ("api_key", "MOCK_API_KEY"),
    ("api-key", "MOCK_API_KEY"),
    ("key", "MOCK_API_KEY"),
    ("subscription_key", "MOCK_API_KEY"),
    ("ocp_apim_subscription_key", "MOCK_API_KEY"),
    ("token", "MOCK_TOKEN"),
    ("access_token", "MOCK_TOKEN"),
    ("auth_token", "MOCK_TOKEN"),
    ("bearer_token", "MOCK_TOKEN"),
    ("session_token", "MOCK_TOKEN"),
    ("client_id", "MOCK_CLIENT_ID"),
    ("client_secret", "MOCK_CLIENT_SECRET"),
    ("client_token", "MOCK_TOKEN"),
    ("app_id", "MOCK_APP_ID"),
    ("app_key", "MOCK_APP_KEY"),
    ("app_token", "MOCK_TOKEN"),
    ("appid", "MOCK_APP_ID"),
    ("secret", "MOCK_SECRET"),
    ("secret_key", "MOCK_SECRET"),
    ("private_key", "MOCK_SECRET"),
    ("consumer_key", "MOCK_API_KEY"),
    ("consumer_secret", "MOCK_SECRET"),
)


def _mock_value_for(name: str) -> str:
    """Pick a mock placeholder that matches what kind of credential ``name`` is."""
    lower = name.lower().replace("-", "_")
    if "secret" in lower:
        return "MOCK_SECRET"
    if "token" in lower:
        return "MOCK_TOKEN"
    if "client_id" in lower or lower.endswith("_id") or lower == "appid":
        return "MOCK_CLIENT_ID"
    return "MOCK_API_KEY"


@dataclass
class GeneratedTestModule:
    """One ``tests/test_<provider>_fetchers.py`` ready to write to disk.

    Parameters
    ----------
    module_name : str
        Filename without ``.py``.
    source : str
        Full module source.
    """

    module_name: str
    source: str


def generate_provider_tests(
    *,
    package_name: str,
    provider_name: str,
    fetchers: list[GeneratedFetcher],
    commands_by_dotted: dict[str, dict[str, Any]],
) -> GeneratedTestModule | None:
    """Render a unit-test module exercising every fetcher in ``fetchers``.

    Parameters
    ----------
    package_name : str
        Snake-case top-level package.
    provider_name : str
        Snake-case provider identifier.
    fetchers : list of GeneratedFetcher
        The fetchers to test.
    commands_by_dotted : dict
        Map ``{dotted_command: cmd_spec}``.

    Returns
    -------
    GeneratedTestModule or None
        ``None`` when there's nothing to test.
    """
    if not fetchers:
        return None

    testable: list[tuple[GeneratedFetcher, dict[str, Any]]] = []
    for f in sorted(fetchers, key=lambda x: x.fetcher_class):
        dotted = _dotted_for_fetcher(f, commands_by_dotted)
        cmd_spec = commands_by_dotted.get(dotted, {}) if dotted else {}
        params = _derive_test_params(cmd_spec, provider_name)
        if params is None:
            continue
        testable.append((f, params))

    if not testable:
        return None

    parts: list[str] = [
        f'"""Auto-generated unit tests for the {provider_name} provider."""',
        "",
        "import pytest",
        "from openbb_core.app.service.user_service import UserService",
        "",
    ]
    for f, _ in testable:
        parts.append(
            f"from {package_name}.providers.{provider_name}.models."
            f"{f.module_name} import {f.fetcher_class}"
        )
    parts.append("")
    parts.append("")
    parts.append(
        "test_credentials = UserService()"
        ".default_user_settings.credentials.model_dump(mode='json')"
    )
    parts.append("")
    parts.append("")
    header_filters, query_filters = _merge_redactions([f for f, _ in testable])
    parts.append('@pytest.fixture(scope="module")')
    parts.append("def vcr_config():")
    parts.append('    """Scrub credential fields from recorded cassettes."""')
    parts.append("    return {")
    parts.append(f'        "filter_headers": {header_filters!r},')
    parts.append(f'        "filter_query_parameters": {query_filters!r},')
    parts.append("    }")
    parts.append("")
    parts.append("")
    for f, params in testable:
        parts.append("@pytest.mark.record_http")
        parts.append(
            f"def test_{_snake(f.fetcher_class)}(credentials=test_credentials):"
        )
        parts.append(f"    params = {params!r}")
        parts.append(f"    fetcher = {f.fetcher_class}()")
        parts.append("    result = fetcher.test(params, credentials)")
        parts.append("    assert result is None")
        parts.append("")
        parts.append("")

    source = "\n".join(parts).rstrip() + "\n"
    return GeneratedTestModule(
        module_name=f"test_{provider_name}_fetchers",
        source=source,
    )


def _merge_redactions(
    fetchers: list[GeneratedFetcher],
) -> tuple[list[tuple[str, str | None]], list[tuple[str, str]]]:
    """Build (header_filters, query_filters) for the ``vcr_config`` fixture."""
    headers: dict[str, str | None] = {}
    queries: dict[str, str] = {}
    for f in fetchers:
        for info in f.credentials_used.values():
            wire = info.get("name")
            location = info.get("in", "query")
            if not wire:
                continue
            if location == "header":
                headers[wire] = _mock_value_for(wire)
            elif location == "cookie":
                # Cookies travel on the wire as the ``Cookie`` header, which
                # ``_STANDARD_HEADER_REDACTIONS`` already blanket-redacts below
                # — VCR has no way to filter a single cookie within it.
                continue
            else:
                queries[wire] = _mock_value_for(wire)
    for n, v in _STANDARD_HEADER_REDACTIONS:
        headers[n] = v
    for n, v in _STANDARD_QUERY_REDACTIONS:
        queries[n] = v
    return (
        sorted(headers.items()),
        sorted(queries.items()),
    )


def _dotted_for_fetcher(
    fetcher: GeneratedFetcher,
    commands_by_dotted: dict[str, dict[str, Any]],
) -> str | None:
    """Find the dotted command path that produced ``fetcher``."""
    target = fetcher.module_name
    for dotted in commands_by_dotted:
        if _normalize_to_module(dotted) == target:
            return dotted
    return None


def _normalize_to_module(dotted: str) -> str:
    """Match ``fetcher_gen._module_name_from_command`` exactly."""
    import re

    safe = re.sub(r"[^0-9a-zA-Z]+", "_", dotted).strip("_").lower()
    if not safe:
        safe = "command"
    if safe[0].isdigit():
        safe = f"_{safe}"
    return safe


_DATE_PARAM_NAMES: frozenset[str] = frozenset(
    {
        "date",
        "from",
        "to",
        "fromdate",
        "todate",
        "start_date",
        "end_date",
        "startdate",
        "enddate",
    }
)


def _is_date_param(name: str) -> bool:
    """Heuristic: this param's name implies a date / time range filter."""
    lower = name.lower().replace("-", "_")
    return lower in _DATE_PARAM_NAMES or "date" in lower


def _derive_test_params(
    cmd_spec: dict[str, Any], provider_name: str
) -> dict[str, Any] | None:
    """Build a kwargs dict for the command's testable params, or ``None``."""
    out: dict[str, Any] = {}
    for raw in cmd_spec.get("parameters") or []:
        if not isinstance(raw, dict):
            continue
        name = raw.get("name")
        if not name or name == "provider":
            continue
        param_providers = raw.get("providers") or []
        if param_providers and provider_name not in param_providers:
            continue
        field_name, _ = safe_field_name(name)
        if raw.get("required"):
            value = _spec_supplied_value(raw)
            if value is None:
                return None
            out[field_name] = value
        elif _is_date_param(name):
            out[field_name] = _refresh_date_shape(name, "1970-01-01")
    return out


def _spec_supplied_value(param: dict[str, Any]) -> Any:
    """Return a value the spec itself vouches for, or ``None`` to abort the test."""
    raw_value: Any = None
    if param.get("example") is not None:
        raw_value = param["example"]
    elif param.get("default") is not None:
        raw_value = param["default"]
    else:
        choices = param.get("choices") or []
        if choices:
            raw_value = choices[0]
    if raw_value is None:
        return None
    return _refresh_date_shape(param.get("name") or "", raw_value)


def _refresh_date_shape(name: str, value: Any) -> Any:
    """Replace an aged date-shaped string with an equivalent current date."""
    import re
    from datetime import date, datetime, timedelta

    if not isinstance(value, str):
        return value
    lower = name.lower()
    is_start = "start" in lower or lower in {"from", "fromdate"}
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        today = date.today()
        return str(today - timedelta(days=30) if is_start else today)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?", value):
        now = datetime.now(UTC).replace(microsecond=0)
        chosen = (now - timedelta(days=30)) if is_start else now
        return chosen.isoformat().replace("+00:00", "Z")
    return value


def _snake(camel: str) -> str:
    """``CamelCase`` -> ``snake_case`` for test function names."""
    out: list[str] = []
    for i, ch in enumerate(camel):
        if ch.isupper() and i > 0 and not camel[i - 1].isupper():
            out.append("_")
        out.append(ch.lower())
    return "".join(out)
