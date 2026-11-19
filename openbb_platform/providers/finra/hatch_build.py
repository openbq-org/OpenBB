"""Hatchling build hook that bundles ``openbb_finra/assets/security_types.json.gz``."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import (  # ty: ignore[unresolved-import]
    BuildHookInterface,
)

_ROOT = Path(__file__).resolve().parent
_ASSET = _ROOT / "openbb_finra" / "assets" / "security_types.json.gz"
_GENERATOR = _ROOT / "openbb_finra" / "utils" / "generate_securities.py"
_FORCE_ENV = "OPENBB_FINRA_FORCE_ASSET_REBUILD"


class SecurityTypesBuildHook(BuildHookInterface):
    """Build hook that generates the security-type asset when it is missing."""

    PLUGIN_NAME = "finra-security-types"

    def initialize(self, version: str, build_data: dict) -> None:
        """Generate the asset when it is missing or a rebuild is forced, then bundle it."""
        force = os.environ.get(_FORCE_ENV, "").lower() in {"1", "true", "yes"}

        if force or not _ASSET.exists():
            sys.stderr.write(
                "finra-security-types: classifying FINRA's traded symbols...\n"
            )
            returncode = subprocess.call(  # noqa: S603
                [sys.executable, str(_GENERATOR)], cwd=str(_ROOT)
            )

            if returncode != 0 or not _ASSET.exists():
                self.app.abort(
                    "finra-security-types: failed to generate security_types.json.gz "
                    f"(exit code {returncode}). api.finra.org must be "
                    "reachable during the build."
                )
        else:
            sys.stderr.write(
                f"finra-security-types: reusing {_ASSET.name} "
                f"(set {_FORCE_ENV}=1 to rebuild)\n"
            )

        relative = _ASSET.relative_to(_ROOT).as_posix()
        build_data.setdefault("force_include", {})[str(_ASSET)] = relative
        build_data.setdefault("artifacts", []).append(relative)
