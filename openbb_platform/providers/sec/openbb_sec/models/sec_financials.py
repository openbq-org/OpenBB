"""SEC Financial Statements Utility."""

# flake8: noqa: PLR0911, PLR0912, PLR0914
import contextlib
import io
import re
from functools import lru_cache
from typing import Any, Literal

from openbb_core.provider.abstract.query_params import QueryParams
from pydantic import Field, PrivateAttr, computed_field, field_validator

from openbb_sec.models.sec_filing import Filing, LazyDict
from openbb_sec.utils.definitions import (
    _ASC_SECTIONS,
    _ASC_SUBTOPICS,
    _ASC_TOPICS,
    DEI_FIELDS,
)
from openbb_sec.utils.xbrl_taxonomy_helper import (
    TaxonomyStyle,
    XBRLNode,
    XBRLParser,
    get_label_url_for_import,
)

_EXHIBIT_TITLES = {
    "1": "Underwriting Agreement",
    "2": "Plan of Acquisition, Reorganization, Arrangement, Liquidation or Succession",
    "3": "Articles of Incorporation and Bylaws",
    "4": "Instruments Defining the Rights of Security Holders",
    "5": "Opinion re Legality",
    "8": "Opinion re Tax Matters",
    "9": "Voting Trust Agreement",
    "10": "Material Contracts",
    "11": "Statement re Computation of Per Share Earnings",
    "12": "Statement re Computation of Ratios",
    "13": "Annual Report to Security Holders",
    "14": "Code of Ethics",
    "15": "Letter re Unaudited Interim Financial Information",
    "16": "Letter re Change in Certifying Accountant",
    "18": "Letter re Change in Accounting Principles",
    "21": "Subsidiaries of the Registrant",
    "22": "Published Report re Matters Submitted to a Vote",
    "23": "Consents of Experts and Counsel",
    "24": "Power of Attorney",
    "25": "Statement of Eligibility of Trustee",
    "27": "Financial Data Schedule",
    "31": "Rule 13a-14(a)/15d-14(a) Certifications",
    "32": "Section 1350 Certifications",
    "95": "Mine Safety Disclosures",
    "99": "Additional Exhibits",
    "101": "Interactive Data Files (XBRL)",
    "104": "Cover Page Interactive Data File",
}


def _exhibit_title(exhibit_type: str) -> str:
    """Return the standard Regulation S-K title for an exhibit type (e.g. EX-21)."""
    match = re.search(r"EX-?(\d+)", exhibit_type.upper())
    return _EXHIBIT_TITLES.get(match.group(1), "") if match else ""


def _clean_exhibit_text(text: str) -> str:
    """Tidy exhibit descriptions that filers split into per-character spans.

    Inline styling (e.g. a bold first letter) puts adjacent characters in
    separate spans, so joining their text inserts stray spaces ("202 6",
    "16 ,"). Collapse whitespace, drop spaces before punctuation, and rejoin
    split digit runs; intra-word letter splits are left as-is (unsafe to merge).
    """
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:)])", r"\1", text)
    text = re.sub(r"(?<=\d) (?=\d)", "", text)
    return text


