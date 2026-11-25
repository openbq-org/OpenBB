"""Install the tracked, published OpenBB packages in editable mode."""

# flake8: noqa: S603, S607

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from importlib.util import find_spec
from pathlib import Path

PLATFORM_PATH = Path(__file__).parent.resolve()
REPO_PATH = PLATFORM_PATH.parent
PACKAGE_GLOBS = (
    "openbb_platform/core/pyproject.toml",
    "openbb_platform/extensions/*/pyproject.toml",
    "openbb_platform/obbject_extensions/*/pyproject.toml",
    "openbb_platform/providers/*/pyproject.toml",
    "cli/pyproject.toml",
)
ROUTERS_PATH = Path("openbb_platform/extensions")
ALWAYS_INSTALLED_ROUTERS = frozenset({"openbb-news"})
UV_BUILD_LOG = "uv_build_frontend=debug"
REQUIREMENT_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def log(message: str) -> None:
    """Write a progress line to stdout immediately.

    Parameters
    ----------
    message : str
        The line to write.
    """
    sys.stdout.write(f"[dev_install] {message}\n")
    sys.stdout.flush()


def run_step(title: str, command: list[str], env: dict[str, str]) -> None:
    """Run one install step, streaming its output and reporting its duration.

    Parameters
    ----------
    title : str
        The step name shown in the progress lines.
    command : list[str]
        The command to run from the repository root.
    env : dict[str, str]
        The environment for the command.
    """
    log(f"{title}...")
    start = time.monotonic()
    subprocess.run(command, cwd=REPO_PATH, env=env, check=True)
    log(f"{title} finished in {time.monotonic() - start:.1f}s")


def get_uv() -> list[str]:
    """Return the command that invokes uv.

    Returns
    -------
    list[str]
        The uv module of the running interpreter, else the uv executable on PATH.

    Raises
    ------
    SystemExit
        If uv is not installed.
    """
    if find_spec("uv"):
        return [sys.executable, "-m", "uv"]
    uv = shutil.which("uv")
    if uv:
        return [uv]
    sys.exit(
        "dev_install.py requires uv: "
        "https://docs.astral.sh/uv/getting-started/installation/"
    )


def load_toml(path: Path) -> dict:
    """Parse a TOML file.

    Parameters
    ----------
    path : Path
        The TOML file to read.

    Returns
    -------
    dict
        The parsed document.
    """
    return tomllib.loads(path.read_text(encoding="utf-8"))


def get_tracked_packages() -> list[Path]:
    """Return the repository-relative directory of every tracked, published package.

    Returns
    -------
    list[Path]
        Package directories, sorted.
    """
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", *(f":(glob){g}" for g in PACKAGE_GLOBS)],
        cwd=REPO_PATH,
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(Path(f).parent for f in result.stdout.split("\0") if f)


def is_optional_router(package: Path, pyproject: dict) -> bool:
    """Return whether a package is a router extension installed only with --routers.

    Parameters
    ----------
    package : Path
        The repository-relative package directory.
    pyproject : dict
        The package's parsed pyproject.toml.

    Returns
    -------
    bool
        True for an extension that registers an `openbb_core_extension` router,
        other than those in ALWAYS_INSTALLED_ROUTERS.
    """
    project = pyproject.get("project", {})
    return (
        package.parent == ROUTERS_PATH
        and "openbb_core_extension" in project.get("entry-points", {})
        and project.get("name") not in ALWAYS_INSTALLED_ROUTERS
    )


def normalize_name(name: str) -> str:
    """Return the PEP 503 normalized form of a distribution name.

    Parameters
    ----------
    name : str
        The distribution name.

    Returns
    -------
    str
        The lowercase name with runs of ``-``, ``_``, and ``.`` collapsed to ``-``.
    """
    return re.sub(r"[-_.]+", "-", name).lower()


