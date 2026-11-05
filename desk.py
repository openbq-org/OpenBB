"""OpenBB Trading Desk launcher (Windows, macOS, Linux).

Started by OpenBB-Desk.bat / OpenBB-Desk.command / desk.sh, which make sure
uv and the .venv exist. Standard library only.

    python desk.py            menu
    python desk.py install    install or update everything in .venv
    python desk.py start      OpenBB API (Workspace) + MCP server, opens Workspace
    python desk.py claude     Claude Code in this project (/trading-desk)
    python desk.py status     market clock and the desk's trader/ state
    python desk.py ibkr       check the IB Gateway connection (paper by default)
    python desk.py test       run the desk's tests
"""

# ruff: noqa: D103, T201, S603

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
WINDOWS = os.name == "nt"
BIN = VENV / ("Scripts" if WINDOWS else "bin")
PY = BIN / ("python.exe" if WINDOWS else "python")
STAMP = VENV / ".desk-installed"
API_PORT = int(os.environ.get("OPENBB_API_PORT", "6900"))
MCP_PORT = int(os.environ.get("OPENBB_MCP_PORT", "8001"))
WORKSPACE_URL = "https://pro.openbb.co"
TRADER = ROOT / "trader"
CONFIG_EXAMPLE = ROOT / "openbb_platform/extensions/daytrader/desk/config.example.json"

# What the desk needs. Left out on purpose: eia (its build needs an EIA API
# key), imf / ecb / oecd / bls (their builds download whole macro catalogs).
DESK_PACKAGES = [
    "core[flask,pandas]",
    "extensions/platform_api",
    "extensions/mcp_server",
    "extensions/news",
    "extensions/daytrader[ibkr]",
    "extensions/equity",
    "extensions/derivatives",
    "extensions/economy",
    "extensions/etf",
    "extensions/index",
    "extensions/technical",
    "extensions/quantitative",
    "providers/sec",
    "providers/cboe",
    "providers/finra",
    "providers/nasdaq",
    "providers/fred",
    "providers/federal_reserve",
    "providers/government_us",
    "providers/cftc",
]
DESK_EXTRAS = ["pytest>=8", "pytest-asyncio>=0.23"]

ENV = dict(os.environ)
ENV["OPENBB_DAYTRADER_WORKDIR"] = str(ROOT)
ENV["PYTHONUTF8"] = "1"
ENV["PATH"] = str(BIN) + os.pathsep + ENV.get("PATH", "")
ENV["VIRTUAL_ENV"] = str(VENV)


def say(msg: str = "") -> None:
    print(msg, flush=True)


def uv() -> list[str]:
    found = shutil.which("uv")
    if found:
        return [found]
    for cand in (Path.home() / ".local/bin/uv", Path.home() / ".cargo/bin/uv"):
        for c in (cand, cand.with_suffix(".exe")):
            if c.exists():
                return [str(c)]
    sys.exit(
        "[ERR] uv introuvable | [FIX] relancez OpenBB-Desk.bat / OpenBB-Desk.command"
    )


def run(cmd: list[str], **kw) -> int:
    say("> " + " ".join(cmd))
    return subprocess.call(cmd, cwd=ROOT, env=ENV, **kw)


def installed() -> bool:
    """Installed here: a .venv whose stamp names this folder (scripts hold absolute paths)."""
    if not (PY.exists() and STAMP.exists()):
        return False
    if STAMP.read_text(encoding="utf-8").strip() != str(ROOT):
        say("Le dossier du projet a été déplacé : réinstallation de .venv.")
        shutil.rmtree(VENV, ignore_errors=True)
        return False
    return True


def sync_skills() -> None:
    """Git on Windows checks symlinks out as text files: keep real copies in sync."""
    src = ROOT / "openbb_platform/extensions/daytrader/openbb_daytrader/skills"
    for skill in sorted(src.glob("trader-*")):
        link = ROOT / ".claude/skills" / skill.name
        if link.is_symlink() and link.is_dir():
            continue
        if link.is_dir():
            shutil.rmtree(link)
        elif link.exists():
            link.unlink()
        shutil.copytree(skill, link, ignore=shutil.ignore_patterns("__pycache__"))


