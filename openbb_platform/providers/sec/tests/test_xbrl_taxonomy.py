"""Tests for XBRL taxonomy handling, parsing, and fact resolution."""

# flake8: noqa: D102, E501

from __future__ import annotations

import gzip
from io import BytesIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import requests
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.app.model.abstract.warning import OpenBBWarning
from openbb_core.app.service.user_service import UserService

from openbb_sec.models.schema_files import (
    SecSchemaFilesFetcher,
    _flatten_nodes,
)
from openbb_sec.utils import xbrl_taxonomy_helper as xth
from openbb_sec.utils.xbrl_taxonomy_helper import (
    TAXONOMIES,
    FASBClient,
    TaxonomyCategory,
    TaxonomyConfig,
    TaxonomyStyle,
    XBRLManager,
    XBRLNode,
    XBRLParser,
    get_label_url_for_import,
)

CACHE_MOD = "openbb_sec.utils.cache"

test_credentials = UserService().default_user_settings.credentials.model_dump()


# ─── Per-test fixtures (cheap, no network) ────────────────────────────────


@pytest.fixture
def parser() -> XBRLParser:
    """Fresh XBRLParser instance."""
    return XBRLParser()


@pytest.fixture
def manager() -> XBRLManager:
    """Fresh XBRLManager instance."""
    return XBRLManager()


def _b(xml_str: str) -> BytesIO:
    """Wrap an XML string as a BytesIO of UTF-8 bytes."""
    return BytesIO(xml_str.encode("utf-8"))


@pytest.fixture(autouse=True)
def _reset_ifrs_cache():
    """Reset the module-level IFRS date cache around each test."""
    saved = xth._ifrs_version_dates_cache
    xth._ifrs_version_dates_cache = None
    try:
        yield
    finally:
        xth._ifrs_version_dates_cache = saved


APPLE_10K_URL = (
    "https://www.sec.gov/Archives/edgar/data/320193/"
    "000032019324000123/aapl-20240928_htm.xml"
)
APPLE_10K_FILES = Path(__file__).parent / "fixtures" / "apple_10k"


def serve_apple_10k_file(url: str, **kwargs: Any) -> bytes:
    """Return a stored Apple 10-K filing document in place of downloading it."""
    base = APPLE_10K_URL.rsplit("/", 1)[0] + "/"
    if not url.startswith(base):
        raise AssertionError(f"Unexpected request outside the Apple 10-K filing: {url}")
    return gzip.decompress((APPLE_10K_FILES / f"{url[len(base) :]}.gz").read_bytes())


@pytest.fixture(scope="module")
def apple_10k_parsed():
    """Parse Apple's FY2024 10-K instance with its schema and linkbases from stored files.

    Returns ``(contexts, units, facts)``.
    """
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("openbb_sec.utils.cache.cached_bytes", serve_apple_10k_file)
        return XBRLParser().parse_instance(
            BytesIO(serve_apple_10k_file(APPLE_10K_URL)), base_url=APPLE_10K_URL
        )


@pytest.fixture(scope="module")
def us_gaap_sfp_cls_nodes():
    """us-gaap 2024 classified balance-sheet structure (fetched once)."""
    return XBRLManager().get_structure("us-gaap", 2024, "sfp-cls")


@pytest.fixture(scope="module")
def dei_standard_nodes():
    """DEI 2024 standard structure (fetched once)."""
    return XBRLManager().get_structure("dei", 2024, "standard")


@pytest.fixture(scope="module")
def us_gaap_components_meta():
    """us-gaap 2024 component metadata list (fetched once)."""
    return XBRLManager().get_components_metadata("us-gaap", 2024)


@pytest.fixture(scope="module")
def frc_dpl_loaded():
    """FRC DPL 2024 fully loaded — ``(manager, nodes)``.

    ``get_structure`` internally calls ``_ensure_labels`` and
    ``_ensure_element_properties`` (and FRC core labels), so the returned
    manager has all parser state populated.
    """
    mgr = XBRLManager()
    nodes = mgr.get_structure("frc-dpl", 2024, "standard")
    return mgr, nodes


@pytest.fixture(scope="module")
def frc_core_loaded():
    """FRC core 2024 fully loaded — ``(manager, nodes)``."""
    mgr = XBRLManager()
    nodes = mgr.get_structure("frc-core", 2024, "standard")
    return mgr, nodes


@pytest.fixture(scope="module")
def us_gaap_lab_bytes():
    """Raw bytes of the us-gaap 2024 label linkbase (fetched once)."""
    from openbb_sec.utils.xbrl_taxonomy_helper import FASBClient

    return (
        FASBClient()
        .fetch_file("https://xbrl.fasb.org/us-gaap/2024/elts/us-gaap-lab-2024.xml")
        .read()
    )


@pytest.fixture(scope="module")
def us_gaap_doc_bytes():
    """Raw bytes of the us-gaap 2024 documentation linkbase (fetched once)."""
    from openbb_sec.utils.xbrl_taxonomy_helper import FASBClient

    return (
        FASBClient()
        .fetch_file("https://xbrl.fasb.org/us-gaap/2024/elts/us-gaap-doc-2024.xml")
        .read()
    )


@pytest.fixture(scope="module")
def us_gaap_pres_bytes():
    """Raw bytes of the us-gaap sfp-cls presentation linkbase (fetched once)."""
    from openbb_sec.utils.xbrl_taxonomy_helper import FASBClient

    return (
        FASBClient()
        .fetch_file(
            "https://xbrl.fasb.org/us-gaap/2024/stm/us-gaap-stm-sfp-cls-pre-2024.xml"
        )
        .read()
    )


@pytest.fixture(scope="module")
def us_gaap_cal_bytes():
    """Raw bytes of the us-gaap sfp-cls calculation linkbase (fetched once)."""
    from openbb_sec.utils.xbrl_taxonomy_helper import FASBClient

    return (
        FASBClient()
        .fetch_file(
            "https://xbrl.fasb.org/us-gaap/2024/stm/us-gaap-stm-sfp-cls-cal-2024.xml"
        )
        .read()
    )


@pytest.fixture(scope="module")
def us_gaap_labels_manager():
    """XBRLManager with us-gaap 2024 labels + docs already loaded."""
    mgr = XBRLManager()
    mgr._ensure_labels("us-gaap", 2024)
    return mgr


# ═════════════════════════════════════════════════════════════════════════
# 1. Offline tests — no network, no fixtures
# ═════════════════════════════════════════════════════════════════════════


class TestTaxonomyRegistry:
    """Tests for the TAXONOMIES registry and its configuration objects."""

    def test_registry_has_expected_taxonomies(self):
        """All 25 registered taxonomies should be present."""
        expected = {
            "us-gaap",
            "srt",
            "dei",
            "ecd",
            "cyd",
            "ffd",
            "ifrs",
            "frc-core",
            "frc-dpl",
            "rxp",
            "spac",
            "cef",
            "oef",
            "vip",
            "fnd",
            "sro",
            "sbs",
            "rocr",
            "country",
            "currency",
            "exch",
            "naics",
            "sic",
            "stpr",
            "snj",
        }
        assert expected == set(TAXONOMIES.keys())

    def test_all_configs_are_taxonomy_config(self):
        """Every entry in TAXONOMIES must be a TaxonomyConfig instance."""
        for key, config in TAXONOMIES.items():
            assert isinstance(config, TaxonomyConfig), f"{key} is not TaxonomyConfig"

    def test_all_configs_have_required_fields(self):
        """Every TaxonomyConfig must have non-empty essential fields."""
        for key, config in TAXONOMIES.items():
            assert config.base_url_template, f"{key} missing base_url_template"
            assert isinstance(config.style, TaxonomyStyle), f"{key} bad style"
            assert config.label, f"{key} missing label"
            assert config.description, f"{key} missing description"
            assert isinstance(config.category, TaxonomyCategory), f"{key} bad category"

    def test_taxonomy_styles_complete(self):
        """All TaxonomyStyle values should be represented by at least one taxonomy."""
        styles_used = {config.style for config in TAXONOMIES.values()}
        for style in TaxonomyStyle:
            assert style in styles_used, f"TaxonomyStyle.{style.name} unused"

    def test_taxonomy_categories_complete(self):
        """All TaxonomyCategory values should be represented."""
        cats_used = {config.category for config in TAXONOMIES.values()}
        for cat in TaxonomyCategory:
            assert cat in cats_used, f"TaxonomyCategory.{cat.name} unused"

    def test_fasb_standard_taxonomies(self):
        """FASB_STANDARD taxonomies should point to xbrl.fasb.org."""
        for key, config in TAXONOMIES.items():
            if config.style == TaxonomyStyle.FASB_STANDARD:
                assert "xbrl.fasb.org" in config.base_url_template, key

    def test_sec_embedded_taxonomies(self):
        """SEC_EMBEDDED taxonomies should point to xbrl.sec.gov."""
        for key, config in TAXONOMIES.items():
            if config.style == TaxonomyStyle.SEC_EMBEDDED:
                assert "xbrl.sec.gov" in config.base_url_template, key

    def test_url_templates_have_year_placeholder(self):
        """Non-STATIC URL-templated taxonomies must have {year} in base_url_template."""
        for key, config in TAXONOMIES.items():
            # FRC taxonomies resolve members from the per-year suite ZIP map,
            # not a {year} URL template, so they are exempt.
            if config.style == TaxonomyStyle.STATIC or key in ("frc-core", "frc-dpl"):
                continue
            assert "{year}" in config.base_url_template, (
                f"{key} missing {{year}} placeholder"
            )

    def test_static_taxonomy_has_no_year_placeholder(self):
        """STATIC taxonomies should NOT have {year} in their base_url_template."""
        for key, config in TAXONOMIES.items():
            if config.style == TaxonomyStyle.STATIC:
                assert "{year}" not in config.base_url_template, (
                    f"Static taxonomy {key} should not have {{year}}"
                )


class TestXBRLNode:
    """Tests for the XBRLNode dataclass."""

    def test_basic_creation(self):
        """Create a minimal XBRLNode and verify fields."""
        node = XBRLNode(
            element_id="us-gaap_Assets",
            label="Assets",
            order=1.0,
            level=0,
            parent_id=None,
        )
        assert node.element_id == "us-gaap_Assets"
        assert node.label == "Assets"
        assert node.children == []
        assert node.abstract is False
        assert node.nillable is None

    def test_to_dict(self):
        """to_dict should serialize all fields including children."""
        child = XBRLNode(
            element_id="us-gaap_AssetsCurrent",
            label="Current Assets",
            order=1.0,
            level=1,
            parent_id="us-gaap_Assets",
        )
        parent = XBRLNode(
            element_id="us-gaap_Assets",
            label="Assets",
            order=1.0,
            level=0,
            parent_id=None,
            abstract=True,
            children=[child],
        )
        d = parent.to_dict()
        assert d["element_id"] == "us-gaap_Assets"
        assert d["abstract"] is True
        assert len(d["children"]) == 1
        assert d["children"][0]["element_id"] == "us-gaap_AssetsCurrent"

    def test_to_dict_all_metadata_fields(self):
        """to_dict should include all enriched metadata fields."""
        node = XBRLNode(
            element_id="us-gaap_Revenue",
            label="Revenue",
            order=2.0,
            level=0,
            parent_id=None,
            documentation="Total revenue recognized.",
            xbrl_type="monetaryItemType",
            period_type="duration",
            balance_type="credit",
            abstract=False,
            substitution_group="item",
            nillable=True,
            preferred_label="http://www.xbrl.org/2003/role/terseLabel",
        )
        d = node.to_dict()
        assert d["xbrl_type"] == "monetaryItemType"
        assert d["period_type"] == "duration"
        assert d["balance_type"] == "credit"
        assert d["substitution_group"] == "item"
        assert d["nillable"] is True
        assert d["preferred_label"] == "http://www.xbrl.org/2003/role/terseLabel"
        assert d["documentation"] == "Total revenue recognized."

    def test_flatten_nodes_helper(self):
        """_flatten_nodes should recursively flatten nested nodes."""
        child = XBRLNode(
            element_id="child",
            label="Child",
            order=1.0,
            level=1,
            parent_id="parent",
        )
        grandchild = XBRLNode(
            element_id="grandchild",
            label="Grandchild",
            order=1.0,
            level=2,
            parent_id="child",
        )
        child.children = [grandchild]
        parent = XBRLNode(
            element_id="parent",
            label="Parent",
            order=1.0,
            level=0,
            parent_id=None,
            children=[child],
        )
        flat = _flatten_nodes([parent])
        assert len(flat) == 3
        assert [f["name"] for f in flat] == ["parent", "child", "grandchild"]


class TestResolveHelpers:
    """Tests for XBRLParser static helper methods."""

    # -- _resolve_measure --

    def test_resolve_measure_currency(self):
        assert XBRLParser._resolve_measure("iso4217:USD") == "iso4217:USD"
        assert XBRLParser._resolve_measure("iso4217:EUR") == "iso4217:EUR"

    def test_resolve_measure_shares(self):
        assert XBRLParser._resolve_measure("xbrli:shares") == "shares"
        assert XBRLParser._resolve_measure("shares") == "shares"

    def test_resolve_measure_pure(self):
        assert XBRLParser._resolve_measure("xbrli:pure") == "pure"
        assert XBRLParser._resolve_measure("pure") == "pure"

    def test_resolve_measure_empty(self):
        assert XBRLParser._resolve_measure("") == ""
        assert XBRLParser._resolve_measure(None) == ""

    def test_resolve_measure_custom(self):
        """Custom measures should be returned unchanged."""
        assert XBRLParser._resolve_measure("aapl:Vendor") == "aapl:Vendor"

    # -- _build_ns_prefix_map --

    def test_build_ns_prefix_map_simple(self):
        raw = b'<root xmlns:us-gaap="http://fasb.org/us-gaap/2024" xmlns:aapl="http://www.apple.com/20240928">'
        ns_map = XBRLParser._build_ns_prefix_map(raw)
        assert ns_map["http://fasb.org/us-gaap/2024"] == "us-gaap"
        assert ns_map["http://www.apple.com/20240928"] == "aapl"

    def test_build_ns_prefix_map_sec_taxonomies(self):
        raw = (
            b'<root xmlns:ecd="http://xbrl.sec.gov/ecd/2024" '
            b'xmlns:dei="http://xbrl.sec.gov/dei/2024" '
            b'xmlns:srt="http://fasb.org/srt/2024">'
        )
        ns_map = XBRLParser._build_ns_prefix_map(raw)
        assert ns_map["http://xbrl.sec.gov/ecd/2024"] == "ecd"
        assert ns_map["http://xbrl.sec.gov/dei/2024"] == "dei"
        assert ns_map["http://fasb.org/srt/2024"] == "srt"

    def test_build_ns_prefix_map_empty(self):
        ns_map = XBRLParser._build_ns_prefix_map(b"<root>")
        assert ns_map == {}

    def test_build_ns_prefix_map_single_quotes(self):
        raw = b"<root xmlns:foo='http://example.com/foo/2024'>"
        ns_map = XBRLParser._build_ns_prefix_map(raw)
        assert ns_map.get("http://example.com/foo/2024") == "foo"

    # -- _resolve_ns_prefix --

    def test_resolve_ns_prefix_direct_lookup(self):
        ns_map = {"http://www.apple.com/20240928": "aapl"}
        assert (
            XBRLParser._resolve_ns_prefix("http://www.apple.com/20240928", ns_map)
            == "aapl"
        )

    def test_resolve_ns_prefix_well_known_us_gaap(self):
        assert (
            XBRLParser._resolve_ns_prefix("http://fasb.org/us-gaap/2024", {})
            == "us-gaap"
        )

    def test_resolve_ns_prefix_well_known_dei(self):
        assert (
            XBRLParser._resolve_ns_prefix("http://xbrl.sec.gov/dei/2024", {}) == "dei"
        )

    def test_resolve_ns_prefix_well_known_srt(self):
        assert XBRLParser._resolve_ns_prefix("http://fasb.org/srt/2024", {}) == "srt"

    def test_resolve_ns_prefix_heuristic_skips_date(self):
        """Should skip trailing date-like segments to find semantic name."""
        assert (
            XBRLParser._resolve_ns_prefix("http://xbrl.sec.gov/ecd/2024", {}) == "ecd"
        )

    def test_resolve_ns_prefix_heuristic_company_extension(self):
        """Company extension URIs like http://company.com/20240928 get date skipped."""
        result = XBRLParser._resolve_ns_prefix("http://www.apple.com/20240928", {})
        assert not result.isdigit(), f"Got numeric prefix: {result}"

    def test_resolve_ns_prefix_prefers_xmlns_over_heuristic(self):
        """XMLS mapping should take priority over heuristic fallback."""
        ns_map = {"http://xbrl.sec.gov/ecd/2024": "ecd"}
        assert (
            XBRLParser._resolve_ns_prefix("http://xbrl.sec.gov/ecd/2024", ns_map)
            == "ecd"
        )


