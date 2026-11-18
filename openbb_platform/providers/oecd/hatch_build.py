"""Hatchling build hook: materialize the OECD SDMX cache before packaging.

The compressed catalog (``openbb_oecd/assets/oecd_cache.json.xz``) is
gitignored — it must be produced fresh at build time by
``openbb_oecd.utils.generate_cache.main`` against OECD SDMX endpoints
and bundled into the sdist + wheel + editable install.
"""

from __future__ import annotations

import os
import subprocess
import sys
from contextlib import suppress
from pathlib import Path
from typing import TextIO

# ``hatchling`` is a PEP 517 build-time dependency (declared in
# ``[build-system].requires`` of ``pyproject.toml``), not a runtime or
# test/lint dependency. Type-check environments don't install it, so we
# tell ty the unresolved import is intentional rather than pulling
# hatchling into the lint env.
from hatchling.builders.hooks.plugin.interface import (  # ty: ignore[unresolved-import]
    BuildHookInterface,
)

_ROOT = Path(__file__).resolve().parent
_CACHE_PATH = _ROOT / "openbb_oecd" / "assets" / "oecd_cache.json.xz"
_GENERATE_CACHE = _ROOT / "openbb_oecd" / "utils" / "generate_cache.py"
_FORCE_ENV = "OPENBB_OECD_FORCE_CACHE_REBUILD"


def _open_tty() -> TextIO | None:
    """Open ``/dev/tty`` for direct terminal output, or ``None`` on Windows / CI.

    PEP 517 build frontends (pip, uv, build) capture the backend's
    stdout/stderr and only surface them in error summaries — which
    means a printed-and-flushed message inside a build hook is
    completely invisible to the user during a 4-minute OECD fetch.
    Writing to ``/dev/tty`` is the standard escape hatch: it's the
    controlling terminal, untouched by pip's capture pipeline.
    """
    with suppress(OSError):
        return open("/dev/tty", "w", buffering=1, encoding="utf-8")  # noqa: SIM115
    return None


class OecdCacheBuildHook(BuildHookInterface):
    """Build hook that materializes ``oecd_cache.json.xz`` before packaging."""

    PLUGIN_NAME = "oecd-cache"

    # Class-level flag — Hatch runs ``build_sdist`` and ``build_wheel`` in
    # the same Python process, so this state survives between target builds
    # and lets the second target reuse the cache the first target just
    # produced even when ``OPENBB_OECD_FORCE_CACHE_REBUILD=1`` is set.
    # Without this guard a release build would fetch from OECD twice (once
    # per target).
    _generated_this_session: bool = False

    def initialize(self, version: str, build_data: dict) -> None:
        """Generate (or reuse) the cache, then mark it for inclusion."""
        # Fires for every target: sdist + wheel + editable. The cache is
        # bundled into all three. Editable installs need it in the source
        # tree so the runtime loader at
        # ``openbb_oecd/utils/metadata/_constants.py``'s
        # ``_SHIPPED_CACHE_FILE`` resolves.
        tty = _open_tty()

        def _say(msg: str) -> None:
            """Emit *msg* to the controlling terminal AND to stderr.

            ``/dev/tty`` bypasses pip / uv / build's stdout+stderr
            capture so the user sees progress live. The stderr copy is
            for log files, CI captures, and the eventual pip error
            summary when something does go wrong.
            """
            line = msg if msg.endswith("\n") else msg + "\n"
            if tty is not None:
                with suppress(OSError):
                    tty.write(line)
                    tty.flush()
            sys.stderr.write(line)
            sys.stderr.flush()

        cls = type(self)

        # ``force`` is honored at most once per ``uv build`` process: the
        # first target (sdist) regenerates against live OECD, then the
        # ``_generated_this_session`` flag short-circuits the second
        # target (wheel) into reusing the just-written file. Without
        # this gate a release build hits OECD twice.
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
                _say(f"oecd-cache: reusing {_CACHE_PATH.name} ({reuse_reason})")
            else:
                _say(
                    "oecd-cache: regenerating from OECD SDMX (~4 min, ~6 API calls)..."
                )
                # Invoke ``generate_cache.py`` by **path**, not by
                # module name, so the isolated PEP 517 build env
                # doesn't import ``openbb_oecd/__init__.py`` (which
                # pulls in ``openbb_core`` — not listed as a
                # build-time requirement). The script itself is
                # self-contained: stdlib + ``requests``, and
                # ``requests`` is in ``[build-system].requires``.
                #
                # Stream stdout line-by-line, tee each line to both
                # ``/dev/tty`` (live, escapes pip/uv capture) AND
                # stderr (so CI logs, ``-v`` mode, and the error
                # summary still have the trace). ``PYTHONUNBUFFERED=1``
                # keeps the subprocess from line-buffering since its
                # stdout isn't a TTY.
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
                        "oecd-cache: failed to generate oecd_cache.json.xz "
                        f"(exit code {returncode}). See the "
                        "``generate_cache`` output above for details. "
                        "OECD SDMX (sdmx.oecd.org) must be reachable "
                        "during build."
                    )

                cls._generated_this_session = True
        finally:
            if tty is not None:
                tty.close()

        # Force inclusion regardless of VCS status (the file is gitignored).
        rel = _CACHE_PATH.relative_to(_ROOT).as_posix()
        build_data.setdefault("force_include", {})[str(_CACHE_PATH)] = rel
        build_data.setdefault("artifacts", []).append(rel)
