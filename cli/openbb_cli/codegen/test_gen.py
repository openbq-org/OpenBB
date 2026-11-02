"""Emit per-provider unit-test modules for a generated extension."""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass
from datetime import UTC
from itertools import islice, product
from typing import TYPE_CHECKING, Any

from openbb_cli.codegen.pydantic_gen import query_field_name

if TYPE_CHECKING:
    from openbb_cli.codegen.fetcher_gen import GeneratedFetcher, UrlChoices


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
        params = _derive_test_params(
            cmd_spec,
            provider_name,
            class_name=f.fetcher_class.removesuffix("Fetcher") + "QueryParams",
        )
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
    safe = re.sub(r"[^0-9a-zA-Z]+", "_", dotted).strip("_").lower()
    if not safe:
        safe = "command"
    if safe[0].isdigit():
        safe = f"_{safe}"
    return f"{safe}_" if keyword.iskeyword(safe) else safe


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
    cmd_spec: dict[str, Any], provider_name: str, class_name: str = "QueryParams"
) -> dict[str, Any] | None:
    """Build a kwargs dict for the command's testable params, or ``None``.

    Keys are the generated ``QueryParams`` field names, the attribute names
    ``Fetcher.test`` reads back from the validated query. The params satisfy
    the command's required groups and, for a command with several URLs, form
    one of them; when that is impossible the test is skipped.
    """
    out: dict[str, Any] = {}
    params_by_name: dict[str, dict[str, Any]] = {}
    heuristic: set[str] = set()
    placeholders = {
        name
        for template in cmd_spec.get("url_templates")
        or [cmd_spec.get("url_path") or ""]
        for name in re.findall(r"\{([^}]+)\}", template)
    }
    for raw in cmd_spec.get("parameters") or []:
        if not isinstance(raw, dict):
            continue
        name = raw.get("name")
        if not name or name == "provider":
            continue
        param_providers = raw.get("providers") or []
        if param_providers and provider_name not in param_providers:
            continue
        params_by_name[name] = raw
        if raw.get("required"):
            value = _spec_supplied_value(raw)
            if value is None:
                return None
            out[name] = value
        elif (
            _is_date_param(name)
            and not raw.get("choices")
            and raw.get("in", "query") != "path"
            and name not in placeholders
        ):
            out[name] = _refresh_date_shape(name, "1970-01-01")
            heuristic.add(name)
    groups = cmd_spec.get("required_groups") or []
    satisfied = _satisfy_groups(groups, out, params_by_name, heuristic)
    if satisfied is None:
        return None
    formed = _satisfy_url_templates(cmd_spec, satisfied, params_by_name)
    if formed is None:
        return None
    from openbb_cli.codegen.fetcher_gen import query_params_fields

    field_names = query_params_fields(
        {**cmd_spec, "parameters": list(params_by_name.values())},
        provider_name,
        class_name,
    )
    return {
        field_names.get(name) or query_field_name(name): value
        for name, value in formed.items()
    }


def _is_present(out: dict[str, Any], name: str) -> bool:
    """Whether ``out`` passes a value for ``name``, by the validator's rule."""
    return out.get(name) not in (None, "", [])


def _group_holds(group: dict[str, Any], out: dict[str, Any]) -> bool:
    """Whether ``out`` passes the generated ``_check_required_groups`` for ``group``."""
    if not group.get("required", True) and not any(
        _is_present(out, name) for name in group.get("members") or []
    ):
        return True
    met = sum(
        all(_is_present(out, name) for name in alt)
        for alt in group.get("alternatives") or []
    )
    return met == 1 if group.get("combinator") == "oneOf" else met >= 1


_MAX_GROUP_COMBINATIONS = 512


