"""Hatchling build hook for ``openbb_bls/assets/bls_cache.zip``."""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import TextIO

from hatchling.builders.hooks.plugin.interface import (  # ty: ignore[unresolved-import]
    BuildHookInterface,
)

_ROOT = Path(__file__).resolve().parent
_CACHE_PATH = _ROOT / "openbb_bls" / "assets" / "bls_cache.zip"
_GENERATE_CACHE = _ROOT / "openbb_bls" / "utils" / "generate_cache.py"
_FORCE_ENV = "OPENBB_BLS_FORCE_CACHE_REBUILD"


def _open_tty() -> TextIO | None:
    """Open ``/dev/tty`` for direct terminal output, or ``None`` on Windows / CI."""
    with suppress(OSError):
        return open("/dev/tty", "w", buffering=1, encoding="utf-8")  # noqa: SIM115
    return None


class BlsCacheBuildHook(BuildHookInterface):
    """Build hook that materializes ``bls_cache.zip`` before packaging."""

    PLUGIN_NAME = "bls-cache"

    _generated_this_session: bool = False

    def initialize(self, version: str, build_data: dict) -> None:
        """Generate (or reuse) the cache, then mark it for inclusion."""
        tty = _open_tty()

        def _say(msg: str) -> None:
            line = msg if msg.endswith("\n") else msg + "\n"
            if tty is not None:
                with suppress(OSError):
                    tty.write(line)
                    tty.flush()
            sys.stderr.write(line)
            sys.stderr.flush()

        cls = type(self)
        force = (
            os.environ.get(_FORCE_ENV, "").lower() in {"1", "true", "yes"}
            and not cls._generated_this_session
        )
        try:
            if _CACHE_PATH.exists() and not force:
                reuse_reason = (
                    "this build session already regenerated it"
                    if cls._generated_this_session
                    else f"set {_FORCE_ENV}=1 to rebuild"
                )
                _say(f"bls-cache: reusing {_CACHE_PATH.name} ({reuse_reason})")
            else:
                _say(
                    "bls-cache: regenerating from download.bls.gov "
                    "(~3 min, ~30 sequential survey fetches)..."
                )
                env = {
                    **os.environ,
                    "PYTHONUNBUFFERED": "1",
                    "PYTHONIOENCODING": "utf-8",
                }
                proc = subprocess.Popen(  # noqa: S603
                    [sys.executable, str(_GENERATE_CACHE)],
                    cwd=str(_ROOT),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
                assert proc.stdout is not None  # noqa: S101
                for line in proc.stdout:
                    if tty is not None:
                        with suppress(OSError):
                            tty.write(line)
                            tty.flush()
                    sys.stderr.write(line)
                    sys.stderr.flush()
                returncode = proc.wait()

                if returncode != 0 or not _CACHE_PATH.exists():
                    self.app.abort(
                        "bls-cache: failed to generate bls_cache.zip "
                        f"(exit code {returncode}). See the "
                        "``generate_cache`` output above for details. "
                        "download.bls.gov must be reachable during build."
                    )

                cls._generated_this_session = True
        finally:
            if tty is not None:
                tty.close()

        rel = _CACHE_PATH.relative_to(_ROOT).as_posix()
        build_data.setdefault("force_include", {})[str(_CACHE_PATH)] = rel
        build_data.setdefault("artifacts", []).append(rel)
