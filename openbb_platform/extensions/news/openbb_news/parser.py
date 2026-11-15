"""RSS/Atom feed and article body helpers."""

import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from time import struct_time
from typing import TYPE_CHECKING, NamedTuple

if TYPE_CHECKING:
    from aiohttp import ClientSession

_CHROME_TAGS: tuple[str, ...] = (
    "script",
    "style",
    "noscript",
    "iframe",
    "nav",
    "header",
    "footer",
    "aside",
    "form",
    "button",
    "svg",
)
_TEMPLATE_MARKERS: tuple[str, ...] = ("[[", "{{")
_MIN_PARAGRAPHS = 2
_FEED_TIMEOUT_SEC = 8.0
_ARTICLE_TIMEOUT_SEC = 6.0
_TIMESTAMP_RE = re.compile(r"^\d{1,2}:\d{2}(?::\d{2})?$")


_WEBKIT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    " (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_SAFARI_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_7) AppleWebKit/605.1.15"
    " (KHTML, like Gecko) Version/18.2 Safari/605.1.15"
)
_FEED_ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "application/rss+xml,application/atom+xml,*/*;q=0.8"
)
# The shared session decodes only gzip/deflate. Overriding request headers
# drops its default Accept-Encoding, so aiohttp advertises br, which then
# arrives undecoded and unparseable; pin an encoding the session can decode.
_SAFE_ENCODING = "gzip, deflate"


def _pinned(user_agent: str | None = None) -> dict[str, str]:
    """Build a browser-like header set the shared session can decode."""
    headers = {"Accept": _FEED_ACCEPT, "Accept-Encoding": _SAFE_ENCODING}
    if user_agent:
        headers["User-Agent"] = user_agent
    return headers


# Hosts whose rotating-UA / JSON-Accept defaults get 403/406/202 or br-encoded.
_HOST_HEADERS: dict[str, dict[str, str]] = {
    # Drugs.com article pages 403 the rotating Gecko user agents.
    "drugs.com": _pinned(_WEBKIT_UA),
    # Cloudflare/Akamai edges gate these feeds on the user agent; Safari passes.
    "espn.com": _pinned(_SAFARI_UA),
    "heavy.com": _pinned(_SAFARI_UA),
    "bleepingcomputer.com": _pinned(_SAFARI_UA),
    "pbs.org": _pinned(_SAFARI_UA),
    # Techmeme's feed rejects the session default Accept: application/json.
    "techmeme.com": _pinned(),
}


class _SiteRule(NamedTuple):
    """Article extraction rule for a single host."""

    container: str
    """XPath for the element holding the article."""

    cut: tuple[str, ...]
    """XPath tests; the first matching child of ``container`` ends the article."""

    hero_skip: tuple[str, ...] = ()
    """Substrings marking a hero image as a site placeholder rather than art."""


_SITE_RULES: dict[str, _SiteRule] = {
    # Drugs.com has no <article> and its <main> holds the sidebar, so //main
    # swallows related teasers, newsletter pitches and vendor copyright.
    "drugs.com": _SiteRule(
        container="//div[contains(@class, 'ddc-main-content')]",
        cut=(
            "self::*[contains(@class, 'ddc-disclaimer')]",
            "self::*[contains(@class, 'more-resources')]",
            "self::h2[normalize-space()='More news resources']",
            "self::h2[normalize-space()='Subscribe to our newsletter']",
        ),
        hero_skip=("ddc-opengraph-logomark",),
    ),
}


def _host(url: str | None) -> str:
    """Return the hostname of ``url`` without a ``www.`` prefix."""
    if not url:
        return ""
    from urllib.parse import urlparse

    hostname = (urlparse(url).hostname or "").lower()
    return hostname[4:] if hostname.startswith("www.") else hostname


