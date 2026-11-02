"""Generate ``pyproject.toml`` and the package skeleton files."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class GeneratedProject:
    """Output of ``generate_pyproject``.

    Parameters
    ----------
    project_name : str
        PyPI distribution name.
    package_name : str
        Snake-case Python package name.
    source : str
        Full ``pyproject.toml`` contents.
    """

    project_name: str
    package_name: str
    source: str


def generate_pyproject(
    *,
    project_name: str,
    package_name: str,
    providers: list[str],
    routers: list,
    description: str,
    version: str = "0.1.0",
    spec_provenance: dict[str, str] | None = None,
) -> GeneratedProject:
    """Render a PEP 621 + Hatchling ``pyproject.toml`` for the bundled extension.

    Parameters
    ----------
    project_name : str
        PyPI / distribution name.
    package_name : str
        Python package directory name (snake_case).
    providers : list of str
        Provider identifiers.
    routers : list of GeneratedRouter
        Top-level routers.
    description : str
        Free-form description for ``[project] description``.
    version : str
        Initial version string.

    Returns
    -------
    GeneratedProject
        Project metadata plus the ``pyproject.toml`` source.
    """
    provider_entries = "\n".join(
        f'{p} = "{package_name}.providers.{p}:{p}_provider"' for p in sorted(providers)
    )
    router_entries = "\n".join(
        f'{r.entry_point_name} = "{package_name}.routers.{r.module_name}:router"'
        for r in routers
        if r.entry_point_name
    )
    provenance_block = _render_provenance_block(spec_provenance or {})
    body = f"""[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"


[project]
name = "{project_name}"
version = "{version}"
description = {description!r}
requires-python = ">=3.11,<4"
license = {{ text = "Apache-2.0" }}
dependencies = [
    "openbb-core>=2.0.0",
]


[tool.hatch.build.targets.wheel]
packages = ["{package_name}"]


[project.entry-points."openbb_provider_extension"]
{provider_entries}

[project.entry-points."openbb_core_extension"]
{router_entries}
{provenance_block}
[tool.ruff]
line-length = 100
target-version = "py310"

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "D"]
ignore = [
    "D100", "D101", "D102", "D103", "D104", "D105", "D107",
    "D200", "D205", "D212", "D401", "D415",
    "E501", "B008",
]

[tool.ruff.lint.pydocstyle]
convention = "numpy"
"""
    return GeneratedProject(
        project_name=project_name,
        package_name=package_name,
        source=body,
    )


def _render_provenance_block(provenance: dict[str, str]) -> str:
    """Render ``[tool.openbb-codegen]`` (empty string when no provenance)."""
    keys = (
        "source_url",
        "api_version",
        "generator",
        "generated_at",
        "spec_version",
        "spec_sha256",
    )
    entries = [(k, provenance[k]) for k in keys if provenance.get(k)]
    if not entries:
        return ""
    body = "\n".join(f"{k} = {v!r}" for k, v in entries)
    return f"\n[tool.openbb-codegen]\n{body}\n"
