"""Nox sessions."""

from pathlib import Path

import nox

ROOT_DIR = Path(__file__).parent.parent.parent
PLATFORM_DIR = ROOT_DIR / "openbb_platform"
PLATFORM_TESTS = [
    str(PLATFORM_DIR / p) for p in ["tests", "core", "providers", "extensions"]
]
CLI_DIR = ROOT_DIR / "cli"
CLI_TESTS = CLI_DIR / "tests"


@nox.session(python=["3.11", "3.12", "3.13", "3.14"])
def unit_test_platform(session):
    """Run the test suite."""
    session.install("uv")
    session.run(
        "python", str(PLATFORM_DIR / "dev_install.py"), "--routers", external=True
    )
    session.install("pytest")
    session.install("pytest-cov")

    session.run(
        "pytest",
        *PLATFORM_TESTS,
        f"--cov={PLATFORM_DIR}",
        "-m",
        "not integration",
    )


@nox.session(python=["3.11", "3.12", "3.13", "3.14"])
def unit_test_cli(session):
    """Run the test suite."""
    session.install("uv")
    session.run(
        "python", str(PLATFORM_DIR / "dev_install.py"), "--routers", external=True
    )
    session.install("pytest")
    session.install("pytest-cov")
    session.run("pytest", CLI_TESTS, f"--cov={CLI_DIR}")