class _TagStripper(HTMLParser):
    """Collect text data while discarding tags."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def strip_html(text: str) -> str:
    """Strip HTML tags and collapse whitespace."""
    if not text:
        return ""
    stripper = _TagStripper()
    stripper.feed(text)
    return " ".join("".join(stripper.parts).split())


def html_to_markdown(fragment: str) -> str:
    """Render an HTML fragment as markdown, preserving anchors and images."""
    if not fragment:
        return ""

    from lxml import html as _html

    try:
        root = _html.fragment_fromstring(fragment, create_parent="div")
    except Exception:  # noqa: BLE001
        return strip_html(fragment)

    parts: list[str] = []

    def emit(el) -> None:
        tag = el.tag.lower() if isinstance(el.tag, str) else ""
        if tag == "a":
            href = (el.get("href") or "").strip()
            inner = " ".join(el.text_content().split())
            if inner and href:
                parts.append(f"[{inner}]({href})")
            elif inner:
                parts.append(inner)
            parts.append(" ")
            if el.tail:
                parts.append(el.tail)
            return
        if tag == "img":
            src = (el.get("src") or "").strip()
            alt = (el.get("alt") or "").strip()
            if src:
                parts.append(f"![{alt}]({src})")
            if el.tail:
                parts.append(el.tail)
            return
        if tag == "br":
            parts.append("\n")
        elif tag == "p" and parts and not parts[-1].endswith("\n"):
            parts.append("\n\n")
        if el.text:
            parts.append(el.text)
        for child in el:
            emit(child)
        if tag == "p":
            parts.append("\n\n")
        if el.tail:
            parts.append(el.tail)

    emit(root)
    rendered = "".join(parts)
    lines = [" ".join(line.split()) for line in rendered.split("\n")]
    return "\n".join(lines).strip()


def truncate(text: str, limit: int = 280) -> str:
    """Truncate at the nearest word boundary within ``limit``."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",.;:") + "…"


def struct_time_to_iso(t: "struct_time | None") -> str:
    """Convert a feedparser ``struct_time`` to ISO 8601."""
    if t is None:
        return datetime.now(UTC).isoformat()
    return datetime(*t[:6], tzinfo=UTC).isoformat()


async def fetch_feed(session: "ClientSession", url: str):
    """Fetch and parse an RSS/Atom feed."""
    import aiohttp
    import feedparser

    kwargs: dict = {"timeout": aiohttp.ClientTimeout(total=_FEED_TIMEOUT_SEC)}
    headers = _HOST_HEADERS.get(_host(url))
    if headers:
        kwargs["headers"] = headers

    try:
        response = await session.get(url, **kwargs)
        async with response:
            response.raise_for_status()
            payload = await response.read()
    except (aiohttp.ClientError, TimeoutError):
        return feedparser.parse(b"")
    return feedparser.parse(payload)


def _strip_chrome(doc) -> None:
    """Remove chrome tags in place."""
    selector = " | ".join(f"//{tag}" for tag in _CHROME_TAGS)
    for el in doc.xpath(selector):
        parent = el.getparent()
        if parent is not None:
            parent.remove(el)


def _looks_clean(text: str) -> bool:
    """Reject empty results and unrendered template fragments."""
    return bool(text) and not any(marker in text for marker in _TEMPLATE_MARKERS)


def _jsonld_field(doc, field: str) -> str | None:
    """Pull a top-level string field from any JSON-LD script."""
    import json

    for script in doc.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            data = json.loads(script)
        except (json.JSONDecodeError, TypeError):
            continue
        for entry in data if isinstance(data, list) else [data]:
            if not isinstance(entry, dict):
                continue
            for candidate in (entry, *(entry.get("@graph") or [])):
                if not isinstance(candidate, dict):
                    continue
                value = candidate.get(field)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, list) and value:
                    first = value[0]
                    if isinstance(first, str) and first.strip():
                        return first.strip()
                    if isinstance(first, dict):
                        nested = first.get("url")
                        if isinstance(nested, str) and nested.strip():
                            return nested.strip()
                if isinstance(value, dict):
                    nested = value.get("url")
                    if isinstance(nested, str) and nested.strip():
                        return nested.strip()
    return None


