"""Session-scoped fixture that builds & installs a synthetic OpenBB extension.

This is the integration substrate for tests that need a *real* ``from
openbb import obb`` to expose a real command. Rather than depending on
the developer having any of the production extensions
(``openbb-fixedincome``, ``openbb-equity``, ``openbb-fmp``, …)
installed, the fixture writes a self-contained extension distribution
to disk, ``pip install``s it into the current interpreter, and runs
``openbb-build`` so the static package under ``openbb/package/`` is
regenerated with that extension's command(s) baked in.

Because the static package is wired via entry points discovered at
*interpreter start*, every test that imports ``openbb`` after the build
must do so in a fresh ``python`` subprocess. The fixture exposes a
helper, ``run_in_obb``, that runs an inline snippet of code in a child
interpreter with the freshly-built package on its path.

Cleanup: after the session, the synthetic distribution is uninstalled
and the generated ``openbb/package/`` and ``openbb/assets/`` directories
are restored to their pre-test state.
"""

import contextlib
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

CORE_DIR = Path(__file__).resolve().parents[1]
OPENBB_DIR = CORE_DIR / "openbb"
PACKAGE_DIR = OPENBB_DIR / "package"
ASSETS_DIR = OPENBB_DIR / "assets"

EXT_NAME = "openbb-fake-integration"
EXT_PKG = "openbb_fake_integration"


PYPROJECT = """\
[project]
name = "{ext_name}"
version = "0.0.1"
requires-python = ">=3.11,<4"
dependencies = ["openbb-core"]

[project.entry-points."openbb_core_extension"]
fake_integration = "{pkg}.router:router"

[project.entry-points."openbb_provider_extension"]
fake_integration = "{pkg}:fake_integration_provider"

[project.entry-points."openbb_obbject_extension"]
fake_accessor = "{pkg}.accessor:ext"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["{pkg}"]
"""

INIT_PY = '''\
"""Synthetic provider for OpenBB integration tests."""

from typing import Any

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.provider import Provider
from openbb_core.provider.standard_models.available_indicators import (
    AvailableIndicatorsData,
    AvailableIndicesQueryParams,
)


class _FakeIntegrationData(AvailableIndicatorsData):
    """Provider-specific data for the fake_integration provider."""

    extra: str | None = None


class _FakeIntegrationFetcher(
    Fetcher[AvailableIndicesQueryParams, list[_FakeIntegrationData]]
):
    """Deterministic fetcher: returns one row regardless of input."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> AvailableIndicesQueryParams:
        return AvailableIndicesQueryParams(**params)

    @staticmethod
    def extract_data(
        query: AvailableIndicesQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        return [{"symbol": "FAKE", "extra": "ok"}]

    @staticmethod
    def transform_data(
        query: AvailableIndicesQueryParams,
        data: list[dict[str, Any]],
        **kwargs,
    ) -> list[_FakeIntegrationData]:
        return [_FakeIntegrationData(**row) for row in data]


fake_integration_provider = Provider(
    name="fake_integration",
    description="Synthetic provider used by the openbb-core integration suite.",
    website="https://example.invalid",
    credentials=None,
    fetcher_dict={"AvailableIndicators": _FakeIntegrationFetcher},
)
'''

ROUTER_PY = '''\
"""Synthetic router for OpenBB integration tests."""

from openbb_core.app.model.command_context import CommandContext
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.provider_interface import (
    ExtraParams,
    ProviderChoices,
    StandardParams,
)
from openbb_core.app.query import Query
from openbb_core.app.router import Router

router = Router(prefix="", description="Fake integration extension.")


@router.command(model="AvailableIndicators")
async def list_indicators(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Return synthetic indicator rows for integration testing."""
    return await OBBject.from_query(Query(**locals()))
'''


ACCESSOR_PY = '''\
"""Synthetic OBBject accessor extension.

Demonstrates the ``openbb_obbject_extension`` entry-point group.
``Extension.obbject_accessor`` registers ``FakeAccessor`` as
``OBBject.fake_accessor``, so any ``OBBject`` instance can call
``result.fake_accessor.upper_symbols()`` (the typical pandas-style
accessor pattern).
"""

from openbb_core.app.model.extension import Extension

ext = Extension(name="fake_accessor", description="Fake accessor for integration tests.")


@ext.obbject_accessor
class FakeAccessor:
    """Custom accessor exposed as ``OBBject.fake_accessor``."""

    def __init__(self, obbject):
        """Hold a reference to the wrapped OBBject (pandas-accessor pattern)."""
        self._obbject = obbject

    def upper_symbols(self) -> list[str]:
        """Return the symbol field of every row, uppercased."""
        out = []
        for row in self._obbject.results or []:
            sym = (
                row.symbol
                if hasattr(row, "symbol")
                else (row.get("symbol") if isinstance(row, dict) else None)
            )
            if sym is not None:
                out.append(str(sym).upper())
        return out

    def row_count(self) -> int:
        """Return the number of result rows."""
        return len(self._obbject.results or [])
'''


def _snapshot_dir(src: Path, dst: Path) -> None:
    if src.exists():
        shutil.copytree(src, dst, dirs_exist_ok=True)


