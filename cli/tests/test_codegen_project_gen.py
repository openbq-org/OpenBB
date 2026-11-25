"""Tests for openbb_cli.codegen.project_gen — pyproject.toml emission."""

from __future__ import annotations

from dataclasses import dataclass

from openbb_cli.codegen import project_gen as pg


@dataclass
class _Router:
    entry_point_name: str | None
    module_name: str


def test_generate_pyproject_emits_provider_and_router_entry_points():
    routers = [
        _Router(entry_point_name="equity", module_name="equity"),
        _Router(entry_point_name="economy", module_name="economy"),
    ]
    out = pg.generate_pyproject(
        project_name="openbb-codegen",
        package_name="openbb_codegen",
        providers=["fmp", "intrinio"],
        routers=routers,
        description="Generated extension.",
    )

    assert isinstance(out, pg.GeneratedProject)
    assert out.project_name == "openbb-codegen"
    assert out.package_name == "openbb_codegen"

    src = out.source
    assert 'name = "openbb-codegen"' in src
    assert 'version = "0.1.0"' in src
    assert "description = 'Generated extension.'" in src
    assert 'packages = ["openbb_codegen"]' in src
    # Provider entry-points (sorted alphabetically)
    assert (
        'fmp = "openbb_codegen.providers.fmp:fmp_provider"\n'
        'intrinio = "openbb_codegen.providers.intrinio:intrinio_provider"'
    ) in src
    # Router entry-points
    assert 'equity = "openbb_codegen.routers.equity:router"' in src
    assert 'economy = "openbb_codegen.routers.economy:router"' in src


def test_generate_pyproject_skips_routers_without_entry_point():
    routers = [
        _Router(entry_point_name=None, module_name="equity_price"),
        _Router(entry_point_name="equity", module_name="equity"),
    ]
    out = pg.generate_pyproject(
        project_name="openbb-x",
        package_name="openbb_x",
        providers=[],
        routers=routers,
        description="d",
    )
    assert "equity_price" not in out.source
    assert 'equity = "openbb_x.routers.equity:router"' in out.source


def test_generate_pyproject_respects_custom_version():
    out = pg.generate_pyproject(
        project_name="openbb-x",
        package_name="openbb_x",
        providers=[],
        routers=[],
        description="d",
        version="1.2.3",
    )
    assert 'version = "1.2.3"' in out.source


def test_generate_pyproject_emits_provenance_block_when_provided():
    out = pg.generate_pyproject(
        project_name="openbb-x",
        package_name="openbb_x",
        providers=[],
        routers=[],
        description="d",
        spec_provenance={
            "source_url": "https://example.com/openapi.json",
            "api_version": "3.0.0",
            "generator": "openbb-cli==2.0.0",
            "generated_at": "2026-05-02T12:00:00+00:00",
            "spec_version": "5",
            "spec_sha256": "deadbeef" * 8,
        },
    )
    src = out.source
    assert "[tool.openbb-codegen]" in src
    assert "source_url = 'https://example.com/openapi.json'" in src
    assert "api_version = '3.0.0'" in src
    assert "generator = 'openbb-cli==2.0.0'" in src
    assert "generated_at = '2026-05-02T12:00:00+00:00'" in src
    assert "spec_version = '5'" in src
    assert f"spec_sha256 = '{'deadbeef' * 8}'" in src


def test_generate_pyproject_omits_provenance_block_when_empty():
    out = pg.generate_pyproject(
        project_name="openbb-x",
        package_name="openbb_x",
        providers=[],
        routers=[],
        description="d",
        spec_provenance={"source_url": "", "api_version": ""},
    )
    assert "[tool.openbb-codegen]" not in out.source


def test_generate_pyproject_ruff_config_ignores_ambiguous_field_names():
    """Upstream schemas name fields ``l`` (low, last id); E741 would flag every one."""
    out = pg.generate_pyproject(
        project_name="openbb-codegen",
        package_name="openbb_codegen",
        providers=["fmp"],
        routers=[],
        description="Generated extension.",
    )
    assert '"E501", "E741", "B008",' in out.source