def _satisfy_groups(
    groups: list[dict[str, Any]],
    out: dict[str, Any],
    params_by_name: dict[str, dict[str, Any]],
    heuristic: set[str],
) -> dict[str, Any] | None:
    """Return ``out`` changed so every required group passes, or ``None``.

    Optional groups set off only by params the date heuristic added are
    disarmed by removing those params. Then every combination of one
    alternative per group (an optional group may also be left out) is tried in
    order, up to a bound: missing values come from the spec, and for ``oneOf``
    the params only unchosen alternatives need are removed. Required params
    are never removed.
    """
    if all(_group_holds(group, out) for group in groups):
        return out
    base = dict(out)
    for group in groups:
        if group.get("required", True) or _group_holds(group, base):
            continue
        triggered = [n for n in group.get("members") or [] if _is_present(base, n)]
        if triggered and set(triggered) <= heuristic:
            for name in triggered:
                base.pop(name, None)
    if all(_group_holds(group, base) for group in groups):
        return base
    required = {name for name, raw in params_by_name.items() if raw.get("required")}
    options = [
        list(group.get("alternatives") or [])
        + ([] if group.get("required", True) else [None])
        for group in groups
    ]
    for combo in islice(product(*options), _MAX_GROUP_COMBINATIONS):
        candidate = _fill(
            base, [n for alt in combo if alt for n in alt], params_by_name
        )
        if candidate is None:
            continue
        chosen = {name for alt in combo if alt for name in alt}
        for group, alt in zip(groups, combo, strict=True):
            if alt is None or group.get("combinator") != "oneOf":
                continue
            for other in group.get("alternatives") or []:
                for name in other:
                    if name not in chosen and name not in required:
                        candidate.pop(name, None)
        if all(_group_holds(group, candidate) for group in groups):
            return candidate
    return None


def _fill(
    out: dict[str, Any],
    names: list[str],
    params_by_name: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Copy ``out`` with spec-supplied values for any of ``names`` it lacks."""
    candidate = dict(out)
    for name in names:
        if _is_present(candidate, name):
            continue
        raw = params_by_name.get(name)
        value = _spec_supplied_value(raw) if raw is not None else None
        if value is None:
            return None
        candidate[name] = value
    return candidate


def _satisfy_url_templates(
    cmd_spec: dict[str, Any],
    out: dict[str, Any],
    params_by_name: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    """Make ``out`` form one of a merged command's URLs, as its validator checks.

    When the params form none, the first URL whose placeholders can all be
    filled from the spec is filled; ``None`` when no URL can be.
    """
    from openbb_cli.codegen.fetcher_gen import url_choices_for

    choices = url_choices_for(cmd_spec, "", {name: name for name in params_by_name})
    if choices is None or _forms_url(choices, out):
        return out
    for _, path_names, _ in choices.templates:
        candidate = _fill(out, list(path_names), params_by_name)
        if candidate is not None and _forms_url(choices, candidate):
            return candidate
    return None


def _forms_url(choices: UrlChoices, out: dict[str, Any]) -> bool:
    """Whether ``out`` passes the generated ``_check_url_template``."""
    from openbb_cli.dispatchers._unpack import choose_url_template

    values = {
        name: out.get(name, choices.defaults.get(name)) for name in choices.placeholders
    }
    try:
        choose_url_template(choices.templates, values, None, choices.defaults)
    except ValueError:
        return False
    return True


def _spec_supplied_value(param: dict[str, Any]) -> Any:
    """Return a value the spec itself vouches for, or ``None`` to abort the test.

    The example wins, then the default, then the first choice; when the param
    declares ``choices``, an example or default outside them is skipped.
    """
    choices = param.get("choices") or []
    raw_value: Any = next(
        (
            value
            for value in (param.get("example"), param.get("default"))
            if value is not None and (not choices or value in choices)
        ),
        choices[0] if choices else None,
    )
    if raw_value is None:
        return None
    if (
        isinstance(raw_value, list)
        and param.get("is_list")
        and param.get("in", "query") == "query"
    ):
        raw_value = ",".join(str(item) for item in raw_value)
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
