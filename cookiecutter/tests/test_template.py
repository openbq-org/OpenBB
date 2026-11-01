"""Tests for the project template."""

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from cookiecutter.exceptions import FailedHookException
from cookiecutter.main import cookiecutter

from openbb_cookiecutter import get_template_path

PACKAGE = "extension_template"


def generate(tmp_path: Path, extension_types: str, **context: str) -> Path:
    return Path(
        cookiecutter(
            str(get_template_path()),
            output_dir=str(tmp_path),
            no_input=True,
            extra_context={"extension_types": extension_types, **context},
        )
    )


def files(project: Path) -> set[str]:
    return {
        p.relative_to(project).as_posix() for p in project.rglob("*") if p.is_file()
    }


def entry_points(project: Path) -> dict:
    return tomllib.loads((project / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ].get("entry-points", {})


class TestGeneratedFiles:
    """Each extension type generates only its own modules and tests."""

    @pytest.mark.parametrize(
        ("extension_types", "expected"),
        [
            (
                "router",
                {
                    f"{PACKAGE}/routers/template.py",
                    "tests/test_router.py",
                },
            ),
            (
                "provider",
                {
                    f"{PACKAGE}/providers/template/models/example.py",
                    f"{PACKAGE}/providers/template/models/equity_historical.py",
                    "tests/test_provider.py",
                },
            ),
            (
                "obbject",
                {
                    f"{PACKAGE}/obbject/template_ext/__init__.py",
                    "tests/test_obbject.py",
                },
            ),
            (
                "on_command_output",
                {
                    f"{PACKAGE}/obbject/template_ext/on_command_output.py",
                    "tests/test_on_command_output.py",
                },
            ),
            (
                "charting",
                {
                    f"{PACKAGE}/routers/template_views.py",
                    "tests/test_views.py",
                },
            ),
        ],
    )
    def test_single_type(self, tmp_path, extension_types, expected):
        generated = files(generate(tmp_path, extension_types))
        optional = {
            f"{PACKAGE}/routers/template.py",
            f"{PACKAGE}/routers/template_views.py",
            f"{PACKAGE}/providers/template/models/example.py",
            f"{PACKAGE}/obbject/template_ext/on_command_output.py",
            "tests/test_router.py",
            "tests/test_views.py",
            "tests/test_provider.py",
            "tests/test_obbject.py",
            "tests/test_on_command_output.py",
        }
        assert expected <= generated
        assert not (optional - expected) & generated

    def test_all_types(self, tmp_path):
        generated = files(generate(tmp_path, "all"))
        assert {
            "pyproject.toml",
            "README.md",
            ".gitignore",
            f"{PACKAGE}/routers/template.py",
            f"{PACKAGE}/routers/template_views.py",
            f"{PACKAGE}/providers/template/__init__.py",
            f"{PACKAGE}/obbject/template_ext/__init__.py",
            f"{PACKAGE}/obbject/template_ext/on_command_output.py",
            "tests/test_router.py",
            "tests/test_views.py",
            "tests/test_provider.py",
            "tests/test_obbject.py",
            "tests/test_on_command_output.py",
        } <= generated

    def test_local_artifacts_are_not_copied(self, tmp_path):
        generated = files(generate(tmp_path, "all"))
        artifacts = (".ruff_cache", ".ipynb_checkpoints", "__pycache__", ".DS_Store")
        assert not [f for f in generated if any(a in f for a in artifacts)]


class TestPyproject:
    """The generated pyproject declares V5 packaging and entry points."""

    def test_build_and_dependencies(self, tmp_path):
        pyproject = tomllib.loads(
            (generate(tmp_path, "all") / "pyproject.toml").read_text(encoding="utf-8")
        )
        assert pyproject["build-system"]["build-backend"] == "hatchling.build"
        assert pyproject["project"]["dependencies"] == ["openbb-core[pandas]>=2.0.0"]
        assert pyproject["project"]["optional-dependencies"] == {
            "charting": ["openbb-charting>=3.0.0"]
        }
        assert "openbb-devtools>=2.0.1" in pyproject["dependency-groups"]["dev"]

    def test_entry_points_for_all_types(self, tmp_path):
        assert entry_points(generate(tmp_path, "all")) == {
            "openbb_core_extension": {
                "template": f"{PACKAGE}.routers.template:router",
            },
            "openbb_charting_extension": {
                "template": f"{PACKAGE}.routers.template_views:TemplateViews",
            },
            "openbb_provider_extension": {
                "template": f"{PACKAGE}.providers.template:template_provider",
            },
            "openbb_obbject_extension": {
                "to_string": f"{PACKAGE}.obbject.template_ext:ext",
                "template_ext": f"{PACKAGE}.obbject.template_ext:class_ext",
                "nonblocking_plugin": (
                    f"{PACKAGE}.obbject.template_ext.on_command_output:nonblocking_plugin"
                ),
            },
        }

    def test_entry_points_for_router_only(self, tmp_path):
        assert entry_points(generate(tmp_path, "router")) == {
            "openbb_core_extension": {
                "template": f"{PACKAGE}.routers.template:router",
            },
        }


class TestHooks:
    """The post-generation hook validates names."""

    def test_rejects_invalid_package_name(self, tmp_path):
        with pytest.raises(FailedHookException):
            generate(tmp_path, "router", package_name="1-bad")

    def test_rejects_shared_provider_and_obbject_name(self, tmp_path):
        with pytest.raises(FailedHookException):
            generate(tmp_path, "all", obbject_name="template")


@pytest.mark.skipif(shutil.which("ruff") is None, reason="ruff is not installed")
class TestGeneratedCodeQuality:
    """Generated projects pass their own lint and type checks."""

    @pytest.mark.parametrize(
        "extension_types",
        ["router", "provider", "obbject", "on_command_output", "charting", "all"],
    )
    def test_ruff(self, tmp_path, extension_types):
        project = generate(tmp_path, extension_types)
        for command in (["format", "--check"], ["check", "--no-fix"]):
            result = subprocess.run(
                ["ruff", *command, "--no-cache", "."],
                cwd=project,
                capture_output=True,
                text=True,
                check=False,
            )
            assert result.returncode == 0, result.stdout + result.stderr

    @pytest.mark.skipif(shutil.which("ty") is None, reason="ty is not installed")
    def test_ty(self, tmp_path):
        project = generate(tmp_path, "all")
        result = subprocess.run(
            ["ty", "check", "--python", sys.executable, PACKAGE],
            cwd=project,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
