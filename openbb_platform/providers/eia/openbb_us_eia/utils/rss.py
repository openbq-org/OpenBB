"""EIA RSS feed registry, item building, and HTML-widget rendering."""

from datetime import UTC, datetime
from pathlib import Path
from time import struct_time
from typing import TYPE_CHECKING
from urllib.parse import urljoin, urlsplit, urlunsplit

if TYPE_CHECKING:
    from aiohttp import ClientSession

EIA_SITE = "https://www.eia.gov/"
_TEMPLATE = Path(__file__).parents[1] / "assets" / "rss_feed.html"

EIA_RSS_FEEDS: dict[str, dict[str, str]] = {
    "today_in_energy": {
        "label": "Today in Energy",
        "description": "Short, timely articles with graphics on energy facts,"
        " issues, and trends.",
        "url": "https://www.eia.gov/rss/todayinenergy.xml",
        "base": "https://www.eia.gov/todayinenergy/",
        "viewer": "page",
    },
    "whats_new": {
        "label": "What's New",
        "description": "Notification of new EIA products as they are released.",
        "url": "https://www.eia.gov/about/new/WNtest3.php",
        "base": EIA_SITE,
        "viewer": "page",
    },
    "press_releases": {
        "label": "Press Releases",
        "description": "Press releases from the Energy Information Administration.",
        "url": "https://www.eia.gov/rss/press_rss.xml",
        "base": EIA_SITE,
        "viewer": "page",
    },
    "congressional_testimony": {
        "label": "Congressional Testimony",
        "description": "Scheduled testimonies and information EIA presented to"
        " Congress.",
        "url": "https://www.eia.gov/rss/testimony.xml",
        "base": EIA_SITE,
        "viewer": "pdf",
    },
    "presentations": {
        "label": "Presentations",
        "description": "Presentations and speeches given by EIA at various venues.",
        "url": "https://www.eia.gov/rss/presentations.xml",
        "base": EIA_SITE,
        "viewer": "pdf",
    },
    "gasoline_diesel": {
        "label": "Gasoline & Diesel Fuel Update",
        "description": "Retail gasoline and on-highway diesel fuel prices,"
        " nationally and by region.",
        "url": "https://www.eia.gov/petroleum/gasdiesel/includes/gas_diesel_rss.xml",
        "base": "https://www.eia.gov/petroleum/gasdiesel/",
        "viewer": "table",
    },
    "heating_oil_propane": {
        "label": "Heating Oil & Propane Update",
        "description": "Heating oil and propane retail prices and supply,"
        " nationally and by region (October-March).",
        "url": "https://www.eia.gov/petroleum/heatingoilpropane/includes/hopu_rss.xml",
        "base": "https://www.eia.gov/petroleum/heatingoilpropane/",
        "viewer": "table",
    },
}

FEED_TIMEOUT_SEC = 10.0


def feed_choices() -> list[dict[str, str]]:
    """Return ``[{label, value}]`` for every EIA RSS feed (tab options)."""
    return [
        {"label": feed["label"], "value": key} for key, feed in EIA_RSS_FEEDS.items()
    ]


