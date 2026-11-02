"""Top-level codegen orchestrator: spec doc to one installable project."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openbb_cli.codegen.fetcher_gen import (
    FetcherCommandSpec,
    GeneratedFetcher,
    generate_fetcher_module,
)
from openbb_cli.codegen.namespace_tree import (
    build_namespace_tree,
    iter_commands,
    providers_from_tree,
)
from openbb_cli.codegen.post_gen import (
    GeneratedPostCommand,
    PostCommandSpec,
    generate_post_command_module,
)
from openbb_cli.codegen.project_gen import GeneratedProject, generate_pyproject
from openbb_cli.codegen.provider_gen import GeneratedProvider, generate_provider_module
from openbb_cli.codegen.router_gen import (
    GeneratedRouter,
    GeneratedRouters,
    generate_routers,
)
from openbb_cli.codegen.test_gen import GeneratedTestModule, generate_provider_tests


@dataclass
class GeneratedPackage:
    """One installable project that bundles every provider in the spec.

    Parameters
    ----------
    root : Path
        Project root directory.
    project : GeneratedProject
        ``pyproject.toml`` source.
    providers : list of GeneratedProvider
        One provider registration module per declared spec provider.
    routers : GeneratedRouters
        Shared router modules.
    fetchers_by_provider : dict
        ``{provider_name: [GeneratedFetcher, ...]}``.
    post_commands : list of GeneratedPostCommand
        Local-compute POST endpoints.
    top_level_routers : list of str
        Top-level namespace names registered as ``openbb_core_extension`` entry points.
    """

    root: Path
    project: GeneratedProject
    providers: list[GeneratedProvider]
    routers: GeneratedRouters
    fetchers_by_provider: dict[str, list[GeneratedFetcher]]
    post_commands: list[GeneratedPostCommand] = field(default_factory=list)
    top_level_routers: list[str] = field(default_factory=list)
    root_namespace: str = ""
    base_url: str = ""
    commands_by_provider: dict[str, list[str]] = field(default_factory=dict)
    test_modules: list[GeneratedTestModule] = field(default_factory=list)

    def write(self) -> Path:
        """Materialize the project on disk under ``self.root``.

        Returns
        -------
        Path
            ``self.root``.
        """
        pkg = self.root / self.project.package_name
        routers_dir = pkg / "routers"
        providers_dir = pkg / "providers"
        routers_dir.mkdir(parents=True, exist_ok=True)
        providers_dir.mkdir(parents=True, exist_ok=True)

        for path in (pkg, routers_dir, providers_dir):
            init = path / "__init__.py"
            if not init.exists():
                init.write_text(f'"""{path.name} subpackage."""\n')

        (pkg / "utils.py").write_text(RUNTIME_UTILS_SOURCE)

        for r in self.routers.routers:
            (routers_dir / f"{r.module_name}.py").write_text(r.source)

        for prov in self.providers:
            prov_dir = providers_dir / prov.provider_name
            models_dir = prov_dir / "models"
            models_dir.mkdir(parents=True, exist_ok=True)
            for path in (prov_dir, models_dir):
                init = path / "__init__.py"
                if not init.exists():
                    init.write_text(f'"""{path.name} subpackage."""\n')
            (prov_dir / "__init__.py").write_text(prov.source)
            for fetcher in self.fetchers_by_provider.get(prov.provider_name, []):
                (models_dir / f"{fetcher.module_name}.py").write_text(fetcher.source)

        if self.post_commands:
            tools_models = providers_dir / "tools" / "models"
            tools_models.mkdir(parents=True, exist_ok=True)
            for path in (providers_dir / "tools", tools_models):
                init = path / "__init__.py"
                if not init.exists():  # pragma: no cover
                    init.write_text(f'"""{path.name} subpackage."""\n')
            for post in self.post_commands:
                (tools_models / f"{post.module_name}.py").write_text(post.source)

        if self.test_modules:
            tests_dir = self.root / "tests"
            tests_dir.mkdir(parents=True, exist_ok=True)
            init = tests_dir / "__init__.py"
            if not init.exists():
                init.write_text('"""Auto-generated tests."""\n')
            for tm in self.test_modules:
                (tests_dir / f"{tm.module_name}.py").write_text(tm.source)

        (self.root / "pyproject.toml").write_text(self.project.source)
        (self.root / "README.md").write_text(self._readme())
        _apply_ruff(self.root)
        return self.root

    def _readme(self) -> str:
        """Render a README that describes the actual generated surface."""
        ns = self.root_namespace or self.project.package_name
        total_get = sum(len(v) for v in self.fetchers_by_provider.values())
        total_post = len(self.post_commands)
        source = self.base_url or "the source OpenAPI spec"

        sections: list[str] = []
        sections.append(f"# {self.project.project_name}\n")
        sections.append(
            f"OpenBB Platform extension generated from {source}. "
            f"Adds {total_get} GET command{'s' if total_get != 1 else ''}"
            + (
                f" and {total_post} POST command{'s' if total_post != 1 else ''}"
                if total_post
                else ""
            )
            + f" under `obb.{ns}.*`.\n"
        )

        sections.append("## Install\n")
        sections.append("```bash")
        sections.append("pip install -e .")
        sections.append("openbb-build")
        sections.append("```\n")

        sections.append("## Quick start\n")
        first_cmd = self._first_command_example(ns)
        if first_cmd is not None:
            dotted, model = first_cmd
            sections.append("```python")
            sections.append("from openbb import obb")
            sections.append("")
            sections.append(f"# {model}")
            sections.append(f"result = obb.{ns}.{dotted}()")
            sections.append("print(result.to_df())")
            sections.append("```\n")

        sections.append(self._providers_section(ns))
        sections.append(self._commands_section(ns))

        creds = self._unique_credentials()
        if creds:
            sections.append(self._credentials_section(creds))

        sections.append(self._notes_section(ns))

        return "\n".join(sections).rstrip() + "\n"

    def _first_command_example(self, ns: str) -> tuple[str, str] | None:
        """Pick a representative command to seed the Quick start snippet."""
        for prov in sorted(self.commands_by_provider):
            cmds = sorted(self.commands_by_provider[prov])
            if not cmds:
                continue
            dotted = cmds[0]
            fetcher = next(
                (
                    f
                    for f in self.fetchers_by_provider.get(prov, [])
                    if f"{ns}_{f.module_name}".endswith(dotted.replace(".", "_"))
                    or f.module_name == dotted.replace(".", "_")
                ),
                None,
            )
            model = fetcher.model_name if fetcher else "Returns OBBject"
            return dotted, model
        return None

    def _providers_section(self, ns: str) -> str:
        lines = ["## Providers\n"]
        for p in self.providers:
            cmd_count = len(self.commands_by_provider.get(p.provider_name, []))
            label = "command" if cmd_count == 1 else "commands"
            cred_note = (
                f" — credentials: {', '.join(f'`{k}`' for k in p.credential_keys)}"
                if p.credential_keys
                else ""
            )
            lines.append(f"- **{p.provider_name}** ({cmd_count} {label}){cred_note}")
        return "\n".join(lines) + "\n"

    def _commands_section(self, ns: str) -> str:
        lines = ["## Commands\n"]
        lines.append(
            f"Every command lands at `obb.{ns}.<dotted.path>` with a typed "
            "signature, full Pydantic validation, and `OBBject` results.\n"
        )
        groups: dict[str, list[tuple[str, str]]] = {}
        for prov, dotted_paths in self.commands_by_provider.items():
            for dotted in sorted(dotted_paths):
                top = dotted.split(".", 1)[0]
                groups.setdefault(top, []).append((dotted, prov))
        for top in sorted(groups):
            lines.append(f"### `obb.{ns}.{top}`\n")
            for dotted, prov in groups[top]:
                lines.append(f"- `obb.{ns}.{dotted}` — provider: `{prov}`")
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _unique_credentials(self) -> list[str]:
        seen: set[str] = set()
        for p in self.providers:
            seen.update(p.credential_keys)
        return sorted(seen)

    def _credentials_section(self, creds: list[str]) -> str:
        lines = ["## Credentials\n"]
        lines.append(
            "Set these in `~/.openbb_platform/user_settings.json` under the "
            "matching `<provider>_<key>` field, or pass via the `OBB_USER_SETTINGS` "
            "env var:\n"
        )
        for c in creds:
            lines.append(f"- `{c}`")
        lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    def _notes_section(self, ns: str) -> str:
        return (
            "## Notes\n\n"
            "- Routers mount under a single root namespace "
            f"(`obb.{ns}.*`) so the extension never shadows OpenBB's own "
            "first-party routers.\n"
            "- Each `aextract_data` strips single-key envelopes and unpacks "
            "single-element lists at the response boundary; sibling scalar "
            "fields surface as `AnnotatedResult` metadata in `OBBject.extra`.\n"
            "- Non-JSON responses (XML, CSV, plain text) come back as a "
            "single-row dict with `content` / `content_type` rather than "
            "raising on parse.\n"
        )


def _slugify(text: str) -> str:
    """Lower-case + collapse non-alphanumerics to single underscores."""
    cleaned = re.sub(r"[^0-9a-zA-Z]+", "_", text).strip("_").lower()
    return cleaned or "extension"


def _apply_ruff(root: Path) -> None:
    """Run ``ruff check --fix --unsafe-fixes`` and ``ruff format`` over ``root``."""
    ruff = _find_ruff()
    if ruff is None:
        return
    target = str(root)
    subprocess.run(  # noqa: S603
        [ruff, "check", "--fix", "--unsafe-fixes", "--quiet", target],
        check=False,
    )
    subprocess.run(  # noqa: S603
        [ruff, "format", "--quiet", target],
        check=False,
    )


def _find_ruff() -> str | None:
    """Locate the ``ruff`` binary; checks the running Python env first."""
    sibling = Path(sys.executable).parent / "ruff"
    if sibling.exists():
        return str(sibling)
    return shutil.which("ruff")


def _build_root_router(
    *,
    package_name: str,
    root_namespace: str,
    sub_routers: list[GeneratedRouter],
    root_commands: list[str] | None = None,
    root_post_imports: list[tuple[str, str]] | None = None,
    root_has_stream: bool = False,
) -> GeneratedRouter:
    """Emit a top-level router that mounts every namespace under ``root_namespace``.

    Top-level leaf commands (no namespace of their own) are rendered directly
    on this router; unused imports are cleaned up by the ruff pass.
    """
    commands = root_commands or []
    post_imports = root_post_imports or []
    parts: list[str] = [
        f'"""Root router for {root_namespace} — generated from spec."""',
        "",
    ]
    if commands:
        parts.append("from openbb_core.app.model.command_context import CommandContext")
        parts.append("from openbb_core.app.model.obbject import OBBject")
        if root_has_stream:
            parts.append("from openbb_core.app.model.stream import OBBStream")
        parts.append(
            "from openbb_core.app.provider_interface import "
            "ExtraParams, ProviderChoices, StandardParams"
        )
        parts.append("from openbb_core.app.query import Query")
    parts.append("from openbb_core.app.router import Router")
    if post_imports:
        parts.append("")
        for module_path, function_name in post_imports:
            parts.append(
                f"from {module_path} import {function_name} as _{function_name}"
            )
    if sub_routers:
        parts.append("")
        for r in sub_routers:
            parts.append(
                f"from {package_name}.routers.{r.module_name} import "
                f"router as _{r.module_name}_router"
            )
    parts.append("")
    parts.append("")
    parts.append('router = Router(prefix="")')
    if sub_routers:
        parts.append("")
        for r in sub_routers:
            parts.append(
                f"router.include_router(_{r.module_name}_router, "
                f'prefix="/{r.module_name}")'
            )
    if commands:
        parts.append("")
        parts.extend(commands)
    # The root router's file must not share a name with a namespace router: a
    # spec with a top-level ``congress`` namespace under a provider named
    # ``congress`` would otherwise overwrite it and the root would import itself.
    taken = {r.module_name.lower() for r in sub_routers}
    module_name = root_namespace
    while module_name.lower() in taken:
        module_name = f"{module_name}_root"
    return GeneratedRouter(
        module_name=module_name,
        entry_point_name=root_namespace,
        source="\n".join(parts).rstrip() + "\n",
    )


def _assert_unique_router_modules(routers: list[GeneratedRouter]) -> None:
    """Refuse to emit routers that would overwrite each other's files.

    Every router is one module; two sharing a name (case-insensitively, for
    case-folding filesystems) means one silently replaces the other and the
    survivor can import itself. Router modules only ever import their own
    children, so unique names are what keeps the import graph acyclic.
    """
    seen: dict[str, str] = {}
    for r in routers:
        key = r.module_name.lower()
        if key in seen:
            raise ValueError(
                f"Router module name collision: {r.module_name!r} and "
                f"{seen[key]!r} would both be written to routers/{key}.py. "
                "Rename one namespace in the spec, or use --router-name."
            )
        seen[key] = r.module_name
    _assert_acyclic(routers)


def _assert_acyclic(routers: list[GeneratedRouter]) -> None:
    """Raise if the routers' ``from ...routers.<x> import`` graph has a cycle."""
    import re

    edges = {
        r.module_name: set(re.findall(r"\.routers\.(\w+) import", r.source))
        for r in routers
    }
    state: dict[str, int] = {}

    def visit(node: str, path: list[str]) -> None:
        if state.get(node) == 2:
            return
        if state.get(node) == 1:
            cycle = " -> ".join([*path[path.index(node) :], node])
            raise ValueError(f"Circular router import in generated package: {cycle}")
        state[node] = 1
        for nxt in sorted(edges.get(node, ())):
            visit(nxt, [*path, node])
        state[node] = 2

    for name in edges:
        visit(name, [])