class FinancialStatements(Filing):
    """FinancialStatements class."""

    _statements: dict = PrivateAttr(default_factory=dict)
    _tags: dict = PrivateAttr(default_factory=dict)
    _resources: dict = PrivateAttr(default_factory=dict)
    _xsd: dict = PrivateAttr(default_factory=dict)
    _calcs: dict = PrivateAttr(default_factory=dict)
    _labels: dict = PrivateAttr(default_factory=dict)
    _presentation: list[XBRLNode] = PrivateAttr(default_factory=list)
    _metalinks: dict = PrivateAttr(default_factory=dict)
    _std_ref: dict = PrivateAttr(default_factory=dict)
    _instance: dict = PrivateAttr(default_factory=dict)
    _xbrl_units: dict = PrivateAttr(default_factory=dict)
    _text_blocks: dict = PrivateAttr(default_factory=dict)
    _disclosures: dict = PrivateAttr(default_factory=dict)
    _period_context: dict = PrivateAttr(default_factory=dict)
    _period_end1: str = PrivateAttr(default="")
    _period_end2: str = PrivateAttr(default="")
    _html_filing: Any = PrivateAttr(default=None)
    _toc: dict = PrivateAttr(default_factory=dict)
    # Non-XBRL specific attributes (financial statement related only)
    _non_xbrl_statements: dict = PrivateAttr(default_factory=dict)
    _non_xbrl_text_blocks: dict = PrivateAttr(default_factory=dict)
    _non_xbrl_initialized: bool = PrivateAttr(default=False)
    _items_reflowed: bool = PrivateAttr(default=False)
    _xbrl_loaded: bool = PrivateAttr(default=False)

    @computed_field
    @property
    def toc(self) -> dict:
        """Table of contents mapping section keys (e.g., '1A', '7') to titles."""
        if self._toc:
            return self._toc

        import warnings

        from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

        warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

        content = self.get_main_document_content()
        if not content:
            return {}

        soup = BeautifulSoup(content, "lxml")
        toc_dict: dict = {}

        href_to_texts: dict = {}

        for link in soup.find_all("a", href=True):
            href = link.get("href", "")

            if not href or not str(href).startswith("#"):
                continue

            link_text = link.get_text(strip=True)

            if not link_text:
                continue

            if href not in href_to_texts:
                href_to_texts[href] = []

            href_to_texts[href].append(link_text)

        valid_item_pattern = re.compile(
            r"^ITEM\s*(1[0-5]?|[2-9])(A|B|C)?[.:]?$", re.IGNORECASE
        )

        for href, texts in href_to_texts.items():
            item_num = None
            title = None
            for text in texts:
                item_match = valid_item_pattern.match(text.strip())
                if item_match:
                    num = item_match.group(1)
                    suffix = item_match.group(2) or ""
                    item_num = f"{num}{suffix}".upper()
                elif text and not re.match(r"^\d+$", text):
                    if title is None and len(text) > 5:
                        title = text

            if item_num and title and item_num not in toc_dict:
                toc_dict[item_num] = title

        self._toc = toc_dict
        return self._toc

    @computed_field
    @property
    def calendar_period(self) -> str:
        """Calendar for the period ending."""
        from pandas import to_datetime

        year = self._period_ending[:4]
        period = to_datetime(self._period_ending).quarter
        return f"{year}-Q{period}"

    @computed_field
    @property
    def fiscal_period(self) -> str:
        """Fiscal period focus."""
        year = self._fiscal_year
        period = self._fiscal_period
        return (
            f"{year}-{period}"
            if year and period
            else period
            if period
            else year
            if year
            else ""
        )

    def _get_statements_info(self) -> dict:
        """Get statement info as dict of {key: {name, url/data}}."""
        # XBRL statements
        if self._resources:
            statements: dict = {}
            statement_items = self._resources.copy()
            for v in statement_items.values():
                if v.get("group") == "statement":
                    statements[v["short_name"]] = {
                        "name": v.get("long_name", v["short_name"]),
                        "url": v.get("url"),
                    }
            if statements:
                return statements

        # Non-XBRL statements
        if self._non_xbrl_statements:
            return {
                k: {
                    "name": v.get("name", k),
                    "data": v.get("data"),
                    "meta": v.get("meta"),
                }
                for k, v in self._non_xbrl_statements.items()
            }

        return {}

    @property
    def statements(self) -> LazyDict:
        """Lazy-loading dictionary of financial statements.

        Use .keys() to see available statements without loading data.
        Use .labels() to get a dict of {key: name}.
        Access specific statement with fs.statements['income'].

        For XBRL filings: Returns statement data from XBRL
        For non-XBRL filings: Returns {"name": str, "data": DataFrame, "meta": DataFrame}
        """
        statements_info = self._get_statements_info()
        keys_labels = {k: v.get("name", k) for k, v in statements_info.items()}

        def load_statement(key: str) -> dict:
            """Load statement data."""
            return statements_info[key]

        return LazyDict(keys_labels, load_statement)

    def _get_disclosures_info(self) -> dict:
        """Get disclosure info as dict of {key: disclosure_data}."""
        self._ensure_xbrl()
        # XBRL disclosures: combine resources metadata with text block content
        if self._resources:
            disclosures: dict = {}

            # Collect all disclosure sections from resources
            for rval in self._resources.values():
                if not isinstance(rval, dict) or rval.get("group") != "disclosure":
                    continue
                tag = rval.get("anchor_tag") or rval.get("name")
                if not tag:
                    continue
                disclosures[tag] = {
                    "name": rval.get("long_name", rval.get("short_name", tag)),
                    "short_name": rval.get("short_name"),
                    "url": rval.get("url"),
                    "text": "",
                }

            if disclosures and self._text_blocks:
                # Build local-name lookup for disclosure keys
                # e.g. "us-gaap_InventoryDisclosureTextBlock" → "inventorydisclosuretextblock"
                _dk_by_local: dict[str, str] = {}
                for dk in disclosures:
                    local = dk.split("_", 1)[1] if "_" in dk else dk
                    _dk_by_local[local.lower()] = dk

                # Match each text block to a disclosure via presentation roles
                for tb_key, tb_val in self._text_blocks.items():
                    text = tb_val.get("value", "")
                    if not text or text == "\nNone.":
                        continue

                    # 1) Direct key match
                    if tb_key in disclosures:
                        disclosures[tb_key]["text"] = text
                        continue

                    # 2) Match via presentation roles → disclosure local names
                    matched = False
                    for role in tb_val.get("presentation", []):
                        role_lower = role.lower()
                        # Exact match on role
                        if role_lower in _dk_by_local:
                            dk = _dk_by_local[role_lower]
                            # Append if disclosure already has text from another block
                            existing = disclosures[dk].get("text", "")
                            if existing:
                                disclosures[dk]["text"] = existing + "\n\n" + text
                            else:
                                disclosures[dk]["text"] = text
                            matched = True
                            break
                        # Partial match: role is substring of key or vice-versa
                        for dl, dk in _dk_by_local.items():
                            if role_lower in dl or dl in role_lower:
                                existing = disclosures[dk].get("text", "")
                                if existing:
                                    disclosures[dk]["text"] = existing + "\n\n" + text
                                else:
                                    disclosures[dk]["text"] = text
                                matched = True
                                break
                        if matched:
                            break

                    # 3) If still unmatched, try local name match against disclosure keys
                    if not matched:
                        tb_local = (
                            tb_key.split("_", 1)[1].lower()
                            if "_" in tb_key
                            else tb_key.lower()
                        )
                        for dl, dk in _dk_by_local.items():
                            if tb_local in dl or dl in tb_local:
                                existing = disclosures[dk].get("text", "")
                                if existing:
                                    disclosures[dk]["text"] = existing + "\n\n" + text
                                else:
                                    disclosures[dk]["text"] = text
                                break

            if disclosures:
                return disclosures

        # Non-XBRL fallbacks
        if self._disclosures:
            return self._disclosures

        if self._items:
            return self._items

        return {}

    @property
    def disclosures(self) -> LazyDict:
        """Lazy-loading dictionary of disclosures (Notes to Financial Statements).

        Use .keys() to see available disclosures without loading content.
        Use .labels() to get a dict of {key: long_name}.
        Access specific disclosure with fs.disclosures['InventoryDisclosure'].
        """
        disclosures_info = self._get_disclosures_info()
        keys_labels = {
            k: v.get("name", v.get("long_name", k)) if isinstance(v, dict) else k
            for k, v in disclosures_info.items()
        }

        def load_disclosure(key: str) -> dict:
            """Load disclosure data."""
            return disclosures_info[key]

        return LazyDict(keys_labels, load_disclosure)

    @computed_field
    @property
    def text_blocks(self) -> dict:
        """Dictionary of extracted text blocks, if available.

        For XBRL filings: Returns text blocks from XBRL instance
        For non-XBRL filings: Returns text blocks extracted from HTML sections
        """
        self._ensure_xbrl()
        # XBRL text blocks
        if self._text_blocks:
            text_blocks: dict = {}
            disclosure_keys = list(self.disclosures.keys())

            # Build a lookup from presentation role name -> disclosure key.
            # Disclosure keys are like "us-gaap_InventoryDisclosureTextBlock"
            # and presentation roles are like "InventoryDisclosure".
            _role_to_dk: dict[str, str] = {}
            for dk in disclosure_keys:
                local = dk.split("_", 1)[1] if "_" in dk else dk
                _role_to_dk[local.lower()] = dk

            def find_disclosures_for_text_block(tag_data: dict) -> list[str]:
                """Match a text block's presentation roles to disclosure keys."""
                matched: list[str] = []
                pres = tag_data.get("presentation", [])
                for role in pres:
                    role_lower = role.lower()
                    # Exact match on role
                    if role_lower in _role_to_dk:
                        matched.append(_role_to_dk[role_lower])
                        continue
                    # Try partial: role might be a substring of the key
                    for rl, dk in _role_to_dk.items():
                        if role_lower in rl or rl in role_lower:
                            matched.append(dk)
                            break
                return matched

            for k, v in self._text_blocks.items():
                if v.get("value") and v["value"] != "\nNone.":
                    pres = v.get("presentation", [])
                    name = pres[0] if pres else v.get("name")
                    disclosure_list = find_disclosures_for_text_block(v)
                    text_blocks[k] = {
                        "name": name,
                        "disclosure": disclosure_list,
                        "text": v["value"],
                    }
            return text_blocks

        # Non-XBRL text blocks
        if self._non_xbrl_text_blocks:
            return self._non_xbrl_text_blocks

        return {}

    @computed_field
    @property
    def tags(self) -> dict:
        """Dictionary of tags and their properties, if available."""
        self._ensure_xbrl()
        return self._tags

    @computed_field
    @property
    def is_xbrl(self) -> bool:
        """Whether this filing contains XBRL data.

        Non-XBRL filings (typically pre-2009) contain financial statements
        embedded in HTML tables without structured XBRL tagging.
        """
        has_metalinks = bool(self._metalinks)
        has_resources = bool(self._resources) and len(self._resources) > 1
        has_tags = bool(self._tags)
        has_instance = bool(self._instance)

        return has_metalinks or has_resources or has_tags or has_instance

    @computed_field
    @property
    def main_document_url(self) -> str | None:
        """URL of the main filing document (if available)."""
        return self.get_main_document_url()

    def get_main_document_url(self) -> str | None:
        """Get the URL of the main filing document."""
        if not self._document_urls:
            return None

        for doc in self._document_urls:
            doc_type = doc.get("type", "").upper()
            if doc_type in ("10-K", "10-Q", "10-K/A", "10-Q/A"):
                return doc.get("url")

        for doc in self._document_urls:
            url = doc.get("url", "")
            if url.endswith(".htm") or url.endswith(".html"):
                return url

        return None

    def __init__(self, url: str, use_cache: bool = True):
        """Initialize the FinancialStatements class."""
        super().__init__(url, use_cache)
        self._download_metalinks()
        if not (self._resources and len(self._resources) > 1):
            self._initialize_non_xbrl()

    def _ensure_xbrl(self) -> None:
        """Parse the XBRL taxonomy and instance on first access (expensive).

        Building the schema from the linkbases and reading the instance is the
        costly part of a filing parse (tens of seconds for large filers like
        IBM). The narrative-section accessors (Business, Risk Factors, Legal
        Proceedings, item text) read only the main HTML document, so this work
        is deferred until an XBRL-derived output (statements, disclosures, text
        blocks, tags, segments, instance-enriched cover page) is requested.
        """
        if self._xbrl_loaded:
            return
        self._xbrl_loaded = True
        if self._resources and len(self._resources) > 1:
            self._build_schema_from_xml()
            self._download_xbrl_instance()
            self._enrich_cover_page_from_instance()

    @classmethod
    def from_url(cls, url: str, use_cache: bool = True) -> "FinancialStatements":
        """Return a FinancialStatements for a filing URL, parsed once per process."""
        return _financial_statements_cache(url, use_cache)

    def get_statement(self, statement: str = "income"):
        """As-filed statement (income/balance/cash/equity) as (data, meta) DataFrames."""
        return self._download_statement(statement)

    def get_item_sections(self) -> dict:
        """Filing item sections (Item 1, 1A, 3, ...) keyed by item id, with text."""
        from openbb_sec.utils.filing_sections import (
            extract_item_sections,
            extract_via_cross_reference,
            reflow_plain_text,
        )

        if not self._items:
            content = self.get_main_document_content()
            if not content:
                return {}
            markdown = self._clean_html_to_text(content, keep_tables=True)
            self._items = extract_item_sections(markdown)
            if not self._items:
                self._items = extract_via_cross_reference(markdown)
            if not self._items:
                self._items = extract_item_sections(content)

        if self._items and not self._items_reflowed:
            force = not self.is_xbrl
            for item in self._items.values():
                if isinstance(item, dict) and item.get("text"):
                    item["text"] = reflow_plain_text(item["text"], force=force)
            self._items_reflowed = True
        return self._items

    def get_item(self, *item_nums: str) -> dict | None:
        """First item section matching any of the given item numbers."""
        targets = {n.upper() for n in item_nums}
        items = self.get_item_sections()
        for value in items.values():
            if (
                isinstance(value, dict)
                and (value.get("item_num") or "").upper() in targets
            ):
                return value
        for key, value in items.items():
            if key.rsplit("_", 1)[-1].upper() in targets and isinstance(value, dict):
                return value
        return None

    def _item_by_name(self, needle: str) -> dict | None:
        """First item section whose name contains a keyword."""
        for value in self.get_item_sections().values():
            if isinstance(value, dict) and needle in (value.get("name") or "").lower():
                return value
        return None

    def risk_factors(self) -> list:
        """Risk Factors (Item 1A) split into individual factors by bold sub-heading."""
        from openbb_sec.utils.filing_sections import (
            extract_section_html,
            split_bold_sections,
        )

        doc_type = (self.document_type or "").upper()
        if doc_type.startswith(("20-F", "40-F")):
            item = self._item_by_name("risk factor") or self.get_item("3D", "3")
        else:
            item = self._item_by_name("risk factor") or self.get_item("1A")
        if item:
            content = self.get_main_document_content()
            section_html = (
                extract_section_html(content, item.get("item_num") or "1A")
                if content
                else ""
            )
            blocks = (
                split_bold_sections(section_html, "risk_factor") if section_html else []
            )
            blocks = [b for b in blocks if b.get("risk_factor")]
            if blocks:
                return blocks
            text = (item.get("text") or "").strip()
            if text:
                return [{"risk_factor": item.get("name"), "text": text}]
        return self._legacy_risk_factors()

    def _legacy_risk_factors(self) -> list:
        """Risk factors of pre-2005 filings, which predate Item 1A."""
        mda = self.get_item("7") or self._item_by_name("discussion and analysis")
        text = (mda.get("text") if mda else "") or ""
        matches = list(
            re.finditer(
                r"(?im)^\**Factors\s+That\s+May\s+Affect\s+Future\s+Results[^\n]*$",
                text,
            )
        )
        if not matches:
            return []
        body = text[matches[-1].end() :].strip()
        if not body:
            return []
        return [
            {
                "risk_factor": (
                    "Factors That May Affect Future Results and Financial Condition"
                ),
                "text": body,
            }
        ]

    def business(self) -> str | None:
        """Return the Business section (Item 1) as formatted markdown."""
        from openbb_sec.utils.filing_sections import extract_section_html

        def _strip_exec_officers(text: str) -> str:
            return re.split(
                r"(?im)^\s*#{1,6}\s*EXECUTIVE\s+OFFICERS\s+OF\s+THE\s+REGISTRANT\s*$",
                text,
                maxsplit=1,
            )[0].rstrip()

        def _slice_foreign_business(text: str) -> str:
            start_match = re.search(r"(?im)^\s*B\.\s*Business(?:\s+Overview)?\b", text)
            if not start_match:
                return text
            start = start_match.start()
            end_candidates = []
            for pattern in (
                r"(?im)^\s*C\.\s*Organizational\s+Structure\b",
                r"(?im)^\s*D\.\s*Property\b",
                r"(?im)^\s*ITEM\s*4A\b",
                r"(?im)^\s*4A\.\b",
                r"(?im)^\s*ITEM\s*5\b",
            ):
                match = re.search(pattern, text[start:])
                if match:
                    end_candidates.append(start + match.start())
            end = min(end_candidates) if end_candidates else len(text)
            return text[start:end].strip()

        doc_type = (self.document_type or "").upper()
        if doc_type.startswith("10-K"):
            item = self.get_item("1")
        elif doc_type.startswith(("20-F", "40-F")):
            item = self.get_item("4", "4A", "4B") or self._item_by_name(
                "information on the company"
            )
            if not item:
                item = self._item_by_name("business")
        else:
            item = self._item_by_name("business")
        if not item:
            return None
        content = self.get_main_document_content()
        item_num = item.get("item_num") if isinstance(item, dict) else None
        if content and item_num:
            section_html = extract_section_html(content, str(item_num))
            if section_html:
                section_text = self._clean_html_to_text(section_html, keep_tables=False)
                if section_text:
                    cleaned = _strip_exec_officers(section_text)
                    if doc_type.startswith(("20-F", "40-F")):
                        cleaned = _slice_foreign_business(cleaned)
                    return cleaned or None
        text = (item.get("text") or "").strip()
        cleaned = _strip_exec_officers(text)
        if doc_type.startswith(("20-F", "40-F")):
            cleaned = _slice_foreign_business(cleaned)
        return cleaned or None

    def _parse_exhibit_index(self) -> list:
        """Parse the hyperlinked exhibit index from a filing's main document.

        Modern filings list every exhibit — including those incorporated by
        reference to other filings — as ``-sec-extract:exhibit`` anchors with
        the real title and a link to the document.
        """
        content = self.get_main_document_content()
        if not content or "-sec-extract:exhibit" not in content:
            return []
        from urllib.parse import urljoin

        from bs4 import BeautifulSoup

        base = self.get_main_document_url() or ""
        soup = BeautifulSoup(content, "html.parser")
        exhibits: list = []
        seen: set = set()
        for anchor in soup.find_all("a"):
            if "-sec-extract:exhibit" not in (anchor.get("style") or ""):
                continue
            href = anchor.get("href")
            if not isinstance(href, str) or not href:
                continue
            if href.startswith("#") or href in seen:
                continue
            seen.add(href)
            number = ""
            description = anchor.get_text(" ", strip=True)
            row = anchor.find_parent("tr")
            if row:
                cells = [
                    c.get_text(" ", strip=True) for c in row.find_all(["td", "th"])
                ]
                cells = [c for c in cells if c]
                if cells:
                    number = re.sub(r"[*\s]+$", "", cells[0])
                    row_desc = _clean_exhibit_text(" ".join(cells[1:]))
                    if len(row_desc) > len(description):
                        description = row_desc
            if len(description) < 4:
                continue
            label = f"{number} - {description}" if number else description
            exhibits.append({"value": urljoin(base, href), "label": label})
        return exhibits

    def exhibit_choices(self) -> list:
        """Filing exhibits as ``{value, label}`` options."""
        index = self._parse_exhibit_index()
        if index:
            return index
        options: list = []
        for doc in sorted(
            self._document_urls or [],
            key=lambda d: int(d.get("sequence") or 0),
        ):
            dtype = (doc.get("type") or "").upper()
            if not dtype.startswith("EX") or dtype.startswith(
                ("EX-100", "EX-101", "EX-104")
            ):
                continue
            description = (doc.get("description") or "").strip()
            if not description or re.fullmatch(
                r"(?i)(?:exhibit|ex)[-\s.]*[\d.\-a-z]*", description
            ):
                description = _exhibit_title(dtype)
            label = f"{dtype} - {description}" if description else dtype
            options.append({"value": dtype, "label": label})
        return options

    def get_exhibit(self, identifier: str) -> str | None:
        """Return a filing exhibit's content rendered as markdown."""
        if identifier.startswith("http"):
            url, inline = identifier, None
        else:
            doc = next(
                (
                    d
                    for d in self._document_urls
                    if (d.get("type") or "").upper() == identifier.upper()
                ),
                None,
            )
            if not doc:
                return None
            url, inline = doc.get("url"), doc.get("content")

        content = None
        if url:
            content = self._get_document(url, False, self._use_cache)
            if isinstance(content, bytes):
                content = content.decode("utf-8", errors="ignore")
        if not content:
            content = inline
        if not content:
            return None
        if re.search(r"<TEXT>", content[:600], re.IGNORECASE):
            content = re.split(r"<TEXT>", content, maxsplit=1, flags=re.IGNORECASE)[-1]

        if re.search(r"<html|<body", content[:2000], re.IGNORECASE):
            return self._clean_html_to_text(content, keep_tables=True) or None
        from openbb_sec.utils.filing_sections import reflow_plain_text

        return reflow_plain_text(content, force=True) or content

    def legal_proceedings(self) -> dict | None:
        """Legal Proceedings (Item 3 for 10-K, Part II Item 1 for 10-Q).

        When Item 3 only cross-references a note in the financial statements
        (e.g. "see Note 12 ... Commitments and Contingencies"), the referenced
        note's text is appended so the actual proceedings are returned.
        """
        item = self._item_by_name("legal proceeding") or self.get_item("3")
        if not item:
            return None
        text = (item.get("text") or "").strip()
        if _is_legal_redirect(text):
            note = self._legal_contingencies_note()
            if note:
                item = {**item, "text": f"{text}\n\n{note}"}
        return item

    def _legal_contingencies_note(self) -> str:
        """Text of the legal/contingencies note from the disclosures, if present."""
        wanted = ("contingenc", "legal proceeding", "legal matter", "litigation")
        skip = ("(details)", "(tables)", "(policies)", "additional information")
        disclosures = self.disclosures
        labels = disclosures.labels()
        for key in disclosures:
            name = (labels.get(key) or key).lower()
            if not any(w in name for w in wanted) or any(s in name for s in skip):
                continue
            info = disclosures[key]
            text = (info.get("text") or "").strip() if isinstance(info, dict) else ""
            if text:
                return text
        return ""

    def segment_revenue(self) -> list:
        """Segment, geographic, and revenue-disaggregation disclosures with their tables."""
        wanted = ("segment", "geographic", "disaggregat", "revenue")
        skip = ("(details)", "(tables)", "(policies)", "additional information")
        disclosures = self.disclosures
        labels = disclosures.labels()
        results: list = []
        for key in disclosures:
            name = labels.get(key) or key
            lower = name.lower()
            if not any(word in lower for word in wanted) or any(
                s in lower for s in skip
            ):
                continue
            info = disclosures[key]
            text = (info.get("text") or "").strip() if isinstance(info, dict) else ""
            if text:
                results.append({"name": _clean_disclosure_name(name), "text": text})
        return results

    def _enrich_cover_page_from_instance(self):
        """Supplement cover page with data from XBRL instance facts."""
        if not self._instance:
            return
        from pandas import to_datetime

        for inst_key, inst_data in self._instance.items():
            local = inst_key.split("_", 1)[1] if "_" in inst_key else inst_key

            if local not in DEI_FIELDS:
                continue

            cover_key = DEI_FIELDS[local]

            if self._cover_page.get(cover_key):
                continue

            context_list = inst_data.get("context", [])
            if not context_list:
                continue

            val = None
            val_date = None
            for ctx in context_list:
                if ctx.get("dimensions"):
                    continue
                v = ctx.get("value")
                if v and v not in ("", "0", "false"):
                    end = ctx.get("end", "")
                    if val is None or (end and (val_date is None or end > val_date)):
                        val = v
                        val_date = end

            if not val:
                continue

            self._cover_page[cover_key] = val

            if local == "TradingSymbol" and val not in self._trading_symbols:
                self._trading_symbols.append(val)
            elif local == "EntityCommonStockSharesOutstanding":
                try:
                    shares = int(float(val))
                    date_key = val_date or self._period_ending or "unknown"

                    with contextlib.suppress(Exception):
                        date_key = to_datetime(date_key).strftime("%Y-%m-%d")

                    self._shares_outstanding[date_key] = shares
                except (ValueError, TypeError):
                    pass
            elif local == "DocumentFiscalYearFocus":
                if not getattr(self, "_fiscal_year", ""):
                    self._fiscal_year = val
            elif local == "DocumentFiscalPeriodFocus" and not self._fiscal_period:
                self._fiscal_period = val

    def _initialize_non_xbrl(self):
        """Initialize non-XBRL filing data from HTML tables.

        For filings where financial statements are in exhibits (e.g., EX-13 Annual Report),
        this method will also parse those exhibits.
        """
        from openbb_sec.utils.non_xbrl_parser import (
            extract_items,
            extract_text_blocks,
            extract_toc,
            find_all_statements,
            get_statement_names,
        )

        if self._non_xbrl_initialized:
            return

        try:
            main_doc = self.get_embedded_document("10-K") or self.get_embedded_document(
                "10-Q"
            )
            if not main_doc:
                main_doc = self.get_embedded_document(
                    "10-K/A"
                ) or self.get_embedded_document("10-Q/A")

            if main_doc:
                html_content = main_doc
            else:
                main_url = self.get_main_document_url()
                if main_url:
                    html_content = self._get_document(main_url)
                    if isinstance(html_content, bytes):
                        html_content = html_content.decode("utf-8", errors="ignore")
                else:
                    html_content = self.get_main_document_content()
                if not html_content:
                    return

            # Parse all financial statements from main document
            statements_data = find_all_statements(html_content)
            statement_names = get_statement_names()

            for stmt_type, (data_df, meta_df) in statements_data.items():
                display_name = statement_names.get(stmt_type, stmt_type.title())
                self._non_xbrl_statements[stmt_type] = {
                    "name": display_name,
                    "data": data_df,
                    "meta": meta_df,
                }

            # If no statements found in main document, check exhibits
            if not self._non_xbrl_statements:
                self._parse_exhibit_statements(find_all_statements, statement_names)

            # Extract table of contents
            self._toc = extract_toc(html_content)

            # Extract text blocks (notes to financial statements)
            self._non_xbrl_text_blocks = extract_text_blocks(html_content)
            self._disclosures = self._non_xbrl_text_blocks

            if not self._disclosures:
                self._parse_exhibit_disclosures(extract_text_blocks)

            if not self._items:
                self._items = extract_items(html_content)
                if not self._items:
                    self._parse_exhibit_items(extract_items, extract_text_blocks)

            self._non_xbrl_initialized = True

        except Exception as e:
            import warnings

            warnings.warn(f"Failed to parse non-XBRL filing: {e}")

    def _parse_exhibit_statements(self, find_all_statements, statement_names):
        """Parse financial statements from exhibits (e.g., EX-13 Annual Report)."""
        exhibit_priority = ["EX-13", "EX-13.1", "EX-13.2", "13", "ANNUAL REPORT"]

        for exhibit_key in exhibit_priority:
            exhibit_html = self.get_embedded_document(exhibit_key)
            if exhibit_html:
                try:
                    statements_data = find_all_statements(exhibit_html)
                    for stmt_type, (data_df, meta_df) in statements_data.items():
                        if stmt_type not in self._non_xbrl_statements:
                            display_name = statement_names.get(
                                stmt_type, stmt_type.title()
                            )
                            self._non_xbrl_statements[stmt_type] = {
                                "name": display_name,
                                "data": data_df,
                                "meta": meta_df,
                            }
                    if self._non_xbrl_statements:
                        return
                except Exception:  # noqa: S112
                    continue

        # Fall back to downloading exhibits if not embedded
        exhibits = self.exhibits
        for exhibit_key in exhibit_priority:
            if exhibit_key in exhibits:
                try:
                    exhibit_data = exhibits[exhibit_key]
                    url = exhibit_data.get("url", "")
                    if not url:
                        continue
                    exhibit_html = self._get_document(url)
                    if isinstance(exhibit_html, bytes):
                        exhibit_html = exhibit_html.decode("utf-8", errors="ignore")
                    if exhibit_html:
                        statements_data = find_all_statements(exhibit_html)
                        for stmt_type, (data_df, meta_df) in statements_data.items():
                            if stmt_type not in self._non_xbrl_statements:
                                display_name = statement_names.get(
                                    stmt_type, stmt_type.title()
                                )
                                self._non_xbrl_statements[stmt_type] = {
                                    "name": display_name,
                                    "data": data_df,
                                    "meta": meta_df,
                                }
                        if self._non_xbrl_statements:
                            return
                except Exception:  # noqa: S112
                    continue

        # If still no statements, try all HTML exhibits
        for exhibit_key, exhibit_doc in exhibits.items():
            if exhibit_key in exhibit_priority:
                continue
            url = exhibit_doc.get("url", "")
            if not (url.endswith(".htm") or url.endswith(".html")):
                continue
            try:
                exhibit_html = self._get_document(url)
                if isinstance(exhibit_html, bytes):
                    exhibit_html = exhibit_html.decode("utf-8", errors="ignore")
                if exhibit_html:
                    statements_data = find_all_statements(exhibit_html)
                    for stmt_type, (data_df, meta_df) in statements_data.items():
                        if stmt_type not in self._non_xbrl_statements:
                            display_name = statement_names.get(
                                stmt_type, stmt_type.title()
                            )
                            self._non_xbrl_statements[stmt_type] = {
                                "name": display_name,
                                "data": data_df,
                                "meta": meta_df,
                            }
                    if self._non_xbrl_statements:
                        return
            except Exception:  # noqa: S112
                continue

    def _parse_exhibit_disclosures(self, extract_text_blocks):
        """Parse disclosures (notes to FS) from exhibits if not found in main document."""
        exhibit_priority = ["EX-13", "EX-13.1", "EX-13.2", "13"]

        for exhibit_key in exhibit_priority:
            exhibit_html = self.get_embedded_document(exhibit_key)
            if exhibit_html:
                try:
                    disclosures = extract_text_blocks(exhibit_html)
                    if disclosures:
                        self._disclosures = disclosures
                        self._non_xbrl_text_blocks = disclosures
                        return
                except Exception:  # noqa: S112
                    continue

        exhibits = self.exhibits
        for exhibit_key in exhibit_priority:
            if exhibit_key in exhibits:
                try:
                    exhibit_data = exhibits[exhibit_key]
                    url = exhibit_data.get("url", "")

                    if not url:
                        continue

                    exhibit_html = self._get_document(url)

                    if isinstance(exhibit_html, bytes):
                        exhibit_html = exhibit_html.decode("utf-8", errors="ignore")

                    if exhibit_html:
                        disclosures = extract_text_blocks(exhibit_html)
                        if disclosures:
                            self._disclosures = disclosures
                            self._non_xbrl_text_blocks = disclosures
                            return
                except Exception:  # noqa: S112
                    continue

    def _parse_exhibit_items(self, extract_items, extract_text_blocks):
        """Parse items (Item 1, Item 7, etc.) and text blocks from exhibits.

        This FinancialStatements version also extracts text blocks for disclosures.
        """
        exhibit_priority = ["EX-13", "EX-13.1", "EX-13.2", "13"]

        for exhibit_key in exhibit_priority:
            exhibit_html = self.get_embedded_document(exhibit_key)
            if exhibit_html:
                try:
                    items = extract_items(exhibit_html)
                    if items:
                        self._items = items
                        if not self._disclosures:
                            disclosures = extract_text_blocks(exhibit_html)
                            if disclosures:
                                self._disclosures = disclosures
                                self._non_xbrl_text_blocks = disclosures
                        return
                except Exception:  # noqa: S112
                    continue

        exhibits = self.exhibits
        for exhibit_key in exhibit_priority:
            if exhibit_key in exhibits:
                try:
                    exhibit_data = exhibits[exhibit_key]
                    url = exhibit_data.get("url", "")
                    if not url:
                        continue
                    exhibit_html = self._get_document(url)
                    if isinstance(exhibit_html, bytes):
                        exhibit_html = exhibit_html.decode("utf-8", errors="ignore")
                    if exhibit_html:
                        items = extract_items(exhibit_html)
                        if items:
                            self._items = items
                            if not self._disclosures:
                                disclosures = extract_text_blocks(exhibit_html)
                                if disclosures:
                                    self._disclosures = disclosures
                                    self._non_xbrl_text_blocks = disclosures
                            return
                except Exception:  # noqa: S112
                    continue

    @staticmethod
    def _enrich_std_ref(entry: dict) -> dict:
        """Add human-readable names and a formatted reference to a std_ref entry."""
        topic = entry.get("Topic", "")
        subtopic = entry.get("SubTopic", "")
        section = entry.get("Section", "")
        paragraph = entry.get("Paragraph", "")

        topic_name = _ASC_TOPICS.get(topic, "")
        subtopic_name = _ASC_SUBTOPICS.get(subtopic, subtopic)
        section_name = _ASC_SECTIONS.get(section, section)

        # Build "ASC 718-10-50-2" style reference
        ref_parts = [p for p in (topic, subtopic, section, paragraph) if p]
        ref_code = "-".join(ref_parts) if ref_parts else ""

        enriched = entry.copy()
        if topic_name:
            enriched["topic_name"] = topic_name
        if subtopic_name and subtopic_name != subtopic:
            enriched["subtopic_name"] = subtopic_name
        if section_name and section_name != section:
            enriched["section_name"] = section_name
        if ref_code:
            label = f"ASC {ref_code}"
            if topic_name:
                label += f" ({topic_name})"
            enriched["reference"] = label

        return enriched

    def _download_metalinks(self):
        """Download the MetaLinks.json file from the SEC website."""
        metalinks_url = ""
        for d in self._document_urls:
            if d.get("url", "").endswith("MetaLinks.json"):
                metalinks_url = d["url"]
                break
        if not metalinks_url:
            return

        if not self._metalinks:
            full_res = self._get_document(metalinks_url)
            self._metalinks = full_res.get("instance", {}).copy()
            self._std_ref = full_res.get("std_ref", {})
            res = self._metalinks.copy()
        else:
            res = self._metalinks.copy()

        statement_items: dict = self._resources if self._resources else {}
        tags: dict = self._tags if self._tags else {}

        try:
            keys = list(res)
            for key in keys:
                for item in list(res[key]["report"]):
                    if not item:
                        continue
                    if res[key]["report"].get(item):
                        anchor = res[key]["report"][item].get("uniqueAnchor") or res[
                            key
                        ]["report"][item].get("firstAnchor")
                        subgroup = res[key]["report"][item].get("subGroupType")
                        menucat = res[key]["report"][item].get("menuCat")
                        _item = res[key]["report"][item]
                        statement_items[
                            item.replace("R", "r") if item[0] == "R" else item
                        ] = {
                            "short_name": _item.get("shortName"),
                            "long_name": _item.get("longName"),
                            "group": _item.get("groupType"),
                            "sub_group": (
                                subgroup if subgroup and subgroup != "''" else None
                            ),
                            "menu_category": (
                                menucat if menucat and menucat != "''" else None
                            ),
                            "anchor_tag": (
                                anchor.get("name", "").replace(":", "_")
                                if anchor
                                else None
                            ),
                            "order": _item.get("order"),
                            "unit_ref": anchor.get("unitRef") if anchor else None,
                            "xsi_nil": (
                                anchor.get("xsiNil") == "true"
                                if anchor and anchor.get("xsiNil")
                                else None
                            ),
                            "decimals": anchor.get("decimals") if anchor else None,
                            "ancestors": (
                                anchor.get("ancestors", []) if anchor else None
                            ),
                            "context_ref": anchor.get("contextRef") if anchor else None,
                            "id": anchor.get("id") if anchor else None,
                            "base_ref": anchor.get("baseRef") if anchor else None,
                            "url": (
                                f"{self._url}{item}.htm" if item[0] == "R" else None
                            ),
                        }

                for item in list(res[key]["tag"]):
                    if res[key]["tag"].get(item):
                        _item = res[key]["tag"][item]
                        role = _item.get("lang", {}).get("en-US", {}).get(
                            "role", {}
                        ) or _item.get("lang", {}).get("en-us", {}).get("role", {})
                        calculation = res[key]["tag"][item].get("calculation", {})
                        calcs = {}
                        for k in calculation:
                            calcs["calculation"] = k.split("role/")[-1]
                            calcs.update(calculation[k])
                        presentation = [
                            d.split("role/")[-1]
                            for d in res[key]["tag"][item].get("presentation", [])
                        ]
                        tags[item] = {
                            "xbrl_type": res[key]["tag"][item].get("xbrltype"),
                            "name": res[key]["tag"][item].get("localname"),
                            "presentation": presentation,
                            "crdr": res[key]["tag"][item].get("crdr"),
                            **calcs,
                            **role,
                            "auth_ref": [
                                self._enrich_std_ref(self._std_ref[ref_id])
                                for ref_id in (
                                    res[key]["tag"][item].get("auth_ref") or []
                                )
                                if ref_id in self._std_ref
                            ]
                            or res[key]["tag"][item].get("auth_ref"),
                        }

            for k, v in statement_items.copy().items():
                if not v:
                    continue

                if (
                    v.get("short_name")
                    in (
                        "Cover Page",
                        "Document And Entity Information",
                    )
                    or v.get("menu_category") == "Cover"
                ):
                    self._cover_page_url = v.get("url", "") or self._cover_page_url

                tag = v.get("anchor_tag", "")

                if tag and tag in tags:
                    statement_items[k].update(
                        {k: v for k, v in tags[tag].items() if k != "tag"}
                    )

            self._resources.update(statement_items)
            self._tags.update(tags)

        except Exception as e:
            raise RuntimeError(f"Failed to parse MetaLinks.json: {e}") from e

    def _fetch_external_taxonomy_labels(self, imports: list):
        """Fetch labels from imported external taxonomies (us-gaap, srt, dei, etc.).

        Updates self._labels with documentation and labels from standard taxonomies.
        """
        from openbb_sec.utils.cache import _cache_get, _cache_set  # noqa: PLC0415

        for imp in imports:
            schema_location = imp.get("schemaLocation", "")
            label_url = get_label_url_for_import(schema_location)

            if not label_url:
                continue

            cache_key = f"xbrl-labels:{label_url}"
            external_labels = _cache_get(cache_key) if self._use_cache else None

            if external_labels is None:
                try:
                    content = self._get_document(label_url)
                    parser = XBRLParser()

                    style = (
                        TaxonomyStyle.FASB_STANDARD
                        if "fasb.org" in label_url
                        else TaxonomyStyle.SEC_EMBEDDED
                    )

                    external_labels = parser.parse_label_linkbase(
                        io.BytesIO(self._ensure_bytes(content)), style
                    )
                except Exception:  # noqa: S112
                    continue

                if self._use_cache and external_labels:
                    _cache_set(cache_key, external_labels, None)

            for element_id, label_roles in external_labels.items():
                if element_id not in self._labels:
                    self._labels[element_id] = {}
                for role, value in label_roles.items():
                    if role not in self._labels[element_id]:
                        self._labels[element_id][role] = value

    def _build_schema_from_xml(self):
        """Build the schema from the linkbase, definitions, labels, and calculations files."""

        tags: dict = self._tags if self._tags else {}
        items: list = []

        xsd_url = [
            d.get("url")
            for d in self._document_urls
            if d.get("url", "").endswith(".xsd") or d.get("type", "") == "EX-101.SCH"
        ]

        if xsd_url:
            if not self._xsd:
                xsd_content = self._get_document(xsd_url[0])
                parser = XBRLParser()
                elements, roles, embedded_linkbase, imports = parser.parse_schema(
                    io.BytesIO(self._ensure_bytes(xsd_content))
                )

                self._xsd = {"elements": elements, "roles": roles, "imports": imports}

                for elem_id, elem_data in elements.items():
                    if elem_id not in tags:
                        tags[elem_id] = elem_data
                    else:
                        tags[elem_id].update(elem_data)

                doc_nums: set = set()
                for role in roles:
                    doc_num = role.get("document_number", "")
                    if doc_num and doc_num not in doc_nums:
                        doc_nums.add(doc_num)
                        items.append(role)

                if embedded_linkbase is not None:
                    try:
                        import xml.etree.ElementTree as ET

                        embedded_bytes = ET.tostring(
                            embedded_linkbase, encoding="unicode"
                        ).encode("utf-8")
                        embedded_parser = XBRLParser()
                        embedded_labels = embedded_parser.parse_label_linkbase(
                            io.BytesIO(embedded_bytes), TaxonomyStyle.SEC_EMBEDDED
                        )
                        for element_id, label_roles in embedded_labels.items():
                            if element_id not in self._labels:
                                self._labels[element_id] = {}
                            self._labels[element_id].update(label_roles)
                    except Exception:  # noqa: S110
                        pass

                self._fetch_external_taxonomy_labels(imports)

            else:
                elements = self._xsd.get("elements", {})
                roles = self._xsd.get("roles", [])
                for elem_id, elem_data in elements.items():
                    if elem_id not in tags:
                        tags[elem_id] = elem_data
                    else:
                        tags[elem_id].update(elem_data)
                doc_nums = set()
                for role in roles:
                    doc_num = role.get("document_number", "")
                    if doc_num and doc_num not in doc_nums:
                        doc_nums.add(doc_num)
                        items.append(role)

            items = sorted(items, key=lambda x: x.get("document_number", ""))

            statement_items: dict = self._resources if self._resources else {}

            for r_num, item in enumerate(items, start=1):
                item["url"] = self._url + f"R{r_num}.htm"
                if not statement_items.get(f"r{r_num}"):
                    statement_items[f"r{r_num}"] = item

            self._resources.update(statement_items)

        linkbase_url = [
            d.get("url")
            for d in self._document_urls
            if d.get("description", "").endswith("LABEL LINKBASE DOCUMENT")
            or d.get("url", "").endswith("_lab.xml")
            or d.get("type", "") == "EX-101.LAB"
        ]

        if linkbase_url:
            content = self._get_document(linkbase_url[0])
            parser = XBRLParser()
            try:
                linkbase_labels = parser.parse_label_linkbase(
                    io.BytesIO(self._ensure_bytes(content)), TaxonomyStyle.FASB_STANDARD
                )
                for element_id, roles in linkbase_labels.items():
                    if element_id not in self._labels:
                        self._labels[element_id] = {}
                    for role, value in roles.items():
                        if role not in self._labels[element_id]:
                            self._labels[element_id][role] = value
            except Exception:  # noqa: S110
                pass

        for element_id, roles in self._labels.items():
            if element_id in tags:
                tags[element_id].update(roles)

        # Handle Presentation via XBRLParser
        presentation_url = [
            d.get("url")
            for d in self._document_urls
            if d.get("description", "").endswith("PRESENTATION LINKBASE DOCUMENT")
            or d.get("url", "").endswith("_pre.xml")
            or d.get("type", "") == "EX-101.PRE"
        ]

        if presentation_url:
            try:
                content = self._get_document(presentation_url[0])
                parser = XBRLParser()
                roots = parser.parse_presentation(
                    io.BytesIO(self._ensure_bytes(content)), TaxonomyStyle.FASB_STANDARD
                )

                def flatten_tree(nodes, parent_id=None):
                    for node in nodes:
                        tag = node.element_id
                        if tag not in tags:
                            tags[tag] = {}

                        tags[tag]["order"] = str(node.order)
                        if parent_id:
                            tags[tag]["parent_tag"] = parent_id

                        if node.preferred_label:
                            tags[tag]["preferred_label"] = node.preferred_label.split(
                                "/"
                            )[-1]

                        flatten_tree(node.children, tag)

                flatten_tree(roots)
                self._presentation = roots

            except Exception:  # noqa: S110
                pass

        # Calculations - using XBRLParser
        calcs_url = [
            d.get("url")
            for d in self._document_urls
            if d.get("description", "").endswith("CALCULATION LINKBASE DOCUMENT")
            or d.get("url", "").endswith("_cal.xml")
            or d.get("type", "") == "EX-101.CAL"
        ]

        if calcs_url:
            try:
                content = self._get_document(calcs_url[0])
                parser = XBRLParser()
                calc_data = parser.parse_calculation(
                    io.BytesIO(self._ensure_bytes(content)), TaxonomyStyle.FASB_STANDARD
                )

                for element_id, calc_info in calc_data.items():
                    if element_id in tags:
                        tags[element_id]["order"] = calc_info.get("order")
                        tags[element_id]["weight"] = calc_info.get("weight")
                        tags[element_id]["parent_tag"] = calc_info.get(
                            "parent_tag"
                        ) or tags[element_id].get("parent_tag")
                    else:
                        tags[element_id] = calc_info

                self._calcs = calc_data

            except Exception:  # noqa: S110
                pass

        self._tags.update(tags)

    def _download_xbrl_instance(self):
        """Download the XBRL instance document."""
        instance_url = [
            d.get("url")
            for d in self._document_urls
            if d.get("description", "").endswith("INSTANCE DOCUMENT")
            or d.get("type", "") == "EX-101.INS"
            or d.get("url", "").endswith("_htm.xml")
        ]

        if instance_url:
            instance_content = self._get_document(instance_url[0])
            parser = XBRLParser()
            contexts, units, facts = parser.parse_instance(
                io.BytesIO(self._ensure_bytes(instance_content)),
                base_url=self._url,
            )

            if not contexts and not facts:
                return

            self._period_context = contexts
            self._xbrl_units = units

            new_instance_dict: dict = {}
            for tag, fact_list in facts.items():
                new_instance_dict[tag] = {"context": fact_list}

            self._instance.update(new_instance_dict)

            # Supplement self._tags with label/documentation from enriched
            # facts where tags are missing that metadata.
            for tag, fact_list in facts.items():
                if not fact_list:
                    continue
                first = fact_list[0]
                if tag not in self._tags:
                    self._tags[tag] = {}
                tag_data = self._tags[tag]
                if (
                    not tag_data.get("label")
                    and first.get("label")
                    and first["label"] != tag
                ):
                    tag_data["label"] = first["label"]
                if not tag_data.get("documentation") and first.get("documentation"):
                    tag_data["documentation"] = first["documentation"]

            def find_tag_data(tag_key: str) -> dict:
                """Find tag metadata, trying multiple key formats."""
                if tag_key in self._tags:
                    tag_data = self._tags.get(tag_key, {})
                    if isinstance(tag_data, dict):
                        return tag_data.copy()

                # Every fact tag with context is added to self._tags by the
                # supplement loop above, so the direct lookup always succeeds and
                # this local-name fallback is never reached.
                if "_" in tag_key:  # pragma: no cover
                    local_name = tag_key.split("_", 1)[1]
                    for tk, tv in self._tags.items():
                        if (
                            "_" in tk
                            and tk.split("_", 1)[1] == local_name
                            and isinstance(tv, dict)
                        ):
                            return tv.copy()

                return {}  # pragma: no cover

            for k, v in new_instance_dict.items():
                if "TextBlock" in k and v.get("context"):
                    tag = find_tag_data(k)
                    context_list = v.get("context", [])
                    if context_list and context_list[0].get("value"):
                        text_block = self._clean_html_to_text(
                            context_list[0]["value"], keep_tables=True
                        )
                        tag.update({"value": text_block})
                        self._text_blocks[k] = {
                            tk: tv
                            for tk, tv in tag.items()
                            if tk
                            not in ("xsi_nil", "balance_type", "order", "xbrl_type")
                        }

    def _parse_non_xbrl_statement(self, statement: str):
        """Parse financial statements from non-XBRL (pre-2009) SEC filings.

        Delegates to the dedicated non_xbrl_parser module.

        Parameters
        ----------
        statement : str
            The type of statement to extract: 'balance', 'income', 'cash', 'equity'

        Returns
        -------
        tuple
            (DataFrame, DataFrame) - statement data and metadata
        """
        from openbb_sec.utils.non_xbrl_parser import parse_non_xbrl_statement

        content = self.get_main_document_content()
        if not content:
            raise ValueError("No main document content found for this filing")

        statement_df, meta_df = parse_non_xbrl_statement(content, statement)

        if statement_df.empty:
            raise ValueError(
                f"Could not find {statement} statement in the filing."
                " This may be a non-standard HTML format."
            )

        return statement_df, meta_df

    def _download_statement(self, statement: str):
        """Download the balance sheet belonging to the loaded statement."""
        from datetime import timedelta

        from numpy import nan
        from pandas import NA, DataFrame, DateOffset, concat, offsets, to_datetime

        self._ensure_xbrl()
        # For non-XBRL filings, use the HTML parsing method
        if not self.is_xbrl:
            return self._parse_non_xbrl_statement(statement)

        statement_map = {
            "balance": "balance sheet",
            "cash": "cash flows",
            "income": "income",
            "operations": "operations",
            "equity": "equity",
            "financial_conditions": "financial condition",
        }

        statements_info = self._get_statements_info()

        if statement == "income":
            matched = {
                k: v
                for k, v in statements_info.items()
                if ("operations" in k.lower() or "income" in k.lower())
                and "parenthetical" not in k.lower()
            }
        elif statement == "balance":
            matched = {
                k: v
                for k, v in statements_info.items()
                if ("balance" in k.lower() or "condition" in k.lower())
                and "parenthetical" not in k.lower()
            }
        else:
            search_term = statement_map.get(statement)
            matched = {
                k: v
                for k, v in statements_info.items()
                if search_term
                and search_term in k.lower()
                and "parenthetical" not in k.lower()
            }

        if not matched:
            raise ValueError(
                f"No items found in the filing, cannot proceed with document type:"
                f" {self.document_type} and statement: {statement}"
                f" -> {self.document_type} -> {self.statements}"
            )

        urls = [v.get("url") for v in matched.values() if v.get("url")]

        if not urls:
            raise ValueError(
                f"No URLs found for statement: {statement}"
                f" -> matched: {list(matched.keys())}"
            )

        output_statement = DataFrame()
        output_meta = DataFrame()
        col1_name = ""
        try:
            for url in urls:
                table, item_map = self._download_statement_from_url(
                    url, is_equity=statement == "equity"
                )

                if not table.empty:
                    col1_name = col1_name if col1_name else table.columns[0]
                    table.columns = [col1_name] + table.columns[1:].tolist()
                    output_statement = (
                        concat([output_statement, table], axis=0)
                        if not output_statement.empty
                        else table
                    )

                if not item_map.empty:
                    item_map = item_map.dropna(how="all", axis=1)
                    output_meta = (
                        item_map
                        if output_meta.empty
                        else concat([output_meta, item_map], axis=0)
                    )
        except Exception as e:
            raise RuntimeError(f"Failed to download statement: {e} -> {e.args}") from e

        output_statement = output_statement.reset_index(drop=True)
        statement_cols = output_statement.columns.tolist()

        if statement != "equity":
            output_statement.columns = ["label"] + statement_cols[1:]

            if not output_meta.empty:
                output_meta = output_meta.reset_index(drop=True)
                output_meta = output_meta.rename(
                    columns={
                        "Name": "tag",
                        "Namespace Prefix": "taxonomy",
                        "Data Type": "data_type",
                        "Balance Type": "balance_type",
                        "Period Type": "period_type",
                    }
                )
                output_meta["data_type"] = output_meta.data_type.astype(str).apply(
                    lambda x: x.split(":")[-1] if x and isinstance(x, str) else x
                )

        try_order = [
            "totalLabel",
            "negatedPeriodStartLabel",
            "negatedPeriodEndLabel",
            "periodStartLabel",
            "periodEndLabel",
            "negatedTerseLabel",
            "terseLabel",
            "negatedLabel",
            "label",
            "verboseLabel",
        ]
        instance_dict = self._instance.copy()
        tags = self.tags.copy()

        def normalize_instance_key(instance_key: str) -> str:
            """Normalize an instance key to match the canonical tag format."""
            if instance_key in tags:
                return instance_key
            if "_" in instance_key:
                local_name = instance_key.split("_", 1)[1]
                for tag_key in tags:
                    if "_" in tag_key and tag_key.split("_", 1)[1] == local_name:
                        return tag_key
            return instance_key

        value_to_tags: dict = {}
        for tag_key, data in instance_dict.items():
            normalized_key = normalize_instance_key(tag_key)
            contexts = data.get("context", [])
            for ctx in contexts:
                ctx_value = ctx.get("value", "")
                if ctx_value and ctx_value.replace("-", "").replace(".", "").isdigit():
                    try:
                        abs_val = abs(float(ctx_value))
                        if abs_val not in value_to_tags:
                            value_to_tags[abs_val] = []
                        if normalized_key not in value_to_tags[abs_val]:
                            value_to_tags[abs_val].append(normalized_key)
                    except ValueError:
                        continue

        def _normalize_label(label: str) -> str:
            """Normalize 'Total/Net X' ↔ 'X, Total/Net' for matching."""
            s = label.strip().lower()
            for prefix in ("total ", "net "):
                if s.startswith(prefix):
                    return s[len(prefix) :].strip().rstrip(",")
            for suffix in (", total", ",total", ", net", ",net"):
                if s.endswith(suffix):
                    return s[: -len(suffix)].strip()
            return s

        def apply_label(x):
            """Apply a label to the column by matching against tag labels."""
            x_text = "" if x is None else str(x).strip()
            if not x_text or x_text.lower() == "nan":
                return None
            x_lower = x_text.lower()
            # Exact match
            for key, value in tags.items():
                for match in try_order:
                    tag_label = value.get(match, "")
                    if tag_label and tag_label.lower() == x_lower:
                        return key
            # Normalized match: 'Total assets' ↔ 'Assets, Total'
            x_base = _normalize_label(x_lower)
            if x_base != x_lower:
                for key, value in tags.items():
                    for match in try_order:
                        tag_label = value.get(match, "")
                        if tag_label:
                            tag_base = _normalize_label(tag_label.lower())
                            if tag_base == x_base:
                                return key
            return None

        def apply_parent_tag(x):
            """Apply a parent tag to the column."""
            if parent_tag := tags.get(x, {}).get("parentTag") or tags.get(x, {}).get(
                "parent_tag"
            ):
                return parent_tag

            if not output_meta.empty and hasattr(output_meta, "parent_tag"):
                new_value = output_meta[output_meta.tag == x].parent_tag
                if not new_value.empty:
                    return new_value.values[0]

            return None

        def check_unit(x):
            """Check the unit string and normalize to a clean format.

            Handles both legacy unitRef ID formats (e.g. 'unit_Standard_iso4217_USD')
            and resolved unit strings from parse_instance (e.g. 'iso4217:USD',
            'shares', 'iso4217:USD / shares').
            """
            if not x or x in ("na", "n"):
                return None
            # Legacy unitRef ID format: 'unit_Standard_iso4217_USD', 'U_iso4217USD'
            if x.lower().startswith(("unit", "u_")):
                parts = x.split("_")
                if parts and len(parts) > 2:
                    if parts[1].lower() == "standard":
                        return parts[2]
                    if parts[1].lower() == "divide":
                        return parts[2] + "per" + parts[3].title()
                if (
                    parts
                    and len(parts) == 2
                    and (len(parts[1]) == 3 or parts[1] in ["shares", "pure"])
                ):
                    return parts[1]
            # Resolved compound unit: 'iso4217:USD / shares'
            if " / " in x:
                num, den = x.split(" / ", 1)
                num_clean = num.split(":")[-1] if ":" in num else num
                den_clean = den.split(":")[-1] if ":" in den else den
                return f"{num_clean}Per{den_clean.title()}"
            # Resolved simple unit with namespace: 'iso4217:USD'
            if ":" in x:
                return x.split(":")[-1]
            return x

        def apply_unit(x):
            """Apply a unit to the column."""
            if not x or x in ("na", "n"):
                return None
            if not output_meta.empty and hasattr(output_meta, "unit"):
                new_value = output_meta[output_meta.tag == x].unit
                if not new_value.empty:
                    return check_unit(new_value.values[0])

            instance = instance_dict.get(x, {}).get("context", [])
            if not instance or len(instance) < 1:
                return None
            unit = instance[0].get("unit")
            if unit:
                return check_unit(unit)
            return None

        def apply_decimals(x):
            """Apply a decimals to the column."""
            if not output_meta.empty and hasattr(output_meta, "decimals"):
                new_value = output_meta[output_meta.tag == x].decimals
                if not new_value.empty:
                    return new_value.values[0]

            instance = instance_dict.get(x, {}).get("context", [])
            if not instance or len(instance) < 1:
                return None
            decimals = instance[0].get("decimals")
            if decimals:
                return decimals
            return None

        def apply_balance(x):
            """Apply a balance type to the column."""
            if balance := tags.get(x, {}).get("crdr"):
                return balance
            if not output_meta.empty and hasattr(output_meta, "balance_type"):
                new_value = output_meta[output_meta.tag == x].balance_type
                if not new_value.empty and new_value.values[0] not in ("n", "na"):
                    return new_value.values[0]
            return None

        def apply_weight(x):
            """Apply a weight to the column."""
            if weight := tags.get(x, {}).get("weight"):
                return weight
            if not output_meta.empty and hasattr(output_meta, "weight"):
                new_value = output_meta[output_meta.tag == x].weight
                if not new_value.empty:
                    return new_value.values[0]
            return None

        def check_values(tag) -> list:
            """Check the value of the tag."""
            value = instance_dict.get(tag, {}).get("context", [])
            if not value or len(value) < 1:
                return []
            result = []
            for v in value:
                raw = v.get("value", "")
                if (
                    raw
                    and str(raw)
                    .replace("-", "")
                    .replace(".", "")
                    .replace(",", "")
                    .isdigit()
                ):
                    try:
                        result.append(abs(float(raw)))
                    except (
                        ValueError,
                        TypeError,
                    ):  # pragma: no cover - the isdigit guard above already ensures float() succeeds
                        continue
            return result

        def apply_fix_tag(row):
            """Verify and fix initial tags applied from the label."""
            nonlocal statement

            old_tag = row.tag
            label = row.label
            row_value = (
                row.value
                if hasattr(row, "value")
                else row.Total
                if hasattr(row, "Total")
                else None
            )
            if not row_value or row_value == "--":
                return row

            row_value = abs(float(row_value))
            potential_values = check_values(old_tag)

            if row_value in potential_values:
                return row

            matching_keys = value_to_tags.get(row_value, [])

            if not matching_keys:
                return row

            if len(matching_keys) == 1:
                row.tag = matching_keys[0]
                return row

            if (
                statement == "equity" and matching_keys
            ):  # pragma: no cover - equity statements return before apply_fix_tag is ever applied
                row.tag = matching_keys[0]
                return row

            for key in matching_keys:
                if key in tags:
                    for match in try_order:
                        if tags[key].get(match, "").lower() == label.lower():
                            row.tag = key
                            return row

            def _clean_words(text: str) -> set:
                return set(
                    w
                    for w in re.sub(r"[,;:()'\"|]", " ", text.lower()).split()
                    if len(w) > 3
                )

            label_words = _clean_words(label)

            for key in matching_keys:
                if key in tags:
                    for match in try_order:
                        tag_label = tags[key].get(match, "")
                        if tag_label:
                            tag_words = _clean_words(tag_label)
                            if (
                                label_words
                                and tag_words
                                and len(label_words & tag_words) >= 2
                            ):
                                row.tag = key
                                return row

            for key in matching_keys:
                if key in tags:
                    local_name = key.split("_", 1)[1] if "_" in key else key
                    tag_name_words = set(
                        w.lower()
                        for w in re.findall(r"[A-Z][a-z]+", local_name)
                        if len(w) > 3
                    )
                    overlap = len(label_words & tag_name_words)
                    if (
                        label_words
                        and tag_name_words
                        and (
                            overlap >= 2 or (overlap >= 1 and len(tag_name_words) == 1)
                        )
                    ):
                        row.tag = key
                        return row

            tags_matching = [k for k in matching_keys if k in tags]
            if len(tags_matching) == 1:
                row.tag = tags_matching[0]
                return row

            return row

        def get_instance_context(tag_key: str) -> list:
            """Get context list from instance_dict, trying multiple key formats."""
            if not isinstance(tag_key, str):
                return []
            if tag_key in instance_dict:
                return instance_dict[tag_key].get("context", [])
            if "_" in tag_key:
                local_name = tag_key.split("_", 1)[1]
                for inst_key, inst_data in instance_dict.items():
                    if "_" in inst_key and inst_key.split("_", 1)[1] == local_name:
                        return inst_data.get("context", [])
            return []

        def apply_context_ref(row):
            """Apply a context reference to the column."""
            tag = row.tag
            value = row.value
            context = get_instance_context(tag)
            period_type = None

            if (
                output_meta is not None
                and not output_meta.empty
                and hasattr(output_meta, "period_type")
            ):
                period_type = output_meta[output_meta.tag == tag].period_type

            period_type = (
                period_type.values[0]
                if period_type is not None and not period_type.empty
                else None
            )

            if not context or len(context) < 1:
                return None

            expected_end = None
            expected_months = None
            period_label = str(getattr(row, "period_ending", "") or "")
            if period_label:
                expected_end = period_label.split(" -- ", 1)[0].strip()
                if " -- " in period_label:
                    suffix = period_label.split(" -- ", 1)[1].strip().lower()
                    month_match = re.search(r"(\d+)\s*months?", suffix)
                    if month_match:
                        expected_months = int(month_match.group(1))
                    else:
                        month_words = {
                            "one": 1,
                            "two": 2,
                            "three": 3,
                            "four": 4,
                            "five": 5,
                            "six": 6,
                            "seven": 7,
                            "eight": 8,
                            "nine": 9,
                            "ten": 10,
                            "eleven": 11,
                            "twelve": 12,
                        }
                        for word, months in month_words.items():
                            if re.search(rf"\b{word}\s+months?\b", suffix):
                                expected_months = months
                                break

            if value and value != "--":
                for c in context:
                    if not c:
                        continue
                    con = c.get("context_ref", "")
                    if not con:
                        continue
                    con_end = c.get("end")
                    if expected_end and con_end:
                        parsed_end = None
                        with contextlib.suppress(Exception):
                            parsed_end = to_datetime(con_end).strftime("%Y-%m-%d")
                        if parsed_end != expected_end:
                            continue
                    if expected_months and c.get("start") and c.get("end"):
                        parsed_months = None
                        with contextlib.suppress(Exception):
                            start = to_datetime(c.get("start"))
                            end = to_datetime(c.get("end"))
                            parsed_months = (
                                (end.year - start.year) * 12
                                + end.month
                                - start.month
                                + 1
                            )
                        if parsed_months != expected_months:
                            continue
                    elif expected_months and c.get("end") and not c.get("start"):
                        continue
                    val = c.get("value")
                    if not val or val == "--":
                        continue
                    try:
                        if (
                            val
                            and "--" not in str(val)
                            and abs(float(val)) == abs(float(value))
                        ):
                            return con
                    except (ValueError, TypeError):
                        continue

            return None

        if statement == "equity":
            output_statement.columns = ["label"] + output_statement.columns[1:].tolist()
            output_statement["tag"] = output_statement.apply(
                lambda row: apply_label(row["label"]),
                axis=1,
            )
            return output_statement.replace({nan: None}), output_meta.replace(
                {nan: None}
            )

        output_statement = output_statement.reset_index(drop=False)
        output_statement = output_statement.rename(columns={"index": "order"})
        output_statement["order"] = output_statement.order.apply(lambda x: x + 1)
        output_statement["tag"] = output_statement.apply(
            lambda row: apply_label(row["label"]),
            axis=1,
        )

        flattened_output = output_statement.melt(
            id_vars=["order", "tag", "label"],
            var_name="period_ending",
            value_name="value",
        )

        flattened_output = flattened_output.apply(apply_fix_tag, axis=1)
        flattened_output.loc[:, "context_ref"] = flattened_output.apply(
            apply_context_ref, axis=1
        )

        def apply_dimension_label(row):
            """Apply the correct label based on dimension members in context_ref."""
            context_ref = row.context_ref if hasattr(row, "context_ref") else None
            if not context_ref or not isinstance(context_ref, str):
                return row.label

            generic_labels = {
                "net sales and revenues",
                "revenues",
                "net sales and revenue",
                "revenue",
                "sales and revenues",
                "sales",
            }

            if row.label.lower() not in generic_labels:
                return row.label

            member_pattern = r"([a-z\-]+)_([A-Za-z]+Member)"
            matches = re.findall(member_pattern, context_ref)

            if not matches:
                return row.label

            for prefix, member_name in matches:
                member_key = f"{prefix}_{member_name}"
                member_info = tags.get(member_key, {})
                terse_label = member_info.get("terseLabel")
                if terse_label and terse_label.lower() != row.label.lower():
                    return terse_label

            return row.label

        flattened_output["label"] = flattened_output.apply(
            apply_dimension_label, axis=1
        )

        output_statement = flattened_output.copy().sort_values(
            by=["order", "period_ending"],
            ascending=[True, False],
        )

        output_statement["parent_tag"] = output_statement.tag.apply(apply_parent_tag)
        output_statement["unit"] = output_statement.tag.apply(apply_unit)
        output_statement["decimals"] = output_statement.tag.apply(apply_decimals)
        output_statement["balance"] = output_statement.tag.apply(apply_balance)
        output_statement["weight"] = output_statement.tag.apply(apply_weight)

        def apply_preferred_label(x):
            """Apply a preferred label to the column."""
            if preferred := tags.get(x, {}).get("preferred_label"):
                return preferred

            if not output_meta.empty and hasattr(output_meta, "preferred_label"):
                new_value = output_meta[output_meta.tag == x].preferred_label
                if not new_value.empty:
                    return new_value.values[0]

            return None

        output_statement["preferred_label"] = output_statement.tag.apply(
            apply_preferred_label
        )

        def apply_period_beginning(row):
            """Apply a period beginning to the column."""
            context = row.context_ref if hasattr(row, "context_ref") else None
            period_start = ""

            if context and isinstance(context, str):
                if context.lower().startswith("as_of"):
                    return period_start

                if context.lower().startswith("duration"):
                    start_date = "_".join(context.split("_")[1:4]).replace("_", "-")
                    start_date = to_datetime(start_date).strftime("%Y-%m-%d")

                    return start_date

                period_start = self._period_context.get(context, {}).get("start")

                if not period_start and (
                    len("_".join(context.split("_")[:3])) == 23
                    or (
                        context[2] == "_"
                        and len("_".join(context.split("_")[:2])) == 12
                    )
                ):
                    period_start = context.split("_")[1]

                if period_start:
                    return period_start

            if row.value and row.value != "--" and " -- " in row.period_ending:
                period_end = row.period_ending
                period_months = period_end.split(" -- ")[-1][0]
                period_end = to_datetime(period_end.split(" -- ")[0])
                period_start = (
                    period_end
                    - DateOffset(months=int(period_months))
                    + offsets.MonthEnd(0)
                    + offsets.MonthBegin(1)
                ).strftime("%Y-%m-%d")

                return period_start

            if (
                row.value
                and row.value != "--"
                and row.period_ending
                and self.document_type == "10-K"
            ):
                period_end = to_datetime(row.period_ending.split(" -- ")[0])
                period_start = (
                    period_end.replace(year=period_end.year - 1) + timedelta(days=1)
                ).strftime("%Y-%m-%d")

                return period_start

            return None

        def apply_fix_period_end(row):
            """Apply a period ending to the column."""
            con_ref = row.context_ref if hasattr(row, "context_ref") else None
            if con_ref and isinstance(con_ref, str):
                context_data = self._period_context.get(con_ref, {})
                context_end = context_data.get("end")
                context_start = context_data.get("start")
                context_period_type = context_data.get("period_type")
                if context_end:
                    with contextlib.suppress(Exception):
                        period_end = to_datetime(context_end).strftime("%Y-%m-%d")
                        if (
                            context_period_type == "duration"
                            and context_start
                            and context_end
                        ):
                            start = to_datetime(context_start)
                            end = to_datetime(context_end)
                            n_months = (
                                (end.year - start.year) * 12
                                + end.month
                                - start.month
                                + 1
                            )
                            row.period_ending = (
                                f"{period_end} -- {n_months} Months Ended"
                            )
                        else:
                            row.period_ending = period_end

            con_ref = row.context_ref

            if (
                con_ref and row.period_beginning and " -- " not in row.period_ending
            ) or row.value == "--":
                return row

            return row

        output_statement.loc[:, "period_beginning"] = output_statement.apply(
            apply_period_beginning, axis=1
        )
        output_statement = output_statement.apply(apply_fix_period_end, axis=1)

        period_with_duration = output_statement["period_ending"].dropna().astype(str)
        period_with_duration = period_with_duration[
            period_with_duration.str.contains(" -- ", regex=False)
        ]
        period_end_lookup: dict[str, str] = {}
        for period_label in period_with_duration.tolist():
            period_date = period_label.split(" -- ", 1)[0]
            if period_date not in period_end_lookup:
                period_end_lookup[period_date] = period_label

        if period_end_lookup:
            output_statement["period_ending"] = output_statement["period_ending"].apply(
                lambda x: (
                    period_end_lookup.get(str(x), str(x))
                    if x is not None and " -- " not in str(x)
                    else x
                )
            )

        output_statement = output_statement[
            [
                "order",
                "tag",
                "parent_tag",
                "preferred_label",
                "balance",
                "weight",
                "decimals",
                "context_ref",
                "period_beginning",
                "period_ending",
                "unit",
                "label",
                "value",
            ]
        ]

        output_statement = output_statement.sort_values(
            by=["order", "period_ending", "period_beginning"],
            ascending=[True, False, False],
        )

        output_statement = output_statement.drop_duplicates(
            subset=[
                "tag",
                "value",
                "period_ending",
                "period_beginning",
                "context_ref",
            ],
            keep="first",
        )
        output_statement = output_statement.sort_values(
            by=["order", "period_ending", "period_beginning"],
            ascending=[True, False, False],
        )

        # Enrich output_meta with missing tags
        statement_tags = set(output_statement.tag.dropna().unique())
        meta_tags = (
            set(output_meta.tag.unique())
            if not output_meta.empty and "tag" in output_meta.columns
            else set()
        )
        missing_tags = statement_tags - meta_tags

        if missing_tags:
            new_rows = []
            for tag in missing_tags:
                tag_info = tags.get(tag, {})
                taxonomy = tag.split("_")[0] if "_" in tag else None
                new_row = {
                    "tag": tag,
                    "taxonomy": taxonomy,
                    "data_type": tag_info.get("xbrl_type"),
                    "balance_type": tag_info.get("crdr"),
                    "period_type": tag_info.get("period_type"),
                    "weight": tag_info.get("weight"),
                    "unit": None,
                    "decimals": None,
                    "name": tag_info.get("name"),
                    "preferred_label": tag_info.get("preferred_label"),
                    "parent_tag": tag_info.get("parentTag")
                    or tag_info.get("parent_tag"),
                    "description": tag_info.get("documentation"),
                }
                instance_data = instance_dict.get(tag, {}).get("context", [])

                if instance_data:
                    new_row["unit"] = check_unit(instance_data[0].get("unit"))
                    new_row["decimals"] = instance_data[0].get("decimals")

                new_rows.append(new_row)

            if new_rows:
                missing_df = DataFrame(new_rows)
                output_meta = concat(
                    [output_meta, missing_df], axis=0, ignore_index=True
                )

        def format_value(x):
            if x is None or x in {"--", ""}:
                return None
            try:
                f = float(x)

                if f == int(f):
                    return int(f)

                return f
            except (
                ValueError,
                TypeError,
            ):  # pragma: no cover - values reaching format_value are numeric or already None/"--", so float() never raises here
                return x

        output_statement["value"] = output_statement["value"].apply(format_value)

        return output_statement.replace({NA: None, nan: None, "": None}).reset_index(
            drop=True
        ), output_meta.replace({NA: None, nan: None, "": None}).reset_index(drop=True)

    def _download_statement_from_url(self, url, is_equity: bool = False):
        """Download a financial statement file from a SEC URL."""
        from pandas import DataFrame, MultiIndex, concat, isnull, to_datetime

        tables = self._get_document(url, read_html_table=True)

        df = tables[0].copy()

        df1 = DataFrame()
        df2 = DataFrame()

        is_multiindex = len(df.columns) == 5 or isinstance(df.columns[1], tuple)

        if is_multiindex and self.document_type == "10-K" and len(df.columns) == 5:
            df = df.iloc[:, [0, 2, 3, 4]].copy()

        is_annual_multi = len(df.columns) == 4 and isinstance(df.columns, MultiIndex)

        if is_annual_multi:
            df1 = df.copy()
            self._period_end1 = df1.columns[1][0]
            df1.columns = df.columns.droplevel(0)
        elif is_multiindex:
            if len(df.columns) == 5:
                df1 = df.iloc[:, :3].copy()
                self._period_end1 = df1.columns[1][0]
                df2 = df.iloc[:, [0, 3, 4]].copy()
                self._period_end2 = df2.columns[1][0]
            elif len(df.columns) == 3:
                df1 = df.copy()
                self._period_end1 = df.columns[1][0]
                df1.columns = df.columns.droplevel(0)
        else:
            if df.columns[0] == df.columns[1].replace(".1", ""):
                df = df.drop(columns=[df.columns[1]])
            df1 = df
            self._period_end1 = "12 Months Ended"

        def _process_statement(self, statement):
            """Process the statement."""
            nonlocal is_equity

            period_end = (
                self._period_end2
                if hasattr(self, "_period_end2")
                and self._period_end2
                and self._period_end2.lower().endswith("ended")
                else None
            ) or (
                self._period_end1
                if hasattr(self, "_period_end1")
                and self._period_end1
                and self._period_end1.lower().endswith("ended")
                else None
            )

            if isinstance(statement.columns, MultiIndex):
                period_end = statement.columns[1][0]
                statement.columns = [d[1] for d in statement.columns]

            multiplier_str = (
                statement.columns[0].split("$ in ")[-1]
                if "$ in " in statement.columns[0]
                else ""
            )
            shares_multiplier_str = (
                statement.columns[0].split(" shares in ")[-1].split(",")[0]
                if " shares in " in statement.columns[0].lower()
                else ""
            )

            multiplier = self._multiplier_map(multiplier_str) if multiplier_str else 1
            shares_multiplier = (
                self._multiplier_map(shares_multiplier_str)
                if shares_multiplier_str
                else 1
            )

            pattern = re.compile(
                r"\(in [a-zA-Z] per share\)|per\s+(?:common\s+)?share\b|weighted average number of",
                re.IGNORECASE,
            )
            pattern_shares = re.compile(
                r"(shares authorized|shares issued|shares outstanding)$",
                re.IGNORECASE,
            )

            def clean_col(x):
                """Clean a column name."""
                if str(x).startswith("["):
                    return None
                new_str = (
                    str(x)
                    .replace("(", "-")
                    .replace(")", "")
                    .replace(",", "")
                    .replace("$", "")
                    .replace(" ", "")
                )
                try:
                    return float(new_str)
                except ValueError:
                    return None

            mask = ~statement.iloc[:, 0].astype(str).str.match(r"^\[\d+\]")
            statement = statement[mask].reset_index(drop=True)

            if not is_equity:
                value_cols = statement.columns[1:]
                for col in value_cols:
                    statement[col] = statement[col].replace("--", float("nan"))
                label_col = statement.columns[0]
                has_label = statement[label_col].astype(str).str.strip() != ""
                has_values = statement[value_cols].notna().any(axis=1)
                statement = statement[has_label | has_values].reset_index(drop=True)

            def format_date(x):
                """Format a date."""
                if not x:
                    return None
                date_part = " ".join(str(x).split()[:3])
                with contextlib.suppress(Exception):
                    return to_datetime(date_part).strftime("%Y-%m-%d")
                return None

            date_col_map: dict = {}
            if not is_equity:
                for col in statement.columns[1:]:
                    parsed_date = format_date(col)
                    if parsed_date:
                        date_col_map[col] = parsed_date
                if date_col_map:
                    statement = statement[[statement.columns[0], *date_col_map.keys()]]

            for col in statement.columns[1:]:
                statement[col] = statement[col].apply(clean_col)

                def _scale_row_value(row):
                    if isnull(row[col]):
                        return "--"

                    label = str(row[statement.columns[0]]).lower()
                    is_per_share = bool(pattern.search(label)) or (
                        "(in dollars per share)" in label
                    )
                    is_share_count = "(in shares)" in label or bool(
                        pattern_shares.search(label)
                    )

                    if is_per_share:
                        return float(row[col])

                    if is_share_count:
                        return int(row[col] * shares_multiplier)

                    value = row[col] * multiplier
                    return int(value)

                statement[col] = statement.apply(
                    _scale_row_value,
                    axis=1,
                )

            col_1 = statement.columns[0]
            col_1 = col_1.split(" $ in ")[0]
            if period_end:
                statement.columns = (
                    statement.columns
                    if is_equity is True
                    else [col_1]
                    + [
                        f"{date_col_map.get(d) or format_date(d)} -- {period_end}"
                        for d in statement.columns[1:].tolist()
                    ]
                )
            else:
                statement.columns = (
                    statement.columns
                    if is_equity is True
                    else [col_1]
                    + [
                        date_col_map.get(d) or format_date(d)
                        for d in statement.columns[1:].tolist()
                    ]
                )

            item_map = DataFrame()

            for table in tables[1:]:
                df = table.set_index(0).T
                df.columns = [d.replace(":", "") for d in df.columns]
                item_map = concat([item_map, df], axis=0) if not item_map.empty else df

            if not item_map.empty:
                item_map = item_map.reset_index(drop=True)

            instance_dict = self._instance.copy()
            tags = self._tags.copy()

            def map_units(x):
                """Map the units to a multiplier."""
                instance = instance_dict.get(x, {}).get("context", [])
                if not instance or len(instance) < 1:
                    return None
                unit = instance[0].get("unit")
                if not unit:
                    return None
                return unit

            def map_decimals(x):
                """Map the decimals to a number."""
                instance = instance_dict.get(x, {}).get("context", [])
                if not instance or len(instance) < 1:
                    return None
                decimals = instance[0].get("decimals")
                if not decimals:
                    return None
                return decimals

            def apply_parent_tag(x):
                """Apply a parent tag to the column."""
                tag = tags.get(x, {})
                parent_tag = tag.get("parentTag") or tag.get("parent_tag")
                if parent_tag:
                    return parent_tag
                return None

            if is_equity is False:
                item_map["weight"] = item_map.Name.apply(
                    lambda x: self.tags.get(x, {}).get("weight")
                )
                item_map["unit"] = item_map.Name.apply(map_units)
                item_map["decimals"] = item_map.Name.apply(map_decimals)
                item_map["Balance Type"] = item_map["Balance Type"].apply(
                    lambda x: str(x).replace("na", "") if x else None
                )
                item_map["name"] = item_map.Name.apply(
                    lambda x: self.tags.get(x, {}).get("name")
                )
                item_map["preferred_label"] = item_map.Name.apply(
                    lambda x: self.tags.get(x, {}).get("preferred_label")
                )
                item_map["parent_tag"] = item_map.Name.apply(apply_parent_tag)
                item_map["description"] = item_map.Name.apply(
                    lambda x: self.tags.get(x, {}).get("documentation")
                )
                for col in item_map.columns:
                    if col.startswith("["):
                        item_map = item_map.drop(columns=col)
                    else:
                        item_map[col] = item_map[col].apply(
                            lambda x: (
                                x
                                if x and str(x).strip() not in ["na", "n", "nan"]
                                else None
                            )
                        )

            return statement, item_map.dropna()

        merged_df = DataFrame()
        merged_meta = DataFrame()

        if not df2.empty:
            for data in [df1, df2]:
                statement, item_map = _process_statement(self, data)
                statement = statement.set_index(statement.columns[0])
                merged_df = (
                    concat([merged_df, statement], axis=1)
                    if not merged_df.empty
                    else statement
                )
                merged_meta = (
                    concat([merged_meta, item_map], axis=0)
                    if not merged_meta.empty
                    else item_map
                )
            merged_df = merged_df.reset_index()
            merged_meta = merged_meta.reset_index(drop=True)
        else:
            return _process_statement(self, df1)

        return merged_df, merged_meta