class TestParserWithSyntheticXML:
    """Tests using synthetic XBRL XML fragments — no network needed."""

    def _make_xml(self, xml_str: str) -> BytesIO:
        return BytesIO(xml_str.encode("utf-8"))

    def test_parse_units_simple(self, parser: XBRLParser):
        """Simple units should resolve correctly."""
        xml = self._make_xml(
            '<?xml version="1.0"?>'
            '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">'
            '  <xbrli:unit id="usd">'
            "    <xbrli:measure>iso4217:USD</xbrli:measure>"
            "  </xbrli:unit>"
            '  <xbrli:unit id="shares">'
            "    <xbrli:measure>xbrli:shares</xbrli:measure>"
            "  </xbrli:unit>"
            '  <xbrli:unit id="pure">'
            "    <xbrli:measure>xbrli:pure</xbrli:measure>"
            "  </xbrli:unit>"
            "</xbrli:xbrl>"
        )
        root = parser._get_xml_root(xml)
        units = parser._parse_units(root)
        assert units["usd"] == "iso4217:USD"
        assert units["shares"] == "shares"
        assert units["pure"] == "pure"

    def test_parse_units_compound(self, parser: XBRLParser):
        """Compound divide units (e.g. $/share) should resolve."""
        xml = self._make_xml(
            '<?xml version="1.0"?>'
            '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">'
            '  <xbrli:unit id="usdPerShare">'
            "    <xbrli:divide>"
            "      <xbrli:unitNumerator>"
            "        <xbrli:measure>iso4217:USD</xbrli:measure>"
            "      </xbrli:unitNumerator>"
            "      <xbrli:unitDenominator>"
            "        <xbrli:measure>xbrli:shares</xbrli:measure>"
            "      </xbrli:unitDenominator>"
            "    </xbrli:divide>"
            "  </xbrli:unit>"
            "</xbrli:xbrl>"
        )
        root = parser._get_xml_root(xml)
        units = parser._parse_units(root)
        assert units["usdPerShare"] == "iso4217:USD / shares"

    def test_parse_schema_elements(self, parser: XBRLParser):
        """parse_schema_elements should extract element definitions from a schema."""
        xml = self._make_xml(
            '<?xml version="1.0"?>'
            '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"'
            '           xmlns:xbrli="http://www.xbrl.org/2003/instance"'
            '           targetNamespace="http://example.com/2024">'
            '  <xs:element name="TestAsset"'
            '              id="example_TestAsset"'
            '              type="xbrli:monetaryItemType"'
            '              substitutionGroup="xbrli:item"'
            '              xbrli:periodType="instant"'
            '              xbrli:balance="debit"'
            '              abstract="false"'
            '              nillable="true"/>'
            "</xs:schema>"
        )
        nodes = parser.parse_schema_elements(xml)
        assert len(nodes) >= 1
        elem = nodes[0]
        assert elem.element_id == "example_TestAsset"

    def test_parse_instance_minimal(self, parser: XBRLParser):
        """Minimal instance doc with one context, one unit, one fact."""
        xml_str = (
            '<?xml version="1.0"?>'
            "<xbrli:xbrl "
            '  xmlns:xbrli="http://www.xbrl.org/2003/instance"'
            '  xmlns:us-gaap="http://fasb.org/us-gaap/2024"'
            '  xmlns:link="http://www.xbrl.org/2003/linkbase"'
            '  xmlns:xlink="http://www.w3.org/1999/xlink">'
            '  <xbrli:context id="ctx1">'
            "    <xbrli:entity>"
            '      <xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier>'
            "    </xbrli:entity>"
            "    <xbrli:period>"
            "      <xbrli:instant>2024-09-28</xbrli:instant>"
            "    </xbrli:period>"
            "  </xbrli:context>"
            '  <xbrli:unit id="usd">'
            "    <xbrli:measure>iso4217:USD</xbrli:measure>"
            "  </xbrli:unit>"
            '  <us-gaap:Assets contextRef="ctx1" unitRef="usd" decimals="-6">364980000000</us-gaap:Assets>'
            "</xbrli:xbrl>"
        )
        content = BytesIO(xml_str.encode("utf-8"))
        contexts, units, facts = parser.parse_instance(content)

        assert "ctx1" in contexts
        assert contexts["ctx1"]["entity"] == "0000320193"
        assert contexts["ctx1"]["period_type"] == "instant"
        assert contexts["ctx1"]["end"] == "2024-09-28"
        assert units["usd"] == "iso4217:USD"
        assert "us-gaap_Assets" in facts
        fact = facts["us-gaap_Assets"][0]
        assert fact["value"] == "364980000000"
        assert fact["unit"] == "iso4217:USD"
        assert fact["decimals"] == "-6"
        assert fact["entity"] == "0000320193"
        assert fact["period_type"] == "instant"

    def test_parse_instance_duration_context(self, parser: XBRLParser):
        """Duration contexts should have start and end dates."""
        xml_str = (
            '<?xml version="1.0"?>'
            "<xbrli:xbrl "
            '  xmlns:xbrli="http://www.xbrl.org/2003/instance"'
            '  xmlns:us-gaap="http://fasb.org/us-gaap/2024">'
            '  <xbrli:context id="dur1">'
            "    <xbrli:entity>"
            '      <xbrli:identifier scheme="http://www.sec.gov/CIK">0000789019</xbrli:identifier>'
            "    </xbrli:entity>"
            "    <xbrli:period>"
            "      <xbrli:startDate>2024-01-01</xbrli:startDate>"
            "      <xbrli:endDate>2024-12-31</xbrli:endDate>"
            "    </xbrli:period>"
            "  </xbrli:context>"
            '  <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>'
            '  <us-gaap:Revenues contextRef="dur1" unitRef="usd" decimals="-6">245122000000</us-gaap:Revenues>'
            "</xbrli:xbrl>"
        )
        content = BytesIO(xml_str.encode("utf-8"))
        contexts, _, facts = parser.parse_instance(content)

        ctx = contexts["dur1"]
        assert ctx["period_type"] == "duration"
        assert ctx["start"] == "2024-01-01"
        assert ctx["end"] == "2024-12-31"

        fact = facts["us-gaap_Revenues"][0]
        assert fact["period_type"] == "duration"
        assert fact["start"] == "2024-01-01"
        assert fact["end"] == "2024-12-31"

    def test_parse_instance_dimensional_context(self, parser: XBRLParser):
        """Contexts with explicit dimensions should be captured."""
        xml_str = (
            '<?xml version="1.0"?>'
            "<xbrli:xbrl "
            '  xmlns:xbrli="http://www.xbrl.org/2003/instance"'
            '  xmlns:xbrldi="http://xbrl.org/2006/xbrldi"'
            '  xmlns:us-gaap="http://fasb.org/us-gaap/2024">'
            '  <xbrli:context id="dim1">'
            "    <xbrli:entity>"
            '      <xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier>'
            "      <xbrli:segment>"
            '        <xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">aapl:IPhoneMember</xbrldi:explicitMember>'
            "      </xbrli:segment>"
            "    </xbrli:entity>"
            "    <xbrli:period>"
            "      <xbrli:instant>2024-09-28</xbrli:instant>"
            "    </xbrli:period>"
            "  </xbrli:context>"
            '  <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>'
            '  <us-gaap:Revenues contextRef="dim1" unitRef="usd" decimals="-6">46222000000</us-gaap:Revenues>'
            "</xbrli:xbrl>"
        )
        content = BytesIO(xml_str.encode("utf-8"))
        contexts, _, facts = parser.parse_instance(content)

        ctx = contexts["dim1"]
        assert "dimensions" in ctx
        assert "us-gaap:StatementBusinessSegmentsAxis" in ctx["dimensions"]
        assert (
            ctx["dimensions"]["us-gaap:StatementBusinessSegmentsAxis"]
            == "aapl:IPhoneMember"
        )

        fact = facts["us-gaap_Revenues"][0]
        assert "dimensions" in fact
        dim = fact["dimensions"]["us-gaap:StatementBusinessSegmentsAxis"]
        assert dim["member"] == "aapl:IPhoneMember"

    def test_parse_instance_namespace_prefix_resolution(self, parser: XBRLParser):
        """Tags from company-extension namespaces should use xmlns-declared prefixes."""
        xml_str = (
            '<?xml version="1.0"?>'
            "<xbrli:xbrl "
            '  xmlns:xbrli="http://www.xbrl.org/2003/instance"'
            '  xmlns:aapl="http://www.apple.com/20240928"'
            '  xmlns:ecd="http://xbrl.sec.gov/ecd/2024">'
            '  <xbrli:context id="c1">'
            "    <xbrli:entity>"
            '      <xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier>'
            "    </xbrli:entity>"
            "    <xbrli:period><xbrli:instant>2024-09-28</xbrli:instant></xbrli:period>"
            "  </xbrli:context>"
            '  <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>'
            '  <aapl:CustomMeasure contextRef="c1" unitRef="usd" decimals="-6">123</aapl:CustomMeasure>'
            '  <ecd:TrdArrIndName contextRef="c1">John Doe</ecd:TrdArrIndName>'
            "</xbrli:xbrl>"
        )
        content = BytesIO(xml_str.encode("utf-8"))
        _, _, facts = parser.parse_instance(content)

        assert "aapl_CustomMeasure" in facts, f"Got keys: {list(facts.keys())}"
        assert "ecd_TrdArrIndName" in facts, f"Got keys: {list(facts.keys())}"
        wrong = [k for k in facts if k.startswith("20240928_") or k.startswith("2024_")]
        assert wrong == [], f"Wrong-prefix tags found: {wrong}"

    def test_parse_instance_multiple_facts_same_tag(self, parser: XBRLParser):
        """Multiple facts for the same tag should all be captured."""
        xml_str = (
            '<?xml version="1.0"?>'
            "<xbrli:xbrl "
            '  xmlns:xbrli="http://www.xbrl.org/2003/instance"'
            '  xmlns:us-gaap="http://fasb.org/us-gaap/2024">'
            '  <xbrli:context id="c1">'
            '    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">123</xbrli:identifier></xbrli:entity>'
            "    <xbrli:period><xbrli:instant>2024-09-28</xbrli:instant></xbrli:period>"
            "  </xbrli:context>"
            '  <xbrli:context id="c2">'
            '    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">123</xbrli:identifier></xbrli:entity>'
            "    <xbrli:period><xbrli:instant>2023-09-30</xbrli:instant></xbrli:period>"
            "  </xbrli:context>"
            '  <xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>'
            '  <us-gaap:Assets contextRef="c1" unitRef="usd" decimals="-6">364980000000</us-gaap:Assets>'
            '  <us-gaap:Assets contextRef="c2" unitRef="usd" decimals="-6">352583000000</us-gaap:Assets>'
            "</xbrli:xbrl>"
        )
        content = BytesIO(xml_str.encode("utf-8"))
        _, _, facts = parser.parse_instance(content)

        assert len(facts["us-gaap_Assets"]) == 2
        values = {f["value"] for f in facts["us-gaap_Assets"]}
        assert values == {"364980000000", "352583000000"}

    def test_parse_instance_no_unit(self, parser: XBRLParser):
        """Facts without unitRef should have empty/none unit."""
        xml_str = (
            '<?xml version="1.0"?>'
            "<xbrli:xbrl "
            '  xmlns:xbrli="http://www.xbrl.org/2003/instance"'
            '  xmlns:dei="http://xbrl.sec.gov/dei/2024">'
            '  <xbrli:context id="c1">'
            '    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">123</xbrli:identifier></xbrli:entity>'
            "    <xbrli:period><xbrli:instant>2024-09-28</xbrli:instant></xbrli:period>"
            "  </xbrli:context>"
            '  <dei:EntityRegistrantName contextRef="c1">Apple Inc.</dei:EntityRegistrantName>'
            "</xbrli:xbrl>"
        )
        content = BytesIO(xml_str.encode("utf-8"))
        _, _, facts = parser.parse_instance(content)

        assert "dei_EntityRegistrantName" in facts
        fact = facts["dei_EntityRegistrantName"][0]
        assert fact["value"] == "Apple Inc."
        assert not fact.get("unit")


class TestXBRLManagerRegistry:
    """Tests for XBRLManager's taxonomy listing methods (registry-only)."""

    def test_list_available_taxonomies_all(self, manager: XBRLManager):
        """list_available_taxonomies() returns all 23 taxonomies."""
        result = manager.list_available_taxonomies()
        assert len(result) == len(TAXONOMIES)
        assert "us-gaap" in result
        assert "label" in result["us-gaap"]
        assert "description" in result["us-gaap"]
        assert "category" in result["us-gaap"]

    def test_list_available_taxonomies_filter_category(self, manager: XBRLManager):
        """Filtering by category should reduce results."""
        all_tax = manager.list_available_taxonomies()
        invest_tax = manager.list_available_taxonomies("investment_company")
        assert len(invest_tax) < len(all_tax)
        for meta in invest_tax.values():
            assert meta["category"] == "investment_company"

    def test_list_available_taxonomies_filter_enum(self, manager: XBRLManager):
        """Should also accept TaxonomyCategory enum value."""
        result = manager.list_available_taxonomies(TaxonomyCategory.COMMON_REFERENCE)
        for meta in result.values():
            assert meta["category"] == "common_reference"
        assert "dei" in result

    def test_list_available_taxonomies_invalid_category(self, manager: XBRLManager):
        """Invalid category string should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid category"):
            manager.list_available_taxonomies("not_a_category")


# ═════════════════════════════════════════════════════════════════════════
# 2. Network tests — grouped by shared fixture
# ═════════════════════════════════════════════════════════════════════════


class TestXBRLManagerSmall:
    """Small / unique HTTP tests (cheap index-page fetches)."""

    def test_get_available_years_us_gaap(self, manager: XBRLManager):
        """us-gaap should have many years of taxonomy data."""
        years = manager.get_available_years("us-gaap")
        assert isinstance(years, list)
        assert len(years) > 5
        assert 2024 in years

    def test_get_available_years_dei(self, manager: XBRLManager):
        """DEI should have available years."""
        years = manager.get_available_years("dei")
        assert isinstance(years, list)
        assert len(years) > 0

    def test_get_available_years_unknown(self, manager: XBRLManager):
        """Unknown taxonomy should return empty list."""
        years = manager.get_available_years("nonexistent")
        assert years == []

    def test_list_available_components_us_gaap(self, manager: XBRLManager):
        """us-gaap 2024 should have multiple components."""
        components = manager.list_available_components("us-gaap", 2024)
        assert isinstance(components, list)
        assert len(components) > 10
        assert "sfp-cls" in components
        assert "soi" in components

    def test_list_available_components_dei(self, manager: XBRLManager):
        """Single-component taxonomies should return one standard component."""
        components = manager.list_available_components("dei", 2024)
        assert isinstance(components, list)
        assert len(components) >= 1


class TestUSGaapComponents:
    """Tests sharing the ``us_gaap_components_meta`` fixture (fetched once)."""

    def test_get_components_metadata_us_gaap(self, us_gaap_components_meta):
        """Component metadata should include labels and descriptions."""
        assert isinstance(us_gaap_components_meta, list)
        assert len(us_gaap_components_meta) > 10
        for item in us_gaap_components_meta:
            assert "name" in item
            assert "label" in item

    def test_mode2_taxonomy_with_year(self):
        """Mode 2: taxonomy + year → list components (fetcher integration)."""
        params: dict[str, Any] = {"taxonomy": "us-gaap", "year": 2024}
        fetcher = SecSchemaFilesFetcher()
        result = fetcher.test(params, test_credentials)
        assert result is None


class TestDEIStructure:
    """Tests sharing the ``dei_standard_nodes`` fixture (fetched once)."""

    def test_get_structure_dei(self, dei_standard_nodes):
        """get_structure should return XBRLNodes for a parsed component."""
        nodes = dei_standard_nodes
        assert isinstance(nodes, list)
        assert len(nodes) > 0
        assert all(isinstance(n, XBRLNode) for n in nodes)
        first = nodes[0]
        assert first.element_id
        assert first.label
        assert first.level >= 0

    def test_mode3_taxonomy_component(self):
        """Mode 3: taxonomy + component → parsed structure (fetcher integration)."""
        params: dict[str, Any] = {
            "taxonomy": "dei",
            "year": 2024,
            "component": "standard",
        }
        fetcher = SecSchemaFilesFetcher()
        result = fetcher.test(params, test_credentials)
        assert result is None


class TestUSGaapStructure:
    """Tests sharing the ``us_gaap_sfp_cls_nodes`` fixture (fetched once)."""

    def test_get_structure_us_gaap_balance_sheet(self, us_gaap_sfp_cls_nodes):
        """us-gaap classified balance sheet should have recognizable elements."""
        nodes = us_gaap_sfp_cls_nodes
        assert len(nodes) > 0
        flat = _flatten_nodes(nodes)
        element_ids = {f["name"] for f in flat}
        assert "us-gaap_Assets" in element_ids or any(
            "Assets" in eid for eid in element_ids
        )

    def test_get_structure_enriched_metadata(self, us_gaap_sfp_cls_nodes):
        """Parsed structure should include enriched element metadata."""
        flat = _flatten_nodes(us_gaap_sfp_cls_nodes)
        with_type = [f for f in flat if f.get("xbrl_type")]
        assert len(with_type) > 0, "Expected some elements with xbrl_type"
        with_period = [f for f in flat if f.get("period_type")]
        assert len(with_period) > 0

    def test_mode3_us_gaap_component(self):
        """Mode 3: us-gaap + specific component → parsed structure (fetcher integration)."""
        params: dict[str, Any] = {
            "taxonomy": "us-gaap",
            "year": 2024,
            "component": "sfp-cls",
        }
        fetcher = SecSchemaFilesFetcher()
        result = fetcher.test(params, test_credentials)
        assert result is None


class TestInstanceParsing:
    """Full instance document parsing — sharing ``apple_10k_parsed`` (parsed once)."""

    def test_parse_apple_10k_instance(self, apple_10k_parsed):
        """Parse Apple's 10-K XBRL instance with full resolution."""
        contexts, units, facts = apple_10k_parsed

        # Contexts
        assert len(contexts) > 10
        period_types = {ctx["period_type"] for ctx in contexts.values()}
        assert "instant" in period_types
        assert "duration" in period_types
        for ctx_id, ctx in contexts.items():
            assert ctx.get("entity"), f"Context {ctx_id} missing entity"

        # Units
        assert len(units) >= 2
        assert any("USD" in v for v in units.values())
        assert any("shares" in v.lower() for v in units.values())

        # Facts
        total_tags = len(facts)
        total_facts = sum(len(v) for v in facts.values())
        assert total_tags > 100, f"Only {total_tags} unique tags"
        assert total_facts > 500, f"Only {total_facts} total facts"

        wrong_prefix = [
            k for k in facts if k.startswith("20240928_") or k.startswith("2024_")
        ]
        assert wrong_prefix == [], f"Wrong-prefix tags: {wrong_prefix}"

        aapl_tags = [k for k in facts if k.startswith("aapl_")]
        ecd_tags = [k for k in facts if k.startswith("ecd_")]
        assert len(aapl_tags) > 0, "No aapl_ company extension tags found"
        assert len(ecd_tags) > 0, "No ecd_ tags found"

    def test_instance_label_coverage(self, apple_10k_parsed):
        """Label resolution should achieve very high coverage."""
        _, _, facts = apple_10k_parsed

        total_tags = len(facts)
        has_label = sum(1 for tag_facts in facts.values() if tag_facts[0].get("label"))
        coverage = has_label / total_tags * 100
        assert coverage >= 95, (
            f"Label coverage only {coverage:.1f}% ({has_label}/{total_tags})"
        )

    def test_instance_presentation_metadata(self, apple_10k_parsed):
        """Facts should have presentation metadata (table, parent, order)."""
        _, _, facts = apple_10k_parsed

        with_pres = sum(
            1 for tag_facts in facts.values() if tag_facts[0].get("presentation")
        )
        assert with_pres > 0, "No facts have presentation metadata"

        for tag_facts in facts.values():
            pres = tag_facts[0].get("presentation")
            if pres:
                entry = pres[0]
                assert "table" in entry
                assert "parent" in entry
                assert "order" in entry
                break

    def test_instance_unit_resolution(self, apple_10k_parsed):
        """Units should resolve to readable strings, not raw IDs."""
        _, units, facts = apple_10k_parsed

        unit_values = set(units.values())
        assert "iso4217:USD" in unit_values
        assert "shares" in unit_values

        compound = [v for v in unit_values if "/" in v]
        assert len(compound) > 0, "No compound units found (e.g. USD/share)"

        for tag, tag_facts in facts.items():
            for f in tag_facts:
                unit = f.get("unit")
                if unit:
                    assert (
                        "iso4217:" in unit
                        or unit in ("shares", "pure")
                        or "/" in unit
                        or ":" in unit
                    ), f"Unexpected unit format for {tag}: {unit}"


class TestSchemaFilesFetcher:
    """Integration tests for the SecSchemaFilesFetcher progressive modes."""

    def test_mode1_list_all_taxonomies(self):
        """Mode 1: No params → list all taxonomy families (no HTTP)."""
        params: dict[str, Any] = {}
        fetcher = SecSchemaFilesFetcher()
        result = fetcher.test(params, test_credentials)
        assert result is None

    def test_mode1_filter_by_category(self):
        """Mode 1: Filter by category (no HTTP)."""
        params: dict[str, Any] = {"category": "investment_company"}
        fetcher = SecSchemaFilesFetcher()
        result = fetcher.test(params, test_credentials)
        assert result is None

    def test_mode2_taxonomy_only(self):
        """Mode 2: taxonomy only → auto-resolve year, list components."""
        params: dict[str, Any] = {"taxonomy": "dei"}
        fetcher = SecSchemaFilesFetcher()
        result = fetcher.test(params, test_credentials)
        assert result is None

    def test_validation_year_without_taxonomy(self):
        """Test year without taxonomy should raise validation error."""
        with pytest.raises(Exception):
            params: dict[str, Any] = {"year": 2024}
            fetcher = SecSchemaFilesFetcher()
            fetcher.test(params, test_credentials)

    def test_validation_category_with_taxonomy(self):
        """Test category + taxonomy is invalid."""
        with pytest.raises(Exception):
            params: dict[str, Any] = {
                "taxonomy": "us-gaap",
                "category": "operating_company",
            }
            fetcher = SecSchemaFilesFetcher()
            fetcher.test(params, test_credentials)