_SKIP_TOP_NAMESPACES: frozenset[str] = frozenset({"coverage"})


def _runtime_utils_source() -> str:
    """Read the canonical ``unpack_response`` source from ``_unpack.py``."""
    from pathlib import Path

    text = (
        Path(__file__)
        .resolve()
        .parent.parent.joinpath("dispatchers", "_unpack.py")
        .read_text()
    )
    return text


RUNTIME_UTILS_SOURCE = _runtime_utils_source()


def generate_packages(
    spec_doc: dict[str, Any],
    *,
    output_root: Path,
    provider_name: str | None = None,
    project_name: str | None = None,
    package_name: str | None = None,
    router_name: str | None = None,
    description: str | None = None,
    website: str | None = None,
    version: str = "0.1.0",
) -> GeneratedPackageSet:
    """Build ONE ``GeneratedPackage`` bundling every provider in ``spec_doc``.

    Parameters
    ----------
    spec_doc : dict
        Loaded ``.spec`` document.
    output_root : Path
        Directory under which the project is created.
    provider_name : str, optional
        Project / package slug.
    project_name, package_name, description, website : str, optional
        Project-level overrides.
    router_name : str, optional
        Overrides the generated top-level router's module/entry-point name.
        Defaults to ``provider_name``.
    version : str
        Initial version string for ``pyproject.toml``.

    Returns
    -------
    GeneratedPackageSet
        Single-element wrapper around the project.
    """
    base_url = (spec_doc.get("base_url") or "").rstrip("/")
    api_prefix = spec_doc.get("api_prefix") or ""
    fixed_headers = {str(k): str(v) for k, v in (spec_doc.get("headers") or {}).items()}
    filtered_commands = {
        name: cmd
        for name, cmd in (spec_doc.get("commands") or {}).items()
        if name.split(".", 1)[0] not in _SKIP_TOP_NAMESPACES
    }
    full_tree = build_namespace_tree(filtered_commands)
    declared_providers = providers_from_tree(full_tree)

    project_slug = _slugify(provider_name or "codegen")
    project_name = project_name or f"openbb-{project_slug.replace('_', '-')}"
    package_name = package_name or f"openbb_{project_slug}"
    description = (
        description or f"Generated OpenBB Platform extension bundle ({project_slug})."
    )
    website = website or base_url

    fetchers_by_provider: dict[str, list[GeneratedFetcher]] = {}
    post_commands: list[GeneratedPostCommand] = []
    fetchers_index: dict[str, GeneratedFetcher] = {}
    post_index: dict[str, GeneratedPostCommand] = {}

    if not declared_providers:
        target_providers: list[str] = [_slugify(provider_name or "default")]
    else:
        target_providers = sorted(declared_providers)

    commands_by_provider: dict[str, list[str]] = {}
    commands_by_dotted: dict[str, dict[str, Any]] = {}

    for dotted, cmd_spec in iter_commands(full_tree):
        commands_by_dotted[dotted] = cmd_spec
        method = (cmd_spec.get("method") or "get").lower()
        body = cmd_spec.get("request_body_schema")
        has_body = isinstance(body, dict) and (
            body.get("properties") or body.get("type") == "array"
        )
        cmd_providers = cmd_spec.get("providers") or []

        if method == "post" and has_body:
            post = generate_post_command_module(
                PostCommandSpec(
                    name=dotted,
                    cmd_spec=cmd_spec,
                    base_url=base_url,
                    api_prefix=api_prefix,
                    provider_name="tools",
                    headers=fixed_headers,
                )
            )
            post_commands.append(post)
            post_index[dotted] = post
            commands_by_provider.setdefault("tools", []).append(dotted)
            continue

        owners = (
            [p for p in target_providers if p in cmd_providers]
            if cmd_providers
            else target_providers
        )
        if not owners:  # pragma: no cover
            continue
        for prov in owners:
            fetcher = generate_fetcher_module(
                FetcherCommandSpec(
                    name=dotted,
                    cmd_spec=cmd_spec,
                    base_url=base_url,
                    api_prefix=api_prefix,
                    provider_name=prov,
                    headers=fixed_headers,
                )
            )
            fetchers_by_provider.setdefault(prov, []).append(fetcher)
            commands_by_provider.setdefault(prov, []).append(dotted)
            fetchers_index.setdefault(dotted, fetcher)

    routers = generate_routers(
        full_tree,
        package_name=package_name,
        provider_name="",
        fetchers_by_command=fetchers_index,
        post_commands_by_command=post_index,
    )
    for r in routers.routers:
        r.source = r.source.replace(
            f"{package_name}.providers..models.",
            f"{package_name}.providers.tools.models.",
        )
    routers.root_post_imports = [
        (
            module_path.replace(
                f"{package_name}.providers..models.",
                f"{package_name}.providers.tools.models.",
            ),
            function_name,
        )
        for module_path, function_name in routers.root_post_imports
    ]

    root_namespace = _slugify(router_name or provider_name or project_slug)
    sub_routers = [r for r in routers.routers if r.entry_point_name]
    for r in sub_routers:
        r.entry_point_name = None
    root_router = _build_root_router(
        package_name=package_name,
        root_namespace=root_namespace,
        sub_routers=sub_routers,
        root_commands=routers.root_commands,
        root_post_imports=routers.root_post_imports,
        root_has_stream=routers.root_has_stream,
    )
    routers.routers.append(root_router)
    _assert_unique_router_modules(routers.routers)

    providers: list[GeneratedProvider] = []
    for prov in target_providers:
        providers.append(
            generate_provider_module(
                package_name=package_name,
                provider_name=prov,
                description=f"{prov} provider proxied through {base_url}.",
                website=website,
                fetchers=fetchers_by_provider.get(prov, []),
            )
        )
    if post_commands:
        providers.append(
            generate_provider_module(
                package_name=package_name,
                provider_name="tools",
                description=(
                    "Local-compute commands (econometrics, quantitative, "
                    f"technical) proxied through {base_url}."
                ),
                website=website,
                fetchers=[],
            )
        )

    project = generate_pyproject(
        project_name=project_name,
        package_name=package_name,
        providers=[p.provider_name for p in providers],
        routers=[r for r in routers.routers if r.entry_point_name],
        description=description,
        version=version,
        spec_provenance={
            "source_url": str(spec_doc.get("source_url") or ""),
            "api_version": str(spec_doc.get("api_version") or ""),
            "generator": str(spec_doc.get("generator") or ""),
            "generated_at": str(spec_doc.get("generated_at") or ""),
            "spec_version": str(spec_doc.get("version") or ""),
            "spec_sha256": str(spec_doc.get("content_sha256") or ""),
        },
    )

    test_modules: list[GeneratedTestModule] = []
    for prov in target_providers:
        tm = generate_provider_tests(
            package_name=package_name,
            provider_name=prov,
            fetchers=fetchers_by_provider.get(prov, []),
            commands_by_dotted=commands_by_dotted,
        )
        if tm is not None:
            test_modules.append(tm)

    package = GeneratedPackage(
        root=Path(output_root) / project_name,
        project=project,
        providers=providers,
        routers=routers,
        fetchers_by_provider=fetchers_by_provider,
        post_commands=post_commands,
        top_level_routers=[
            r.entry_point_name for r in routers.routers if r.entry_point_name
        ],
        root_namespace=root_namespace,
        base_url=base_url,
        commands_by_provider=commands_by_provider,
        test_modules=test_modules,
    )
    return GeneratedPackageSet(packages=[package])


@dataclass
class GeneratedPackageSet:
    """Wrapper around the generated package list (kept for caller symmetry)."""

    packages: list[GeneratedPackage] = field(default_factory=list)

    def write(self) -> list[Path]:
        """Materialize every package; returns the list of written roots."""
        return [pkg.write() for pkg in self.packages]