async def get_form10_urls_by_symbol(symbol: str, use_cache: bool = True) -> list:
    """Get Form 10-K/Q URLs by symbol.

    This function uses the SecCompanyFilingsFetcher to filter 10-Q/K filings.

    Parameters
    ----------
    symbol : str
        The ticker symbol of the company.
    use_cache : bool, optional
        Whether to use cached data, by default True.

    Returns
    -------
    list
        A list of dictionaries containing filing date, period ending, filing type, and URL.
    """
    from openbb_sec.models.company_filings import SecCompanyFilingsFetcher

    filings_fetcher = SecCompanyFilingsFetcher()
    params = {
        "symbol": symbol,
        "form_type": _FILING_FORMS,
        "use_cache": use_cache,
    }

    filings = await filings_fetcher.fetch_data(params, {})

    form_10s: list = []

    for filing in filings:
        form_10s.append(
            {
                "filing_date": filing.filing_date,  # type: ignore
                "period_ending": filing.report_date,  # type: ignore
                "filing_type": filing.report_type,  # type: ignore
                "url": filing.report_url,  # type: ignore
            }
        )

    return form_10s


class FilingSectionQueryParams(QueryParams):
    """Shared query parameters for symbol-driven SEC filing-section endpoints."""

    symbol: str = Field(description="Symbol to get data for.")
    url: str | None = Field(
        default=None,
        description="Direct URL to a 10-K/10-Q filing, e.g. from `latest_financial_reports`."
        " When provided, the filing is parsed directly and the other params are ignored.",
    )
    calendar_year: int | None = Field(
        default=None,
        description="Calendar year of the filing. Defaults to the most recent.",
    )
    calendar_period: Literal["Q1", "Q2", "Q3", "Q4"] | None = Field(
        default=None,
        description="Calendar quarter (Q1-Q4) of the filing; leave empty for the"
        " most recent annual report.",
    )
    use_cache: bool = Field(
        default=True,
        description="Use the cache for downloaded filings. Default is True.",
    )

    @field_validator("symbol", mode="before", check_fields=False)
    @classmethod
    def _to_upper(cls, v):
        """Upper-case the symbol."""
        return v.upper() if isinstance(v, str) else v

    @field_validator(
        "calendar_period", "calendar_year", mode="before", check_fields=False
    )
    @classmethod
    def _empty_to_none(cls, v):
        """Treat an empty string (e.g. the 'Annual' widget option) as None."""
        return None if v == "" else v