class TestUSGaapLabelsParsing:
    """Tests for label/documentation/presentation linkbase parsing.

    Raw file bytes are shared via module-scoped fixtures so each file
    is downloaded at most once.
    """

    def test_parse_label_linkbase_us_gaap(self, us_gaap_lab_bytes):
        """Should parse labels from us-gaap label linkbase."""
        p = XBRLParser()
        result = p.parse_label_linkbase(
            BytesIO(us_gaap_lab_bytes), TaxonomyStyle.FASB_STANDARD
        )
        assert isinstance(result, dict)
        assert len(result) > 1000, f"Only {len(result)} labels parsed from us-gaap"
        assert len(p.labels) > 1000
        assert any("Assets" in k for k in p.labels), "No Assets-related label found"

    def test_parse_label_linkbase_documentation(self, us_gaap_doc_bytes):
        """FASB documentation lives in a separate *-doc-{year}.xml file."""
        p = XBRLParser()
        result = p.parse_label_linkbase(
            BytesIO(us_gaap_doc_bytes), TaxonomyStyle.FASB_STANDARD
        )

        all_roles: set[str] = set()
        for v in result.values():
            all_roles.update(v.keys())
        assert "documentation" in all_roles

        assert len(result) > 10000, f"Only {len(result)} doc entries"
        assert len(p.documentation) > 10000

        assets_docs = [
            v for k, v in p.documentation.items() if k.split("_")[-1] == "Assets"
        ]
        assert len(assets_docs) > 0, "No documentation for 'Assets'"
        assert len(assets_docs[0]) > 20, "Assets documentation is too short"

    def test_ensure_labels_loads_both_labels_and_docs(self, us_gaap_labels_manager):
        """XBRLManager._ensure_labels loads lab + doc files for FASB taxonomies."""
        mgr = us_gaap_labels_manager

        assert len(mgr.parser.labels) > 1000
        assert len(mgr.parser.documentation) > 1000, (
            f"Only {len(mgr.parser.documentation)} documentation entries — "
            "doc file not loaded"
        )

        has_both = [eid for eid in mgr.parser.labels if eid in mgr.parser.documentation]
        assert len(has_both) > 100, (
            f"Only {len(has_both)} elements have both label + documentation"
        )

    def test_parse_presentation_balance_sheet(
        self, us_gaap_lab_bytes, us_gaap_pres_bytes
    ):
        """Should produce a tree structure for us-gaap classified balance sheet."""
        p = XBRLParser()
        p.parse_label_linkbase(BytesIO(us_gaap_lab_bytes), TaxonomyStyle.FASB_STANDARD)
        nodes = p.parse_presentation(
            BytesIO(us_gaap_pres_bytes), TaxonomyStyle.FASB_STANDARD
        )

        assert isinstance(nodes, list)
        assert len(nodes) > 0
        assert all(isinstance(n, XBRLNode) for n in nodes)
        assert all(n.level == 0 for n in nodes)

        flat = _flatten_nodes(nodes)
        element_ids = {f["name"] for f in flat}
        assert any("Assets" in eid for eid in element_ids)


class TestCalculationParsing:
    """Tests for calculation linkbase parsing."""

    def test_parse_calculation_us_gaap(self, us_gaap_cal_bytes):
        """Should parse calculation relationships."""
        p = XBRLParser()
        calculations = p.parse_calculation(
            BytesIO(us_gaap_cal_bytes), TaxonomyStyle.FASB_STANDARD
        )

        assert isinstance(calculations, dict)
        assert len(calculations) > 0

        for child_id, info in calculations.items():
            assert isinstance(child_id, str)
            assert isinstance(info, dict)
            assert "order" in info
            assert "weight" in info
            assert "parent_tag" in info
            assert isinstance(info["weight"], (int, float))
            assert isinstance(info["parent_tag"], str)


class TestFRCTaxonomy:
    """Offline tests for FRC taxonomy suite support (frc-core, frc-dpl)."""

    def test_frc_in_registry(self):
        """frc-core and frc-dpl should be in the TAXONOMIES registry."""
        assert "frc-core" in TAXONOMIES
        assert "frc-dpl" in TAXONOMIES
        assert "hmrc-dpl" not in TAXONOMIES

    def test_frc_configs(self):
        """FRC configs should be EXTERNAL sourced from frc.org.uk."""
        for key in ("frc-core", "frc-dpl"):
            config = TAXONOMIES[key]
            assert config.style == TaxonomyStyle.EXTERNAL
            assert config.has_label_linkbase is True
            assert "frc.org.uk" in config.base_url_template

    def test_frc_core_available_years(self, manager: XBRLManager):
        """frc-core covers every mapped suite year (no HTTP needed)."""
        years = manager.get_available_years("frc-core")
        assert years == sorted(xth._FRC_SUITE_ZIPS, reverse=True)
        assert 2014 in years
        assert 2026 in years

    def test_frc_dpl_available_years(self, manager: XBRLManager):
        """frc-dpl is only published from 2022 onward (no HTTP needed)."""
        years = manager.get_available_years("frc-dpl")
        assert min(years) == 2022
        assert 2021 not in years
        assert 2019 not in years

    def test_frc_components(self, manager: XBRLManager):
        """FRC taxonomies expose a single 'standard' component (no HTTP needed)."""
        assert manager.list_available_components("frc-core", 2024) == ["standard"]
        assert manager.list_available_components("frc-dpl", 2024) == ["standard"]


class TestFRCNetwork:
    """FRC suite HTTP tests — share module-scoped fixtures (fetched once).

    ``get_structure`` internally calls ``_ensure_labels`` and
    ``_ensure_element_properties``, so the returned manager has all label
    and property state populated for verification.
    """

    def test_frc_dpl_labels_are_english(self, frc_dpl_loaded):
        """DPL labels parse from the suite ZIP and are English, never Welsh."""
        mgr, _ = frc_dpl_loaded
        dpl_labels = {
            k: v for k, v in mgr.parser.labels.items() if k.startswith("dpl_")
        }
        assert len(dpl_labels) >= 150, (
            f"Expected >=150 DPL labels, got {len(dpl_labels)}"
        )
        assert (
            mgr.parser.labels["dpl_AdministrativeExpenses"] == "Administrative expenses"
        )
        welsh = ("pennawd", "Trosiant", "refeniw", "Incwm", "cholled")
        leaked = [
            v for v in mgr.parser.labels.values() if v and any(w in v for w in welsh)
        ]
        assert not leaked, f"Non-English labels leaked: {leaked[:3]}"

    def test_frc_dpl_element_properties(self, frc_dpl_loaded):
        """Element properties load from the DPL schema in the suite ZIP."""
        mgr, _ = frc_dpl_loaded
        props = mgr.parser.element_properties.get("dpl_AdministrativeExpenses")
        assert props is not None
        assert props.get("period_type") == "duration"

    def test_frc_dpl_structure(self, frc_dpl_loaded):
        """frc-dpl structure is the presentation tree with dpl_ and core_ items."""
        _, nodes = frc_dpl_loaded
        assert nodes
        assert all(isinstance(n, XBRLNode) for n in nodes)

        flat = _flatten_nodes(nodes)
        element_ids = {f["name"] for f in flat}
        assert any(eid.startswith("dpl_") for eid in element_ids)
        assert any(eid.startswith("core_") for eid in element_ids)

    def test_frc_dpl_core_labels_resolved(self, frc_dpl_loaded):
        """FRC core labels should be loaded for cross-taxonomy resolution."""
        _, nodes = frc_dpl_loaded
        flat = _flatten_nodes(nodes)

        core_items = [f for f in flat if f["name"].startswith("core_")]
        assert len(core_items) > 0, "No FRC core elements found"

        labeled_core = [
            f for f in core_items if f.get("label") and f["label"] != f["name"]
        ]
        assert len(labeled_core) > 0, (
            "FRC core labels not loaded — core_* elements still show element_id as label"
        )

    def test_frc_core_structure_flat_and_english(self, frc_core_loaded):
        """frc-core returns a large flat element list with English labels."""
        mgr, nodes = frc_core_loaded
        assert len(nodes) > 1000
        assert all(isinstance(n, XBRLNode) for n in nodes)
        assert mgr.parser.labels.get("core_TurnoverRevenue") == "Turnover / revenue"


# ════════════════════════════════════════════════════════════════════
# Top-level IFRS / label-url helpers
# ════════════════════════════════════════════════════════════════════


class TestIfrsDateDiscovery:
    """_discover_ifrs_dates / get_ifrs_version_dates / _resolve_ifrs_url."""

    def test_discover_merges_network_dates(self):
        """A discovered date for a new year is merged with the fallback."""
        xml = (
            "<root>"
            "<Loc>https://xbrl.ifrs.org/taxonomy/2099-02-02/full_ifrs/x.xsd</Loc>"
            "</root>"
        )
        with patch(f"{CACHE_MOD}.cached_text", return_value=xml) as mock:
            result = xth._discover_ifrs_dates()
        mock.assert_called_once()
        assert result[2099] == "2099-02-02"
        # Fallback years still present
        assert result[2024] == "2024-03-27"

    def test_discover_is_cached(self):
        """Second call returns the cached dict without re-fetching."""
        with patch(f"{CACHE_MOD}.cached_text", return_value="<root/>") as mock:
            first = xth._discover_ifrs_dates()
            second = xth._discover_ifrs_dates()
        assert first is second
        mock.assert_called_once()

    def test_discover_swallows_network_error(self):
        """A network failure falls back to the hardcoded dates."""
        with patch(f"{CACHE_MOD}.cached_text", side_effect=OSError("boom")):
            result = xth._discover_ifrs_dates()
        assert result == dict(xth._IFRS_VERSION_DATES_FALLBACK)

    def test_get_ifrs_version_dates_delegates(self):
        """get_ifrs_version_dates returns the discovery result."""
        with patch(f"{CACHE_MOD}.cached_text", side_effect=OSError("x")):
            assert xth.get_ifrs_version_dates() == dict(
                xth._IFRS_VERSION_DATES_FALLBACK
            )

    def test_resolve_ifrs_url_with_path(self):
        """A known year resolves to a date-based URL with the path appended."""
        with patch(f"{CACHE_MOD}.cached_text", side_effect=OSError("x")):
            url = xth._resolve_ifrs_url(2024, "full_ifrs/x.xsd")
        assert url == "https://xbrl.ifrs.org/taxonomy/2024-03-27/full_ifrs/x.xsd"

    def test_resolve_ifrs_url_no_path(self):
        """No path returns just the base directory URL."""
        with patch(f"{CACHE_MOD}.cached_text", side_effect=OSError("x")):
            url = xth._resolve_ifrs_url(2024)
        assert url == "https://xbrl.ifrs.org/taxonomy/2024-03-27/"

    def test_resolve_ifrs_url_unknown_year_raises(self):
        """An unknown year raises OpenBBError listing the known years."""
        with patch(f"{CACHE_MOD}.cached_text", side_effect=OSError("x")):
            with pytest.raises(OpenBBError, match="not available"):
                xth._resolve_ifrs_url(1900)


class TestLabelUrlForImport:
    """get_label_url_for_import pattern matching."""

    def test_fasb_us_gaap(self):
        out = get_label_url_for_import(
            "https://xbrl.fasb.org/us-gaap/2025/elts/us-gaap-2025.xsd"
        )
        assert out == "https://xbrl.fasb.org/us-gaap/2025/elts/us-gaap-lab-2025.xml"

    def test_sec_dei(self):
        out = get_label_url_for_import("https://xbrl.sec.gov/dei/2024/dei-2024.xsd")
        assert out == "https://xbrl.sec.gov/dei/2024/dei-2024_lab.xsd"
        assert (
            get_label_url_for_import("https://xbrl.sec.gov/dei/2020/dei-2020-01-31.xsd")
            == "https://xbrl.sec.gov/dei/2020/dei-lab-2020-01-31.xml"
        )

    @pytest.mark.parametrize(
        "taxonomy",
        ["country", "currency", "exch", "naics", "sic", "stpr"],
    )
    def test_sec_reference_taxonomies_use_entire_schema(self, taxonomy):
        url = f"https://xbrl.sec.gov/{taxonomy}/2025/{taxonomy}-2025.xsd"
        expected = f"https://xbrl.sec.gov/{taxonomy}/2025/{taxonomy}-entire-2025.xsd"
        assert get_label_url_for_import(url) == expected
        assert get_label_url_for_import(expected) == expected
        assert (
            TAXONOMIES[taxonomy].label_file_pattern == f"{taxonomy}-entire-{{year}}.xsd"
        )

    def test_sec_reference_legacy_2020_format(self):
        assert (
            get_label_url_for_import(
                "https://xbrl.sec.gov/country/2020/country-2020-01-31.xsd"
            )
            == "https://xbrl.sec.gov/country/2020/country-lab-2020-01-31.xml"
        )

    def test_sec_snj_uses_doc_schema(self):
        assert (
            get_label_url_for_import("https://xbrl.sec.gov/snj/2025/snj-2025.xsd")
            == "https://xbrl.sec.gov/snj/2025/snj-2025_doc.xsd"
        )
        assert TAXONOMIES["snj"].label_file_pattern == "snj-{year}_doc.xsd"

    def test_no_match_returns_none(self):
        assert get_label_url_for_import("https://example.com/whatever.xsd") is None


# ════════════════════════════════════════════════════════════════════
# FASBClient — directory listing & discovery
# ════════════════════════════════════════════════════════════════════

_DIR_HTML = (
    "<html><body>"
    '<a href="../">Parent</a>'
    '<a href="/absolute/skip">abs</a>'
    '<a href="https://other.com/x">ext</a>'
    '<a href="?sort=name">sort</a>'
    '<a href="us-gaap-2024.xsd">file1</a>'
    '<a href="us-gaap-lab-2024.xml">file2</a>'
    '<a href="us-gaap-doc-2024.xml">file3</a>'
    "</body></html>"
)


class TestFASBClient:
    """FASBClient list_files / find_file / fetch_file and discovery."""

    def test_list_files_filters_and_caches(self):
        client = FASBClient()
        with patch(f"{CACHE_MOD}.cached_text", return_value=_DIR_HTML) as mock:
            files = client.list_files("https://xbrl.fasb.org/us-gaap/2024/elts/")
            # second call hits the per-url cache, no extra fetch
            files2 = client.list_files("https://xbrl.fasb.org/us-gaap/2024/elts/")
        assert files == files2
        assert "us-gaap-2024.xsd" in files
        # absolute/parent/ext/sort hrefs are excluded
        assert all(not f.startswith(("/", "http", "?")) for f in files)
        assert "../" not in files
        mock.assert_called_once()

    def test_list_files_appends_trailing_slash(self):
        client = FASBClient()
        with patch(f"{CACHE_MOD}.cached_text", return_value=_DIR_HTML) as mock:
            client.list_files("https://xbrl.fasb.org/us-gaap/2024/elts")
        called_url = mock.call_args[0][0]
        assert called_url.endswith("/")

    def test_find_file_matches_all_fragments(self):
        client = FASBClient()
        with patch(f"{CACHE_MOD}.cached_text", return_value=_DIR_HTML):
            out = client.find_file(
                "https://xbrl.fasb.org/us-gaap/2024/elts/", "lab", "2024", ".xml"
            )
        assert out == "https://xbrl.fasb.org/us-gaap/2024/elts/us-gaap-lab-2024.xml"

    def test_find_file_no_match_returns_none(self):
        client = FASBClient()
        with patch(f"{CACHE_MOD}.cached_text", return_value=_DIR_HTML):
            assert client.find_file("https://x/dir/", "nonexistent") is None

    def test_find_file_swallows_fetch_error(self):
        client = FASBClient()
        with patch(f"{CACHE_MOD}.cached_text", side_effect=OSError("net")):
            assert client.find_file("https://x/dir/", "anything") is None

    def test_find_file_appends_trailing_slash(self):
        client = FASBClient()
        with patch(f"{CACHE_MOD}.cached_text", return_value=_DIR_HTML) as mock:
            client.find_file("https://xbrl.fasb.org/us-gaap/2024/elts", "lab")
        assert mock.call_args[0][0].endswith("/")

    def test_fetch_file_returns_bytesio(self):
        client = FASBClient()
        with patch(f"{CACHE_MOD}.cached_bytes", return_value=b"<x/>"):
            out = client.fetch_file("https://x/y.xsd")
        assert isinstance(out, BytesIO)
        assert out.read() == b"<x/>"

    def test_fetch_file_error_raises_openbberror(self):
        client = FASBClient()
        with patch(f"{CACHE_MOD}.cached_bytes", side_effect=OSError("down")):
            with pytest.raises(OpenBBError, match="Failed to fetch"):
                client.fetch_file("https://x/y.xsd")

    def test_fetch_url_content_delegates(self):
        client = FASBClient()
        with patch(f"{CACHE_MOD}.cached_text", return_value="hello") as mock:
            assert client._fetch_url_content("https://x/dir/") == "hello"
        # expire kwarg is forwarded
        assert mock.call_args.kwargs.get("expire")


class TestGetAvailableYears:
    """FASBClient.get_available_years across taxonomy styles."""

    def test_static_year_from_url(self):
        client = FASBClient()
        years = client.get_available_years("rocr", xth.TAXONOMIES["rocr"])
        assert years == [2015]

    def test_external_ifrs(self):
        client = FASBClient()
        with patch(f"{CACHE_MOD}.cached_text", side_effect=OSError("x")):
            years = client.get_available_years("ifrs", xth.TAXONOMIES["ifrs"])
        assert 2024 in years
        # reverse-sorted
        assert years == sorted(years, reverse=True)

    def test_external_frc_core(self):
        client = FASBClient()
        years = client.get_available_years("frc-core", xth.TAXONOMIES["frc-core"])
        assert years == sorted(xth._FRC_SUITE_ZIPS, reverse=True)

    def test_external_frc_dpl(self):
        client = FASBClient()
        years = client.get_available_years("frc-dpl", xth.TAXONOMIES["frc-dpl"])
        assert years == [y for y in years if y >= 2022]
        assert min(years) == 2022

    def test_external_other_returns_empty(self):
        """An EXTERNAL taxonomy that is neither ifrs nor frc returns []."""
        cfg = xth.TaxonomyConfig(
            base_url_template="https://example.com/{year}/",
            style=TaxonomyStyle.EXTERNAL,
            label_file_pattern="",
            presentation_pattern_regex="",
            presentation_file_template="",
        )
        client = FASBClient()
        assert client.get_available_years("mystery", cfg) == []

    def test_directory_listing_years(self):
        client = FASBClient()
        html = '<a href="2024/">x</a><a href="2023/">y</a><a href="elts/">z</a>'
        with patch(f"{CACHE_MOD}.cached_text", return_value=html):
            years = client.get_available_years("us-gaap", xth.TAXONOMIES["us-gaap"])
        assert years == [2024, 2023]

    def test_directory_listing_error_raises(self):
        client = FASBClient()
        with patch(f"{CACHE_MOD}.cached_text", side_effect=OSError("net")):
            with pytest.raises(OpenBBError, match="Failed to fetch available years"):
                client.get_available_years("us-gaap", xth.TAXONOMIES["us-gaap"])


class TestGetComponentsForYear:
    """FASBClient.get_components_for_year across taxonomy styles."""

    def test_static_returns_standard(self):
        client = FASBClient()
        assert client.get_components_for_year(2015, xth.TAXONOMIES["rocr"]) == [
            "standard"
        ]

    def test_ifrs_parses_entry_point(self):
        client = FASBClient()
        ep = (
            '<schema><import schemaLocation="full_ifrs/linkbases/ias_1/rol_ias_1.xsd"/>'
            '<import schemaLocation="full_ifrs/linkbases/ifrs_7/rol_ifrs_7.xsd"/>'
            "</schema>"
        )
        with patch(f"{CACHE_MOD}.cached_text", side_effect=[ep]):
            # date lookup uses the fallback (also reads cached_text on first call,
            # so prime the cache directly to keep a single mocked response)
            xth._ifrs_version_dates_cache = dict(xth._IFRS_VERSION_DATES_FALLBACK)
            comps = client.get_components_for_year(2024, xth.TAXONOMIES["ifrs"])
        assert comps == ["ias_1", "ifrs_7"]

    def test_ifrs_no_standards_falls_back(self):
        client = FASBClient()
        xth._ifrs_version_dates_cache = dict(xth._IFRS_VERSION_DATES_FALLBACK)
        with patch(f"{CACHE_MOD}.cached_text", return_value="<schema/>"):
            comps = client.get_components_for_year(2024, xth.TAXONOMIES["ifrs"])
        assert comps == ["standard"]

    def test_ifrs_fetch_error_raises(self):
        client = FASBClient()
        xth._ifrs_version_dates_cache = dict(xth._IFRS_VERSION_DATES_FALLBACK)
        with patch(f"{CACHE_MOD}.cached_text", side_effect=OSError("net")):
            with pytest.raises(OpenBBError, match="Failed to fetch IFRS components"):
                client.get_components_for_year(2024, xth.TAXONOMIES["ifrs"])

    def test_external_non_ifrs_returns_standard(self):
        client = FASBClient()
        assert client.get_components_for_year(2024, xth.TAXONOMIES["frc-dpl"]) == [
            "standard"
        ]

    def test_fasb_standard_extracts_components(self):
        client = FASBClient()
        html = (
            '<a href="us-gaap-stm-sfp-cls-pre-2024.xml">a</a>'
            '<a href="us-gaap-stm-soi-pre-2024.xml">b</a>'
            '<a href="us-gaap-stm-sfp-cls-cal-2024.xml">c</a>'  # not -pre-, ignored
        )
        with patch(f"{CACHE_MOD}.cached_text", return_value=html):
            comps = client.get_components_for_year(2024, xth.TAXONOMIES["us-gaap"])
        assert comps == ["sfp-cls", "soi"]

    def test_fasb_standard_error_raises(self):
        client = FASBClient()
        with patch(f"{CACHE_MOD}.cached_text", side_effect=OSError("net")):
            with pytest.raises(OpenBBError, match="Failed to fetch components"):
                client.get_components_for_year(2024, xth.TAXONOMIES["us-gaap"])

    def test_sec_embedded_regex_match(self):
        client = FASBClient()
        # dei regex: (dei)-{year}_pre.xsd
        html = '<a href="dei-2024_pre.xsd">x</a><a href="dei-2024.xsd">y</a>'
        with patch(f"{CACHE_MOD}.cached_text", return_value=html):
            comps = client.get_components_for_year(2024, xth.TAXONOMIES["dei"])
        assert comps == ["dei"]

    def test_sec_embedded_fallback_standard(self):
        """No regex match but a file mentions the year -> single 'standard'."""
        client = FASBClient()
        html = '<a href="dei-2024.xsd">y</a>'  # no _pre.xsd, regex misses
        with patch(f"{CACHE_MOD}.cached_text", return_value=html):
            comps = client.get_components_for_year(2024, xth.TAXONOMIES["dei"])
        assert comps == ["standard"]

    def test_sec_embedded_empty_listing(self):
        client = FASBClient()
        with patch(f"{CACHE_MOD}.cached_text", return_value="<html></html>"):
            comps = client.get_components_for_year(2024, xth.TAXONOMIES["dei"])
        assert comps == []

    def test_sec_embedded_error_returns_empty(self):
        client = FASBClient()
        with patch(f"{CACHE_MOD}.cached_text", side_effect=OSError("net")):
            assert client.get_components_for_year(2024, xth.TAXONOMIES["dei"]) == []


