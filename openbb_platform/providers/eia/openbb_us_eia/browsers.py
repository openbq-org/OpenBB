"""EIA data-browser widgets."""

import re
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
)
from openbb_core.app.router import Router


async def request_info(request: Request) -> dict:
    """Extract deepcopy-safe request fields for the widget/proxy endpoints."""
    body = b""
    if request.method == "POST":
        try:
            body = await request.body()
        except Exception:  # noqa: BLE001
            body = b""
    return {
        "url": str(request.url).split("?", 1)[0],
        "query": request.url.query,
        "path": request.url.path,
        "method": request.method,
        "body": body,
        "content_type": request.headers.get("Content-Type", ""),
        "referer": request.headers.get("Referer", ""),
        "user": _user_key(request.headers.get("X-OpenBB-User", "")),
    }


def _user_key(identity: str) -> str:
    """Return a stable, non-identifying key that isolates one user's widget state."""
    from hashlib import sha256

    return sha256(identity.encode("utf-8")).hexdigest()[:16] if identity else ""


def _mcp_url() -> str:
    """Return this same server's dedicated EIA MCP endpoint, for iframe auto-connect.

    The route is registered on this very API process (see ``eia_router.py``),
    which reverse-proxies to the EIA MCP subprocess, so the URL the Workspace
    connects to shares the exact host/port ``openbb-platform-api`` itself is
    bound to. The ``eia`` extension name is applied as a path prefix by the
    core router loader, so the served path is ``.../eia/eia_mcp``.
    """
    import os

    from openbb_core.app.service.system_service import SystemService

    host = os.environ.get("OPENBB_API_HOST", "127.0.0.1")
    port = os.environ.get("OPENBB_API_PORT", "6900")
    prefix = SystemService().system_settings.api_settings.prefix
    return f"http://{host}:{port}{prefix}/eia/eia_mcp"


router = Router(prefix="", description="EIA interactive data browsers.")

_TEMPLATE = Path(__file__).parent / "assets" / "data_browser.html"
_EIA_ORIGIN = "https://www.eia.gov"

_PROXY_ASSETS = Path(__file__).parent / "assets" / "proxy"


def _style(name: str) -> str:
    """Return a proxy stylesheet wrapped in a ``style`` tag."""
    return f"<style>{(_PROXY_ASSETS / name).read_text(encoding='utf-8')}</style>"


def _script(name: str) -> str:
    """Return a proxy script wrapped in a ``script`` tag."""
    return f"<script>{(_PROXY_ASSETS / name).read_text(encoding='utf-8')}</script>"


_CHROME_CSS = _style("chrome.css")
_DARK_CSS = _style("dark.css")
_MAP_LAYOUT_CSS = _style("map_layout.css")
_MAP_CONTRAST_CSS = _style("map_contrast.css")
_NGQS_GRID_CSS = _style("ngqs_grid.css")
_STATES_CSS = _style("states.css")
_INTERNATIONAL_CSS = _style("international.css")
_ARTICLE_CSS = _style("article.css")
_VIEW_BRIDGE_TEMPLATE = _script("view_bridge.js")


def _view_bridge_js() -> str:
    """Render the bridge that reports the iframe's view path/hash and ready state."""
    return _VIEW_BRIDGE_TEMPLATE


_TABLE_BRIDGE_TEMPLATE = _script("table_bridge.js")


def _table_bridge_js(browser: str, user: str = "") -> str:
    """Render the bridge that publishes the browser's rendered table."""
    return _TABLE_BRIDGE_TEMPLATE.replace("__OBB_BROWSER__", browser).replace(
        "__OBB_USER__", user
    )


_XHR_TAG_TEMPLATE = _script("xhr_tag.js")


def _xhr_tag_js(browser: str, user: str = "") -> str:
    """Render the request tagger that binds each proxied request to its view."""
    return _XHR_TAG_TEMPLATE.replace("__OBB_BROWSER__", browser).replace(
        "__OBB_USER__", user
    )


_DIALOG_CLAMP_JS = _script("dialog_clamp.js")
_VIEW_SELECT_SYNC_JS = _script("view_select_sync.js")
_ASSET_FIX_JS = _script("asset_fix.js")
_NAV_GUARD_JS = _script("nav_guard.js")
_DEAD_SCRIPTS = re.compile(
    r"""<script\b[^>]*\bsrc=["'][^"']*"""
    r"""(?:googletagmanager|gtag/js|ga-file-downloads|/akam/|akamaihd"""
    r"""|remote\.loader|/sayt)"""
    r"""[^"']*["'][^>]*>\s*</script>""",
    re.I,
)
_ABS_EIA_RE = re.compile(r"(?:https?:)?//www\.eia\.gov(?=/)", re.I)
_ESCAPED_EIA_RE = re.compile(r"(?:https?:)?\\/\\/www\.eia\.gov(?=\\/)", re.I)
_AKAMAI_INLINE = re.compile(
    r"<script\b[^>]*>(?:(?!</script>).)*?"
    r"(?:aksb|akamaihd|bazadebezolkohpepadr)"
    r"(?:(?!</script>).)*?</script>",
    re.I | re.S,
)
_AKAMAI_NOSCRIPT = re.compile(
    r"<noscript>(?:(?!</noscript>).)*?/akam/(?:(?!</noscript>).)*?</noscript>",
    re.I | re.S,
)
_SEARCH_INLINE = re.compile(
    r"<script\b[^>]*>(?:(?!</script>).)*?"
    r"(?:remote\.loader|search\.usa\.gov)"
    r"(?:(?!</script>).)*?</script>",
    re.I | re.S,
)
_ARTICLE_DEAD_SCRIPTS = re.compile(
    r"""<script\b[^>]*\bsrc=["'][^"']*"""
    r"""(?:highcharts|jquery[.-]ui|touch-punch)[^"']*["'][^>]*>\s*</script>""",
    re.I,
)
_ARTICLE_PATHS = ("todayinenergy/", "pressroom/")
_SPA_PATHS = ("international/", "states/")
_ROOT_PATH_RE = re.compile(r"""(["'])/(?!/)""")
_ESCAPED_ROOT_RE = re.compile(r"""(["'])\\/(?!\\?/)""")
_JS_ROOT_RE = re.compile(
    r"""(["'])/(about|api|coal|dnav|electricity|global|international|maps"""
    r"""|naturalgas|opendata|outlooks|petroleum|realtime|rss|states|totalenergy)"""
    r"""(?=[/"'])"""
)
_SPA_ROOT_RE = re.compile(r"""(["'])/(states|state|international)(?=[/"'])""")

EIA_DATA_BROWSERS: dict[str, dict[str, str]] = {
    "electricity": {
        "description": "U.S. electric power statistics: net generation, consumption, retail sales, revenue and average retail price, fuel receipts, costs and quality, and plant-level operations - by state, sector, and fuel, monthly through annual.",
        "label": "Electricity",
        "path": "electricity/data/browser/",
        "hash": "#/topic/0?agg=2,0,1&fuel=vtvv&geo=g&sec=g&freq=M&start=200101"
        "&end=202604&ctype=linechart&ltype=pin&linechart=ELEC.GEN.ALL-US-99.M"
        "~ELEC.GEN.COW-US-99.M~ELEC.GEN.NG-US-99.M~ELEC.GEN.NUC-US-99.M"
        "~ELEC.GEN.HYC-US-99.M~ELEC.GEN.WND-US-99.M~ELEC.GEN.TSN-US-99.M",
    },
    "coal": {
        "description": "U.S. coal statistics: production, consumption and quality, prices by rank, recoverable reserves and mine capacity, exports and imports, and mine- and plant-level shipments - by state, region, mine type, and coal rank.",
        "label": "Coal",
        "path": "coal/data/browser/",
        "hash": "",
    },
    "total_energy": {
        "description": "The Monthly Energy Review: recent and historical U.S. energy statistics, including total energy production, consumption, stocks, and trade; energy prices; overviews of petroleum, natural gas, coal, electricity, nuclear energy, renewable energy, and carbon dioxide emissions; and energy unit conversion values.",
        "label": "Total Energy (MER)",
        "path": "totalenergy/data/browser/",
        "hash": "",
    },
    "steo": {
        "description": "The Short-Term Energy Outlook: EIA's monthly 18-month forecast of energy supply, demand, prices, and inventories - crude oil and liquid fuels, natural gas, electricity, coal, renewables, and energy-related carbon dioxide emissions - for the United States and the world.",
        "label": "Short-Term Energy Outlook",
        "path": "outlooks/steo/data/browser/",
        "hash": "",
    },
    "aeo": {
        "description": "The Annual Energy Outlook: EIA's long-term projections of U.S. energy production, consumption, trade, prices, and emissions through 2050, in the Reference case and alternative side cases covering economic growth, oil prices, and technology.",
        "label": "Annual Energy Outlook",
        "path": "outlooks/aeo/data/browser/",
        "hash": "",
    },
    "international": {
        "description": "International energy statistics for more than 200 countries and regions: production, consumption, imports, exports, reserves, and carbon dioxide emissions for petroleum and other liquids, natural gas, coal, electricity, nuclear, and renewables.",
        "label": "International",
        "path": "international/overview/world",
        "hash": "",
    },
    "petroleum_imports": {
        "description": "Company-level U.S. crude oil and petroleum product imports (Form EIA-814): volumes by country of origin, port and PAD District of entry, processing refinery and company, crude grade, and API gravity - monthly and annual.",
        "label": "Petroleum Imports",
        "path": "petroleum/imports/browser/",
        "hash": "#/?vs=PET_IMPORTS.WORLD-US-ALL.A",
    },
    "natural_gas_query": {
        "description": "The Natural Gas Annual Respondent Query System (Form EIA-176): company- and state-level natural gas volumes and prices, covering production, deliveries by consuming sector, underground and LNG storage, and supplemental supplies.",
        "label": "Natural Gas Annual Respondent Query System",
        "path": "naturalgas/ngqs/",
        "hash": "#?report=RP2",
    },
    "states": {
        "description": "State Energy Profiles: energy production, consumption, prices, expenditures, and cross-state rankings for coal, natural gas, petroleum, electricity, nuclear, and renewables, for every U.S. state and territory.",
        "label": "State Energy Profiles",
        "path": "states/overview",
        "hash": "",
    },
    "maps": {
        "description": "EIA's oil and natural gas maps: shale plays and sedimentary basins, pipelines and infrastructure, refineries, and production regions - as PDF and image maps.",
        "label": "Oil & Natural Gas Maps",
        "path": "maps/oil-naturalgas.php",
        "hash": "",
    },
}