def _restore_dir(src: Path, dst: Path) -> None:
    shutil.rmtree(dst, ignore_errors=True)
    if src.exists():
        shutil.copytree(src, dst)


def _pip(*args: str) -> None:
    subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pip", *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build a subprocess env that opts into coverage.py auto-startup if a config exists.

    Strips ``COV_CORE_*`` so the child does not also try to bootstrap via
    ``pytest_cov.embed.init()`` (which would race with ``coverage.process_startup``
    and write into the parent's locked data file).
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("COV_CORE_")}
    rcfile = CORE_DIR / ".coveragerc"
    if rcfile.exists():
        env["COVERAGE_PROCESS_START"] = str(rcfile)
    if extra:
        env.update(extra)
    return env


def _run_openbb_build() -> None:
    """Invoke ``openbb-build`` in a fresh subprocess.

    A child process is required because ``ExtensionLoader``/``RouterLoader``
    cache entry points at module load time; the parent process cannot
    discover the freshly-installed distribution without a restart.
    """
    env = _subprocess_env({"OPENBB_AUTO_BUILD": "true"})
    subprocess.run(
        [sys.executable, "-c", "import openbb"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture(scope="session")
def fake_extension_installed(tmp_path_factory):
    """Build, install, openbb-build, yield, then uninstall and restore."""
    work = tmp_path_factory.mktemp("fake_ext_dist")
    pkg_dir = work / EXT_PKG
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text(INIT_PY, encoding="utf-8")
    (pkg_dir / "router.py").write_text(ROUTER_PY, encoding="utf-8")
    (pkg_dir / "accessor.py").write_text(ACCESSOR_PY, encoding="utf-8")
    (work / "pyproject.toml").write_text(
        PYPROJECT.format(ext_name=EXT_NAME, pkg=EXT_PKG), encoding="utf-8"
    )

    snapshot_root = tmp_path_factory.mktemp("openbb_snapshot")
    pkg_snapshot = snapshot_root / "package"
    assets_snapshot = snapshot_root / "assets"
    _snapshot_dir(PACKAGE_DIR, pkg_snapshot)
    _snapshot_dir(ASSETS_DIR, assets_snapshot)

    try:
        _pip("install", "--no-deps", "-e", str(work))
        # The parent pytest interpreter processed `.pth` files at startup, so
        # the editable install isn't visible to `import` here even though
        # `importlib.metadata.entry_points()` will return the new entry point.
        # Add the source dir to sys.path so subsequent unit tests in this same
        # process that instantiate `ExtensionLoader` can `ep.load()` it.
        if str(work) not in sys.path:
            sys.path.insert(0, str(work))
        _run_openbb_build()

        ext_pkg_module = PACKAGE_DIR / "fake_integration.py"
        if not ext_pkg_module.exists():
            pytest.fail(
                "openbb-build did not emit fake_integration.py; "
                f"contents of {PACKAGE_DIR}: "
                f"{sorted(p.name for p in PACKAGE_DIR.glob('*.py'))}"
            )

        yield {
            "ext_name": EXT_NAME,
            "ext_pkg": EXT_PKG,
            "package_dir": PACKAGE_DIR,
            "assets_dir": ASSETS_DIR,
        }
    finally:
        with contextlib.suppress(subprocess.CalledProcessError):
            _pip("uninstall", "-y", EXT_NAME)
        with contextlib.suppress(ValueError):
            sys.path.remove(str(work))
        # Drop any cached imports of the synthetic package so later tests
        # that re-instantiate `ExtensionLoader` don't see a phantom module.
        for mod_name in [m for m in sys.modules if m.startswith(EXT_PKG)]:
            del sys.modules[mod_name]
        _restore_dir(pkg_snapshot, PACKAGE_DIR)
        _restore_dir(assets_snapshot, ASSETS_DIR)


@pytest.fixture(scope="session")
def run_in_obb(fake_extension_installed):  # noqa: ARG001
    """Run an inline snippet under a fresh ``python`` subprocess that imports ``openbb``.

    Returns a callable ``run(snippet: str) -> dict``. The snippet must
    assign a JSON-serializable value to a variable called ``RESULT``;
    the wrapper ``json.dumps`` it to stdout and the helper parses it
    back into Python.
    """

    def _run(snippet: str) -> dict:
        wrapper = textwrap.dedent("""
            import json, sys
            from openbb import obb  # noqa: F401
            {snippet}
            sys.stdout.write(json.dumps(RESULT))
            """).format(snippet=textwrap.indent(snippet, ""))
        proc = subprocess.run(  # noqa: S603
            [sys.executable, "-c", wrapper],
            check=False,
            capture_output=True,
            text=True,
            env=_subprocess_env({"OPENBB_AUTO_BUILD": "false"}),
        )
        if proc.returncode != 0:
            raise AssertionError(
                f"obb subprocess failed (rc={proc.returncode})\n"
                f"--- stdout ---\n{proc.stdout}\n"
                f"--- stderr ---\n{proc.stderr}"
            )
        return json.loads(proc.stdout)

    return _run