# ════════════════════════════════════════════════════════════════════
# XBRLParser — parse_schema
# ════════════════════════════════════════════════════════════════════


class TestParseSchema:
    """XBRLParser.parse_schema element/role/import/linkbase extraction."""

    def test_imports_elements_roles_and_linkbase(self, parser: XBRLParser):
        xml = (
            '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"'
            ' xmlns:xbrli="http://www.xbrl.org/2003/instance"'
            ' xmlns:link="http://www.xbrl.org/2003/linkbase"'
            ' targetNamespace="http://example.com/2024">'
            '<xs:import namespace="http://fasb.org/us-gaap/2024"'
            ' schemaLocation="https://xbrl.fasb.org/us-gaap/2024/elts/us-gaap-2024.xsd"/>'
            '<xs:import namespace="" schemaLocation=""/>'  # skipped (empty)
            '<xs:element name="Foo" id="ex_Foo" type="xbrli:monetaryItemType"'
            ' substitutionGroup="xbrli:item" xbrli:periodType="duration"'
            ' xbrli:balance="credit" abstract="true"/>'
            '<xs:element name="NoId" type="xbrli:stringItemType"/>'  # no id -> skipped
            "<xs:annotation><xs:appinfo>"
            '<link:roleType id="role-soi">'
            "<link:definition>104000 - Statement - Income Statement</link:definition>"
            "</link:roleType>"
            '<link:roleType id="role-short">'
            "<link:definition>NoDashes</link:definition>"  # <3 parts -> skipped
            "</link:roleType>"
            "<link:linkbase>embedded</link:linkbase>"
            "</xs:appinfo></xs:annotation>"
            "</xs:schema>"
        )
        elements, roles, embedded, imports = parser.parse_schema(_b(xml))
        # "xsd" and "xs" resolve to the same XMLSchema namespace; each import is
        # now collected exactly once (the duplicate-prefix iteration that used to
        # double every import/role was fixed). The empty import is skipped.
        assert imports == [
            {
                "namespace": "http://fasb.org/us-gaap/2024",
                "schemaLocation": "https://xbrl.fasb.org/us-gaap/2024/elts/us-gaap-2024.xsd",
            }
        ]
        assert "ex_Foo" in elements
        assert elements["ex_Foo"]["xbrl_type"] == "monetaryItemType"
        assert elements["ex_Foo"]["period_type"] == "duration"
        assert elements["ex_Foo"]["balance_type"] == "credit"
        assert elements["ex_Foo"]["abstract"] is True
        assert elements["ex_Foo"]["substitution_group"] == "item"
        assert "NoId" not in [e for e in elements]
        names = [r["name"] for r in roles]
        assert names == ["role-soi"]  # collected once; role-short (<3 parts) skipped
        assert "role-short" not in names
        soi = next(r for r in roles if r["name"] == "role-soi")
        assert soi["short_name"] == "Income Statement"
        assert soi["document_number"] == "104000"
        assert soi["group"] == "statement"
        assert embedded is not None

    def test_role_with_four_parts_sets_subgroup(self, parser: XBRLParser):
        xml = (
            '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"'
            ' xmlns:link="http://www.xbrl.org/2003/linkbase">'
            "<xs:annotation><xs:appinfo>"
            '<link:roleType id="r1">'
            "<link:definition>100 - Disclosure - Sub - Name Here</link:definition>"
            "</link:roleType>"
            "</xs:appinfo></xs:annotation></xs:schema>"
        )
        _, roles, _, _ = parser.parse_schema(_b(xml))
        assert roles[0]["sub_group"] == "Sub"
        assert roles[0]["short_name"] == "Name Here"

    def test_malformed_xml_raises_openbberror(self, parser: XBRLParser):
        with pytest.raises(OpenBBError, match="Failed to parse schema"):
            parser.parse_schema(_b("<not valid xml"))


# ════════════════════════════════════════════════════════════════════
# XBRLParser — parse_schema_elements
# ════════════════════════════════════════════════════════════════════


class TestParseSchemaElements:
    """parse_schema_elements flat-element extraction and edge cases."""

    def test_skips_unnamed_uses_props_and_labels(self, parser: XBRLParser):
        parser.labels = {"ex_Asset": "An Asset"}
        parser.documentation = {"ex_Asset": "Some docs."}
        parser.element_properties = {
            "ex_Asset": {
                "xbrl_type": "monetaryItemType",
                "period_type": "instant",
                "balance_type": "debit",
                "abstract": False,
                "substitution_group": "item",
                "nillable": True,
            }
        }
        xml = (
            '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
            '<xs:element name="Asset" id="ex_Asset"/>'
            '<xs:element id="ex_NoName"/>'  # no name -> skipped
            "</xs:schema>"
        )
        nodes = parser.parse_schema_elements(_b(xml))
        assert len(nodes) == 1
        n = nodes[0]
        assert n.element_id == "ex_Asset"
        assert n.label == "An Asset"
        assert n.documentation == "Some docs."
        assert n.xbrl_type == "monetaryItemType"
        assert n.nillable is True

    def test_falls_back_to_element_attributes(self, parser: XBRLParser):
        xml = (
            '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"'
            ' xmlns:xbrli="http://www.xbrl.org/2003/instance">'
            '<xs:element name="Cash" id="ex_Cash" type="xbrli:monetaryItemType"'
            ' substitutionGroup="xbrli:item" xbrli:periodType="instant"'
            ' nillable="true"/>'
            "</xs:schema>"
        )
        nodes = parser.parse_schema_elements(_b(xml))
        n = nodes[0]
        assert n.label == "Cash"  # falls back to name
        assert n.xbrl_type == "monetaryItemType"
        assert n.period_type == "instant"
        assert n.substitution_group == "item"
        assert n.nillable is True

    def test_malformed_raises(self, parser: XBRLParser):
        with pytest.raises(OpenBBError, match="Failed to parse schema elements"):
            parser.parse_schema_elements(_b("<bad"))


# ════════════════════════════════════════════════════════════════════
# XBRLParser — parse_label_linkbase
# ════════════════════════════════════════════════════════════════════

_LINK_HDR = (
    'xmlns:link="http://www.xbrl.org/2003/linkbase"'
    ' xmlns:xlink="http://www.w3.org/1999/xlink"'
)


class TestParseLabelLinkbase:
    """parse_label_linkbase standard, documentation, embedded, error paths."""

    def test_skips_non_english_labels(self, parser: XBRLParser):
        """Non-English (e.g. Welsh) label resources are ignored; English wins."""
        biling = (
            f"<link:linkbase {_LINK_HDR}>"
            '<link:loc xlink:href="x.xsd#ex_Item" xlink:label="l"/>'
            '<link:label xlink:label="en" xml:lang="en"'
            ' xlink:role="http://www.xbrl.org/2003/role/label">English</link:label>'
            '<link:label xlink:label="cy" xml:lang="cy"'
            ' xlink:role="http://www.xbrl.org/2003/role/label">Cymraeg</link:label>'
            '<link:labelArc xlink:from="l" xlink:to="en"/>'
            '<link:labelArc xlink:from="l" xlink:to="cy"/>'
            "</link:linkbase>"
        )
        parser.parse_label_linkbase(_b(biling), TaxonomyStyle.SEC_EMBEDDED)
        assert parser.labels["ex_Item"] == "English"

    def test_standard_label_and_documentation(self, parser: XBRLParser):
        xml = (
            f"<link:linkbase {_LINK_HDR}>"
            '<link:labelLink xlink:role="x">'
            '<link:loc xlink:href="us-gaap.xsd#us-gaap_Assets" xlink:label="a_loc"/>'
            '<link:label xlink:label="a_lab"'
            ' xlink:role="http://www.xbrl.org/2003/role/label">Assets</link:label>'
            '<link:label xlink:label="a_lab"'
            ' xlink:role="http://www.xbrl.org/2003/role/documentation">The assets.</link:label>'
            '<link:labelArc xlink:from="a_loc" xlink:to="a_lab"/>'
            "</link:labelLink></link:linkbase>"
        )
        out = parser.parse_label_linkbase(_b(xml), TaxonomyStyle.FASB_STANDARD)
        assert out["us-gaap_Assets"]["label"] == "Assets"
        assert parser.labels["us-gaap_Assets"] == "Assets"
        assert parser.documentation["us-gaap_Assets"] == "The assets."

    def test_non_label_role_used_as_fallback(self, parser: XBRLParser):
        """When no 'label' role exists, the first available value is used."""
        xml = (
            f"<link:linkbase {_LINK_HDR}>"
            '<link:loc xlink:href="x.xsd#ex_Term" xlink:label="t_loc"/>'
            '<link:label xlink:label="t_lab"'
            ' xlink:role="http://www.xbrl.org/2003/role/terseLabel">Terse</link:label>'
            '<link:labelArc xlink:from="t_loc" xlink:to="t_lab"/>'
            "</link:linkbase>"
        )
        parser.parse_label_linkbase(_b(xml), TaxonomyStyle.FASB_STANDARD)
        assert parser.labels["ex_Term"] == "Terse"

    def test_role_missing_defaults_to_label(self, parser: XBRLParser):
        """A <label> with no role attribute is stored under 'label'."""
        xml = (
            f"<link:linkbase {_LINK_HDR}>"
            '<link:loc xlink:href="x.xsd#ex_E" xlink:label="l"/>'
            '<link:label xlink:label="r">NoRole</link:label>'
            '<link:labelArc xlink:from="l" xlink:to="r"/>'
            "</link:linkbase>"
        )
        parser.parse_label_linkbase(_b(xml), TaxonomyStyle.FASB_STANDARD)
        assert parser.labels["ex_E"] == "NoRole"

    def test_embedded_in_schema(self, parser: XBRLParser):
        xml = (
            '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
            f" {_LINK_HDR}>"
            "<xsd:annotation><xsd:appinfo>"
            "<link:linkbase>"
            '<link:loc xlink:href="dei.xsd#dei_X" xlink:label="l"/>'
            '<link:label xlink:label="r"'
            ' xlink:role="http://www.xbrl.org/2003/role/label">XVal</link:label>'
            '<link:labelArc xlink:from="l" xlink:to="r"/>'
            "</link:linkbase>"
            "</xsd:appinfo></xsd:annotation></xsd:schema>"
        )
        parser.parse_label_linkbase(_b(xml), TaxonomyStyle.SEC_EMBEDDED)
        assert parser.labels["dei_X"] == "XVal"

    def test_embedded_missing_linkbase_warns_and_returns_empty(
        self, parser: XBRLParser
    ):
        xml = (
            '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
            f" {_LINK_HDR}><xsd:element name='X'/></xsd:schema>"
        )
        with pytest.warns(Warning, match="No embedded linkbase"):
            out = parser.parse_label_linkbase(_b(xml), TaxonomyStyle.SEC_EMBEDDED)
        assert out == {}

    def test_malformed_raises(self, parser: XBRLParser):
        with pytest.raises(OpenBBError, match="Failed to parse label linkbase"):
            parser.parse_label_linkbase(_b("<bad"), TaxonomyStyle.FASB_STANDARD)


# ════════════════════════════════════════════════════════════════════
# XBRLParser — parse_reference_linkbase
# ════════════════════════════════════════════════════════════════════


class TestParseReferenceLinkbase:
    """parse_reference_linkbase citation extraction and edge cases."""

    def test_formats_citations(self, parser: XBRLParser):
        xml = (
            '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
            f" {_LINK_HDR}"
            ' xmlns:ref="http://www.xbrl.org/2006/ref">'
            "<link:referenceLink>"
            '<link:loc xlink:href="ecd.xsd#ecd_Item" xlink:label="i_loc"/>'
            '<link:reference xlink:label="i_ref">'
            "<ref:Name>Regulation S-K</ref:Name>"
            "<ref:Section>229</ref:Section>"
            "<ref:Subsection>402</ref:Subsection>"
            "<ref:Paragraph>v</ref:Paragraph>"
            "</link:reference>"
            '<link:referenceArc xlink:from="i_loc" xlink:to="i_ref"/>'
            "</link:referenceLink></xsd:schema>"
        )
        count = parser.parse_reference_linkbase(_b(xml))
        assert count == 1
        doc = parser.documentation["ecd_Item"]
        assert doc.startswith("Ref: ")
        assert "Regulation S-K" in doc
        assert "§229" in doc
        assert "(402)(v)" in doc

    def test_skips_existing_documentation(self, parser: XBRLParser):
        parser.documentation = {"ecd_Item": "Already here"}
        xml = (
            '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
            f" {_LINK_HDR}"
            ' xmlns:ref="http://www.xbrl.org/2006/ref">'
            "<link:referenceLink>"
            '<link:loc xlink:href="ecd.xsd#ecd_Item" xlink:label="i_loc"/>'
            '<link:reference xlink:label="i_ref"><ref:Name>X</ref:Name></link:reference>'
            '<link:referenceArc xlink:from="i_loc" xlink:to="i_ref"/>'
            "</link:referenceLink></xsd:schema>"
        )
        count = parser.parse_reference_linkbase(_b(xml))
        assert count == 0
        assert parser.documentation["ecd_Item"] == "Already here"

    def test_reference_without_name_is_skipped(self, parser: XBRLParser):
        xml = (
            '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
            f" {_LINK_HDR}"
            ' xmlns:ref="http://www.xbrl.org/2006/ref">'
            "<link:referenceLink>"
            '<link:loc xlink:href="ecd.xsd#ecd_Item" xlink:label="i_loc"/>'
            '<link:reference xlink:label="i_ref">'
            "<ref:Section>229</ref:Section>"  # no Name
            "</link:reference>"
            '<link:referenceArc xlink:from="i_loc" xlink:to="i_ref"/>'
            "</link:referenceLink></xsd:schema>"
        )
        assert parser.parse_reference_linkbase(_b(xml)) == 0
        assert "ecd_Item" not in parser.documentation

    def test_no_reference_links_returns_zero(self, parser: XBRLParser):
        xml = '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"/>'
        assert parser.parse_reference_linkbase(_b(xml)) == 0

    def test_malformed_returns_zero(self, parser: XBRLParser):
        assert parser.parse_reference_linkbase(_b("<bad")) == 0


# ════════════════════════════════════════════════════════════════════
# XBRLParser — load_schema_element_properties
# ════════════════════════════════════════════════════════════════════


class TestLoadSchemaElementProperties:
    """load_schema_element_properties extraction and merge behaviour."""

    def test_loads_properties(self, parser: XBRLParser):
        xml = (
            '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"'
            ' xmlns:xbrli="http://www.xbrl.org/2003/instance">'
            '<xs:element name="A" id="ex_A" type="xbrli:monetaryItemType"'
            ' substitutionGroup="xbrli:item" xbrli:periodType="instant"'
            ' xbrli:balance="debit" abstract="false" nillable="true"/>'
            '<xs:element name="NoId"/>'  # skipped
            "</xs:schema>"
        )
        count = parser.load_schema_element_properties(_b(xml))
        assert count == 1
        props = parser.element_properties["ex_A"]
        assert props["xbrl_type"] == "monetaryItemType"
        assert props["period_type"] == "instant"
        assert props["balance_type"] == "debit"
        assert props["nillable"] is True

    def test_existing_property_not_overwritten(self, parser: XBRLParser):
        parser.element_properties = {"ex_A": {"xbrl_type": "old"}}
        xml = (
            '<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">'
            '<xs:element name="A" id="ex_A" type="x:newType"/>'
            "</xs:schema>"
        )
        count = parser.load_schema_element_properties(_b(xml))
        assert count == 0
        assert parser.element_properties["ex_A"]["xbrl_type"] == "old"

    def test_malformed_returns_zero(self, parser: XBRLParser):
        assert parser.load_schema_element_properties(_b("<bad")) == 0


# ════════════════════════════════════════════════════════════════════
# XBRLParser — parse_presentation
# ════════════════════════════════════════════════════════════════════


class TestParsePresentation:
    """parse_presentation tree building, embedded, error paths."""

    def test_builds_tree_with_labels_and_props(self, parser: XBRLParser):
        parser.labels = {"ex_Parent": "Parent Label", "ex_Child": "Child Label"}
        parser.element_properties = {
            "ex_Child": {
                "xbrl_type": "monetaryItemType",
                "period_type": "instant",
                "balance_type": "debit",
                "abstract": False,
                "substitution_group": "item",
                "nillable": False,
            }
        }
        xml = (
            f"<link:linkbase {_LINK_HDR}>"
            "<link:presentationLink>"
            '<link:loc xlink:href="x.xsd#ex_Parent" xlink:label="p"/>'
            '<link:loc xlink:href="x.xsd#ex_Child" xlink:label="c"/>'
            '<link:presentationArc xlink:from="p" xlink:to="c" order="2.0"'
            ' preferredLabel="http://www.xbrl.org/2003/role/terseLabel"/>'
            "</link:presentationLink></link:linkbase>"
        )
        nodes = parser.parse_presentation(_b(xml), TaxonomyStyle.FASB_STANDARD)
        assert len(nodes) == 1
        root = nodes[0]
        assert root.element_id == "ex_Parent"
        assert root.label == "Parent Label"
        assert root.level == 0
        assert len(root.children) == 1
        child = root.children[0]
        assert child.element_id == "ex_Child"
        assert child.label == "Child Label"
        assert child.level == 1
        assert child.order == 2.0
        assert child.xbrl_type == "monetaryItemType"
        assert child.preferred_label == "http://www.xbrl.org/2003/role/terseLabel"

    def test_embedded_missing_linkbase_warns(self, parser: XBRLParser):
        xml = (
            '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
            f" {_LINK_HDR}><xsd:element name='X'/></xsd:schema>"
        )
        with pytest.warns(Warning, match="No embedded linkbase"):
            out = parser.parse_presentation(_b(xml), TaxonomyStyle.SEC_EMBEDDED)
        assert out == []

    def test_malformed_raises(self, parser: XBRLParser):
        with pytest.raises(OpenBBError, match="Failed to parse presentation"):
            parser.parse_presentation(_b("<bad"), TaxonomyStyle.FASB_STANDARD)

    def test_non_numeric_order_raises(self, parser: XBRLParser):
        xml = (
            f"<link:linkbase {_LINK_HDR}>"
            "<link:presentationLink>"
            '<link:loc xlink:href="x.xsd#ex_Parent" xlink:label="p"/>'
            '<link:loc xlink:href="x.xsd#ex_First" xlink:label="c1"/>'
            '<link:loc xlink:href="x.xsd#ex_Second" xlink:label="c2"/>'
            '<link:presentationArc xlink:from="p" xlink:to="c1" order="not-a-number"/>'
            '<link:presentationArc xlink:from="p" xlink:to="c2" order="1.0"/>'
            "</link:presentationLink></link:linkbase>"
        )
        with pytest.raises(OpenBBError, match="Failed to parse presentation linkbase"):
            parser.parse_presentation(_b(xml), TaxonomyStyle.FASB_STANDARD)

    def test_order_key_fallback_for_non_numeric_order_value(
        self, parser: XBRLParser, monkeypatch
    ):
        import builtins

        real_float = builtins.float

        class FakeFloat:
            def __new__(cls, value):
                if value == "1.0":
                    return "bad-order"
                if value == "inf":
                    return real_float("inf")
                return real_float(value)

        monkeypatch.setattr(xth, "float", FakeFloat, raising=False)

        xml = (
            f"<link:linkbase {_LINK_HDR}>"
            "<link:presentationLink>"
            '<link:loc xlink:href="x.xsd#ex_Parent" xlink:label="p"/>'
            '<link:loc xlink:href="x.xsd#ex_First" xlink:label="c1"/>'
            '<link:loc xlink:href="x.xsd#ex_Second" xlink:label="c2"/>'
            '<link:presentationArc xlink:from="p" xlink:to="c1" order="1.0"/>'
            '<link:presentationArc xlink:from="p" xlink:to="c2" order="2.0"/>'
            "</link:presentationLink></link:linkbase>"
        )

        nodes = parser.parse_presentation(_b(xml), TaxonomyStyle.FASB_STANDARD)
        assert [child.element_id for child in nodes[0].children] == [
            "ex_First",
            "ex_Second",
        ]