_BROWSER_PATHS = frozenset(spec["path"] for spec in EIA_DATA_BROWSERS.values())


def _app_root(path: str) -> str:
    """Return the leading path segment(s) that identify a browser's app."""
    segments = path.split("/")
    if segments[0] == "outlooks" and len(segments) > 1:
        return f"{segments[0]}/{segments[1]}/"
    return f"{segments[0]}/"


_APP_ROOT_TO_BROWSER = {
    _app_root(spec["path"]): spec["path"] for spec in EIA_DATA_BROWSERS.values()
}


def _derive_browser(path: str) -> str:
    """Map a proxied resource path to the browser whose app owns it."""
    for root, browser in _APP_ROOT_TO_BROWSER.items():
        if path.startswith(root):
            return browser
    return ""


MAPS_PAGE = "maps/oil-naturalgas.php"


_TABLE_ROWS: dict[tuple[str, str, str], tuple[list, float]] = {}
_NOT_TABLE_RE = re.compile(
    r"method=getConfig"
    r"|method=getImportExportConfigJSON"
    r"|method=getRowMetadata"
    r"|method=getMapData"
    r"|type=config"
    r"|type=defaults"
    r"|type=mapData"
    r"|/status\.json"
    r"|/release_dates\.json"
    r"|/ngqs/data/(?:version|report|items|sortby)(?:\?|$)"
    r"|/international/api/(?:activities|configurations|countries|country_groups"
    r"|fips_groups|frequencies|max_min_periods|political_groups|product_activities"
    r"|products|selection_trees|unit_groups|unit_groups_assoc|units|views)/data"
    r"|/international/api/articles/"
    r"|/international/(?:content|api/analysis|api/other-groups\.json)"
    r"|/states/api/Projects/States/Json/"
    r"|/states/rankings/getRankingCategories"
    r"|/states/content/(?:facts|tie|resources|l2articles"
    r"|getRegionsOrganizations|getOtherWebsites)"
    r"|/geo\.json",
    re.I,
)


def is_data_response(target: str, content_type: str) -> bool:
    """Return ``True`` for a proxied response carrying a browser's table data."""
    if "/global/" in target or "json" not in content_type:
        return False
    return not _NOT_TABLE_RE.search(target)


_LAST_DATA: dict[tuple[str, str], tuple[dict, float]] = {}
_VIEW_DATA: dict[tuple[str, str, str], tuple[dict, float]] = {}
_CURRENT_VIEW: dict[tuple[str, str], tuple[str, float]] = {}
_WIDGET_STATE: dict[tuple[str, str], tuple[dict, float]] = {}
_PAGE_CONTINUATION_RE = re.compile(r"[?&]offset=(?!0(?:&|$))\d")


def view_key(view: str) -> str:
    """Strip a view's query string, keeping any hash the classic browsers use."""
    head, marker, fragment = view.partition("#")
    head = head.partition("?")[0]
    return f"{head}#{fragment}" if marker else head


def _put(store: dict, key, value, seq: float) -> None:
    """Store ``value`` unless a later-issued one is already there."""
    existing = store.get(key)
    if existing is not None and existing[1] > seq:
        return
    store[key] = (value, seq)


def _freshest_any_user(store: dict, *rest: str) -> tuple | None:
    """Return the freshest ``(value, seq)`` entry for ``(any_user, *rest)``.

    A caller reading state (the MCP tool in particular) has no way to
    guarantee its own identity hash matches the one a widget's iframe used
    when it reported state, so the real source of truth is whichever widget
    instance most recently reported this exact state -- regardless of whose
    user hash it was filed under.
    """
    best = None
    for key, entry in store.items():
        if key[1:] == rest and (best is None or entry[1] > best[1]):
            best = entry
    return best


def set_current_view(browser: str, view: str, seq: float = 0.0, user: str = "") -> None:
    """Record the view a browser is displaying for one user."""
    _put(_CURRENT_VIEW, (user, browser), view, seq)


def get_current_view(browser: str, user: str = "") -> str:
    """Return the view a browser is displaying for one user.

    Falls back to the anonymous bucket when a user-scoped entry is missing, so
    a beacon that could not resolve a user hash still lands on the state a
    prior (or concurrent) anonymous beacon recorded for the same browser.
    """
    entry = _CURRENT_VIEW.get((user, browser))
    if entry is None and user:
        entry = _CURRENT_VIEW.get(("", browser))
    return entry[0] if entry is not None else ""


def set_data_target(
    browser: str, view: str, request: dict, seq: float = 0.0, user: str = ""
) -> None:
    """Record the data request a browser issued, keyed by the view that issued it."""
    _put(_LAST_DATA, (user, browser), request, seq)
    if view:
        _put(_VIEW_DATA, (user, browser, view_key(view)), request, seq)


def get_data_target(browser: str, user: str = "") -> dict | None:
    """Return the data request behind the view a browser is currently displaying."""
    view = view_key(get_current_view(browser, user))
    if view:
        entry = _VIEW_DATA.get((user, browser, view))
        if entry is None and user:
            entry = _VIEW_DATA.get(("", browser, view))
        if entry is not None:
            return entry[0]
    entry = _LAST_DATA.get((user, browser))
    if entry is None and user:
        entry = _LAST_DATA.get(("", browser))
    return entry[0] if entry is not None else None


def set_table_rows(
    browser: str, rows: list, seq: float = 0.0, user: str = "", view: str = ""
) -> None:
    """Record the table a browser rendered, keyed by the view that rendered it."""
    _put(_TABLE_ROWS, (user, browser, view_key(view)), rows, seq)


def get_table_rows(browser: str, user: str = "", view: str = "") -> list | None:
    """Return the table a browser rendered for one view."""
    entry = _TABLE_ROWS.get((user, browser, view_key(view)))
    if entry is None and user:
        entry = _TABLE_ROWS.get(("", browser, view_key(view)))
    return entry[0] if entry is not None else None


def set_widget_state(
    browser: str, state: dict, seq: float = 0.0, user: str = ""
) -> None:
    """Record the latest widget interaction state for one browser and user."""
    _put(_WIDGET_STATE, (user, browser), state, seq)


def get_widget_state(browser: str, user: str = "") -> dict | None:
    """Return the latest widget interaction state for one browser and user."""
    entry = _WIDGET_STATE.get((user, browser))
    if entry is None and user:
        entry = _WIDGET_STATE.get(("", browser))
    if entry is None:
        entry = _freshest_any_user(_WIDGET_STATE, browser)
    return entry[0] if entry is not None else None


_MAPS_TAB_RE = re.compile(r'<li><label for="maps-eia-tab-\d+">(.*?)</label></li>', re.S)
_MAPS_BLOCK_RE = re.compile(r'<div class="tab-content">', re.S)
_MAPS_SECTION_RE = re.compile(r"<h[12][^>]*>(.*?)</h[12]>", re.S)
_MAPS_ANCHOR_RE = re.compile(
    r'<a href="(?P<href>[^"]+\.(?:pdf|jpe?g|png))"[^>]*?title="(?P<title>[^"]+)"',
    re.I,
)
_MAPS_TITLE_RE = re.compile(
    r"^(?P<name>.+?)\s*\((?P<date>[^()]*)\)\s*\((?:pdf|jpe?g|png)\)\s*$", re.I
)
_MAPS_FORMAT_SUFFIX_RE = re.compile(r"\s*\((?:pdf|jpe?g|png)\)\s*$", re.I)