def strip_html(text: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    if not text:
        return ""
    from html.parser import HTMLParser

    parts: list[str] = []

    class _Stripper(HTMLParser):
        def handle_data(self, data: str) -> None:
            parts.append(data)

    stripper = _Stripper()
    stripper.feed(text)
    return " ".join("".join(parts).split())


_EXCERPT_TAGS = {"strong", "em", "b", "i", "sub", "sup"}
_VOID_TAGS = {"script", "style"}


def article_text(html: str, limit: int = 20000) -> str:
    """Extract an article page's readable text, dropping script/style contents.

    ``strip_html`` keeps every data node, which on a full page pulls inline
    JavaScript and CSS into the result; this mutes ``_VOID_TAGS`` so the output
    is the prose an agent can actually read.
    """
    if not html:
        return ""
    from html.parser import HTMLParser

    class _Text(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []
            self.muted: list[str] = []

        def handle_starttag(self, tag: str, attrs: list) -> None:
            if tag in _VOID_TAGS:
                self.muted.append(tag)

        def handle_endtag(self, tag: str) -> None:
            if tag in _VOID_TAGS and tag in self.muted:
                self.muted.remove(tag)

        def handle_data(self, data: str) -> None:
            if not self.muted:
                self.parts.append(data)

    parser = _Text()
    parser.feed(html)
    return " ".join("".join(parser.parts).split())[:limit]


def clean_excerpt(summary: str, limit: int = 320) -> str:
    """Decode a feed summary to sanitized inline HTML, truncated to ``limit`` chars."""
    from html import escape, unescape
    from html.parser import HTMLParser

    class _Excerpt(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.parts: list[str] = []
            self.count = 0
            self.open: list[str] = []
            self.muted: list[str] = []
            self.done = False

        def handle_starttag(self, tag: str, attrs: list) -> None:
            if tag in _VOID_TAGS:
                self.muted.append(tag)
                return
            if self.done or tag not in _EXCERPT_TAGS:
                return
            self.parts.append(f"<{tag}>")
            self.open.append(tag)

        def handle_endtag(self, tag: str) -> None:
            if tag in _VOID_TAGS:
                if tag in self.muted:
                    self.muted.remove(tag)
                return
            if self.done or tag not in self.open:
                return
            while self.open:
                current = self.open.pop()
                self.parts.append(f"</{current}>")
                if current == tag:
                    break

        def handle_data(self, data: str) -> None:
            if self.done or self.muted:
                return
            remaining = limit - self.count
            if remaining <= 0:
                self.done = True
                return
            text = data
            if len(text) > remaining:
                text = text[:remaining].rsplit(" ", 1)[0].rstrip(",.;:") + "…"
                self.done = True
            self.parts.append(escape(text))
            self.count += len(text)

        def result(self) -> str:
            for tag in reversed(self.open):
                self.parts.append(f"</{tag}>")
            return "".join(self.parts)

    parser = _Excerpt()
    parser.feed(unescape(summary or ""))
    return parser.result()


def struct_time_to_iso(value: "struct_time | None") -> str:
    """Convert a feedparser ``struct_time`` to an ISO 8601 string."""
    if value is None:
        return datetime.now(UTC).isoformat()
    return datetime(*value[:6], tzinfo=UTC).isoformat()


async def fetch_feed(session: "ClientSession", url: str, retries: int = 3):
    """Fetch and parse an RSS feed, retrying transient failures."""
    import asyncio

    import aiohttp
    import feedparser

    for attempt in range(retries):
        try:
            response = await session.get(
                url,
                headers={
                    "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8"
                },
                timeout=aiohttp.ClientTimeout(total=FEED_TIMEOUT_SEC),
            )
            async with response:
                response.raise_for_status()
                payload = await response.read()
            return feedparser.parse(payload)
        except (aiohttp.ClientError, TimeoutError):
            if attempt + 1 < retries:
                await asyncio.sleep(0.4 * (attempt + 1))
    return feedparser.parse(b"")


def _youtube_embed(url: str) -> str | None:
    """Return a YouTube embed URL for a watch/short link, else ``None``."""
    import re

    match = re.search(r"(?:youtu\.be/|youtube\.com/(?:watch\?v=|embed/))([\w-]+)", url)
    return f"https://www.youtube.com/embed/{match.group(1)}" if match else None


def render_price_table(description: str) -> str:
    """Render a fuel-price feed item's ``<br/>`` table as HTML sections."""
    import re

    text = re.sub(r"(?i)<br\s*/?>", "\n", description or "")
    text = strip_html(text) if "<" in text else text
    row_re = re.compile(r"^([\d.,]+)\s*\.{2,}\s*(.+)$")
    parts: list[str] = []
    open_table = False
    for raw in text.split("\n"):
        line = " ".join(raw.split())
        if not line or line.lower().startswith("summary excerpt"):
            continue
        match = row_re.match(line)
        if match:
            if not open_table:
                parts.append('<table class="price">')
                open_table = True
            value, label = match.group(1), _escape(match.group(2))
            parts.append(f"<tr><td>{label}</td><td class=v>{value}</td></tr>")
        else:
            if open_table:
                parts.append("</table>")
                open_table = False
            parts.append(f"<h4>{_escape(line)}</h4>")
    if open_table:
        parts.append("</table>")
    return "".join(parts)


def _escape(text: str) -> str:
    """Escape text for safe inclusion in HTML."""
    from html import escape

    return escape(text or "")


def build_feed(feed_key: str, parsed, limit: int, proxy_base: str = "") -> dict:
    """Normalize a parsed feed into the widget's data payload."""
    spec = EIA_RSS_FEEDS[feed_key]
    base = spec["base"]
    viewer = spec["viewer"]
    feed_title = (parsed.feed.get("title") if parsed.feed else "") or spec["label"]
    entries = sorted(
        parsed.entries,
        key=lambda e: e.get("published_parsed") or e.get("updated_parsed") or (0,) * 9,
        reverse=True,
    )[:limit]

    items: list[dict] = []
    for entry in entries:
        summary = entry.get("summary") or entry.get("description") or ""
        link = urljoin(base, (entry.get("link") or "").strip())
        item: dict = {
            "title": (entry.get("title") or "(untitled)").strip(),
            "date": struct_time_to_iso(
                entry.get("published_parsed") or entry.get("updated_parsed")
            ),
            "author": (entry.get("author") or feed_title).strip(),
            "url": link,
            "excerpt": clean_excerpt(summary),
            "viewer": viewer,
            "src": link,
            "meta": [],
            "body_html": "",
        }
        if viewer == "pdf":
            _fill_presentation(item, entry, base)
        elif viewer == "table":
            item["body_html"] = render_price_table(summary)
        src_parts = urlsplit(item["src"])
        src_host = (src_parts.hostname or "").lower()
        if (
            item["viewer"] in ("page", "pdf")
            and proxy_base
            and (src_host == "eia.gov" or src_host.endswith(".eia.gov"))
        ):
            tail = urlunsplit(
                ("", "", src_parts.path, src_parts.query, src_parts.fragment)
            ).lstrip("/")
            item["src"] = f"{proxy_base}/{tail}"
        items.append(item)

    return {
        "feed": feed_key,
        "label": spec["label"],
        "description": spec["description"],
        "items": items,
    }


def _fill_presentation(item: dict, entry: dict, base: str) -> None:
    """Populate a testimony/presentation item's PDF source and metadata."""
    pdf = str(entry.get("eia_pdf") or "").strip()
    ppt = str(entry.get("eia_ppt") or "").strip()
    item["ppt_url"] = urljoin(base, ppt) if ppt else ""
    if pdf:
        item["src"] = urljoin(base, pdf)
    elif (embed := _youtube_embed(item["url"])) is not None:
        item["src"] = embed
        item["viewer"] = "embed"
    else:
        item["viewer"] = "page"
    for key, label in (
        ("eia_subject", "Subject"),
        ("eia_presentedby", "Presented by"),
        ("eia_presentedto", "Presented to"),
        ("eia_location", "Location"),
    ):
        value = strip_html(str(entry.get(key) or "")).strip()
        if value:
            item["meta"].append({"label": label, "value": value})


def render_rss_html(data: dict, theme: str) -> str:
    """Render the widget HTML for a built feed payload and theme."""
    import json

    payload = {**data, "theme": "light" if theme == "light" else "dark"}
    blob = (
        json.dumps(payload)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    template = _TEMPLATE.read_text(encoding="utf-8")
    return template.replace("__EIA_RSS_DATA__", blob)