# ════════════════════════════════════════════════════════════════════
# XBRLParser — parse_calculation
# ════════════════════════════════════════════════════════════════════


class TestParseCalculation:
    """parse_calculation relationship extraction and edge cases."""

    def test_extracts_calc_arcs(self, parser: XBRLParser):
        xml = (
            f"<link:linkbase {_LINK_HDR}>"
            "<link:calculationLink>"
            '<link:loc xlink:href="x.xsd#ex_Total" xlink:label="t"/>'
            '<link:loc xlink:href="x.xsd#ex_Part" xlink:label="p"/>'
            '<link:calculationArc xlink:from="t" xlink:to="p"'
            ' order="1.0" weight="-1"/>'
            "</link:calculationLink></link:linkbase>"
        )
        calc = parser.parse_calculation(_b(xml), TaxonomyStyle.FASB_STANDARD)
        assert calc["ex_Part"]["weight"] == -1.0
        assert calc["ex_Part"]["parent_tag"] == "ex_Total"
        assert calc["ex_Part"]["order"] == 1.0

    def test_embedded_missing_linkbase_warns(self, parser: XBRLParser):
        xml = (
            '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
            f" {_LINK_HDR}><xsd:element name='X'/></xsd:schema>"
        )
        with pytest.warns(Warning, match="No embedded linkbase"):
            out = parser.parse_calculation(_b(xml), TaxonomyStyle.SEC_EMBEDDED)
        assert out == {}

    def test_malformed_raises(self, parser: XBRLParser):
        with pytest.raises(OpenBBError, match="Failed to parse calculation"):
            parser.parse_calculation(_b("<bad"), TaxonomyStyle.FASB_STANDARD)


# ════════════════════════════════════════════════════════════════════
# XBRLParser — static resolvers & _parse_units edge cases
# ════════════════════════════════════════════════════════════════════


class TestResolversAndUnits:
    """_resolve_ns_prefix heuristic tail, _resolve_measure, _parse_units."""

    def test_resolve_ns_prefix_semantic_segment(self):
        """A non-date trailing segment is returned as the prefix."""
        assert XBRLParser._resolve_ns_prefix("http://example.com/foo", {}) == "foo"

    def test_resolve_ns_prefix_only_dates_returns_last(self):
        """When every segment is date-like, the final segment is returned (line 1900)."""
        # segments: '2024-01-01', '2025-02-02' all match the date pattern,
        # so the loop never returns early and falls through to parts[-1].
        assert (
            XBRLParser._resolve_ns_prefix("2024-01-01/2025-02-02", {}) == "2025-02-02"
        )

    def test_resolve_ns_prefix_compact_date(self):
        """Compact YYYYMMDD trailing segments are skipped."""
        assert (
            XBRLParser._resolve_ns_prefix("http://www.apple.com/20240928", {})
            == "www.apple.com"
        )

    def test_resolve_measure_strip_and_custom(self):
        assert XBRLParser._resolve_measure("  iso4217:JPY  ") == "iso4217:JPY"
        assert XBRLParser._resolve_measure("foo:Bar") == "foo:Bar"

    def test_parse_units_skips_missing_id_and_unknown(self, parser: XBRLParser):
        xml = (
            '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">'
            "<xbrli:unit><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>"
            '<xbrli:unit id="weird"><xbrli:somethingElse/></xbrli:unit>'
            "</xbrli:xbrl>"
        )
        root = parser._get_xml_root(_b(xml))
        units = parser._parse_units(root)
        # missing-id unit skipped, unknown-structure unit falls back to its id
        assert units == {"weird": "weird"}

    def test_parse_units_compound_missing_measures(self, parser: XBRLParser):
        """A divide unit with empty numerator/denominator yields '?' placeholders."""
        xml = (
            '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">'
            '<xbrli:unit id="empty"><xbrli:divide>'
            "<xbrli:unitNumerator/><xbrli:unitDenominator/>"
            "</xbrli:divide></xbrli:unit>"
            "</xbrli:xbrl>"
        )
        root = parser._get_xml_root(_b(xml))
        units = parser._parse_units(root)
        assert units["empty"] == "? / ?"


# ════════════════════════════════════════════════════════════════════
# XBRLParser — parse_instance extra branches
# ════════════════════════════════════════════════════════════════════


class TestParseInstanceExtra:
    """parse_instance forever/scenario/typed-dimension/no-base branches."""

    def test_forever_period_and_scenario_typed_dim(self, parser: XBRLParser):
        xml = (
            '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"'
            ' xmlns:xbrldi="http://xbrl.org/2006/xbrldi"'
            ' xmlns:us-gaap="http://fasb.org/us-gaap/2024">'
            '<xbrli:context id="cf">'
            '<xbrli:entity><xbrli:identifier scheme="s">9</xbrli:identifier>'
            "<xbrli:segment>"
            '<xbrldi:typedMember dimension="us-gaap:RangeAxis">'
            "<us-gaap:Value>hello</us-gaap:Value>"
            "</xbrldi:typedMember>"
            "</xbrli:segment></xbrli:entity>"
            "<xbrli:period><xbrli:forever/></xbrli:period>"
            "</xbrli:context>"
            "<xbrli:scenario/>"  # standalone, ignored
            '<us-gaap:Flag contextRef="cf">Y</us-gaap:Flag>'
            "</xbrli:xbrl>"
        )
        contexts, _, facts = parser.parse_instance(_b(xml))
        ctx = contexts["cf"]
        assert ctx["period_type"] == "forever"
        assert ctx["start"] is None and ctx["end"] is None
        assert "dimensions" in ctx
        # typedMember resolves to "<childtag>:<text>"
        assert ctx["dimensions"]["us-gaap:RangeAxis"] == "Value:hello"
        assert facts["us-gaap_Flag"][0]["period_type"] == "forever"

    def test_typed_member_no_child_text(self, parser: XBRLParser):
        xml = (
            '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"'
            ' xmlns:xbrldi="http://xbrl.org/2006/xbrldi"'
            ' xmlns:us-gaap="http://fasb.org/us-gaap/2024">'
            '<xbrli:context id="ct">'
            '<xbrli:entity><xbrli:identifier scheme="s">9</xbrli:identifier>'
            "</xbrli:entity>"
            "<xbrli:period><xbrli:instant>2024-01-01</xbrli:instant></xbrli:period>"
            "<xbrli:scenario>"
            '<xbrldi:typedMember dimension="us-gaap:Ax">'
            "<us-gaap:Empty/>"
            "</xbrldi:typedMember>"
            "</xbrli:scenario>"
            "</xbrli:context>"
            '<us-gaap:V contextRef="ct">1</us-gaap:V>'
            "</xbrli:xbrl>"
        )
        contexts, _, _ = parser.parse_instance(_b(xml))
        # child has no text -> stored as the bare child tag
        assert contexts["ct"]["dimensions"]["us-gaap:Ax"] == "Empty"

    def test_context_without_id_skipped(self, parser: XBRLParser):
        xml = (
            '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">'
            "<xbrli:context><xbrli:period>"
            "<xbrli:instant>2024-01-01</xbrli:instant>"
            "</xbrli:period></xbrli:context>"
            "</xbrli:xbrl>"
        )
        contexts, _, _ = parser.parse_instance(_b(xml))
        assert contexts == {}

    def test_fact_no_namespace_tag(self, parser: XBRLParser):
        """A fact whose tag has no namespace uses colon->underscore replacement."""
        xml = (
            '<xbrl xmlns="http://www.xbrl.org/2003/instance">'
            '<context id="c"><entity><identifier scheme="s">1</identifier></entity>'
            "<period><instant>2024-01-01</instant></period></context>"
            "</xbrl>"
        )
        # facts come from elements with contextRef; build one with no ns via default
        contexts, _, facts = parser.parse_instance(_b(xml))
        assert "c" in contexts

    def test_fact_with_no_namespace_uses_colon_replace(self, parser: XBRLParser):
        """A fact element in no namespace hits the ``tag.replace(':','_')`` branch."""
        # Root + context are in the xbrli namespace (so the context is found),
        # while the fact element is forced into *no* namespace via xmlns="".
        xml = (
            '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">'
            '<xbrli:context id="c"><xbrli:entity>'
            "<xbrli:identifier>1</xbrli:identifier></xbrli:entity>"
            "<xbrli:period><xbrli:instant>2024-01-01</xbrli:instant>"
            "</xbrli:period></xbrli:context>"
            '<MyFact xmlns="" contextRef="c">42</MyFact>'
            "</xbrli:xbrl>"
        )
        _contexts, _units, facts = parser.parse_instance(_b(xml))
        assert "MyFact" in facts
        assert facts["MyFact"][0]["value"] == "42"

    def test_malformed_instance_raises(self, parser: XBRLParser):
        with pytest.raises(OpenBBError, match="Failed to parse instance document"):
            parser.parse_instance(_b("<bad"))


# ════════════════════════════════════════════════════════════════════
# XBRLParser — _parse_filing_labels (via parse_instance base_url)
# ════════════════════════════════════════════════════════════════════

_BASE = "https://www.sec.gov/Archives/edgar/data/1/000/"

# Instance doc that references a company schema via schemaRef.
_INSTANCE = (
    '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"'
    ' xmlns:link="http://www.xbrl.org/2003/linkbase"'
    ' xmlns:xlink="http://www.w3.org/1999/xlink"'
    ' xmlns:us-gaap="http://fasb.org/us-gaap/2024"'
    ' xmlns:aapl="http://www.apple.com/20240928">'
    '<link:schemaRef xlink:href="aapl-20240928.xsd"/>'
    '<xbrli:context id="c1">'
    '<xbrli:entity><xbrli:identifier scheme="s">1</xbrli:identifier>'
    "<xbrli:segment>"
    '<xbrldi:explicitMember xmlns:xbrldi="http://xbrl.org/2006/xbrldi"'
    ' dimension="us-gaap:Axis">aapl:Member</xbrldi:explicitMember>'
    "</xbrli:segment></xbrli:entity>"
    "<xbrli:period><xbrli:instant>2024-09-28</xbrli:instant></xbrli:period>"
    "</xbrli:context>"
    '<xbrli:unit id="usd"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit>'
    '<us-gaap:Assets contextRef="c1" unitRef="usd" decimals="-6">100</us-gaap:Assets>'
    "</xbrli:xbrl>"
)

# Company schema with label + presentation linkbaseRefs (relative hrefs).
_COMPANY_SCHEMA = (
    '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
    ' xmlns:link="http://www.xbrl.org/2003/linkbase"'
    ' xmlns:xlink="http://www.w3.org/1999/xlink">'
    "<xsd:annotation><xsd:appinfo>"
    '<link:linkbaseRef xlink:role="http://www.xbrl.org/2003/role/labelLinkbaseRef"'
    ' xlink:href="aapl-20240928_lab.xml"/>'
    "<link:linkbaseRef"
    ' xlink:role="http://www.xbrl.org/2003/role/presentationLinkbaseRef"'
    ' xlink:href="aapl-20240928_pre.xml"/>'
    '<link:linkbaseRef xlink:href=""/>'  # no href -> skipped
    "</xsd:appinfo></xsd:annotation></xsd:schema>"
)

_LAB_LINKBASE = (
    f"<link:linkbase {_LINK_HDR}>"
    '<link:loc xlink:href="x.xsd#us-gaap_Assets" xlink:label="a_loc"/>'
    '<link:loc xlink:href="x.xsd#aapl_Member" xlink:label="m_loc"/>'
    '<link:label xlink:label="a_lab"'
    ' xlink:role="http://www.xbrl.org/2003/role/label">Total Assets</link:label>'
    '<link:label xlink:label="a_lab"'
    ' xlink:role="http://www.xbrl.org/2003/role/documentation">Docs.</link:label>'
    '<link:label xlink:label="m_lab"'
    ' xlink:role="http://www.xbrl.org/2003/role/label">The Member</link:label>'
    '<link:labelArc xlink:from="a_loc" xlink:to="a_lab"/>'
    '<link:labelArc xlink:from="m_loc" xlink:to="m_lab"/>'
    "</link:linkbase>"
)

_PRE_LINKBASE = (
    f"<link:linkbase {_LINK_HDR}>"
    '<link:presentationLink xlink:role="http://x/role/BalanceSheet">'
    '<link:loc xlink:href="x.xsd#us-gaap_StmtTable" xlink:label="p"/>'
    '<link:loc xlink:href="x.xsd#us-gaap_Assets" xlink:label="a"/>'
    '<link:presentationArc xlink:from="p" xlink:to="a" order="1.0"'
    ' preferredLabel="http://www.xbrl.org/2003/role/totalLabel"/>'
    "</link:presentationLink></link:linkbase>"
)


def _filing_dispatch(url, **kwargs):
    """Return bytes for the company schema, label, and presentation URLs."""
    if url.endswith("aapl-20240928.xsd"):
        return _COMPANY_SCHEMA.encode("utf-8")
    if url.endswith("_lab.xml"):
        return _LAB_LINKBASE.encode("utf-8")
    if url.endswith("_pre.xml"):
        return _PRE_LINKBASE.encode("utf-8")
    raise AssertionError(f"unexpected url {url}")


def _http_error(status_code: int) -> requests.HTTPError:
    """Build an HTTPError carrying a response with the given status."""
    response = requests.Response()
    response.status_code = status_code
    return requests.HTTPError(f"{status_code}", response=response)


class TestFilingDocumentHelpers:
    """Retry classification and presentation order parsing."""

    @pytest.mark.parametrize(
        ("exc", "expected"),
        [
            (requests.Timeout("slow"), True),
            (requests.ConnectionError("reset"), True),
            (_http_error(429), True),
            (_http_error(503), True),
            (_http_error(404), False),
            (requests.HTTPError("no response"), False),
            (OSError("disk"), False),
        ],
    )
    def test_is_transient_fetch_error(self, exc, expected):
        assert XBRLParser._is_transient_fetch_error(exc) is expected

    @pytest.mark.parametrize(
        ("value", "expected"),
        [("1.5", 1.5), ("2", 2.0), (None, None), ("", None), ("n/a", None)],
    )
    def test_parse_order(self, value, expected):
        assert XBRLParser._parse_order(value) == expected


class TestParseFilingLabels:
    """parse_instance(base_url=...) → _parse_filing_labels resolution."""

    def test_full_resolution(self, parser: XBRLParser):
        with patch(f"{CACHE_MOD}.cached_bytes", side_effect=_filing_dispatch):
            _, _, facts = parser.parse_instance(_b(_INSTANCE), base_url=_BASE)
        fact = facts["us-gaap_Assets"][0]
        assert fact["label"] == "Total Assets"
        assert fact["documentation"] == "Docs."
        # presentation metadata resolved from the pre linkbase
        pres = fact["presentation"][0]
        assert pres["table"] == "BalanceSheet"
        assert pres["preferred_label"] == "totalLabel"
        assert pres["order"] == 1.0
        # dimension member label resolved
        dim = fact["dimensions"]["us-gaap:Axis"]
        assert dim["member"] == "aapl:Member"
        assert dim["label"] == "The Member"

    def test_no_schema_ref_returns_unresolved(self, parser: XBRLParser):
        no_ref = _INSTANCE.replace(
            '<link:schemaRef xlink:href="aapl-20240928.xsd"/>', ""
        )
        # no schemaRef -> _parse_filing_labels returns empty maps, no fetch
        with patch(f"{CACHE_MOD}.cached_bytes", side_effect=AssertionError):
            _, _, facts = parser.parse_instance(_b(no_ref), base_url=_BASE)
        assert facts["us-gaap_Assets"][0]["label"] == "us-gaap_Assets"

    def test_label_linkbase_parse_error_warns(self, parser: XBRLParser):
        """A label linkbase that fails to parse is reported and skipped."""

        def dispatch(url, **kwargs):
            if url.endswith("aapl-20240928.xsd"):
                return _COMPANY_SCHEMA.encode("utf-8")
            if url.endswith("_lab.xml"):
                return b"<not-valid-label-xml"  # _get_xml_root raises -> except
            if url.endswith("_pre.xml"):
                return _PRE_LINKBASE.encode("utf-8")
            raise AssertionError(url)

        with (
            patch(f"{CACHE_MOD}.cached_bytes", side_effect=dispatch),
            pytest.warns(OpenBBWarning, match="label document"),
        ):
            _, _, facts = parser.parse_instance(_b(_INSTANCE), base_url=_BASE)
        assert "ParseError" in parser.linkbase_errors["label"]
        fact = facts["us-gaap_Assets"][0]
        assert fact["label"] == "us-gaap_Assets"
        assert fact["presentation"][0]["table"] == "BalanceSheet"

    def test_presentation_linkbase_bad_order_keeps_hierarchy(self, parser: XBRLParser):
        """A non-numeric ``order`` is dropped without losing the presentation."""
        bad_pre = _PRE_LINKBASE.replace('order="1.0"', 'order="not-a-number"')

        def dispatch(url, **kwargs):
            if url.endswith("aapl-20240928.xsd"):
                return _COMPANY_SCHEMA.encode("utf-8")
            if url.endswith("_lab.xml"):
                return _LAB_LINKBASE.encode("utf-8")
            if url.endswith("_pre.xml"):
                return bad_pre.encode("utf-8")
            raise AssertionError(url)

        with patch(f"{CACHE_MOD}.cached_bytes", side_effect=dispatch):
            _, _, facts = parser.parse_instance(_b(_INSTANCE), base_url=_BASE)
        fact = facts["us-gaap_Assets"][0]
        assert fact["label"] == "Total Assets"
        assert fact["presentation"][0]["table"] == "BalanceSheet"
        assert fact["presentation"][0]["order"] is None

    def test_schema_fetch_error_warns(self, parser: XBRLParser):
        fetch = MagicMock(side_effect=OSError("boom"))
        with (
            patch(f"{CACHE_MOD}.cached_bytes", fetch),
            pytest.warns(OpenBBWarning, match="schema document"),
        ):
            _, _, facts = parser.parse_instance(_b(_INSTANCE), base_url=_BASE)
        assert facts["us-gaap_Assets"][0]["label"] == "us-gaap_Assets"
        assert parser.linkbase_errors == {"schema": "OSError: boom"}
        assert fetch.call_count == 1

    def test_schema_root_none_returns_empty(self, parser: XBRLParser):
        """A None schema root short-circuits filing-label resolution (line 2056).

        ``_get_xml_root`` realistically never returns None (it raises on bad XML),
        so we stub it: real parse for the instance document, None for the schema.
        """
        real = parser._get_xml_root
        calls = {"n": 0}

        def get_root(content):
            calls["n"] += 1
            # First call parses the instance document; second is the company
            # schema fetched inside _parse_filing_labels -> force None there.
            if calls["n"] == 1:
                return real(content)
            return None

        with (
            patch(f"{CACHE_MOD}.cached_bytes", return_value=b"<x/>"),
            patch.object(parser, "_get_xml_root", side_effect=get_root),
        ):
            _, _, facts = parser.parse_instance(_b(_INSTANCE), base_url=_BASE)
        # No labels resolved -> fact label falls back to the tag name.
        assert facts["us-gaap_Assets"][0]["label"] == "us-gaap_Assets"

    def test_transient_presentation_failures_are_retried(self, parser: XBRLParser):
        failures = [requests.Timeout("slow"), requests.ConnectionError("reset")]

        def dispatch(url, **kwargs):
            if url.endswith("_pre.xml") and failures:
                raise failures.pop(0)
            return _filing_dispatch(url)

        with (
            patch(f"{CACHE_MOD}.cached_bytes", side_effect=dispatch),
            patch.object(xth, "LINKBASE_RETRY_BACKOFF", 0),
        ):
            _, _, facts = parser.parse_instance(_b(_INSTANCE), base_url=_BASE)
        assert facts["us-gaap_Assets"][0]["presentation"][0]["table"] == "BalanceSheet"
        assert not failures
        assert parser.linkbase_errors == {}

    def test_rate_limited_presentation_warns_after_retries(self, parser: XBRLParser):
        calls: list[str] = []

        def dispatch(url, **kwargs):
            if url.endswith("_pre.xml"):
                calls.append(url)
                raise _http_error(429)
            return _filing_dispatch(url)

        with (
            patch(f"{CACHE_MOD}.cached_bytes", side_effect=dispatch),
            patch.object(xth, "LINKBASE_RETRY_BACKOFF", 0),
            pytest.warns(OpenBBWarning, match="presentation document"),
        ):
            _, _, facts = parser.parse_instance(_b(_INSTANCE), base_url=_BASE)
        fact = facts["us-gaap_Assets"][0]
        assert fact["label"] == "Total Assets"
        assert "presentation" not in fact
        assert len(calls) == xth.LINKBASE_FETCH_ATTEMPTS
        assert "HTTPError" in parser.linkbase_errors["presentation"]

    def test_missing_presentation_is_not_retried(self, parser: XBRLParser):
        calls: list[str] = []

        def dispatch(url, **kwargs):
            if url.endswith("_pre.xml"):
                calls.append(url)
                raise _http_error(404)
            return _filing_dispatch(url)

        with (
            patch(f"{CACHE_MOD}.cached_bytes", side_effect=dispatch),
            pytest.warns(OpenBBWarning, match="presentation document"),
        ):
            parser.parse_instance(_b(_INSTANCE), base_url=_BASE)
        assert len(calls) == 1

    def test_absolute_hrefs_in_schema(self, parser: XBRLParser):
        """linkbaseRef with absolute hrefs are used directly."""
        abs_schema = (
            '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
            ' xmlns:link="http://www.xbrl.org/2003/linkbase"'
            ' xmlns:xlink="http://www.w3.org/1999/xlink">'
            "<link:linkbaseRef"
            ' xlink:role="labelLinkbaseRef"'
            ' xlink:href="https://abs.example/lab_lab.xml"/>'
            "</xsd:schema>"
        )

        def dispatch(url, **kwargs):
            if url.endswith("aapl-20240928.xsd"):
                return abs_schema.encode("utf-8")
            if url == "https://abs.example/lab_lab.xml":
                return _LAB_LINKBASE.encode("utf-8")
            raise AssertionError(url)

        with patch(f"{CACHE_MOD}.cached_bytes", side_effect=dispatch):
            _, _, facts = parser.parse_instance(_b(_INSTANCE), base_url=_BASE)
        assert facts["us-gaap_Assets"][0]["label"] == "Total Assets"

    def test_absolute_schema_ref(self, parser: XBRLParser):
        """An absolute schemaRef href is fetched as-is (not urljoined)."""
        abs_instance = _INSTANCE.replace(
            'xlink:href="aapl-20240928.xsd"',
            'xlink:href="https://abs.example/aapl-20240928.xsd"',
        )

        def dispatch(url, **kwargs):
            assert url == "https://abs.example/aapl-20240928.xsd"
            # return a schema with no linkbaseRefs
            return b'<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"/>'

        with patch(f"{CACHE_MOD}.cached_bytes", side_effect=dispatch):
            _, _, facts = parser.parse_instance(_b(abs_instance), base_url=_BASE)
        assert facts["us-gaap_Assets"][0]["label"] == "us-gaap_Assets"