def init_trader_folder() -> None:
    sync_skills()
    (TRADER / "state").mkdir(parents=True, exist_ok=True)
    cfg = TRADER / "config.json"
    if not cfg.exists() and CONFIG_EXAMPLE.exists():
        shutil.copy(CONFIG_EXAMPLE, cfg)
        say(f"Créé {cfg.relative_to(ROOT)} : réglez budget, perte max et broker.")


def install() -> int:
    if not PY.exists() and run(
        [*uv(), "venv", str(VENV), "--python", "3.12", "--seed"]
    ):
        return 1
    args: list[str] = []
    for pkg in DESK_PACKAGES:
        args += ["--editable", "openbb_platform/" + pkg]
    code = run([*uv(), "pip", "install", "--python", str(PY), *args, *DESK_EXTRAS])
    code = code or run(
        [str(PY), "-c", "import openbb; openbb.build(verbose=True)"],
    )
    if code:
        say(
            "[ERR] installation échouée | [FIX] lisez le message ci-dessus, relancez « install »"
        )
        return code
    STAMP.write_text(str(ROOT), encoding="utf-8")
    init_trader_folder()
    say("Installation terminée.")
    return 0


def ensure_installed() -> None:
    if not installed():
        say("Première utilisation : installation (10-20 min)...")
        if install():
            sys.exit(1)


