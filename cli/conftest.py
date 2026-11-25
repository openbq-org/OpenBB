"""Session-scoped fixture that builds & installs a synthetic OpenBB extension.

Every test under ``cli/`` (both ``cli/tests/`` and ``cli/integration/``) runs
against the same generated static-package surface. The fixture writes a
self-contained extension distribution to disk, ``pip install``s it into the
current interpreter, and runs ``openbb-build`` so the static package of the
installed ``openbb`` distribution is regenerated with the test extension's
commands baked in.

Modeled directly on ``openbb_platform/core/integration/conftest.py``; reuses
the same snapshot-and-restore approach so the production package dir is
returned to its pre-test state.

Because the static package is wired via entry points discovered at
*interpreter start*, tests that import ``openbb`` after the build must do so
in a fresh ``python`` subprocess. The ``run_in_obb`` helper does exactly
that.
"""

from __future__ import annotations

import contextlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

_OPENBB_SPEC = importlib.util.find_spec("openbb")
if _OPENBB_SPEC is None or _OPENBB_SPEC.origin is None:
    raise ImportError(
        "The openbb package must be installed to run the openbb-cli tests."
    )
OPENBB_DIR = Path(_OPENBB_SPEC.origin).parent
PACKAGE_DIR = OPENBB_DIR / "package"
ASSETS_DIR = OPENBB_DIR / "assets"

EXT_NAME = "openbb-cli-fake"
EXT_PKG = "openbb_cli_fake"


PYPROJECT = """\
[project]
name = "{ext_name}"
version = "0.0.1"
requires-python = ">=3.11,<4"
dependencies = ["openbb-core"]

[project.entry-points."openbb_core_extension"]
cli_test = "{pkg}.router:router"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["{pkg}"]
"""

INIT_PY = '''\
"""Synthetic extension exposing deterministic commands for openbb-cli tests."""
'''