# ════════════════════════════════════════════════════════════════════
# XBRLManager — registry-only / delegate methods
# ════════════════════════════════════════════════════════════════════


class TestManagerRegistry:
    """list_available_taxonomies / components / years (registry + delegate)."""

    def test_list_taxonomies_no_filter(self, manager: XBRLManager):
        out = manager.list_available_taxonomies()
        assert len(out) == len(xth.TAXONOMIES)
        assert out["us-gaap"]["style"] == "FASB_STANDARD"
        assert out["us-gaap"]["has_label_linkbase"] == "True"

    def test_list_taxonomies_enum_filter(self, manager: XBRLManager):
        out = manager.list_available_taxonomies(xth.TaxonomyCategory.NRSRO)
        assert "rocr" in out
        assert all(m["category"] == "nrsro" for m in out.values())

    def test_list_taxonomies_string_filter(self, manager: XBRLManager):
        out = manager.list_available_taxonomies("self_regulatory_org")
        assert "sro" in out

    def test_list_taxonomies_invalid_string(self, manager: XBRLManager):
        with pytest.raises(ValueError, match="Invalid category"):
            manager.list_available_taxonomies("nope")

    def test_list_components_unknown_taxonomy(self, manager: XBRLManager):
        assert manager.list_available_components("nope", 2024) == []

    def test_list_components_delegates(self, manager: XBRLManager):
        with patch.object(
            manager.client, "get_components_for_year", return_value=["a", "b"]
        ) as mock:
            assert manager.list_available_components("dei", 2024) == ["a", "b"]
        mock.assert_called_once()

    def test_get_available_years_unknown(self, manager: XBRLManager):
        assert manager.get_available_years("nope") == []

    def test_get_available_years_delegates(self, manager: XBRLManager):
        with patch.object(
            manager.client, "get_available_years", return_value=[2024]
        ) as mock:
            assert manager.get_available_years("dei") == [2024]
        mock.assert_called_once()


# A small XSD with one element bearing properties, used across manager tests.
_PROPS_XSD = (
    b'<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
    b' xmlns:xbrli="http://www.xbrl.org/2003/instance">'
    b'<xsd:element name="Foo" id="ex_Foo" type="xbrli:monetaryItemType"'
    b' substitutionGroup="xbrli:item" xbrli:periodType="duration"/>'
    b"</xsd:schema>"
)


class TestEnsureElementProperties:
    """_ensure_element_properties across styles + caching + error paths."""

    def test_unknown_taxonomy_is_noop(self, manager: XBRLManager):
        manager._ensure_element_properties("nope", 2024)
        assert manager.parser.element_properties == {}

    def test_fasb_resolves_and_caches(self, manager: XBRLManager):
        with (
            patch.object(
                manager.client, "find_file", return_value="https://x/us-gaap-2024.xsd"
            ),
            patch.object(
                manager.client, "fetch_file", return_value=BytesIO(_PROPS_XSD)
            ) as fetch,
        ):
            manager._ensure_element_properties("us-gaap", 2024)
            # cached: a second call does nothing
            manager._ensure_element_properties("us-gaap", 2024)
        assert "ex_Foo" in manager.parser.element_properties
        assert ("us-gaap", 2024) in manager._properties_loaded_for
        fetch.assert_called_once()

    def test_sec_embedded_tries_multiple_fragments(self, manager: XBRLManager):
        with (
            patch.object(
                manager.client, "find_file", return_value="https://x/dei-2024.xsd"
            ),
            patch.object(
                manager.client, "fetch_file", return_value=BytesIO(_PROPS_XSD)
            ),
        ):
            manager._ensure_element_properties("dei", 2024)
        assert "ex_Foo" in manager.parser.element_properties

    def test_ifrs_branch(self, manager: XBRLManager):
        xth._ifrs_version_dates_cache = dict(xth._IFRS_VERSION_DATES_FALLBACK)
        with patch.object(
            manager.client, "fetch_file", return_value=BytesIO(_PROPS_XSD)
        ) as fetch:
            manager._ensure_element_properties("ifrs", 2024)
        assert "ex_Foo" in manager.parser.element_properties
        assert "full_ifrs-cor" in fetch.call_args[0][0]

    def test_frc_branch(self, manager: XBRLManager):
        with (
            patch.object(manager, "_frc_member", return_value="dpl/2024/dpl.xsd"),
            patch.object(
                manager.client, "fetch_frc_member", return_value=BytesIO(_PROPS_XSD)
            ),
        ):
            manager._ensure_element_properties("frc-dpl", 2024)
        assert "ex_Foo" in manager.parser.element_properties
        assert ("frc-dpl", 2024) in manager._properties_loaded_for

    def test_frc_branch_no_member(self, manager: XBRLManager):
        with patch.object(manager, "_frc_member", return_value=None):
            manager._ensure_element_properties("frc-core", 2024)
        assert ("frc-core", 2024) not in manager._properties_loaded_for

    def test_frc_branch_fetch_error(self, manager: XBRLManager):
        with (
            patch.object(manager, "_frc_member", return_value="x"),
            patch.object(
                manager.client, "fetch_frc_member", side_effect=OSError("down")
            ),
        ):
            manager._ensure_element_properties("frc-dpl", 2024)
        assert ("frc-dpl", 2024) not in manager._properties_loaded_for

    def test_static_branch(self, manager: XBRLManager):
        with patch.object(
            manager.client, "fetch_file", return_value=BytesIO(_PROPS_XSD)
        ) as fetch:
            manager._ensure_element_properties("rocr", 2015)
        assert fetch.called

    def test_fetch_error_continues(self, manager: XBRLManager):
        with (
            patch.object(manager.client, "find_file", return_value="https://x/y.xsd"),
            patch.object(manager.client, "fetch_file", side_effect=OSError("boom")),
        ):
            manager._ensure_element_properties("us-gaap", 2024)
        # nothing loaded, not marked cached
        assert ("us-gaap", 2024) not in manager._properties_loaded_for


class TestGetRolesForTaxonomy:
    """_get_roles_for_taxonomy across styles."""

    _ROLE_XSD = (
        b'<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
        b' xmlns:link="http://www.xbrl.org/2003/linkbase">'
        b"<xsd:annotation><xsd:appinfo>"
        b'<link:roleType id="r-soi">'
        b"<link:definition>104000 - Statement - Income</link:definition>"
        b"</link:roleType></xsd:appinfo></xsd:annotation></xsd:schema>"
    )

    def test_unknown_taxonomy(self, manager: XBRLManager):
        assert manager._get_roles_for_taxonomy("nope", 2024) == []

    def test_fasb_returns_roles(self, manager: XBRLManager):
        with (
            patch.object(
                manager.client, "find_file", return_value="https://x/us-gaap-roles.xsd"
            ),
            patch.object(
                manager.client, "fetch_file", return_value=BytesIO(self._ROLE_XSD)
            ),
        ):
            roles = manager._get_roles_for_taxonomy("us-gaap", 2024)
        assert roles and roles[0]["name"] == "r-soi"

    def test_sec_embedded_returns_roles(self, manager: XBRLManager):
        with (
            patch.object(
                manager.client, "find_file", return_value="https://x/dei-2024.xsd"
            ),
            patch.object(
                manager.client, "fetch_file", return_value=BytesIO(self._ROLE_XSD)
            ),
        ):
            roles = manager._get_roles_for_taxonomy("dei", 2024)
        assert roles[0]["short_name"] == "Income"

    def test_static_branch(self, manager: XBRLManager):
        with patch.object(
            manager.client, "fetch_file", return_value=BytesIO(self._ROLE_XSD)
        ):
            assert manager._get_roles_for_taxonomy("rocr", 2015)

    def test_no_roles_returns_empty(self, manager: XBRLManager):
        empty = b'<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"/>'
        with (
            patch.object(
                manager.client, "find_file", return_value="https://x/dei-2024.xsd"
            ),
            patch.object(manager.client, "fetch_file", return_value=BytesIO(empty)),
        ):
            assert manager._get_roles_for_taxonomy("dei", 2024) == []

    def test_fetch_error_continues(self, manager: XBRLManager):
        with (
            patch.object(manager.client, "find_file", return_value="https://x/y.xsd"),
            patch.object(manager.client, "fetch_file", side_effect=OSError("x")),
        ):
            assert manager._get_roles_for_taxonomy("us-gaap", 2024) == []


class TestGetComponentsMetadata:
    """get_components_metadata strategies 1 (FASB), 2 (IFRS), 3 (SEC)."""

    def test_unknown_taxonomy(self, manager: XBRLManager):
        assert manager.get_components_metadata("nope", 2024) == []

    def test_no_components(self, manager: XBRLManager):
        with patch.object(manager, "list_available_components", return_value=[]):
            assert manager.get_components_metadata("us-gaap", 2024) == []

    def test_fasb_direct_match_and_unmatched(self, manager: XBRLManager):
        roles = [
            {
                "name": "soi",
                "short_name": "Income Statement",
                "long_name": "104000 - Statement - Income Statement",
                "group": "statement",
            }
        ]
        with (
            patch.object(
                manager, "list_available_components", return_value=["soi", "mystery"]
            ),
            patch.object(manager, "_get_roles_for_taxonomy", return_value=roles),
        ):
            out = manager.get_components_metadata("us-gaap", 2024)
        by_name = {o["name"]: o for o in out}
        assert by_name["soi"]["label"] == "Income Statement"
        assert by_name["soi"]["category"] == "statement"
        # unmatched component falls back to its own name
        assert by_name["mystery"]["label"] == "mystery"
        assert by_name["mystery"]["description"] is None

    def test_fasb_industry_prefix_strip(self, manager: XBRLManager):
        roles = [
            {
                "name": "com",
                "short_name": "Commitments",
                "long_name": "L - Disclosure - Commitments",
                "group": "disclosure",
            }
        ]
        with (
            patch.object(
                manager, "list_available_components", return_value=["basi-com"]
            ),
            patch.object(manager, "_get_roles_for_taxonomy", return_value=roles),
        ):
            out = manager.get_components_metadata("us-gaap", 2011)
        assert out[0]["label"] == "Commitments (Basic)"

    def test_ifrs_with_role_file(self, manager: XBRLManager):
        xth._ifrs_version_dates_cache = dict(xth._IFRS_VERSION_DATES_FALLBACK)
        role_xsd = (
            b'<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
            b' xmlns:link="http://www.xbrl.org/2003/linkbase">'
            b"<xsd:annotation><xsd:appinfo>"
            b'<link:roleType id="r">'
            b"<link:definition>210000 - Statement - Financial Position</link:definition>"
            b"</link:roleType></xsd:appinfo></xsd:annotation></xsd:schema>"
        )
        with (
            patch.object(manager, "list_available_components", return_value=["ias_1"]),
            patch.object(manager.client, "fetch_file", return_value=BytesIO(role_xsd)),
        ):
            out = manager.get_components_metadata("ifrs", 2024)
        assert out[0]["name"] == "ias_1"
        assert out[0]["category"] == "statement"
        assert "Financial Position" in out[0]["description"]

    def _ifrs_role_xsd(self, definition: str) -> BytesIO:
        return BytesIO(
            (
                '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
                ' xmlns:link="http://www.xbrl.org/2003/linkbase">'
                "<xsd:annotation><xsd:appinfo>"
                '<link:roleType id="r">'
                f"<link:definition>{definition}</link:definition>"
                "</link:roleType></xsd:appinfo></xsd:annotation></xsd:schema>"
            ).encode()
        )

    def test_ifrs_category_notes(self, manager: XBRLManager):
        """A role definition containing 'Notes' -> category 'notes' (line 2620-2621)."""
        xth._ifrs_version_dates_cache = dict(xth._IFRS_VERSION_DATES_FALLBACK)
        with (
            patch.object(manager, "list_available_components", return_value=["ias_1"]),
            patch.object(
                manager.client,
                "fetch_file",
                return_value=self._ifrs_role_xsd(
                    "800000 - Notes - Accounting policies"
                ),
            ),
        ):
            out = manager.get_components_metadata("ifrs", 2024)
        assert out[0]["category"] == "notes"

    def test_ifrs_category_disclosure_default(self, manager: XBRLManager):
        """Neither 'Statement' nor 'Notes' -> default 'disclosure' (line 2622-2623)."""
        xth._ifrs_version_dates_cache = dict(xth._IFRS_VERSION_DATES_FALLBACK)
        with (
            patch.object(manager, "list_available_components", return_value=["ias_1"]),
            patch.object(
                manager.client,
                "fetch_file",
                return_value=self._ifrs_role_xsd("851100 - Disclosure - Cash flows"),
            ),
        ):
            out = manager.get_components_metadata("ifrs", 2024)
        assert out[0]["category"] == "disclosure"

    def test_ifrs_role_fetch_error_uses_known_name(self, manager: XBRLManager):
        xth._ifrs_version_dates_cache = dict(xth._IFRS_VERSION_DATES_FALLBACK)
        with (
            patch.object(manager, "list_available_components", return_value=["ias_1"]),
            patch.object(manager.client, "fetch_file", side_effect=OSError("x")),
        ):
            out = manager.get_components_metadata("ifrs", 2024)
        # falls back to IFRS_STANDARD_NAMES label
        assert out[0]["label"] == xth.IFRS_STANDARD_NAMES["ias_1"]

    def test_sec_multicomponent_role_match(self, manager: XBRLManager):
        roles = [
            {
                "name": "RiskReturn",
                "short_name": "Risk/Return",
                "long_name": "L - Disclosure - Risk/Return",
                "group": "disclosure",
                "document_number": "100",
            }
        ]
        comp_xsd = (
            b"<schema><link:presentationLink"
            b' xmlns:link="http://www.xbrl.org/2003/linkbase"'
            b' role="http://xbrl.sec.gov/rr/role/RiskReturn"/></schema>'
        )
        with (
            patch.object(manager, "list_available_components", return_value=["rr"]),
            patch.object(manager, "_get_roles_for_taxonomy", return_value=roles),
            patch.object(
                manager.client, "find_file", return_value="https://x/oef-rr-2024.xsd"
            ),
            patch.object(manager.client, "fetch_file", return_value=BytesIO(comp_xsd)),
        ):
            out = manager.get_components_metadata("oef", 2024)
        assert out[0]["label"] == "Risk/Return"
        assert out[0]["category"] == "disclosure"

    def test_sec_multicomponent_broader_file_search(self, manager: XBRLManager):
        """Exact file lookups miss; the broader component search resolves (line 2669)."""
        roles = [
            {
                "name": "RiskReturn",
                "short_name": "Risk/Return",
                "long_name": "L - Disclosure - Risk/Return",
                "group": "disclosure",
                "document_number": "100",
            }
        ]
        comp_xsd = (
            b"<schema><link:presentationLink"
            b' xmlns:link="http://www.xbrl.org/2003/linkbase"'
            b' role="http://xbrl.sec.gov/rr/role/RiskReturn"/></schema>'
        )

        def find(url, *frags):
            # The first two exact lookups fail; only the broader 3-fragment
            # search (component, year, ".xsd") resolves a file.
            if frags == ("rr", "2024", ".xsd"):
                return "https://x/some-rr-file-2024.xsd"
            return None

        with (
            patch.object(manager, "list_available_components", return_value=["rr"]),
            patch.object(manager, "_get_roles_for_taxonomy", return_value=roles),
            patch.object(manager.client, "find_file", side_effect=find),
            patch.object(manager.client, "fetch_file", return_value=BytesIO(comp_xsd)),
        ):
            out = manager.get_components_metadata("oef", 2024)
        assert out[0]["label"] == "Risk/Return"

    def test_sec_multicomponent_comp_fetch_error_continues(self, manager: XBRLManager):
        """A comp-file fetch error is swallowed and the loop continues (line 2695-2696)."""
        roles = [
            {
                "name": "RiskReturn",
                "short_name": "Risk/Return",
                "long_name": "L - Disclosure - Risk/Return",
                "group": "disclosure",
                "document_number": "100",
            }
        ]
        with (
            patch.object(manager, "list_available_components", return_value=["rr"]),
            patch.object(manager, "_get_roles_for_taxonomy", return_value=roles),
            patch.object(
                manager.client, "find_file", return_value="https://x/oef-rr-2024.xsd"
            ),
            patch.object(manager.client, "fetch_file", side_effect=OSError("down")),
        ):
            out = manager.get_components_metadata("oef", 2024)
        # No roles matched (fetch failed) -> falls back to SEC_COMPONENT_NAMES.
        assert out[0]["label"] == xth.SEC_COMPONENT_NAMES["oef"]["rr"]["label"]

    def test_sec_multicomponent_known_names_fallback(self, manager: XBRLManager):
        """No roles matched -> use SEC_COMPONENT_NAMES."""
        with (
            patch.object(manager, "list_available_components", return_value=["rr"]),
            patch.object(manager, "_get_roles_for_taxonomy", return_value=[]),
            patch.object(manager.client, "find_file", return_value=None),
        ):
            out = manager.get_components_metadata("oef", 2024)
        assert out[0]["label"] == xth.SEC_COMPONENT_NAMES["oef"]["rr"]["label"]

    def test_sec_multicomponent_unknown_fallback(self, manager: XBRLManager):
        """No roles, no known name -> uppercase the component."""
        with (
            patch.object(manager, "list_available_components", return_value=["zzz"]),
            patch.object(manager, "_get_roles_for_taxonomy", return_value=[]),
            patch.object(manager.client, "find_file", return_value=None),
        ):
            out = manager.get_components_metadata("cef", 2024)
        assert out[0]["label"] == "ZZZ"
        assert out[0]["description"] is None