def _text(fragment: str) -> str:
    """Strip tags, unescape entities, and collapse whitespace in an HTML fragment."""
    from html import unescape

    return " ".join(unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def parse_maps_page(html: str) -> list[dict]:
    """Parse the oil & natural gas maps page into grouped map documents."""
    tabs = [_text(t) for t in _MAPS_TAB_RE.findall(html)]
    tab_starts = [m.start() for m in _MAPS_BLOCK_RE.finditer(html)]
    sections = [(m.start(), _text(m.group(1))) for m in _MAPS_SECTION_RE.finditer(html)]

    def tab_at(pos: int) -> str:
        index = sum(1 for start in tab_starts if start <= pos) - 1
        if index < 0:
            return ""
        return tabs[index] if index < len(tabs) else f"Maps {index + 1}"

    def section_at(pos: int) -> str:
        current = ""
        for start, title in sections:
            if start > pos:
                break
            current = title
        return current

    entries: dict[tuple, dict] = {}
    for match in _MAPS_ANCHOR_RE.finditer(html):
        pos = match.start()
        tab = tab_at(pos)
        if not tab:
            continue
        href = match.group("href")
        section = section_at(pos)
        parsed = _MAPS_TITLE_RE.match(_text(match.group("title")))
        if parsed:
            title, date = parsed.group("name"), parsed.group("date")
        else:
            title = _MAPS_FORMAT_SUFFIX_RE.sub("", _text(match.group("title")))
            date = ""
        if section and title.lower().startswith(f"{section.lower()}:"):
            title = title[len(section) + 1 :].strip()
        key = (tab, section, title, date)
        entry = entries.setdefault(
            key,
            {"tab": tab, "section": section, "title": title, "date": date},
        )
        entry["pdf" if href.lower().endswith(".pdf") else "image"] = href
    return [e for e in entries.values() if e.get("pdf") or e.get("image")]


_MAPS_CATALOG: list[dict] | None = None


async def fetch_maps_catalog() -> list[dict]:
    """Fetch and cache the parsed maps catalog for the process lifetime."""
    global _MAPS_CATALOG  # noqa: PLW0603
    if _MAPS_CATALOG is None:
        body, _content_type = await _fetch_upstream(f"{_EIA_ORIGIN}/{MAPS_PAGE}")
        _MAPS_CATALOG = parse_maps_page(body.decode("utf-8", "replace"))
    return _MAPS_CATALOG


def rewrite_html(
    html: str,
    proxy_prefix: str,
    article: bool = False,
    dark: bool = False,
    browser: str = "",
    user: str = "",
) -> str:
    """Repoint root-absolute paths at the proxy, drop dead scripts, hide chrome."""
    html = _DEAD_SCRIPTS.sub("", html)
    html = _AKAMAI_INLINE.sub("", html)
    html = _AKAMAI_NOSCRIPT.sub("", html)
    html = _SEARCH_INLINE.sub("", html)
    if article:
        html = _ARTICLE_DEAD_SCRIPTS.sub("", html)
    escaped = proxy_prefix.replace("/", "\\/")
    html = _ROOT_PATH_RE.sub(lambda m: f"{m.group(1)}{proxy_prefix}/", html)
    html = _ESCAPED_ROOT_RE.sub(lambda m: f"{m.group(1)}{escaped}\\/", html)
    html = _ABS_EIA_RE.sub(proxy_prefix, html)
    html = _ESCAPED_EIA_RE.sub(escaped, html)
    injected = (
        _CHROME_CSS
        + _MAP_CONTRAST_CSS
        + (_DARK_CSS if dark else "")
        + _NAV_GUARD_JS
        + _ASSET_FIX_JS
    )
    if browser.startswith(("electricity", "coal")):
        injected += _MAP_LAYOUT_CSS
    if browser.startswith("naturalgas/ngqs"):
        injected += _NGQS_GRID_CSS
    if browser.startswith("states"):
        injected += _STATES_CSS
    if browser.startswith("international"):
        injected += _INTERNATIONAL_CSS
    if browser:
        injected += (
            _xhr_tag_js(browser, user)
            + _table_bridge_js(browser, user)
            + _VIEW_SELECT_SYNC_JS
        )
    if article:
        injected += _ARTICLE_CSS
    else:
        injected += _view_bridge_js() + _DIALOG_CLAMP_JS
    if "</head>" in html:
        return html.replace("</head>", injected + "</head>", 1)
    return injected + html


def _split_widget_params(query: str) -> tuple[str, bool, str, str, float, str]:
    """Split the widget theme, browser, view, sequence and user out of a query."""
    from urllib.parse import parse_qsl, urlencode

    dark = False
    browser = ""
    view = ""
    seq = 0.0
    user = ""
    rest: list[tuple[str, str]] = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        if key == "obb_theme":
            dark = value != "light"
        elif key == "obb_browser":
            browser = value if value in _BROWSER_PATHS else ""
        elif key == "obb_view":
            view = value
        elif key == "obb_user":
            user = value
        elif key == "obb_seq":
            try:
                seq = float(value)
            except ValueError:
                seq = 0.0
        else:
            rest.append((key, value))
    return urlencode(rest, safe=",~;"), dark, browser, view, seq, user


def _proxy_prefix(path: str) -> str:
    """Derive the root-absolute proxy mount from a request path."""
    return path.split("/eia_proxy", 1)[0] + "/eia_proxy"


def _redirect_target(prefix: str, landed: str, dark: bool) -> str:
    """Map an upstream redirect back onto the proxy, keeping the widget params."""
    from urllib.parse import parse_qsl, urlencode

    rest = landed[len(_EIA_ORIGIN) + 1 :]
    path, _, query = rest.partition("?")
    params = [(key, value) for key, value in parse_qsl(query, keep_blank_values=True)]
    params.append(("obb_theme", "dark" if dark else "light"))
    return f"{prefix}/{path}?{urlencode(params, safe=';,')}"


_PROXY_CACHE: dict[str, tuple[float, bytes, str]] = {}
_REDIRECTS: dict[str, str] = {}
_PROXY_CACHE_TTL = 3600.0
_PROXY_CACHE_MAX = 512
_REWRITE_CACHE: dict[tuple[str, str], str] = {}
_REWRITE_CACHE_MAX = 256
_REWRITTEN_TTL = 60.0

_CURL_LOCAL = threading.local()


def _curl_session():
    """Return a per-thread curl_cffi session impersonating Chrome."""
    session = getattr(_CURL_LOCAL, "session", None)
    if session is None:
        from curl_cffi import requests as curl_requests

        session = curl_requests.Session(
            impersonate="chrome", timeout=30, headers={"Referer": _EIA_ORIGIN}
        )
        _CURL_LOCAL.session = session
    return session


def _fetch_sync(target: str) -> tuple[bytes, str, int, str]:
    """Fetch a URL on a worker thread, retrying on transient upstream failures."""
    import time

    last: Exception | None = None
    for attempt in range(3):
        try:
            response = _curl_session().get(target, allow_redirects=True)
            content_type = response.headers.get(
                "Content-Type", "application/octet-stream"
            )
            landed = str(response.url) if response.history else ""
            return response.content, content_type, response.status_code, landed
        except Exception as exc:  # noqa: BLE001
            last = exc
            _CURL_LOCAL.session = None
            time.sleep(0.3 * (attempt + 1))
    raise last  # type: ignore[misc]


def _post_sync(target: str, body: bytes, content_type: str) -> tuple[bytes, str, int]:
    """POST a body to an eia.gov endpoint on a worker thread, with retries."""
    import time

    headers = {"Content-Type": content_type} if content_type else {}
    last: Exception | None = None
    for attempt in range(3):
        try:
            response = _curl_session().post(
                target, data=body, headers=headers, allow_redirects=True
            )
            content_type_out = response.headers.get(
                "Content-Type", "application/octet-stream"
            )
            return response.content, content_type_out, response.status_code
        except Exception as exc:  # noqa: BLE001
            last = exc
            _CURL_LOCAL.session = None
            time.sleep(0.3 * (attempt + 1))
    raise last  # type: ignore[misc]


async def post_upstream(
    target: str, body: bytes, content_type: str
) -> tuple[bytes, str]:
    """POST to an eia.gov data endpoint (never cached; the query is dynamic)."""
    import asyncio

    content, ct, _status = await asyncio.to_thread(
        _post_sync, target, body, content_type
    )
    return content, ct


def _cache_dir() -> Path:
    """Return the on-disk proxy cache directory under the user cache root."""
    from openbb_core.app.utils import get_user_cache_directory

    return Path(get_user_cache_directory()) / "eia_proxy"


_STATIC_EXT = (
    ".js",
    ".css",
    ".map",
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".otf",
    ".pdf",
)


def _is_static(target: str) -> bool:
    """Return whether a target is an immutable asset safe to cache on disk."""
    return target.split("?", 1)[0].lower().endswith(_STATIC_EXT)


def _cache_paths(target: str) -> tuple[Path, Path]:
    """Return the ``(body, content-type)`` disk-cache paths for a target URL."""
    from hashlib import sha256

    digest = sha256(target.encode("utf-8")).hexdigest()[:32]
    cache_dir = _cache_dir()
    return cache_dir / digest, cache_dir / f"{digest}.type"


def _remember(target: str, body: bytes, content_type: str) -> None:
    """Store a fetched resource in the in-memory cache, evicting the oldest."""
    from time import monotonic

    if len(_PROXY_CACHE) >= _PROXY_CACHE_MAX:
        oldest = min(_PROXY_CACHE, key=lambda key: _PROXY_CACHE[key][0])
        del _PROXY_CACHE[oldest]
    _PROXY_CACHE[target] = (monotonic(), body, content_type)


async def _fetch_upstream(target: str) -> tuple[bytes, str]:
    """Fetch one eia.gov resource, served from memory then disk before network."""
    from time import monotonic

    cached = _PROXY_CACHE.get(target)
    if cached and monotonic() - cached[0] < _PROXY_CACHE_TTL:
        return cached[1], cached[2]

    static = _is_static(target)
    body_path, type_path = _cache_paths(target)
    if static and body_path.exists() and type_path.exists():
        body = body_path.read_bytes()
        content_type = type_path.read_text(encoding="utf-8")
        _remember(target, body, content_type)
        return body, content_type

    import asyncio

    body, content_type, status, landed = await asyncio.to_thread(_fetch_sync, target)

    if landed and landed != target:
        _REDIRECTS[target] = landed
        _remember(landed, body, content_type)

    if status == 200:
        _remember(target, body, content_type)
        if static:
            try:
                _cache_dir().mkdir(parents=True, exist_ok=True)
                body_path.write_bytes(body)
                type_path.write_text(content_type, encoding="utf-8")
            except OSError:
                pass
    return body, content_type


_WARM_ASSETS = (
    "global/styles/screen.css",
    "global/styles/eia-styles.min.css?v=11.2",
    "global/styles/EIA_global.css?v=11.1",
    "global/scripts/vendor/jquery/jquery.min.js",
    "global/scripts/vendor/jquery-migrate/jquery.migrate.min.js",
    "global/scripts/global.min.js?v=11.3",
    "global/scripts/eia-scripts.min.js?v=11.3",
    "global/scripts/jquery/jquery-1.11.1.min.js",
    "global/scripts/jquery/highcharts/3.0.10/js/highcharts.js",
)
_WARM_TASKS: set = set()
_ASSET_RE = re.compile(
    r"""(?:href|src)=["']([^"']+\.(?:js|css)(?:\?[^"']*)?)["']""", re.I
)
_MODULE_RE = re.compile(r'"([^"]*node_modules[^"]*)"')
_URLARGS_RE = re.compile(r"""urlArgs['"]\]\s*=\s*['"]([^'"]+)['"]""")


async def _page_assets(page_path: str) -> set[str]:
    """Collect the asset URLs a data-browser page declares, including modules."""
    body, _ = await _fetch_upstream(f"{_EIA_ORIGIN}/{page_path}")
    html = body.decode("utf-8", "replace").replace("\\/", "/")
    args = _URLARGS_RE.search(html)
    suffix = f"?{args.group(1)}" if args else ""

    targets: set[str] = set()
    for match in _ASSET_RE.finditer(html):
        url = match.group(1)
        if url.startswith("http"):
            continue
        targets.add(
            f"{_EIA_ORIGIN}{url}"
            if url.startswith("/")
            else f"{_EIA_ORIGIN}/{page_path}{url}"
        )
    for match in _MODULE_RE.finditer(html):
        module = match.group(1)
        if module.startswith("/"):
            targets.add(f"{_EIA_ORIGIN}{module}.js{suffix}")
    return targets


async def _warm_proxy_cache() -> None:
    """Pre-fetch the shared and data-browser assets so the first load is warm."""
    import asyncio
    from contextlib import suppress

    targets: set[str] = {f"{_EIA_ORIGIN}/{asset}" for asset in _WARM_ASSETS}
    with suppress(Exception):
        targets |= await _page_assets(EIA_DATA_BROWSERS["electricity"]["path"])

    semaphore = asyncio.Semaphore(6)

    async def fetch(target: str) -> None:
        async with semaphore:
            with suppress(Exception):
                await _fetch_upstream(target)

    await asyncio.gather(*(fetch(target) for target in targets))


def _schedule_warm() -> None:
    """Kick off the proxy cache warmup in the background at API startup."""
    import asyncio

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_warm_proxy_cache())
    _WARM_TASKS.add(task)
    task.add_done_callback(_WARM_TASKS.discard)