def _clean_disclosure_name(name: str) -> str:
    """Strip the SEC '<id> - Disclosure - ' prefix from a disclosure label."""
    parts = name.split(" - Disclosure - ", 1)
    return parts[1].strip() if len(parts) == 2 else name


def _is_legal_redirect(text: str) -> bool:
    """Return True when an Item 3 section merely points to a note."""
    if len(text) > 1500:
        return False
    return bool(
        re.search(r"(?i)incorporated\s+(?:herein\s+)?by\s+reference", text)
        or (
            re.search(r"(?i)\bnotes?\s+\d+", text)
            and re.search(r"(?i)financial statements", text)
        )
    )


_FILING_FORMS = "10-K,10-Q,20-F,40-F"
_ANNUAL_FORMS = ("10-K", "20-F", "40-F")


def _is_amendment(filing_type: str | None) -> bool:
    """Return True for an amendment form (e.g. 10-K/A), a distinct document."""
    return (filing_type or "").upper().endswith("/A")


def _is_annual_form(filing_type: str | None) -> bool:
    """Return True for annual forms (domestic 10-K and foreign 20-F/40-F).

    Amendments (10-K/A, 20-F/A) are excluded: a 10-K/A is a separate document
    that often amends only Part III and lacks the Business and MD&A sections.
    """
    ft = (filing_type or "").upper()
    return ft.startswith(_ANNUAL_FORMS) and not _is_amendment(ft)