def broker_env() -> None:
    """Paper unless trader/config.json says "paper": false AND the user types REEL."""
    try:
        cfg = json.loads((TRADER / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    ENV["IBKR_MODE"], ENV["IBKR_ALLOW_LIVE"] = "paper", ""
    if cfg.get("paper", True) is False:
        say("\n!!! trader/config.json demande le compte RÉEL (argent réel) !!!")
        if (
            input("Tapez REEL pour confirmer, Entrée pour rester en paper : ").strip()
            == "REEL"
        ):
            ENV["IBKR_MODE"], ENV["IBKR_ALLOW_LIVE"] = "live", "yes"
        else:
            say("Reste en paper : les ordres seront refusés hors compte paper (DU...).")
    live = ENV["IBKR_MODE"] == "live"
    port = ENV.get("IBKR_PORT") or ("4001" if live else "4002")
    say(
        f"Broker : Interactive Brokers, compte {'RÉEL' if live else 'PAPER'}, IB Gateway port {port}"
    )


def ibkr() -> int:
    ensure_installed()
    init_trader_folder()
    broker_env()
    return run([str(PY), "-m", "openbb_daytrader.ibkr_mcp", "--check"])


def port_busy(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def wait_http(url: str, procs: list, seconds: int = 180) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if any(p.poll() is not None for p in procs):
            return False
        try:
            with urllib.request.urlopen(url, timeout=3):  # noqa: S310
                return True
        except Exception:  # noqa: BLE001
            time.sleep(2)
    return False


def start() -> int:
    ensure_installed()
    init_trader_folder()
    broker_env()
    for port, var in ((API_PORT, "OPENBB_API_PORT"), (MCP_PORT, "OPENBB_MCP_PORT")):
        if port_busy(port):
            say(
                f"[ERR] port {port} déjà utilisé | [FIX] fermez l'autre fenêtre du desk "
                f"ou choisissez un autre port avec la variable {var}"
            )
            return 1
    names = ["API OpenBB", "serveur MCP"]
    procs: list = []
    api = f"http://127.0.0.1:{API_PORT}"
    try:
        procs.append(
            subprocess.Popen(
                [
                    str(PY),
                    "-m",
                    "openbb_platform_api.main",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(API_PORT),
                ],
                cwd=ROOT,
                env=ENV,
            )
        )
        procs.append(
            subprocess.Popen(
                [
                    str(PY),
                    "-m",
                    "openbb_mcp_server.main",
                    "--transport",
                    "streamable-http",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(MCP_PORT),
                ],
                cwd=ROOT,
                env=ENV,
            )
        )
        say("Démarrage de l'API OpenBB...")
        if wait_http(api + "/widgets.json", procs):
            say("")
            say("=" * 64)
            say(f" API OpenBB (backend Workspace) : {api}")
            say(f" Serveur MCP (Claude Desktop)   : http://127.0.0.1:{MCP_PORT}/mcp")
            say(f" OpenBB Workspace : {WORKSPACE_URL}")
            say(f"   Apps > Connect backend > {api}  -> catégorie « Day Trader »")
            say(" Ctrl+C pour tout arrêter.")
            say("=" * 64)
            webbrowser.open(WORKSPACE_URL)
            while all(p.poll() is None for p in procs):
                time.sleep(1)
        for name, p in zip(names, procs):
            if p.poll() is not None:
                say(
                    f"[ERR] {name} arrêté (code {p.returncode}) | [FIX] lisez les logs ci-dessus"
                )
                return 1
        say("[ERR] l'API ne répond pas | [FIX] lisez les logs ci-dessus")
        return 1
    except KeyboardInterrupt:
        say("\nArrêt du desk.")
        return 0
    finally:
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()


def claude() -> int:
    ensure_installed()
    init_trader_folder()
    broker_env()
    cli = shutil.which("claude", path=ENV["PATH"])
    if not cli:
        say(
            "[ERR] Claude Code non installé | [FIX] https://code.claude.com/docs/en/setup"
        )
        return 1
    say("Dans Claude : /trading-desk  (ou /trader-scanner, /trader-broker ...)")
    return run([cli])


def status() -> int:
    ensure_installed()
    init_trader_folder()
    skills = ROOT / "openbb_platform/extensions/daytrader/openbb_daytrader/skills"
    run([str(PY), str(skills / "trader-alerts/alerts.py"), "clock"])
    for name in ("config.json", "plan.json", "orders.json", "portfolio.json"):
        path = TRADER / name
        if path.exists():
            say(f"\n--- trader/{name}")
            try:
                say(
                    json.dumps(json.loads(path.read_text(encoding="utf-8")), indent=2)[
                        :1500
                    ]
                )
            except ValueError:
                say("(illisible)")
    run([str(PY), str(skills / "trader-broker/ticket.py"), "log"])
    return 0


def test() -> int:
    ensure_installed()
    ext = ROOT / "openbb_platform/extensions/daytrader"
    code = run([str(PY), "-m", "pytest", str(ext / "tests"), "-q"])
    return code or subprocess.call(  # noqa: S603
        [str(PY), "-m", "unittest", "discover", "-s", "tests"],
        cwd=ext / "openbb_daytrader/skills",
        env=ENV,
    )


COMMANDS = {
    "install": install,
    "start": start,
    "claude": claude,
    "status": status,
    "ibkr": ibkr,
    "test": test,
}

MENU = [
    ("1", "Démarrer le desk (API + Workspace + MCP)", "start"),
    ("2", "Ouvrir Claude Code (agent /trading-desk)", "claude"),
    ("3", "Statut (horloge marché, plan, ordres)", "status"),
    ("4", "Tester la connexion Interactive Brokers", "ibkr"),
    ("5", "Installer / mettre à jour", "install"),
    ("6", "Lancer les tests", "test"),
    ("q", "Quitter", None),
]


def menu() -> int:
    while True:
        say("\n  OpenBB Trading Desk")
        say("  -------------------")
        for key, label, _ in MENU:
            say(f"  {key}. {label}")
        try:
            choice = input("\n  Choix : ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            return 0
        for key, _, cmd in MENU:
            if choice == key:
                if cmd is None:
                    return 0
                try:
                    COMMANDS[cmd]()
                except KeyboardInterrupt:
                    say("\n  Interrompu.")
                break
        else:
            say("  Choix inconnu.")


def main(argv: list[str]) -> int:
    if not argv:
        return menu()
    cmd = COMMANDS.get(argv[0])
    if not cmd:
        say(__doc__)
        return 2
    return cmd()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