def _article_markdown(node) -> str:
    """Render an article container as markdown with text + inline images."""
    parts: list[str] = []
    text_count = [0]

    def walk(el) -> None:
        tag = el.tag.lower() if isinstance(el.tag, str) else ""
        if tag == "p":
            text = " ".join(el.text_content().split())
            if text and not _TIMESTAMP_RE.match(text):
                parts.append(text)
                text_count[0] += 1
            return
        if tag == "figure":
            srcs = el.xpath(".//img/@src")
            if srcs:
                src = str(srcs[0]).strip()
                cap_nodes = el.xpath(".//figcaption//text()")
                cap = " ".join("".join(cap_nodes).split()) if cap_nodes else ""
                if src:
                    parts.append(f"![{cap}]({src})")
            return
        if tag == "img":
            src = (el.get("src") or "").strip()
            alt = (el.get("alt") or "").strip()
            if src:
                parts.append(f"![{alt}]({src})")
            return
        for child in el:
            walk(child)

    walk(node)
    if text_count[0] < _MIN_PARAGRAPHS:
        return ""
    return "\n\n".join(parts)


def _cut_tail(container, cut: tuple[str, ...]) -> None:
    """Drop the first child matching ``cut`` and every element after it."""
    cutting = False
    for child in list(container):
        if not isinstance(child.tag, str):
            continue
        if not cutting and any(child.xpath(f"boolean({test})") for test in cut):
            cutting = True
        if cutting:
            container.remove(child)


def _site_body(doc, rule: _SiteRule) -> str:
    """Render the article container defined by ``rule`` as markdown."""
    best = ""
    for container in doc.xpath(rule.container):
        _cut_tail(container, rule.cut)
        text = _article_markdown(container)
        if _looks_clean(text) and len(text) > len(best):
            best = text
    return best


def _extract_image_from_doc(doc) -> str | None:
    """Find a hero image URL from meta tags, JSON-LD, or article body."""
    for path in (
        '//meta[@property="og:image"]/@content',
        '//meta[@name="og:image"]/@content',
        '//meta[@name="twitter:image"]/@content',
        '//meta[@property="twitter:image"]/@content',
    ):
        for value in doc.xpath(path):
            url = str(value).strip()
            if url:
                return url
    jsonld = _jsonld_field(doc, "image")
    if jsonld:
        return jsonld
    for path in ("//article//img/@src", "//main//img/@src"):
        for value in doc.xpath(path):
            url = str(value).strip()
            if url:
                return url
    return None


def _extract_body(payload: bytes, url: str | None = None) -> str | None:
    """Return the article body as markdown with inline images."""
    from lxml import html

    try:
        doc = html.fromstring(payload, parser=html.HTMLParser(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None

    rule = _SITE_RULES.get(_host(url))

    hero = _extract_image_from_doc(doc)
    if hero and rule and any(marker in hero for marker in rule.hero_skip):
        hero = None

    body = _jsonld_field(doc, "articleBody")
    if not (body and _looks_clean(body)):
        _strip_chrome(doc)
        best: str = _site_body(doc, rule) if rule else ""
        if not best:
            for article in doc.xpath("//article"):
                text = _article_markdown(article)
                if _looks_clean(text) and len(text) > len(best):
                    best = text
        if not best:
            for main in doc.xpath("//main"):
                text = _article_markdown(main)
                if _looks_clean(text) and len(text) > len(best):
                    best = text
        body = best or None

    if body and hero and "![" not in body:
        body = f"![]({hero})\n\n{body}"

    return body


async def fetch_article_body(session: "ClientSession", url: str) -> str | None:
    """Fetch ``url`` and return its article body."""
    import aiohttp

    kwargs: dict = {"timeout": aiohttp.ClientTimeout(total=_ARTICLE_TIMEOUT_SEC)}
    headers = _HOST_HEADERS.get(_host(url))
    if headers:
        kwargs["headers"] = headers

    try:
        response = await session.get(url, **kwargs)
        async with response:
            response.raise_for_status()
            payload = await response.read()
    except (aiohttp.ClientError, TimeoutError):
        return None
    return _extract_body(payload, url)
