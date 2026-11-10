"""Hatchling build hook for ``openbb_imf/assets/imf_cache.json.xz``."""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys
import zipfile
from contextlib import suppress
from pathlib import Path
from typing import TextIO

import requests
from hatchling.builders.hooks.plugin.interface import (  # ty: ignore[unresolved-import]
    BuildHookInterface,
)

_ROOT = Path(__file__).resolve().parent
_CACHE_PATH = _ROOT / "openbb_imf" / "assets" / "imf_cache.json.xz"
_GENERATE_CACHE = _ROOT / "openbb_imf" / "utils" / "generate_cache.py"
_FORCE_ENV = "OPENBB_IMF_FORCE_CACHE_REBUILD"
_PYPI_RELEASE_URL = "https://pypi.org/pypi/openbb-imf/json"
_WHEEL_CACHE_MEMBER = "openbb_imf/assets/imf_cache.json.xz"


def _open_tty() -> TextIO | None:
    """Open ``/dev/tty`` for direct terminal output."""
    with suppress(OSError):
        return open("/dev/tty", "w", buffering=1, encoding="utf-8")  # noqa: SIM115
    return None


def _copy_published_cache() -> str:
    """Copy ``imf_cache.json.xz`` from the latest openbb-imf wheel on PyPI."""
    release = requests.get(_PYPI_RELEASE_URL, timeout=60)
    release.raise_for_status()
    metadata = release.json()
    wheel = next(f for f in metadata["urls"] if f["packagetype"] == "bdist_wheel")
    download = requests.get(wheel["url"], timeout=300)
    download.raise_for_status()
    if hashlib.sha256(download.content).hexdigest() != wheel["digests"]["sha256"]:
        raise ValueError(f"sha256 mismatch for {wheel['filename']}")
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        payload = archive.read(_WHEEL_CACHE_MEMBER)
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_bytes(payload)
    return metadata["info"]["version"]


class ImfCacheBuildHook(BuildHookInterface):
    """Materialize ``imf_cache.json.xz`` before packaging."""

    PLUGIN_NAME = "imf-cache"

    _generated_this_session: bool = False

    def initialize(self, version: str, build_data: dict) -> None:
        """Generate or reuse the cache, then mark it for inclusion."""
        tty = _open_tty()

        def _say(msg: str) -> None:
            """Emit ``msg`` to ``/dev/tty`` and stderr."""
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
                _say(f"imf-cache: reusing {_CACHE_PATH.name} ({reuse_reason})")
            else:
                _say(
                    "imf-cache: regenerating from IMF SDMX 3.0 "
                    "(api.imf.org/external/sdmx/3.0)..."
                )
                env = {**os.environ, "PYTHONUNBUFFERED": "1"}
                proc = subprocess.Popen(  # noqa: S603
                    [sys.executable, str(_GENERATE_CACHE)],
                    cwd=str(_ROOT),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
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

                if returncode == 0 and _CACHE_PATH.exists():
                    cls._generated_this_session = True
                elif force:
                    self.app.abort(
                        "imf-cache: failed to generate imf_cache.json.xz "
                        f"(exit code {returncode})."
                    )
                else:
                    try:
                        published = _copy_published_cache()
                    except Exception as exc:
                        self.app.abort(
                            "imf-cache: failed to generate imf_cache.json.xz "
                            f"(exit code {returncode}) and could not copy it from "
                            f"the latest openbb-imf release on PyPI: {exc}"
                        )
                    else:
                        _say(
                            f"imf-cache: IMF SDMX unavailable; using "
                            f"{_CACHE_PATH.name} from openbb-imf {published} on PyPI"
                        )
        finally:
            if tty is not None:
                tty.close()

        rel = _CACHE_PATH.relative_to(_ROOT).as_posix()
        build_data.setdefault("force_include", {})[str(_CACHE_PATH)] = rel
        build_data.setdefault("artifacts", []).append(rel)