def no_filing_message(symbol: str) -> str:
    """Friendly message when a symbol has no supported annual/quarterly filing."""
    return (
        f"No 10-K, 10-Q, 20-F, or 40-F filing was found for '{symbol}'. It may be a"
        " foreign private issuer that files only 6-K interim reports, or a company"
        " that does not file these forms with the SEC."
    )


def _calendar_quarter(period_ending: str | None) -> int:
    """Calendar quarter (1-4) of a period-ending date, 0 when unparseable."""
    pe = str(period_ending or "")
    if len(pe) < 7 or not pe[5:7].isdigit():
        return 0
    return (int(pe[5:7]) - 1) // 3 + 1


async def resolve_filing_url(
    symbol: str,
    calendar_year: int | None = None,
    calendar_period: str | None = None,
    use_cache: bool = True,
    annual_default: bool = True,
) -> str:
    """Resolve a symbol to a single filing URL by calendar year and period.

    ``calendar_period`` is a calendar quarter (``Q1``-``Q4``) matched against the
    filing's period-ending date. With no ``calendar_period``, ``annual_default=True``
    selects the latest annual report (10-K, or 20-F/40-F for foreign filers) and
    ``annual_default=False`` selects the latest filing of any form.
    """
    filings = await get_form10_urls_by_symbol(symbol, use_cache)
    filings = sorted(
        filings,
        key=lambda f: (
            str(f.get("period_ending") or ""),
            not _is_amendment(f.get("filing_type")),
            str(f.get("filing_date") or ""),
        ),
        reverse=True,
    )

    if calendar_year:
        filings = [
            f
            for f in filings
            if str(f.get("period_ending") or "")[:4] == str(calendar_year)
        ]

    if calendar_period:
        quarter = int(str(calendar_period)[-1])
        filings = [
            f for f in filings if _calendar_quarter(f.get("period_ending")) == quarter
        ]
    elif annual_default:
        filings = [f for f in filings if _is_annual_form(f.get("filing_type"))]

    return filings[0].get("url", "") if filings else ""


async def resolve_section_url(query, annual_default: bool = True) -> str:
    """Return a filing URL from a section query: an explicit url, or resolved from symbol."""
    if getattr(query, "url", None):
        return query.url
    if not getattr(query, "symbol", None):
        return ""
    return await resolve_filing_url(
        query.symbol,
        getattr(query, "calendar_year", None),
        getattr(query, "calendar_period", None),
        query.use_cache,
        annual_default,
    )


@lru_cache(maxsize=32)
def _financial_statements_cache(url: str, use_cache: bool) -> FinancialStatements:
    """Build and memoize a FinancialStatements per (url, use_cache)."""
    return FinancialStatements(url, use_cache)