def get_editable_target(package: Path, pyproject: dict) -> str:
    """Return the editable install target for a package, with all of its extras.

    Parameters
    ----------
    package : Path
        The repository-relative package directory.
    pyproject : dict
        The package's parsed pyproject.toml.

    Returns
    -------
    str
        The package path, followed by ``[extra,...]`` when it declares extras.
    """
    extras = sorted(pyproject.get("project", {}).get("optional-dependencies", {}))
    return package.as_posix() + (f"[{','.join(extras)}]" if extras else "")


def resolve_dev_requirements(
    pyprojects: dict[Path, dict], selected: list[Path]
) -> tuple[list[Path], list[str], list[str]]:
    """Resolve the ``dev`` dependency groups of the selected packages.

    Parameters
    ----------
    pyprojects : dict[Path, dict]
        The parsed pyproject.toml of every tracked package, by directory.
    selected : list[Path]
        The packages being installed.

    Returns
    -------
    tuple[list[Path], list[str], list[str]]
        Tracked packages that are only dev dependencies and install editable,
        requirements to install from the index, and local path-sourced
        requirements outside the tracked packages, such as test fixtures,
        that are left out.
    """
    tracked = {
        normalize_name(pyproject["project"]["name"]): package
        for package, pyproject in pyprojects.items()
    }
    editables: list[Path] = []
    requirements: list[str] = []
    skipped: list[str] = []
    for package in selected:
        pyproject = pyprojects[package]
        sources = {
            normalize_name(name): source
            for name, source in pyproject.get("tool", {})
            .get("uv", {})
            .get("sources", {})
            .items()
        }
        for requirement in pyproject.get("dependency-groups", {}).get("dev", []):
            match = REQUIREMENT_NAME_RE.match(requirement)
            name = normalize_name(match.group(1)) if match else ""
            if name in tracked:
                target = tracked[name]
                if target not in selected and target not in editables:
                    editables.append(target)
            elif isinstance(sources.get(name), dict) and "path" in sources[name]:
                if requirement not in skipped:
                    skipped.append(requirement)
            elif requirement not in requirements:
                requirements.append(requirement)
    return editables, requirements, skipped


def main(argv: list[str] | None = None) -> None:
    """Install the packages into the running interpreter and build the static assets.

    Parameters
    ----------
    argv : list[str] | None
        Command-line arguments, defaulting to sys.argv.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--routers",
        action="store_true",
        help="Also install the router extensions (equity, economy, fixedincome, ...).",
    )
    args = parser.parse_args(argv)
    log(f"Installing into {sys.executable}")
    pyprojects = {
        package: load_toml(REPO_PATH / package / "pyproject.toml")
        for package in get_tracked_packages()
    }
    selected = [
        package
        for package, pyproject in pyprojects.items()
        if args.routers or not is_optional_router(package, pyproject)
    ]
    install_args: list[str] = []
    for package in selected:
        install_args += [
            "--editable",
            get_editable_target(package, pyprojects[package]),
        ]
        log(f"  + {package.as_posix()}")
    skipped_routers = [
        package.name for package in pyprojects if package not in selected
    ]
    editables, requirements, skipped_local = resolve_dev_requirements(
        pyprojects, selected
    )
    for package in editables:
        install_args += [
            "--editable",
            get_editable_target(package, pyprojects[package]),
        ]
        log(f"  + {package.as_posix()} (dev dependency)")
    install_args += requirements
    log(f"Dev requirements: {', '.join(requirements)}")
    if skipped_routers:
        log(
            "Skipping routers (pass --routers to include): "
            f"{', '.join(skipped_routers)}"
        )
    if skipped_local:
        log(f"Skipping local test packages: {', '.join(skipped_local)}")
    run_step(
        "Resolving, building, and installing with uv "
        "(package builds and their hook output stream below)",
        [*get_uv(), "pip", "install", "--python", sys.executable, *install_args],
        {**os.environ, "RUST_LOG": os.environ.get("RUST_LOG", UV_BUILD_LOG)},
    )
    run_step(
        "Building the openbb package",
        [sys.executable, "-c", "import openbb; openbb.build(verbose=True)"],
        {**os.environ, "OPENBB_AUTO_BUILD": "false"},
    )
    log("Done")


if __name__ == "__main__":
    main()
