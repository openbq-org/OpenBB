"""Run the vendored day-trader-skill scripts and parse their JSON output."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SKILLS_DIR = Path(__file__).parent / "skills"
WORKDIR_ENV = "OPENBB_DAYTRADER_WORKDIR"
TIMEOUT_ENV = "OPENBB_DAYTRADER_TIMEOUT"

SCRIPTS = {
    "scanner": "trader-scanner/scan.py",
    "news": "trader-news/news.py",
    "entry": "trader-entry/entry.py",
    "exit": "trader-exit/exit.py",
    "timemachine": "trader-timemachine/timemachine.py",
    "budget": "trader-budget/size.py",
    "risk": "trader-risk/check.py",
    "broker": "trader-broker/ticket.py",
    "alerts": "trader-alerts/alerts.py",
    "analyst": "trader-analyst/facts.py",
    "pelosi": "trader-pelosi/ptr.py",
}

STATE_FILES = {
    "watchlist": "trader/watchlist.json",
    "entry": "trader/entry.json",
    "plan": "trader/plan.json",
    "timemachine": "trader/timemachine.json",
    "orders": "trader/orders.json",
    "portfolio": "trader/portfolio.json",
    "config": "trader/config.json",
    "alerts": "trader/alerts.json",
    "risk": "trader/state/risk.json",
    "broker": "trader/state/broker.json",
}


class DayTraderError(RuntimeError):
    """A skill script exited with an error."""


def workdir() -> Path:
    """Return the folder that holds the shared `trader/` state.

    Claude Code skills and the OpenBB API must point at the same folder to
    share state: set OPENBB_DAYTRADER_WORKDIR, else the current directory.
    """
    path = Path(os.environ.get(WORKDIR_ENV) or Path.cwd()).expanduser().resolve()
    (path / "trader").mkdir(parents=True, exist_ok=True)
    return path


def script_path(skill: str) -> Path:
    """Return the absolute path of a skill's script."""
    return SKILLS_DIR / SCRIPTS[skill]


def flags(**options: Any) -> list[str]:
    """Turn keyword options into CLI flags.

    None and False are dropped, True becomes a bare flag, lists are spread.
    """
    out: list[str] = []
    for key, value in options.items():
        if value is None or value is False:
            continue
        flag = "--" + key.rstrip("_").replace("_", "-")
        if value is True:
            out.append(flag)
        elif isinstance(value, (list, tuple)):
            if value:
                out.append(flag)
                out.extend(str(v) for v in value)
        else:
            out.extend([flag, str(value)])
    return out


def run(skill: str, args: list[str], parse_json: bool = True) -> Any:
    """Run one skill script inside the shared workdir.

    Returns the parsed JSON (or raw stdout when parse_json is False).
    """
    cmd = [sys.executable, "-I", str(script_path(skill)), *args]
    timeout = float(os.environ.get(TIMEOUT_ENV, "600"))
    proc = subprocess.run(  # noqa: S603
        cmd,
        cwd=workdir(),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    stdout = proc.stdout.strip()
    if parse_json and stdout:
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            pass
    if proc.returncode != 0:
        message = (proc.stderr or stdout or "").strip()
        raise DayTraderError(f"{SCRIPTS[skill]} exited {proc.returncode}: {message}")
    return stdout


def read_state(name: str) -> Any:
    """Read one `trader/` state file, or None if it does not exist yet."""
    path = workdir() / STATE_FILES[name]
    if not path.is_file():
        return None
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)