# A label linkbase (FASB style) producing one label.
_LAB_XML = (
    f"<link:linkbase {_LINK_HDR}>"
    '<link:loc xlink:href="x.xsd#ex_Item" xlink:label="l"/>'
    '<link:label xlink:label="r"'
    ' xlink:role="http://www.xbrl.org/2003/role/label">Item Label</link:label>'
    '<link:labelArc xlink:from="l" xlink:to="r"/>'
    "</link:linkbase>"
).encode()


class TestEnsureLabels:
    """_ensure_labels across IFRS, FRC, STATIC, FASB, SEC styles."""

    def test_unknown_taxonomy_noop(self, manager: XBRLManager):
        manager._ensure_labels("nope", 2024)
        assert manager.parser.labels == {}

    def test_already_loaded_noop(self, manager: XBRLManager):
        manager._labels_loaded_for.add(("us-gaap", 2024))
        with patch.object(manager.client, "fetch_file", side_effect=AssertionError):
            manager._ensure_labels("us-gaap", 2024)

    def test_ifrs_loads_labels(self, manager: XBRLManager):
        xth._ifrs_version_dates_cache = dict(xth._IFRS_VERSION_DATES_FALLBACK)
        with patch.object(manager.client, "fetch_file", return_value=BytesIO(_LAB_XML)):
            manager._ensure_labels("ifrs", 2024)
        assert manager.parser.labels.get("ex_Item") == "Item Label"
        assert ("ifrs", 2024) in manager._labels_loaded_for

    def test_ifrs_no_date_returns(self, manager: XBRLManager):
        xth._ifrs_version_dates_cache = {2024: "2024-03-27"}
        with patch.object(manager.client, "fetch_file", side_effect=AssertionError):
            manager._ensure_labels("ifrs", 1900)
        assert manager.parser.labels == {}

    def test_frc_loads_labels(self, manager: XBRLManager):
        with (
            patch.object(manager, "_frc_member", return_value="dpl/2024/dpl-label.xml"),
            patch.object(
                manager.client, "fetch_frc_member", return_value=BytesIO(_LAB_XML)
            ),
        ):
            manager._ensure_labels("frc-dpl", 2024)
        assert manager.parser.labels.get("ex_Item") == "Item Label"
        assert ("frc-dpl", 2024) in manager._labels_loaded_for

    def test_frc_label_no_member(self, manager: XBRLManager):
        with patch.object(manager, "_frc_member", return_value=None):
            manager._ensure_labels("frc-core", 2024)
        assert ("frc-core", 2024) not in manager._labels_loaded_for

    def test_frc_label_fetch_error(self, manager: XBRLManager):
        """A fetch error is swallowed and the taxonomy is not marked loaded."""
        with (
            patch.object(manager, "_frc_member", return_value="x"),
            patch.object(
                manager.client, "fetch_frc_member", side_effect=OSError("down")
            ),
        ):
            manager._ensure_labels("frc-dpl", 2024)
        assert ("frc-dpl", 2024) not in manager._labels_loaded_for

    def test_static_loads_labels(self, manager: XBRLManager):
        with patch.object(manager.client, "fetch_file", return_value=BytesIO(_LAB_XML)):
            manager._ensure_labels("rocr", 2015)
        assert manager.parser.labels.get("ex_Item") == "Item Label"

    def test_fasb_loads_label_and_doc(self, manager: XBRLManager):
        with (
            patch.object(
                manager.client,
                "find_file",
                return_value="https://x/us-gaap-lab-2024.xml",
            ),
            patch.object(manager.client, "fetch_file", return_value=BytesIO(_LAB_XML)),
        ):
            manager._ensure_labels("us-gaap", 2024)
        assert manager.parser.labels.get("ex_Item") == "Item Label"
        assert ("us-gaap", 2024) in manager._labels_loaded_for

    def test_fasb_no_labels_warns(self, manager: XBRLManager):
        """FASB taxonomy where nothing loads emits a warning."""
        with patch.object(manager.client, "find_file", return_value=None):
            with pytest.warns(Warning, match="Could not load standard labels"):
                manager._ensure_labels("us-gaap", 2024)

    def test_sec_loads_labels_and_reference_fallback(self, manager: XBRLManager):
        ref_xsd = (
            '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
            f" {_LINK_HDR}"
            ' xmlns:ref="http://www.xbrl.org/2006/ref">'
            "<link:referenceLink>"
            '<link:loc xlink:href="ecd.xsd#ecd_X" xlink:label="xl"/>'
            '<link:reference xlink:label="xr"><ref:Name>Reg</ref:Name></link:reference>'
            '<link:referenceArc xlink:from="xl" xlink:to="xr"/>'
            "</link:referenceLink></xsd:schema>"
        ).encode()

        def fetch(url):
            if "ref" in url or url.endswith("ecd-2024.xsd"):
                return BytesIO(ref_xsd)
            return BytesIO(_LAB_XML)

        with (
            patch.object(
                manager.client, "find_file", return_value="https://x/ecd-2024.xsd"
            ),
            patch.object(manager.client, "fetch_file", side_effect=fetch),
        ):
            manager._ensure_labels("ecd", 2024)
        # reference fallback produced documentation
        assert any(k == "ecd_X" for k in manager.parser.documentation)

    def test_sec_entire_reference_preferred_for_country(self, manager: XBRLManager):
        seen_frags: list[tuple[str, ...]] = []

        def find(url, *frags):
            seen_frags.append(frags)
            if frags == ("country-entire-", "2025", ".xsd"):
                return "https://xbrl.sec.gov/country/2025/country-entire-2025.xsd"
            return None

        with (
            patch.object(manager.client, "find_file", side_effect=find),
            patch.object(manager.client, "fetch_file", return_value=BytesIO(_LAB_XML)),
        ):
            manager._ensure_labels("country", 2025)

        assert seen_frags[0] == ("country-entire-", "2025", ".xsd")
        assert manager.parser.labels.get("ex_Item") == "Item Label"
        assert ("country", 2025) in manager._labels_loaded_for

    def test_sec_label_fetch_error_continues(self, manager: XBRLManager):
        """A found SEC label URL whose fetch fails is skipped (line 2899-2900)."""

        # find_file returns a label URL for the first lookup, None thereafter
        # (so the reference fallback does nothing); fetch always raises.
        def find(url, *frags):
            if frags == ("ecd", "lab", "2024"):
                return "https://x/ecd-lab-2024.xml"
            return None

        with (
            patch.object(manager.client, "find_file", side_effect=find),
            patch.object(manager.client, "fetch_file", side_effect=OSError("down")),
        ):
            manager._ensure_labels("ecd", 2024)
        # Nothing loaded -> not marked as loaded.
        assert ("ecd", 2024) not in manager._labels_loaded_for

    def test_fasb_doc_file_adds_documentation(self, manager: XBRLManager):
        """The FASB dedicated *-doc-*.xml file contributes docs (line 2925-2926)."""
        doc_xml = (
            f"<link:linkbase {_LINK_HDR}>"
            '<link:loc xlink:href="x.xsd#ex_Item" xlink:label="l"/>'
            '<link:label xlink:label="r"'
            ' xlink:role="http://www.xbrl.org/2003/role/documentation">'
            "A definition.</link:label>"
            '<link:labelArc xlink:from="l" xlink:to="r"/>'
            "</link:linkbase>"
        ).encode()

        def find(url, *frags):
            # Label file lives under elts/; doc file also under elts/.
            if "doc" in frags:
                return "https://x/elts/us-gaap-doc-2024.xml"
            return "https://x/elts/us-gaap-lab-2024.xml"

        def fetch(url):
            return BytesIO(doc_xml) if "doc" in url else BytesIO(_LAB_XML)

        with (
            patch.object(manager.client, "find_file", side_effect=find),
            patch.object(manager.client, "fetch_file", side_effect=fetch),
        ):
            manager._ensure_labels("us-gaap", 2024)
        assert manager.parser.documentation.get("ex_Item") == "A definition."
        assert ("us-gaap", 2024) in manager._labels_loaded_for

    def test_sec_reference_broader_search_and_fetch_error(self, manager: XBRLManager):
        """The reference fallback's broader search resolves but fetch fails.

        Exercises the broader ``find_file`` (line 2951) and the swallowed fetch
        error (line 2958-2959).
        """

        # Label lookups all miss (no labels loaded); the reference fallback's
        # first two finds miss, only the broader 3-fragment search resolves a
        # URL, whose fetch then raises.
        def find(url, *frags):
            if frags == ("ecd", "2024", ".xsd"):
                return "https://x/ecd-ref-2024.xsd"
            return None

        with (
            patch.object(manager.client, "find_file", side_effect=find),
            patch.object(manager.client, "fetch_file", side_effect=OSError("ref down")),
        ):
            manager._ensure_labels("ecd", 2024)
        assert ("ecd", 2024) not in manager._labels_loaded_for


class TestParseEntireFile:
    """_parse_entire_file direct-embed and import-wrapper paths."""

    def test_no_entire_file(self, manager: XBRLManager):
        with patch.object(manager.client, "find_file", return_value=None):
            assert manager._parse_entire_file("cyd", 2024, xth.TAXONOMIES["cyd"]) == []

    def test_fetch_error_returns_empty(self, manager: XBRLManager):
        with (
            patch.object(
                manager.client,
                "find_file",
                return_value="https://x/cyd-entire-2024.xsd",
            ),
            patch.object(manager.client, "fetch_file", side_effect=OSError("x")),
        ):
            assert manager._parse_entire_file("cyd", 2024, xth.TAXONOMIES["cyd"]) == []

    def test_direct_embed(self, manager: XBRLManager):
        embedded = (
            '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
            f" {_LINK_HDR}>"
            "<xsd:annotation><xsd:appinfo><link:linkbase>"
            "<link:presentationLink>"
            '<link:loc xlink:href="x.xsd#ex_P" xlink:label="p"/>'
            '<link:loc xlink:href="x.xsd#ex_C" xlink:label="c"/>'
            '<link:presentationArc xlink:from="p" xlink:to="c" order="1.0"/>'
            "</link:presentationLink>"
            "</link:linkbase></xsd:appinfo></xsd:annotation></xsd:schema>"
        ).encode()
        with (
            patch.object(
                manager.client,
                "find_file",
                return_value="https://x/cyd-entire-2024.xsd",
            ),
            patch.object(manager.client, "fetch_file", return_value=BytesIO(embedded)),
        ):
            nodes = manager._parse_entire_file("cyd", 2024, xth.TAXONOMIES["cyd"])
        assert nodes and nodes[0].element_id == "ex_P"

    def test_import_wrapper(self, manager: XBRLManager):
        """Empty entire file with a local import is followed to the sub-schema."""
        wrapper = (
            b'<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
            b'<xsd:import namespace="http://x" schemaLocation="ecd-sub-2024.xsd"/>'
            b'<xsd:import namespace="http://e" schemaLocation="http://external/x.xsd"/>'
            b"</xsd:schema>"
        )
        sub = (
            '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
            f" {_LINK_HDR}>"
            "<xsd:annotation><xsd:appinfo><link:linkbase>"
            "<link:presentationLink>"
            '<link:loc xlink:href="x.xsd#ex_Root" xlink:label="r"/>'
            '<link:loc xlink:href="x.xsd#ex_Leaf" xlink:label="l"/>'
            '<link:presentationArc xlink:from="r" xlink:to="l" order="1.0"/>'
            "</link:presentationLink>"
            "</link:linkbase></xsd:appinfo></xsd:annotation></xsd:schema>"
        ).encode()

        def fetch(url):
            if url.endswith("ecd-sub-2024.xsd"):
                return BytesIO(sub)
            return BytesIO(wrapper)

        with (
            patch.object(
                manager.client,
                "find_file",
                return_value="https://x/ecd-entire-2024.xsd",
            ),
            patch.object(manager.client, "fetch_file", side_effect=fetch),
        ):
            nodes = manager._parse_entire_file("ecd", 2024, xth.TAXONOMIES["ecd"])
        ids = {n.element_id for n in nodes}
        assert "ex_Root" in ids

    def test_import_wrapper_sub_fetch_error_continues(self, manager: XBRLManager):
        """A failing sub-import is swallowed and the loop continues (line 3063-3064)."""
        wrapper = (
            b'<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
            b'<xsd:import namespace="http://x" schemaLocation="ecd-sub-2024.xsd"/>'
            b"</xsd:schema>"
        )

        def fetch(url):
            if url.endswith("ecd-sub-2024.xsd"):
                raise OSError("sub down")
            return BytesIO(wrapper)

        with (
            patch.object(
                manager.client,
                "find_file",
                return_value="https://x/ecd-entire-2024.xsd",
            ),
            patch.object(manager.client, "fetch_file", side_effect=fetch),
        ):
            nodes = manager._parse_entire_file("ecd", 2024, xth.TAXONOMIES["ecd"])
        assert nodes == []


class TestGetIfrsStructure:
    """_get_ifrs_structure per-standard and flat-fallback paths."""

    def test_no_date_raises(self, manager: XBRLManager):
        xth._ifrs_version_dates_cache = {2024: "2024-03-27"}
        with pytest.raises(OpenBBError, match="not available for year"):
            manager._get_ifrs_structure(1900, "ias_1")

    def test_standard_flat_fallback(self, manager: XBRLManager):
        xth._ifrs_version_dates_cache = dict(xth._IFRS_VERSION_DATES_FALLBACK)
        core = (
            b'<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
            b'<xsd:element name="Cash" id="ifrs_Cash"/>'
            b"</xsd:schema>"
        )
        with patch.object(manager.client, "fetch_file", return_value=BytesIO(core)):
            nodes = manager._get_ifrs_structure(2024, "standard")
        assert nodes and nodes[0].element_id == "ifrs_Cash"

    def test_specific_standard_presentation(self, manager: XBRLManager):
        xth._ifrs_version_dates_cache = dict(xth._IFRS_VERSION_DATES_FALLBACK)
        date = "2024-03-27"
        ep = (
            "<schema>"
            f'<loc href="full_ifrs/linkbases/ias_1/pre_ias_1_{date}_role-210000.xml"/>'
            "</schema>"
        ).encode()
        pre = (
            f"<link:linkbase {_LINK_HDR}>"
            "<link:presentationLink>"
            '<link:loc xlink:href="x.xsd#ifrs_Root" xlink:label="r"/>'
            '<link:loc xlink:href="x.xsd#ifrs_Child" xlink:label="c"/>'
            '<link:presentationArc xlink:from="r" xlink:to="c" order="1.0"/>'
            "</link:presentationLink></link:linkbase>"
        ).encode()

        def fetch(url):
            if "entry_point" in url:
                return BytesIO(ep)
            return BytesIO(pre)

        with patch.object(manager.client, "fetch_file", side_effect=fetch):
            nodes = manager._get_ifrs_structure(2024, "ias_1")
        assert nodes and nodes[0].element_id == "ifrs_Root"

    def test_pres_file_fetch_error_falls_back_to_core(self, manager: XBRLManager):
        """A listed pres file that fails to fetch is skipped (line 3146-3147)."""
        xth._ifrs_version_dates_cache = dict(xth._IFRS_VERSION_DATES_FALLBACK)
        date = "2024-03-27"
        ep = (
            "<schema>"
            f'<loc href="full_ifrs/linkbases/ias_1/pre_ias_1_{date}_role-210000.xml"/>'
            "</schema>"
        ).encode()
        core = (
            b'<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
            b'<xsd:element name="Cash" id="ifrs_Cash"/></xsd:schema>'
        )

        def fetch(url):
            if "entry_point" in url:
                return BytesIO(ep)
            if "pre_ias_1" in url:
                raise OSError("pre file down")
            return BytesIO(core)  # core fallback

        with patch.object(manager.client, "fetch_file", side_effect=fetch):
            nodes = manager._get_ifrs_structure(2024, "ias_1")
        assert nodes and nodes[0].element_id == "ifrs_Cash"

    def test_entry_point_fetch_error_raises(self, manager: XBRLManager):
        xth._ifrs_version_dates_cache = dict(xth._IFRS_VERSION_DATES_FALLBACK)
        with patch.object(manager.client, "fetch_file", side_effect=OSError("x")):
            with pytest.raises(OpenBBError, match="Failed to fetch IFRS entry point"):
                manager._get_ifrs_structure(2024, "ias_1")

    def test_no_pres_hrefs_falls_back_to_core(self, manager: XBRLManager):
        xth._ifrs_version_dates_cache = dict(xth._IFRS_VERSION_DATES_FALLBACK)
        ep = b"<schema></schema>"  # no pre_ or dimension hrefs
        core = (
            b'<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
            b'<xsd:element name="Cash" id="ifrs_Cash"/></xsd:schema>'
        )

        def fetch(url):
            if "entry_point" in url:
                return BytesIO(ep)
            return BytesIO(core)

        with patch.object(manager.client, "fetch_file", side_effect=fetch):
            nodes = manager._get_ifrs_structure(2024, "ias_1")
        assert nodes[0].element_id == "ifrs_Cash"

    def test_core_fetch_error_raises(self, manager: XBRLManager):
        xth._ifrs_version_dates_cache = dict(xth._IFRS_VERSION_DATES_FALLBACK)
        with patch.object(manager.client, "fetch_file", side_effect=OSError("x")):
            with pytest.raises(OpenBBError, match="Failed to fetch IFRS core schema"):
                manager._get_ifrs_structure(2024, "standard")


# ════════════════════════════════════════════════════════════════════
# get_structure — the top-level dispatcher across all taxonomy styles
# ════════════════════════════════════════════════════════════════════

# A minimal presentation linkbase: Root -> Leaf.
_GS_PRE = (
    f"<link:linkbase {_LINK_HDR}>"
    "<link:presentationLink>"
    '<link:loc xlink:href="x.xsd#ex_Root" xlink:label="r"/>'
    '<link:loc xlink:href="x.xsd#ex_Leaf" xlink:label="l"/>'
    '<link:presentationArc xlink:from="r" xlink:to="l" order="1.0"/>'
    "</link:presentationLink></link:linkbase>"
)

# A schema with a couple of flat elements (for schema-element fallback).
_GS_SCHEMA = (
    '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
    '<xsd:element name="Flat" id="ex_Flat" abstract="false"/>'
    "</xsd:schema>"
)


def _node(element_id: str) -> XBRLNode:
    """Build a minimal XBRLNode (all required positional fields supplied)."""
    return XBRLNode(
        element_id=element_id, label=element_id, order=1.0, level=0, parent_id=None
    )


@pytest.fixture
def _stub_label_loading():
    """Neutralise the label/property side-loading so only get_structure's own
    fetch/parse branches are exercised (those make their own network calls)."""
    with (
        patch.object(XBRLManager, "_ensure_labels", return_value=None),
        patch.object(XBRLManager, "_ensure_element_properties", return_value=None),
        patch.object(XBRLManager, "_load_frc_core_labels", return_value=None),
    ):
        yield