async def eia_table(
    info: Annotated[dict, Depends(request_info)],
) -> Response:
    """Record the table a browser has rendered, so ``raw`` serves that table."""
    import json

    _, _, browser, view, seq, user = _split_widget_params(info["query"])
    if not browser:
        return Response(status_code=204)
    try:
        rows = json.loads(info["body"] or b"[]")
    except ValueError:
        return Response(status_code=204)
    if isinstance(rows, list) and rows and all(isinstance(r, dict) for r in rows):
        set_table_rows(browser, rows, seq, user, view)
    return Response(status_code=204)


async def eia_state(
    info: Annotated[dict, Depends(request_info)],
) -> Response:
    """Record explicit iframe interaction state independently of table rows."""
    import json

    _, _, browser, view, seq, user = _split_widget_params(info["query"])
    if not browser:
        return Response(status_code=204)
    set_current_view(browser, view, seq, user)
    try:
        state = json.loads(info["body"] or b"{}")
    except ValueError:
        state = {}
    if isinstance(state, dict):
        set_widget_state(browser, state, seq, user)
    return Response(status_code=204)


async def eia_mcp_state(browser: str, user: str = "") -> Response:
    """Return the live table for one browser, read from this process's tracked state.

    The EIA MCP tool runs in its own subprocess (see ``eia_mcp.py``) with no
    visibility into this process's in-memory browser state, so it calls back
    here to read exactly what ``raw_table`` would return in this process.
    """
    import json

    spec = EIA_DATA_BROWSERS.get(browser)
    rows = await raw_table(browser, spec, user) if spec is not None else []
    return Response(
        content=json.dumps(rows).encode("utf-8"),
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


async def eia_view(
    info: Annotated[dict, Depends(request_info)],
) -> Response:
    """Record the view a browser navigated to, so ``raw`` follows the current view."""
    _, _, browser, view, seq, user = _split_widget_params(info["query"])
    if browser:
        set_current_view(browser, view, seq, user)
    return Response(status_code=204)


async def eia_proxy(
    path: str,
    info: Annotated[dict, Depends(request_info)],
) -> Response:
    """Reverse-proxy an eia.gov data-browser resource, same-origin."""
    query, dark, tagged, view, seq, user = _split_widget_params(info["query"])
    target = f"{_EIA_ORIGIN}/{path}" + (f"?{query}" if query else "")
    is_post = info["method"] == "POST"
    try:
        if is_post:
            body, content_type = await post_upstream(
                target, info["body"], info["content_type"]
            )
        else:
            body, content_type = await _fetch_upstream(target)
    except Exception:  # noqa: BLE001
        return Response(content=b"Upstream request failed.", status_code=502)

    is_data = is_data_response(target, content_type)
    if is_data and not _PAGE_CONTINUATION_RE.search(target):
        browser = tagged or _derive_browser(path)
        if browser:
            request = {"url": target, "method": info["method"]}
            if is_post:
                request["body"] = info["body"]
                request["content_type"] = info["content_type"]
            if view:
                set_current_view(browser, view, seq, user)
            set_data_target(browser, view, request, seq, user)

    prefix = _proxy_prefix(info["path"])
    landed = _REDIRECTS.get(target)
    if landed and "text/html" in content_type and landed.startswith(f"{_EIA_ORIGIN}/"):
        location = _redirect_target(prefix, landed, dark)
        if location.split("?", 1)[0] != info["path"]:
            return RedirectResponse(location, status_code=307)
    static = {"Cache-Control": f"public, max-age={int(_PROXY_CACHE_TTL)}"}
    if "text/html" in content_type:
        return HTMLResponse(
            content=rewrite_html(
                body.decode("utf-8", "replace"),
                prefix,
                article=path.startswith(_ARTICLE_PATHS),
                dark=dark,
                browser=(path if path in _BROWSER_PATHS else _derive_browser(path)),
                user=user,
            ),
            headers={"Cache-Control": "no-store"},
        )
    return _static_response(path, content_type, body, prefix, is_data, static)


def _rewritten(key: tuple[str, str], build) -> str:
    """Return the rewritten text for ``key``, building and caching it on a miss."""
    cached = _REWRITE_CACHE.get(key)
    if cached is not None:
        return cached
    text = build()
    if len(_REWRITE_CACHE) >= _REWRITE_CACHE_MAX:
        _REWRITE_CACHE.pop(next(iter(_REWRITE_CACHE)))
    _REWRITE_CACHE[key] = text
    return text


def _static_response(
    path: str,
    content_type: str,
    body: bytes,
    prefix: str,
    is_data: bool,
    static: dict,
) -> Response:
    """Rewrite and return a proxied CSS/JS/binary resource."""
    rewritten = {"Cache-Control": f"public, max-age={int(_REWRITTEN_TTL)}"}
    if "text/css" in content_type:

        def build_css() -> str:
            css = body.decode("utf-8", "replace")
            css = re.sub(r"""url\(\s*(['"]?)/(?!/)""", rf"url(\1{prefix}/", css)
            return _ABS_EIA_RE.sub(prefix, css)

        css = _rewritten(("css", f"{prefix}|{path}"), build_css)
        return Response(content=css, media_type="text/css", headers=rewritten)
    if "javascript" in content_type:

        def build_js() -> str:
            script = body.decode("utf-8", "replace")
            if path.startswith(_SPA_PATHS):
                script = _SPA_ROOT_RE.sub(rf"\1{prefix}/\2", script)
            else:
                script = _JS_ROOT_RE.sub(rf"\1{prefix}/\2", script)
            script = _ABS_EIA_RE.sub(prefix, script)
            return _ESCAPED_EIA_RE.sub(prefix.replace("/", "\\/"), script)

        script = _rewritten(("js", f"{prefix}|{path}"), build_js)
        return Response(content=script, media_type=content_type, headers=rewritten)
    headers = {"Cache-Control": "no-store"} if is_data else static
    return Response(content=body, media_type=content_type, headers=headers)


_TABLE_METHOD = "getAggregateData"
_TABLE_ENDPOINT = "data/index.php"
_NON_AGG_HASH_KEYS = frozenset(
    {
        "agg",
        "freq",
        "rtype",
        "ctype",
        "ltype",
        "maptype",
        "rse",
        "pin",
        "start",
        "end",
        "linechart",
        "columnchart",
        "areachart",
        "barchart",
        "map",
        "chartindexed",
    }
)


def table_params_from_hash(fragment: str) -> dict | None:
    """Build the browser's ``getAggregateData`` params from its URL fragment."""
    from urllib.parse import parse_qs

    if not fragment.startswith("#"):
        return None
    path, _, query = fragment[1:].partition("?")
    topic = re.search(r"/topic/(\d+)", path)
    if not topic or not query:
        return None

    values = {key: value[0] for key, value in parse_qs(query).items() if value}
    params: dict[str, str] = {"method": _TABLE_METHOD, "topic": topic.group(1)}
    if "agg" in values:
        params["agg"] = values["agg"]
    for key, value in values.items():
        if key not in _NON_AGG_HASH_KEYS:
            params[key] = value
    params["ids"] = values.get("pin") or values.get(values.get("ctype", ""), "") or ""
    params["freq"] = values.get("freq", "M")
    params["rtype"] = values.get("rtype", "s")
    return params


def _format_period(period: str) -> str:
    """Render an EIA period code as an ISO-style date string."""
    if period.isdigit():
        if len(period) == 6:
            return f"{period[:4]}-{period[4:]}"
        if len(period) == 8:
            return f"{period[:4]}-{period[4:6]}-{period[6:]}"
    return period


def _flatten_cases(data: dict) -> dict:
    """Collapse ``{caseId: {period: value}}`` down to ``{period: value}``."""
    if data and all(isinstance(value, dict) for value in data.values()):
        merged: dict = {}
        for series in data.values():
            merged.update(series)
        return merged
    return data


def _period_columns(all_periods: set) -> list[tuple[str, str]]:
    """Return ``(display, raw)`` period pairs in ascending period order."""
    columns: list[tuple[str, str]] = []
    for period in sorted(all_periods, key=str):
        display = _format_period(str(period))
        if display.isdigit():
            display = f"{display} "
        columns.append((display, period))
    return columns


def _num(value):
    """Coerce a measurement cell to ``float``, or to None.

    EIA marks withheld or negligible values with text in an otherwise numeric
    column -- ``(s)`` for a value too small to display, ``--`` for not
    available, ``W`` for withheld. These are missing data, not labels.
    """
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _table_rows(table: dict) -> list[dict]:
    """One row per series in the browser's table order, periods as columns."""
    units_default = table.get("UNITS") or table.get("units") or ""
    entries = table.get("ROWS") or table.get("rows") or []
    if isinstance(entries, dict):
        entries = list(entries.values())

    parsed: list[tuple[str, str, str, dict]] = []
    all_periods: set = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        data = entry.get("DATA") if "DATA" in entry else entry.get("data")
        data = _flatten_cases(data) if isinstance(data, dict) else {}
        label = (
            entry.get("CHART_NAME")
            or entry.get("chart_name")
            or entry.get("DESCRIPTION")
            or entry.get("description")
            or entry.get("PINNED_NAME")
            or ""
        )
        source = entry.get("SERIES_ID") or entry.get("rowId") or entry.get("MSN") or ""
        units = entry.get("UNITS") or entry.get("units") or units_default
        all_periods.update(data.keys())
        parsed.append((str(label), str(source), str(units), data))

    columns = _period_columns(all_periods)
    rows: list[dict] = []
    for label, source, units, data in parsed:
        row: dict = {"category": label, "units": units, "source_key": source}
        for display, raw in columns:
            row[display] = _num(data.get(raw))
        rows.append(row)
    return rows


def _series_rows(series: list) -> list[dict]:
    """One row per ``{series_id, data}`` series, periods as columns."""
    parsed: list[tuple[str, str, str, dict]] = []
    all_periods: set = set()
    for entry in series:
        if not isinstance(entry, dict):
            continue
        source = str(
            entry.get("series_id") or entry.get("seriesID") or entry.get("id") or ""
        )
        label = str(entry.get("name") or entry.get("description") or source)
        units = str(entry.get("units") or entry.get("unit") or "")
        data = entry.get("data")
        if isinstance(data, dict):
            points = data
        elif isinstance(data, list):
            points = {
                point[0]: point[1]
                for point in data
                if isinstance(point, (list, tuple)) and len(point) > 1
            }
        else:
            continue
        all_periods.update(points.keys())
        parsed.append((label, units, source, points))

    columns = _period_columns(all_periods)
    rows: list[dict] = []
    for label, units, source, points in parsed:
        row: dict = {"category": label, "units": units, "source_key": source}
        for display, raw in columns:
            row[display] = _num(points.get(raw))
        rows.append(row)
    return rows


def _is_states_table(series: list, payload: dict) -> bool:
    """Return True for the State Profiles table payload.

    Its ``series`` entries carry only column metadata; the values live in the
    top-level ``data`` records, keyed by each series' ``column_index``.
    """
    return (
        isinstance(payload.get("data"), list)
        and bool(series)
        and isinstance(series[0], dict)
        and "column_index" in series[0]
    )


def _states_table_rows(series: list, records: list) -> list[dict]:
    """One row per State Profiles series, periods as columns."""
    columns = [
        meta for meta in series if isinstance(meta, dict) and meta.get("column_index")
    ]
    points: dict[str, dict] = {str(meta["column_index"]): {} for meta in columns}
    all_periods: set = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        period = str(record.get("time") or "")
        if not period:
            continue
        all_periods.add(period)
        for key, bucket in points.items():
            if key in record:
                bucket[period] = record[key]

    period_columns = _period_columns(all_periods)
    rows: list[dict] = []
    for meta in columns:
        bucket = points[str(meta["column_index"])]
        row: dict = {
            "category": meta.get("name") or meta.get("series_id") or "",
            "units": meta.get("units") or "",
            "source_key": meta.get("series_id") or "",
        }
        for display, raw in period_columns:
            row[display] = _num(bucket.get(raw))
        rows.append(row)
    return rows


def _ranking_rows(series: list) -> list[dict]:
    """One row per state in a State Energy Profiles ranking."""
    rows: list[dict] = []
    for entry in series:
        if not isinstance(entry, dict):
            continue
        rows.append(
            {
                "category": entry.get("stateName") or entry.get("stateId") or "",
                "units": entry.get("displayName") or "",
                "source_key": entry.get("seriesId") or "",
                "rank": _num(entry.get("rank")),
                "period": entry.get("period") or "",
                "value": _num(entry.get("value")),
            }
        )
    return rows


_SEDS_LABELS: dict = {}


def _seds_labels() -> tuple[dict, dict]:
    """Return ``(state code -> name, MSN code -> series name)`` from the catalog."""
    if not _SEDS_LABELS:
        from openbb_us_eia.utils import catalog

        choices = catalog.get_group("seds").get("choices") or {}
        _SEDS_LABELS["state"] = {
            choice["value"]: choice["label"] for choice in choices.get("state") or []
        }
        _SEDS_LABELS["series"] = {
            choice["value"]: choice["label"] for choice in choices.get("series") or []
        }
    return _SEDS_LABELS["state"], _SEDS_LABELS["series"]


def _state_map_rows(series: dict) -> list[dict]:
    """One row per state for a US map payload (``{msn: {state: value}}``)."""
    state_names, series_names = _seds_labels()
    codes = [code for code, values in series.items() if isinstance(values, dict)]
    states: list[str] = []
    seen: set = set()
    for code in codes:
        for state in series[code]:
            if state not in seen:
                seen.add(state)
                states.append(state)
    rows: list[dict] = []
    for state in states:
        row: dict = {
            "category": state_names.get(state) or state,
            "state": state,
        }
        for code in codes:
            row[series_names.get(code) or code] = _num(series[code].get(state))
        rows.append(row)
    return rows


def _intl_value(point):
    """Return a point's full-precision value, or None for missing markers."""
    if not isinstance(point, list):
        return point
    value = point[-1] if point else None
    return None if isinstance(value, str) else value


def _parse_intl_id(series_id: str) -> tuple[str, str, str, str]:
    """Split an ``INTL.<product>-<activity>-<region>-<unit>.<freq>`` id.

    Returns ``(product, activity, region, unit)``; the product and activity are
    empty when the id carries only a region and unit.
    """
    core = series_id[5:] if series_id.startswith("INTL.") else series_id
    segments = core.rsplit(".", 1)[0].split("-")
    if len(segments) < 2:
        return "", "", "", ""
    if len(segments) < 4:
        return "", "", segments[-2], segments[-1]
    return segments[0], segments[1], segments[-2], segments[-1]


def _sentence(name: str) -> str:
    """Capitalise an EIA label without touching the rest of its casing."""
    return name[:1].upper() + name[1:] if name else ""


def _intl_row_label(product: str, activity: str, labels: dict) -> str:
    """Name a row the way the browser's table does.

    EIA labels a top-level product's row with the activity it totals
    (``Production``), and each child product's row with the product itself
    (``Fuel ethanol``).
    """
    products = labels.get("product") or {}
    activities = labels.get("activity") or {}
    parents = labels.get("parent") or {}
    if product and product in products and parents.get(product) is not None:
        return _sentence(products[product])
    if activity and activity in activities:
        return _sentence(activities[activity])
    return _sentence(products.get(product, ""))


def _epoch_period(stamp, frequency: str) -> str:
    """Render an epoch-millisecond timestamp as the EIA period code for a frequency."""
    from datetime import datetime, timezone

    try:
        moment = datetime.fromtimestamp(int(stamp) / 1000, tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return ""
    if frequency == "M":
        return f"{moment.year}{moment.month:02d}"
    if frequency == "D":
        return f"{moment.year}{moment.month:02d}{moment.day:02d}"
    if frequency == "Q":
        return f"{moment.year}-Q{(moment.month - 1) // 3 + 1}"
    return str(moment.year)


def _is_intl_infographic(data) -> bool:
    """Return True for the International overview's ``series_data/infographic`` rows."""
    return (
        isinstance(data, list)
        and bool(data)
        and isinstance(data[0], dict)
        and "series_id" in data[0]
        and isinstance(data[0].get("data"), list)
    )


def _is_intl_ranking(data) -> bool:
    """Return True for the International overview's flat ``ranking`` records."""
    return (
        isinstance(data, list)
        and bool(data)
        and isinstance(data[0], dict)
        and "ranking" in data[0]
        and "iso" in data[0]
        and "productid" in data[0]
    )


def _ranking_period(value) -> str:
    """Return the four-digit year carried by a ranking's date field."""
    match = re.search(r"\d{4}", str(value if value is not None else ""))
    return match.group(0) if match else ""


def _intl_ranking_rows(records: list, labels: dict | None = None) -> list[dict]:
    """One row per International overview ranking, labelled from the config feeds."""
    labels = labels or {}
    products = labels.get("product") or {}
    activities = labels.get("activity") or {}
    regions = labels.get("region") or {}
    units = labels.get("unit") or {}
    rows: list[dict] = []
    for entry in records:
        if not isinstance(entry, dict):
            continue
        product = products.get(str(entry.get("productid"))) or ""
        activity = activities.get(str(entry.get("activityid"))) or ""
        iso = str(entry.get("iso") or "")
        unit_code = entry.get("unitcode")
        value = entry.get("unrounded_value")
        if value is None:
            value = entry.get("value")
        rows.append(
            {
                "category": _sentence(
                    " ".join(part for part in (product, activity) if part)
                )
                or iso,
                "country": regions.get(iso) or iso,
                "rank": _num(entry.get("ranking")),
                "value": _num(value),
                "units": units.get(unit_code) or (unit_code or ""),
                "period": _ranking_period(entry.get("date")),
                "source_key": iso,
            }
        )
    return rows


def _intl_row(
    series_id: str, country: str, unit: str, labels: dict
) -> tuple[str, str, str, str]:
    """Return ``(label, country, units, source_key)`` for one International series."""
    product, activity, region, coded_unit = _parse_intl_id(series_id)
    regions = labels.get("region") or {}
    units_map = labels.get("unit") or {}
    unit = unit or coded_unit
    return (
        _intl_row_label(product, activity, labels) or series_id,
        country or regions.get(region) or region,
        units_map.get(unit) or unit,
        series_id,
    )


def _intl_infographic_rows(records: list, labels: dict | None = None) -> list[dict]:
    """One row per International overview series, periods as columns."""
    labels = labels or {}
    parsed: list[tuple[tuple[str, str, str, str], dict]] = []
    all_periods: set = set()
    for entry in records:
        if not isinstance(entry, dict):
            continue
        frequency = str(entry.get("frequency") or "A")
        points: dict = {}
        for point in entry.get("data") or []:
            if not isinstance(point, dict):
                continue
            period = _epoch_period(point.get("date"), frequency)
            if period:
                points[period] = point.get("value")
        all_periods.update(points)
        iso = str(entry.get("iso") or "")
        regions = labels.get("region") or {}
        country = regions.get(iso) or iso or str(entry.get("name") or "")
        parsed.append(
            (
                _intl_row(
                    str(entry.get("series_id") or ""),
                    country,
                    str(entry.get("unit") or ""),
                    labels,
                ),
                points,
            )
        )

    columns = _period_columns(all_periods)
    rows: list[dict] = []
    for (label, country, units, source), points in parsed:
        row: dict = {
            "category": label,
            "country": country,
            "units": units,
            "source_key": source,
        }
        for display, raw in columns:
            row[display] = _num(points.get(raw))
        rows.append(row)
    return rows


def _intl_series_rows(data: dict, labels: dict | None = None) -> list[dict]:
    """One row per International series, periods as columns, ordered as displayed.

    The grid groups by country -- World first, then the countries by name -- and
    keeps the product order the payload arrives in. The payload itself is keyed
    product-first, so it has to be regrouped to match the table on screen.
    """
    labels = labels or {}
    order_map: dict[str, int] = labels.get("product_order") or {}
    parsed: list[tuple[tuple, tuple[str, str, str, str], dict]] = []
    all_periods: set = set()
    for series_id, points in data.items():
        if not isinstance(points, dict):
            continue
        product = _parse_intl_id(series_id)[0]
        order = (order_map.get(str(product), len(order_map)), str(product))
        flat = {period: _intl_value(point) for period, point in points.items()}
        all_periods.update(flat.keys())
        parsed.append((order, _intl_row(series_id, "", "", labels), flat))

    parsed.sort(key=lambda item: (item[1][1] != "World", item[1][1], item[0]))

    columns = _period_columns(all_periods)
    rows: list[dict] = []
    for _order, (label, country, units, source), flat in parsed:
        row: dict = {
            "category": label,
            "country": country,
            "units": units,
            "source_key": source,
        }
        for display, raw in columns:
            row[display] = _num(flat.get(raw))
        rows.append(row)
    return rows


def _plant_list_rows(payload: dict) -> list[dict] | None:
    """Rows for the plant-level views, whose table is a record per plant.

    ``DATA_COLUMNS`` is the column set the grid shows; the record carries more
    (coordinates, ids) that the table does not.
    """
    records = payload.get("DATA")
    columns = payload.get("DATA_COLUMNS")
    if not isinstance(records, list) or not isinstance(columns, list):
        return None
    if not records or not isinstance(records[0], dict):
        return None
    names = [name for name in columns if isinstance(name, str)]
    if not names:
        return None
    return [{name: record.get(name) for name in names} for record in records]


def _dict_payload_rows(payload: dict) -> list[dict]:
    """Shape-dispatch a dict payload into tabular rows.

    The classic browsers return the table under ``TABLEDATA`` (electricity,
    coal, imports), lowercase ``tabledata`` (AEO), or ``VIEWSDATA`` (STEO,
    which has no ``TABLEDATA``). ``SERIESDATA`` holds the separately pinned
    series and is only the table when no standard view is selected.
    """
    plants = _plant_list_rows(payload)
    if plants is not None:
        return plants
    return _keyed_payload_rows(payload)


def _keyed_payload_rows(payload: dict) -> list[dict]:
    """Rows for a payload that names its table under a known key."""
    table = payload.get("TABLEDATA") or payload.get("tabledata")
    if not isinstance(table, dict):
        for key in ("VIEWSDATA", "SERIESDATA"):
            candidate = payload.get(key)
            if isinstance(candidate, dict) and candidate.get("ROWS"):
                table = candidate
                break
    if isinstance(table, dict):
        return _table_rows(table)
    if isinstance(payload.get("TABLE_DATA"), list):
        return _series_rows(payload["TABLE_DATA"])
    series = payload.get("series")
    if isinstance(series, list) and series:
        if _is_states_table(series, payload):
            return _states_table_rows(series, payload["data"])
        return (
            _series_rows(series)
            if isinstance(series[0], dict) and "data" in series[0]
            else _ranking_rows(series)
        )
    if isinstance(series, dict) and series:
        return _state_map_rows(series)
    return _data_payload_rows(payload.get("data"))


def _data_payload_rows(data) -> list[dict]:
    """Rows for a ``data``-keyed payload (International series, overview, or plain)."""
    if isinstance(data, dict):
        return _intl_series_rows(data)
    if _is_intl_infographic(data):
        return _intl_infographic_rows(data)
    return (
        [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []
    )


def rows_from_payload(payload) -> list[dict]:
    """Shape-dispatch any EIA browser's data payload into tabular rows."""
    if isinstance(payload, dict):
        return _dict_payload_rows(payload)
    if not isinstance(payload, list):
        return []
    nested = [rows_from_payload(item) for item in payload if isinstance(item, dict)]
    if any(nested):
        return [row for rows in nested for row in rows]
    return [row for row in payload if isinstance(row, dict)]


def _inline_payload(html: str) -> dict:
    """Return Total Energy's inline ``sampleData`` payload, or an empty dict."""
    import json

    start = html.find("sampleData")
    brace = html.find("{", start) if start >= 0 else -1
    if brace < 0:
        return {}
    try:
        payload, _ = json.JSONDecoder().raw_decode(html, brace)
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def parse_inline_table(html: str) -> list[dict]:
    """Pivot Total Energy's inline ``sampleData`` (ROWS/DATACOLUMNS) into rows."""
    payload = _inline_payload(html)
    return _table_rows(payload) if payload else []


def _ngqs_rows(payload: dict) -> list[dict]:
    """Rows for the Natural Gas Query System, using the grid's own column headers.

    The report ships ``columns`` (``headerName``/``field``) alongside ``data``,
    whose records are keyed by the short field ids the grid binds to.
    """
    columns = payload.get("columns")
    records = payload.get("data")
    if not isinstance(columns, list) or not isinstance(records, list):
        return []
    headers: list[tuple[str, str, bool]] = []
    for column in columns:
        if not isinstance(column, dict) or not column.get("field"):
            continue
        header = _text(str(column.get("headerName") or column["field"]))
        if header.isdigit():
            header = f"{header} "
        headers.append((header, column["field"], bool(column.get("numeric"))))

    rows: list[dict] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        row: dict = {}
        for header, field, numeric in headers:
            value = record.get(field)
            row[header] = _num(value) if numeric else value
        rows.append(row)
    return rows


_IMPORTS_LABELS: dict = {}
_IMPORTS_CONFIG = "petroleum/imports/browser/data/index.php?method=getConfig"
_IMPORTS_UNITS = "thousand barrels"


async def _imports_label_maps() -> dict:
    """Return the origin, destination and grade names the imports table is built from.

    The imports endpoint returns only ``seriesID`` and ``data``; the browser
    builds every row label client-side from its config.
    """
    import json

    if _IMPORTS_LABELS:
        return _IMPORTS_LABELS
    try:
        body, _ = await _fetch_upstream(f"{_EIA_ORIGIN}/{_IMPORTS_CONFIG}")
        config = json.loads(body)
    except (ValueError, OSError):
        return {}

    def named(items) -> dict[str, str]:
        return {
            str(item["id"]): item["name"]
            for item in items or []
            if item.get("id") and item.get("name")
        }

    states, padds = named(config.get("states")), named(config.get("padds"))
    labels = {
        "origin": {
            "CTY": named(config.get("countries")),
            "REG": named(config.get("regions")),
            "OPN": named(config.get("opecNonOpec")),
        },
        "destination": {
            "RF": named(config.get("refineries")),
            "PT": named(config.get("ports")),
            "RS": states,
            "PS": states,
            "RP": padds,
            "PP": padds,
        },
        "grade": named(config.get("grades")),
    }
    if labels["grade"]:
        _IMPORTS_LABELS.update(labels)
    return labels


def _imports_name(segment: str, maps: dict) -> str:
    """Resolve a ``<TYPE>_<id>`` (or bare id) series segment to its name."""
    kind, _, ident = segment.partition("_")
    if ident:
        return (maps.get(kind) or {}).get(ident) or segment
    for table in maps.values():
        if segment in table:
            return table[segment]
    return segment


def _imports_rows(records: list, labels: dict | None = None) -> list[dict]:
    """One row per imports series, labelled the way the browser's table is."""
    labels = labels or {}
    origins = labels.get("origin") or {}
    destinations = labels.get("destination") or {}
    grades = labels.get("grade") or {}
    parsed: list[tuple[tuple[str, str, str, str, str], dict]] = []
    all_periods: set = set()
    for entry in records:
        if not isinstance(entry, dict):
            continue
        series_id = str(entry.get("seriesID") or "")
        points = entry.get("data")
        points = points if isinstance(points, dict) else {}
        all_periods.update(points)
        parts = series_id.split(".")
        segments = parts[1].split("-") if len(parts) > 2 else []
        if len(segments) < 3:
            parsed.append(((series_id, "", "", "", series_id), points))
            continue
        origin = _imports_name(segments[0], origins)
        destination = _imports_name(segments[1], destinations)
        grade = (
            "all grades"
            if segments[2] == "ALL"
            else (grades.get(segments[2]) or segments[2])
        )
        cadence = "annual" if parts[2].upper() == "A" else "monthly"
        label = f"Imports of {grade} from {origin} to {destination}, {cadence}"
        parsed.append(((label, origin, destination, grade, series_id), points))

    columns = _period_columns(all_periods)
    rows: list[dict] = []
    for (label, origin, destination, grade, source), points in parsed:
        row: dict = {
            "category": label,
            "origin": origin,
            "destination": destination,
            "grade": grade,
            "units": _IMPORTS_UNITS,
            "source_key": source,
        }
        for display, raw in columns:
            row[display] = _num(points.get(raw))
        rows.append(row)
    return rows


_INTL_LABELS: dict = {}
_INTL_LABEL_FEEDS = ("countries", "political_groups", "units", "products", "activities")


async def _intl_label_maps() -> dict:
    """Return the region, unit, product and activity names International rows need."""
    import json

    if _INTL_LABELS:
        return _INTL_LABELS
    feeds: dict[str, list] = {}
    try:
        for feed in _INTL_LABEL_FEEDS:
            body, _ = await _fetch_upstream(
                f"{_EIA_ORIGIN}/international/api/{feed}/data"
            )
            feeds[feed] = json.loads(body).get("data", [])
    except (ValueError, OSError):
        return {}
    region_map = {c["iso"]: c["name"] for c in feeds["countries"] if c.get("iso")}
    region_map.update(
        {
            g["iso"]: g["name"]
            for g in feeds["political_groups"]
            if g.get("iso") and g.get("name")
        }
    )
    labels = {
        "region": region_map,
        "unit": {
            u["code"]: (u.get("short_name") or u.get("name"))
            for u in feeds["units"]
            if u.get("code")
        },
        "product": {
            str(p["id"]): p["name"] for p in feeds["products"] if p.get("name")
        },
        "activity": {
            str(a["id"]): a["name"] for a in feeds["activities"] if a.get("name")
        },
        "parent": {
            str(p["id"]): p.get("parent") for p in feeds["products"] if p.get("id")
        },
        "product_order": {
            str(p["id"]): index
            for index, p in enumerate(feeds["products"])
            if p.get("id") is not None
        },
    }
    if region_map:
        _INTL_LABELS.update(labels)
    return labels


_PAYLOAD_FIRST = frozenset({"petroleum_imports"})


def _view_query(view: str) -> str:
    """Return a view's own query string, dropping the widget's ``obb_`` markers."""
    from urllib.parse import parse_qsl, urlencode

    query = view.partition("#")[0].partition("?")[2]
    kept = [
        (key, value)
        for key, value in parse_qsl(query, keep_blank_values=True)
        if not key.startswith("obb_")
    ]
    return urlencode(kept, safe=",~;")


def _mer_hash_state(view: str) -> tuple[str, str, str]:
    """Return the ``(frequency, start, end)`` the MER hash encodes for a view."""
    from urllib.parse import parse_qs

    fragment = view.partition("#")[2]
    query = fragment.partition("?")[2] if "?" in fragment else ""
    params = parse_qs(query)
    return (
        (params.get("f") or [""])[0],
        (params.get("start") or [""])[0],
        (params.get("end") or [""])[0],
    )


def _filter_mer_payload(payload: dict, freq: str, start: str, end: str) -> None:
    """Narrow the inline table to one frequency and the selected period range.

    The inline data carries every period at once -- annual codes are four digits,
    monthly six -- so the frequency picks the column width and start/end clip it
    to what the time slider shows.
    """
    rows = payload.get("ROWS") or []
    if freq not in ("M", "A"):
        freq = (
            "M"
            if any(
                len(str(period)) == 6
                for row in rows
                if isinstance(row, dict)
                for period in row.get("DATA") or {}
            )
            else "A"
        )
    width = 6 if freq == "M" else 4
    for row in rows:
        if not isinstance(row, dict):
            continue
        row["DATA"] = {
            period: value
            for period, value in (row.get("DATA") or {}).items()
            if len(str(period)) == width
            and (not start or str(period) >= start)
            and (not end or str(period) <= end)
        }


async def _total_energy_table(path: str, user: str) -> list[dict]:
    """Return the Monthly Energy Review table the user is viewing, from its inline data.

    The MER browser reloads to ``?tbl=<table>`` and keeps the frequency and time
    range in its hash, so the tracked view names the full state. Fetching that
    page and pivoting its inline data -- narrowed to that frequency and range --
    is deterministic, with no scrape or recorded request to go stale or wrong.
    """
    view = get_current_view(path, user)
    query = _view_query(view)
    url = f"{_EIA_ORIGIN}/{path}" + (f"?{query}" if query else "")
    body, _ = await _fetch_upstream(url)
    payload = _inline_payload(body.decode("utf-8", "replace"))
    if not payload:
        return []
    _filter_mer_payload(payload, *_mer_hash_state(view))
    return _table_rows(payload)


async def raw_table(browser: str, spec: dict, user: str = "") -> list[dict]:
    """Return the table the browser is showing, hierarchical where its payload allows."""
    import json
    from urllib.parse import urlencode

    if browser == "maps":
        return await fetch_maps_catalog()

    path = spec["path"]
    if browser == "total_energy":
        return await _total_energy_table(path, user)

    view = get_current_view(path, user)
    payload_first = browser in _PAYLOAD_FIRST
    if not payload_first:
        rendered = get_table_rows(path, user, view)
        if rendered:
            return rendered

    request = get_data_target(path, user)
    if request is None:
        params = table_params_from_hash(spec["hash"])
        if params is None:
            return (get_table_rows(path, user, view) or []) if payload_first else []
        query = urlencode(params, safe="~,")
        endpoint = f"{_EIA_ORIGIN}/{path}{_TABLE_ENDPOINT}?{query}"
        request = {"url": endpoint, "method": "GET"}

    if request.get("method") == "POST":
        raw_body = request.get("body")
        body, _ = await post_upstream(
            request["url"],
            raw_body if isinstance(raw_body, bytes) else b"",
            str(request.get("content_type") or ""),
        )
    else:
        body, _ = await _fetch_upstream(request["url"])
    try:
        payload = json.loads(body)
    except (ValueError, AttributeError):
        return (get_table_rows(path, user, view) or []) if payload_first else []
    payload = await _all_pages(request, payload)
    labelled = await _labelled_rows(browser, payload, view)
    result = rows_from_payload(payload) if labelled is None else labelled
    return (
        result
        if result or not payload_first
        else (get_table_rows(path, user, view) or [])
    )


async def _all_pages(request: dict, payload):
    """Follow a paged payload to its end, so ``raw`` is never a partial table.

    The page asks for ``limit`` series at a time and stitches the pages together
    as they land. Replaying only the request that was recorded would answer with
    the first page and silently drop the rest of the table.
    """
    import json
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
        return payload
    total = payload.get("totalCount")
    if not isinstance(total, int) or len(payload["data"]) >= total:
        return payload

    parts = urlparse(request["url"])
    query = dict(parse_qsl(parts.query))
    try:
        limit = int(query.get("limit", 0))
    except ValueError:
        return payload
    if limit <= 0:
        return payload

    merged = dict(payload["data"])
    offset = limit
    while len(merged) < total and offset < total:
        query["offset"] = str(offset)
        page_url = urlunparse(parts._replace(query=urlencode(query, safe="~,")))
        body, _ = await _fetch_upstream(page_url)
        try:
            page = json.loads(body)
        except (ValueError, AttributeError):
            break
        chunk = page.get("data") if isinstance(page, dict) else None
        if not isinstance(chunk, dict) or not chunk:
            break
        merged.update(chunk)
        offset += limit

    return {**payload, "data": merged, "recordCount": len(merged)}


async def _labelled_rows(browser: str, payload, view: str = "") -> list[dict] | None:
    """Rows for the browsers whose tables are labelled from a separate config."""
    if not isinstance(payload, dict):
        return None
    if browser == "international":
        return await _intl_rows(payload)
    if browser == "petroleum_imports":
        records = payload.get("TABLE_DATA")
        if isinstance(records, list) and records:
            return _imports_rows(records, await _imports_label_maps())
    if browser == "natural_gas_query" and isinstance(payload.get("columns"), list):
        return _ngqs_rows(payload)
    return None


async def _intl_rows(payload: dict) -> list[dict] | None:
    """Rows for an International payload, labelled the way its table is."""
    data = payload.get("data")
    if isinstance(data, dict):
        return _intl_series_rows(data, await _intl_label_maps())
    if isinstance(data, list) and _is_intl_infographic(data):
        return _intl_infographic_rows(data, await _intl_label_maps())
    if isinstance(data, list) and _is_intl_ranking(data):
        return _intl_ranking_rows(data, await _intl_label_maps())
    return None


def _widget_src(
    proxy_base: str, path: str, default_hash: str, view: str, mode: str, user: str
) -> str:
    """Build the iframe src, restoring the user's last view when one was stashed."""
    from urllib.parse import parse_qsl, urlencode

    if view:
        head, marker, fragment = view.partition("#")
        path, _, search = head.partition("?")
        extra = [
            (key, value)
            for key, value in parse_qsl(search, keep_blank_values=True)
            if not key.startswith("obb_")
        ]
        tail = f"#{fragment}" if marker else ""
    else:
        extra = []
        tail = default_hash
    params = [("obb_theme", mode)]
    if user:
        params.append(("obb_user", user))
    params.extend(extra)
    return f"{proxy_base}/{path}?{urlencode(params, safe=',~;')}{tail}"


async def render_browser(
    browser: str,
    theme: str,
    raw: bool,
    info: dict | None,
) -> Response:
    """Render one EIA data browser as an HTML widget, or its table as raw rows."""
    import json
    import os

    from openbb_core.app.service.system_service import SystemService

    spec = EIA_DATA_BROWSERS.get(browser) or EIA_DATA_BROWSERS["electricity"]
    info = info or {}
    user = info.get("user", "")
    if raw:
        return JSONResponse(
            content=await raw_table(browser, spec, user),
            headers={"Cache-Control": "no-store"},
        )
    endpoint = info.get("url")
    if endpoint:
        proxy_base = endpoint.rsplit("/", 1)[0] + "/eia_proxy"
    else:
        host = os.environ.get("OPENBB_API_HOST", "127.0.0.1")
        port = os.environ.get("OPENBB_API_PORT", "6900")
        prefix = SystemService().system_settings.api_settings.prefix
        root = f"http://{host}:{port}{prefix}/eia"
        endpoint = f"{root}/{browser}_browser"
        proxy_base = f"{root}/eia_proxy"
    mode = "light" if theme == "light" else "dark"
    view = "" if browser == "maps" else get_current_view(spec["path"], user)
    payload: dict = {
        "mode": "site",
        "theme": mode,
        "browser": browser,
        "path": spec["path"],
        "user": user,
        "label": spec["label"],
        "description": spec["description"],
        "endpoint": endpoint,
        "src": _widget_src(proxy_base, spec["path"], spec["hash"], view, mode, user),
        "home": _widget_src(proxy_base, spec["path"], spec["hash"], "", mode, user),
        "proxy": proxy_base,
        "maps": [],
    }
    if browser == "maps":
        payload["mode"] = "maps"
        payload["maps"] = await fetch_maps_catalog()
    blob = (
        json.dumps(payload)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    template = _TEMPLATE.read_text(encoding="utf-8")
    return HTMLResponse(
        content=template.replace("__EIA_BROWSER_DATA__", blob),
        headers={"Cache-Control": "no-cache"},
    )


@asynccontextmanager
async def lifespan(_app) -> AsyncGenerator[None, None]:
    """Warm the proxy cache for the lifetime of the API, cleaning up on shutdown."""
    _schedule_warm()
    try:
        yield
    finally:
        for task in list(_WARM_TASKS):
            task.cancel()


router._api_router.lifespan_context = lifespan

router._api_router.add_api_route(
    path="/eia_proxy/{path:path}",
    endpoint=eia_proxy,
    methods=["GET", "POST"],
    include_in_schema=False,
)

router._api_router.add_api_route(
    path="/eia_view",
    endpoint=eia_view,
    methods=["GET", "POST"],
    include_in_schema=False,
)

router._api_router.add_api_route(
    path="/eia_table",
    endpoint=eia_table,
    methods=["POST"],
    include_in_schema=False,
)

router._api_router.add_api_route(
    path="/eia_state",
    endpoint=eia_state,
    methods=["POST"],
    include_in_schema=False,
)

router._api_router.add_api_route(
    path="/eia_mcp_state",
    endpoint=eia_mcp_state,
    methods=["GET"],
    include_in_schema=False,
)


def _browser_endpoint(browser: str):
    """Build the widget endpoint bound to one EIA data browser."""

    async def endpoint(
        info: Annotated[dict | None, Depends(request_info)] = None,
        theme: str = "dark",
        raw: bool = False,
    ) -> Any:
        import json

        response = await render_browser(browser, theme, raw, info)
        if info is None:
            body = bytes(response.body)
            if isinstance(response, JSONResponse):
                return json.loads(body)
            return body.decode("utf-8", "replace")
        return response

    endpoint.__name__ = f"{browser}_browser"
    endpoint.__doc__ = EIA_DATA_BROWSERS[browser]["description"]
    return endpoint


def widget_route(browser: str) -> str:
    """Return the widget route path for one EIA data browser."""
    return f"/{browser}_browser"


def widget_id(browser: str) -> str:
    """Return the Workspace widget id for one EIA data browser."""
    return f"eia_{browser}_browser_us_eia_obb"


for _browser, _spec in EIA_DATA_BROWSERS.items():
    router._api_router.add_api_route(
        path=widget_route(_browser),
        endpoint=_browser_endpoint(_browser),
        methods=["GET"],
        response_class=HTMLResponse,
        openapi_extra={
            "widget_config": {
                "name": f"EIA {_spec['label']} Browser",
                "description": _spec["description"],
                "category": "EIA",
                "subCategory": "Data Browsers",
                "source": ["EIA"],
                "type": "iframe",
                "widgetId": widget_id(_browser),
                "gridData": {"w": 40, "h": 22},
                "params": [
                    {"paramName": "theme", "show": False},
                    {"paramName": "raw", "show": False},
                ],
                "refetchInterval": False,
                "staleTime": 1000,
                "raw": True,
                "storage": {"mcpUrl": _mcp_url()},
            }
        },
    )