ROUTER_PY = '''\
"""Router for the openbb-cli synthetic test extension.

Exposes a small surface under ``obb.cli_test.*`` so the CLI's dispatcher,
controller, and output-adapter tests can resolve real commands through the
production ``obb`` namespace — same code path as installed extensions.
"""

from typing import Any

from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

router = Router(prefix="", description="openbb-cli synthetic test extension.")


@router.command(methods=["GET"])
async def echo(value: str = "hi") -> OBBject[dict[str, Any]]:
    """Return the input wrapped in an OBBject — sync-style payload."""
    return OBBject(results={"echo": value})


@router.command(methods=["GET"])
async def quote(symbol: str) -> OBBject[dict[str, Any]]:
    """Return a deterministic quote-shaped payload, async-style."""
    return OBBject(results={"symbol": symbol, "async": True})


@router.command(methods=["GET"])
async def bomb() -> OBBject[dict[str, Any]]:
    """Raise to exercise dispatcher error isolation."""
    raise RuntimeError("boom")


@router.command(methods=["GET"])
async def rows(n: int = 3) -> OBBject[list[dict[str, Any]]]:
    """Return a deterministic list payload — exercises tabular output adapters."""
    return OBBject(results=[{"i": i, "v": i * 2} for i in range(n)])
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
    """Build a subprocess env that opts into coverage.py auto-startup if available.

    Strips ``COV_CORE_*`` so the child does not try to bootstrap via
    ``pytest_cov.embed.init()`` (would race with ``coverage.process_startup``
    and write into the parent's locked data file).
    """
    env = {k: v for k, v in os.environ.items() if not k.startswith("COV_CORE_")}
    rcfile = Path(__file__).resolve().parent / ".coveragerc"
    if rcfile.exists():
        env["COVERAGE_PROCESS_START"] = str(rcfile)
    if extra:
        env.update(extra)
    return env


def _run_openbb_build() -> None:
    """Trigger ``openbb-build`` via auto-build on first import in a fresh subprocess.

    A child process is required because ``ExtensionLoader``/``RouterLoader``
    cache entry points at module load time; the parent process cannot
    discover the freshly-installed distribution without a restart.
    """
    env = _subprocess_env({"OPENBB_AUTO_BUILD": "true"})
    subprocess.run(  # noqa: S603
        [sys.executable, "-c", "import openbb"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture(scope="session", autouse=True)
def cli_fake_extension_installed(tmp_path_factory):
    """Build, install, openbb-build, yield, then uninstall and restore.

    Auto-used at session scope so every test in ``cli/`` runs against the
    same generated static package surface. The synthetic extension exposes
    ``obb.cli_test.{echo,quote,bomb,rows}`` for dispatcher / output / controller
    tests to resolve through the real plugin-discovery path.
    """
    work = tmp_path_factory.mktemp("cli_fake_ext_dist")
    pkg_dir = work / EXT_PKG
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text(INIT_PY, encoding="utf-8")
    (pkg_dir / "router.py").write_text(ROUTER_PY, encoding="utf-8")
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
        if str(work) not in sys.path:
            sys.path.insert(0, str(work))
        _run_openbb_build()

        ext_pkg_module = PACKAGE_DIR / "cli_test.py"
        if not ext_pkg_module.exists():
            pytest.fail(
                "openbb-build did not emit cli_test.py; "
                f"contents of {PACKAGE_DIR}: "
                f"{sorted(p.name for p in PACKAGE_DIR.glob('*.py'))}"
            )

        yield {
            "ext_name": EXT_NAME,
            "ext_pkg": EXT_PKG,
            "package_dir": PACKAGE_DIR,
            "assets_dir": ASSETS_DIR,
            "work_dir": work,
        }
    finally:
        with contextlib.suppress(subprocess.CalledProcessError):
            _pip("uninstall", "-y", EXT_NAME)
        with contextlib.suppress(ValueError):
            sys.path.remove(str(work))
        for mod_name in [m for m in sys.modules if m.startswith(EXT_PKG)]:
            del sys.modules[mod_name]
        _restore_dir(pkg_snapshot, PACKAGE_DIR)
        _restore_dir(assets_snapshot, ASSETS_DIR)
        _combine_partial_coverage()


def _combine_partial_coverage() -> None:
    """Merge ``.coverage.<host>.pid<N>.<rand>`` partials and erase them.

    ``parallel = True`` in ``.coveragerc`` makes every subprocess (the
    ``_run_openbb_build`` build call and every ``run_in_obb`` snippet) write a
    uniquely-named partial. Without ``coverage combine`` they accumulate at
    the repo root across runs. Run combine if any partial exists; otherwise
    no-op so suites that don't use the subprocess path stay clean.
    """
    here = Path(__file__).resolve().parent
    if not list(here.glob(".coverage.*")):
        return
    with contextlib.suppress(subprocess.CalledProcessError, FileNotFoundError):
        subprocess.run(  # noqa: S603
            [sys.executable, "-m", "coverage", "combine"],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(here),
        )
    for partial in here.glob(".coverage.*"):
        with contextlib.suppress(OSError):
            partial.unlink()


OBB_WORKER = """\
import contextlib, io, json, sys, traceback
from openbb import obb
out = sys.stdout
for line in sys.stdin:
    namespace = {"obb": obb}
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            exec(json.loads(line), namespace)
        response = {"ok": True, "result": namespace["RESULT"]}
    except Exception:
        response = {"ok": False, "error": traceback.format_exc()}
    out.write(json.dumps(response, default=str) + "\\n")
    out.flush()
"""


@pytest.fixture(scope="session")
def run_in_obb(cli_fake_extension_installed, tmp_path_factory):  # noqa: ARG001
    """Run inline snippets in one session-wide subprocess that imports ``openbb`` once.

    Returns a callable ``run(snippet: str) -> dict``. The snippet must assign
    a JSON-serializable value to ``RESULT``. Each snippet executes in a fresh
    namespace inside a worker started after the session build, so commands
    resolve through the real generated static ``obb`` namespace without
    re-importing it for every test.
    """
    stderr_path = tmp_path_factory.mktemp("obb_worker") / "stderr.log"
    with stderr_path.open("w", encoding="utf-8") as stderr:
        worker = subprocess.Popen(  # noqa: S603
            [sys.executable, "-c", OBB_WORKER],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
            env=_subprocess_env({"OPENBB_AUTO_BUILD": "false"}),
        )
        if worker.stdin is None or worker.stdout is None:
            raise RuntimeError("obb worker started without piped stdin/stdout")
        worker_stdin = worker.stdin
        worker_stdout = worker.stdout

        def _run(snippet: str) -> dict:
            worker_stdin.write(json.dumps(textwrap.dedent(snippet).strip()) + "\n")
            worker_stdin.flush()
            line = worker_stdout.readline()
            if not line:
                raise AssertionError(
                    f"obb worker exited (rc={worker.wait()})\n"
                    f"--- stderr ---\n{stderr_path.read_text(encoding='utf-8')}"
                )
            response = json.loads(line)
            if not response["ok"]:
                raise AssertionError(f"obb snippet failed\n{response['error']}")
            return response["result"]

        try:
            yield _run
        finally:
            worker_stdin.close()
            worker.wait(timeout=60)