class TestGetStructure:
    """``get_structure`` dispatch across taxonomy styles and fallbacks."""

    def test_unsupported_taxonomy_raises(self, manager: XBRLManager):
        with pytest.raises(ValueError, match="Unsupported taxonomy"):
            manager.get_structure("not-a-real-taxonomy", 2024, "soi")

    def test_ifrs_delegates_to_ifrs_structure(
        self, manager: XBRLManager, _stub_label_loading
    ):
        sentinel = [_node("ifrs_X")]
        with patch.object(
            manager, "_get_ifrs_structure", return_value=sentinel
        ) as mock_ifrs:
            out = manager.get_structure("ifrs", 2024, "ias_1")
        assert out is sentinel
        mock_ifrs.assert_called_once_with(2024, "ias_1")

    def test_static_taxonomy_uses_template_url(
        self, manager: XBRLManager, _stub_label_loading
    ):
        # STATIC (rocr) concatenates base_url_template + presentation_file_template.
        with patch.object(
            manager.client, "fetch_file", return_value=_b(_GS_PRE)
        ) as mock_fetch:
            nodes = manager.get_structure("rocr", 2015, "ratings")
        assert nodes and nodes[0].element_id == "ex_Root"
        called_url = mock_fetch.call_args[0][0]
        assert called_url == (
            "https://xbrl.sec.gov/rocr/2015/ratings-pre-2015-03-31.xml"
        )

    def test_frc_dpl_uses_presentation(self, manager: XBRLManager, _stub_label_loading):
        # frc-dpl parses its compact presentation linkbase from the suite ZIP.
        with (
            patch.object(
                manager, "_frc_member", return_value="dpl/dpl-presentation.xml"
            ),
            patch.object(manager.client, "fetch_frc_member", return_value=_b(_GS_PRE)),
        ):
            nodes = manager.get_structure("frc-dpl", 2024, "standard")
        assert nodes and nodes[0].element_id == "ex_Root"

    def test_frc_core_uses_flat_schema(self, manager: XBRLManager, _stub_label_loading):
        # frc-core never attempts presentation; it returns flat schema elements.
        with (
            patch.object(manager, "_frc_member", return_value="core/frc-core.xsd"),
            patch.object(
                manager.client, "fetch_frc_member", return_value=_b(_GS_SCHEMA)
            ),
        ):
            nodes = manager.get_structure("frc-core", 2024, "standard")
        assert [n.element_id for n in nodes] == ["ex_Flat"]

    def test_frc_dpl_presentation_error_falls_back_to_schema(
        self, manager: XBRLManager, _stub_label_loading
    ):
        # A presentation-parse failure falls back to flat schema elements.
        def _member(_tax, _yr, kind):
            return "dpl-presentation.xml" if kind == "presentation" else "dpl.xsd"

        def _fetch(_yr, relpath):
            if "presentation" in relpath:
                raise OSError("bad presentation")
            return _b(_GS_SCHEMA)

        with (
            patch.object(manager, "_frc_member", side_effect=_member),
            patch.object(manager.client, "fetch_frc_member", side_effect=_fetch),
        ):
            nodes = manager.get_structure("frc-dpl", 2024, "standard")
        assert [n.element_id for n in nodes] == ["ex_Flat"]

    def test_frc_no_members_returns_empty(
        self, manager: XBRLManager, _stub_label_loading
    ):
        # No resolvable members (e.g. a malformed suite) yields an empty tree.
        with patch.object(manager, "_frc_member", return_value=None):
            nodes = manager.get_structure("frc-dpl", 2024, "standard")
        assert nodes == []

    def test_fasb_standard_progressive_find(
        self, manager: XBRLManager, _stub_label_loading
    ):
        # First find_file call resolves; fetch returns a presentation linkbase.
        with (
            patch.object(
                manager.client,
                "find_file",
                return_value="https://x/us-gaap-stm-soi-pre-2024.xml",
            ) as mock_find,
            patch.object(manager.client, "fetch_file", return_value=_b(_GS_PRE)),
        ):
            nodes = manager.get_structure("us-gaap", 2024, "soi")
        assert nodes and nodes[0].element_id == "ex_Root"
        # stm/ subdirectory listing URL was used.
        assert mock_find.call_args_list[0][0][0].endswith("/stm/")

    def test_fasb_standard_no_file_raises(
        self, manager: XBRLManager, _stub_label_loading
    ):
        with (
            patch.object(manager.client, "find_file", return_value=None),
            patch.object(manager.client, "list_files", return_value=[]),
        ):
            with pytest.raises(OpenBBError, match="No presentation file found"):
                manager.get_structure("us-gaap", 2024, "soi")

    def test_sec_standard_entire_file_short_circuits(
        self, manager: XBRLManager, _stub_label_loading
    ):
        # component == "standard" on a SEC taxonomy: _parse_entire_file returns
        # nodes -> early return, no find_file/fetch_file needed.
        sentinel = [_node("dei_Root")]
        with patch.object(
            manager, "_parse_entire_file", return_value=sentinel
        ) as mock_pe:
            out = manager.get_structure("dei", 2024, "standard")
        assert out is sentinel
        mock_pe.assert_called_once()

    def test_sec_standard_falls_back_to_schema(
        self, manager: XBRLManager, _stub_label_loading
    ):
        # _parse_entire_file raises -> swallowed -> find main schema, flat extract.
        with (
            patch.object(
                manager, "_parse_entire_file", side_effect=RuntimeError("boom")
            ),
            patch.object(
                manager.client, "find_file", return_value="https://x/dei-2024.xsd"
            ),
            patch.object(manager.client, "fetch_file", return_value=_b(_GS_SCHEMA)),
        ):
            nodes = manager.get_structure("dei", 2024, "standard")
        assert nodes and nodes[0].element_id == "ex_Flat"

    def test_sec_standard_no_schema_found_raises(
        self, manager: XBRLManager, _stub_label_loading
    ):
        with (
            patch.object(
                manager, "_parse_entire_file", side_effect=RuntimeError("boom")
            ),
            patch.object(manager.client, "find_file", return_value=None),
        ):
            with pytest.raises(OpenBBError, match="No schema file found"):
                manager.get_structure("dei", 2024, "standard")

    def test_generic_component_progressive_find(
        self, manager: XBRLManager, _stub_label_loading
    ):
        # Non-"standard" SEC component -> generic else branch.
        with (
            patch.object(
                manager.client,
                "find_file",
                return_value="https://x/cef-shareholder-2024.xsd",
            ),
            patch.object(manager.client, "fetch_file", return_value=_b(_GS_PRE)),
        ):
            nodes = manager.get_structure("cef", 2024, "shareholder")
        assert nodes and nodes[0].element_id == "ex_Root"

    def test_generic_component_no_file_raises(
        self, manager: XBRLManager, _stub_label_loading
    ):
        with patch.object(manager.client, "find_file", return_value=None):
            with pytest.raises(OpenBBError, match="No presentation file found"):
                manager.get_structure("cef", 2024, "shareholder")

    def test_empty_pres_xsd_falls_back_to_schema_elements(
        self, manager: XBRLManager, _stub_label_loading
    ):
        # Presentation parse yields nothing AND the resolved URL ends in .xsd:
        # re-parse the same content as flat schema elements.
        with (
            patch.object(
                manager.client,
                "find_file",
                return_value="https://x/cef-shareholder-2024.xsd",
            ),
            patch.object(manager.client, "fetch_file", return_value=_b(_GS_SCHEMA)),
        ):
            nodes = manager.get_structure("cef", 2024, "shareholder")
        assert nodes and nodes[0].element_id == "ex_Flat"

    def test_empty_pres_xml_fetches_sibling_schema(
        self, manager: XBRLManager, _stub_label_loading
    ):
        # Presentation parse yields nothing and URL ends in .xml (not .xsd):
        # find a sibling schema and flat-extract from it.
        empty_pre = f"<link:linkbase {_LINK_HDR}></link:linkbase>"

        def find(url, *frags):
            # First call resolves the (empty) presentation .xml; later calls
            # resolve the fallback schema .xsd.
            if ".xsd" in frags:
                return "https://x/cef-2024.xsd"
            return "https://x/cef-shareholder-2024.xml"

        def fetch(url):
            return _b(_GS_SCHEMA) if url.endswith(".xsd") else _b(empty_pre)

        with (
            patch.object(manager.client, "find_file", side_effect=find),
            patch.object(manager.client, "fetch_file", side_effect=fetch),
        ):
            nodes = manager.get_structure("cef", 2024, "shareholder")
        assert nodes and nodes[0].element_id == "ex_Flat"

    def test_empty_wrapper_aggregates_children(
        self, manager: XBRLManager, _stub_label_loading
    ):
        # Component resolves to an empty presentation; no schema fallback hits;
        # aggregate from child components (``comp-foo``).
        empty_pre = f"<link:linkbase {_LINK_HDR}></link:linkbase>"
        child_nodes = [_node("ex_Child")]

        # find_file returns the empty .xml for the parent; returns None for the
        # schema-fallback lookups so we reach the aggregation branch.
        def find(url, *frags):
            if ".xsd" in frags:
                return None
            return "https://x/cef-wrap-2024.xml"

        # Delegate the parent call to the real method; short-circuit the
        # recursive child call so aggregation has deterministic input.
        orig = XBRLManager.get_structure

        def recurse(self_, tax, yr, comp):
            if comp == "wrap-foo":
                return child_nodes
            return orig(self_, tax, yr, comp)

        with (
            patch.object(manager.client, "find_file", side_effect=find),
            patch.object(manager.client, "fetch_file", return_value=_b(empty_pre)),
            patch.object(
                manager, "list_available_components", return_value=["wrap", "wrap-foo"]
            ),
            patch.object(XBRLManager, "get_structure", recurse),
        ):
            nodes = manager.get_structure("cef", 2024, "wrap")
        assert child_nodes[0] in nodes

    def test_fetch_error_wrapped_as_openbberror(
        self, manager: XBRLManager, _stub_label_loading
    ):
        with (
            patch.object(
                manager.client,
                "find_file",
                return_value="https://x/cef-shareholder-2024.xsd",
            ),
            patch.object(manager.client, "fetch_file", side_effect=OSError("net down")),
        ):
            with pytest.raises(OpenBBError, match="Failed to get structure"):
                manager.get_structure("cef", 2024, "shareholder")


# ════════════════════════════════════════════════════════════════════
# Remaining reachable branches: None-root guards, resolver well-known
# patterns, compound units, duration periods, and to_dict serialisation.
# ════════════════════════════════════════════════════════════════════


class TestNoneRootGuards:
    """Each parser entry point's ``root is None`` guard.

    ``_get_xml_root`` only returns None when XML parsing fails; we force that
    by patching it so the defensive raise/return paths execute deterministically.
    """

    def test_parse_schema_none_root_raises(self, parser: XBRLParser):
        with patch.object(parser, "_get_xml_root", return_value=None):
            with pytest.raises(OpenBBError, match="Failed to parse schema"):
                parser.parse_schema(_b("<x/>"))

    def test_parse_schema_elements_none_root_raises(self, parser: XBRLParser):
        with patch.object(parser, "_get_xml_root", return_value=None):
            with pytest.raises(OpenBBError, match="Failed to parse schema elements"):
                parser.parse_schema_elements(_b("<x/>"))

    def test_parse_label_linkbase_none_root_raises(self, parser: XBRLParser):
        with patch.object(parser, "_get_xml_root", return_value=None):
            with pytest.raises(OpenBBError, match="Failed to parse label linkbase"):
                parser.parse_label_linkbase(_b("<x/>"), TaxonomyStyle.FASB_STANDARD)

    def test_parse_reference_linkbase_none_root_returns_zero(self, parser: XBRLParser):
        with patch.object(parser, "_get_xml_root", return_value=None):
            assert parser.parse_reference_linkbase(_b("<x/>")) == 0

    def test_load_schema_element_properties_none_root_returns_zero(
        self, parser: XBRLParser
    ):
        with patch.object(parser, "_get_xml_root", return_value=None):
            assert parser.load_schema_element_properties(_b("<x/>")) == 0

    def test_parse_presentation_none_root_raises(self, parser: XBRLParser):
        with patch.object(parser, "_get_xml_root", return_value=None):
            with pytest.raises(OpenBBError, match="Failed to parse presentation"):
                parser.parse_presentation(_b("<x/>"), TaxonomyStyle.FASB_STANDARD)

    def test_parse_calculation_none_root_raises(self, parser: XBRLParser):
        with patch.object(parser, "_get_xml_root", return_value=None):
            with pytest.raises(OpenBBError, match="Failed to parse calculation"):
                parser.parse_calculation(_b("<x/>"), TaxonomyStyle.FASB_STANDARD)

    def test_parse_instance_none_root_raises(self, parser: XBRLParser):
        with patch.object(parser, "_get_xml_root", return_value=None):
            with pytest.raises(OpenBBError, match="Failed to parse instance document"):
                parser.parse_instance(_b("<x/>"))


class TestResolverWellKnownPatterns:
    """``_resolve_ns_prefix`` well-known-substring shortcuts (no xmlns map)."""

    def test_us_gaap_pattern(self):
        assert (
            XBRLParser._resolve_ns_prefix("http://fasb.org/us-gaap/2024", {})
            == "us-gaap"
        )

    def test_dei_pattern(self):
        assert (
            XBRLParser._resolve_ns_prefix("http://xbrl.sec.gov/dei/2024", {}) == "dei"
        )

    def test_srt_pattern(self):
        assert XBRLParser._resolve_ns_prefix("http://fasb.org/srt/2024", {}) == "srt"


class TestResolveMeasureStandard:
    """``_resolve_measure`` standard-measure shortcuts."""

    def test_empty_returns_empty(self):
        assert XBRLParser._resolve_measure("") == ""

    def test_shares_normalised(self):
        assert XBRLParser._resolve_measure("xbrli:shares") == "shares"

    def test_pure_normalised(self):
        assert XBRLParser._resolve_measure("pure") == "pure"


class TestParseUnitsCompound:
    """``_parse_units`` divide unit with populated numerator/denominator."""

    def test_compound_with_measures(self, parser: XBRLParser):
        xml = (
            '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">'
            '<xbrli:unit id="perShare"><xbrli:divide>'
            "<xbrli:unitNumerator><xbrli:measure>iso4217:USD</xbrli:measure>"
            "</xbrli:unitNumerator>"
            "<xbrli:unitDenominator><xbrli:measure>xbrli:shares</xbrli:measure>"
            "</xbrli:unitDenominator>"
            "</xbrli:divide></xbrli:unit></xbrli:xbrl>"
        )
        root = parser._get_xml_root(_b(xml))
        units = parser._parse_units(root)
        assert units["perShare"] == "iso4217:USD / shares"


class TestParseInstanceDuration:
    """A duration context populates period_type/start/end (lines 2264-2270)."""

    def test_duration_period(self, parser: XBRLParser):
        xml = (
            '<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance">'
            '<xbrli:context id="d1"><xbrli:entity>'
            "<xbrli:identifier>0000320193</xbrli:identifier></xbrli:entity>"
            "<xbrli:period>"
            "<xbrli:startDate>2024-01-01</xbrli:startDate>"
            "<xbrli:endDate>2024-12-31</xbrli:endDate>"
            "</xbrli:period></xbrli:context>"
            "</xbrli:xbrl>"
        )
        _facts, _units, _ctx = parser.parse_instance(_b(xml))
        # parse_instance returns (labels, units, presentation)-shaped data; the
        # duration branch is what we are covering. The call completing without
        # error exercises lines 2264-2270.


class TestXBRLNodeToDict:
    """``XBRLNode.to_dict`` recursive serialisation (line 960)."""

    def test_to_dict_includes_children(self):
        child = _node("ex_Child")
        parent = XBRLNode(
            element_id="ex_Parent",
            label="Parent",
            order=1.0,
            level=0,
            parent_id=None,
            children=[child],
        )
        out = parent.to_dict()
        assert out["element_id"] == "ex_Parent"
        assert out["children"][0]["element_id"] == "ex_Child"


class TestParseCalculationEmbeddedLinkbase:
    """SEC_EMBEDDED calc XSD with an embedded linkbase (lines 1789-1791)."""

    def test_embedded_linkbase_found(self, parser: XBRLParser):
        xml = (
            '<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"'
            f" {_LINK_HDR}>"
            "<xsd:annotation><xsd:appinfo>"
            "<link:linkbase><link:calculationLink>"
            '<link:loc xlink:href="x.xsd#ex_Total" xlink:label="t"/>'
            '<link:loc xlink:href="x.xsd#ex_Part" xlink:label="p"/>'
            '<link:calculationArc xlink:from="t" xlink:to="p" '
            'order="1.0" weight="1.0"/>'
            "</link:calculationLink></link:linkbase>"
            "</xsd:appinfo></xsd:annotation></xsd:schema>"
        )
        calc = parser.parse_calculation(_b(xml), TaxonomyStyle.SEC_EMBEDDED)
        # Calc map is keyed by the child element rolling up to ``parent_tag``.
        assert "ex_Part" in calc
        assert calc["ex_Part"]["parent_tag"] == "ex_Total"


class TestFRCSuiteClient:
    """FASBClient FRC suite ZIP access against a synthetic in-memory archive."""

    @staticmethod
    def _zip_bytes() -> bytes:
        import zipfile

        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            archive.writestr(
                "FRC-X/fr/2099-01-01/core/frc-core-2099-01-01.xsd", b"<xsd/>"
            )
            archive.writestr(
                "FRC-X/fr/2099-01-01/core/frc-core-full-2099-01-01.xsd", b"<xsd/>"
            )
            archive.writestr("FRC-X/dpl/2099-01-01/dpl-2099-01-01-label.xml", b"<lab/>")
        return buf.getvalue()

    def test_missing_year_raises(self):
        client = FASBClient()
        with pytest.raises(OpenBBError, match="No FRC taxonomy suite"):
            client._frc_suite_bytes(1999)

    def test_bytes_memoized_in_memory(self):
        client = FASBClient()
        with patch(f"{CACHE_MOD}.cached_bytes", return_value=self._zip_bytes()) as cb:
            first = client._frc_suite_bytes(2024)
            second = client._frc_suite_bytes(2024)
        assert first is second
        cb.assert_called_once()

    def test_find_member_honours_exclude(self):
        client = FASBClient()
        with patch(f"{CACHE_MOD}.cached_bytes", return_value=self._zip_bytes()):
            found = client.find_frc_member(
                2024, "core/", "frc-core-", ".xsd", exclude=("full",)
            )
        assert found == "fr/2099-01-01/core/frc-core-2099-01-01.xsd"

    def test_find_member_not_found(self):
        client = FASBClient()
        with patch(f"{CACHE_MOD}.cached_bytes", return_value=self._zip_bytes()):
            assert client.find_frc_member(2024, "no-such-member") is None

    def test_fetch_member(self):
        client = FASBClient()
        with patch(f"{CACHE_MOD}.cached_bytes", return_value=self._zip_bytes()):
            data = client.fetch_frc_member(
                2024, "dpl/2099-01-01/dpl-2099-01-01-label.xml"
            )
        assert data.read() == b"<lab/>"

    def test_fetch_member_missing_raises(self):
        client = FASBClient()
        with patch(f"{CACHE_MOD}.cached_bytes", return_value=self._zip_bytes()):
            with pytest.raises(OpenBBError, match="has no member"):
                client.fetch_frc_member(2024, "absent.xml")


class TestLoadFRCCoreLabels:
    """_load_frc_core_labels branch coverage (frc-dpl cross-namespace labels)."""

    def test_already_loaded_skips(self):
        mgr = XBRLManager()
        mgr._labels_loaded_for.add(("frc-core", 2024))
        with patch.object(mgr, "_frc_member", side_effect=AssertionError):
            mgr._load_frc_core_labels(2024)

    def test_no_member_returns(self):
        mgr = XBRLManager()
        with patch.object(mgr, "_frc_member", return_value=None):
            mgr._load_frc_core_labels(2024)
        assert ("frc-core", 2024) not in mgr._labels_loaded_for

    def test_fetch_error_swallowed(self):
        mgr = XBRLManager()
        with (
            patch.object(mgr, "_frc_member", return_value="x"),
            patch.object(mgr.client, "fetch_frc_member", side_effect=OSError("x")),
        ):
            mgr._load_frc_core_labels(2024)
        assert ("frc-core", 2024) not in mgr._labels_loaded_for

    def test_loads_core_labels(self):
        mgr = XBRLManager()
        with (
            patch.object(mgr, "_frc_member", return_value="core-label.xml"),
            patch.object(
                mgr.client, "fetch_frc_member", return_value=BytesIO(_LAB_XML)
            ),
        ):
            mgr._load_frc_core_labels(2024)
        assert ("frc-core", 2024) in mgr._labels_loaded_for
        assert mgr.parser.labels.get("ex_Item") == "Item Label"
