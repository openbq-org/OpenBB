"""XBRL Taxonomy Helper - Handles fetching and parsing of XBRL taxonomies from FASB and SEC.

This module provides a comprehensive mapping of all SEC/FASB XBRL taxonomy schemas
used across different filer categories, along with tools for fetching and parsing
taxonomy structures, labels, and presentation hierarchies.

Taxonomy Families by Filer Category
===================================

Operating Companies (10-K, 10-Q, 8-K, 20-F, S-1, DEF 14A, etc.)
---------------------------------------------------------------
  - us-gaap  : US Generally Accepted Accounting Principles (FASB). The core financial
               reporting taxonomy for all US domestic operating companies. Defines elements
               for balance sheets, income statements, cash flows, equity, and disclosures.
               Published annually by FASB. Schema: xbrl.fasb.org/us-gaap/{year}/
  - srt      : SEC Reporting Taxonomy (FASB). Supplemental elements for SEC-specific
               disclosures not in US GAAP, such as segment reporting axes, consolidation
               items, and product/service descriptions. Schema: xbrl.fasb.org/srt/{year}/
  - dei      : Document and Entity Information (SEC). Basic filer metadata: entity name,
               CIK, fiscal year end, filing date, document type, shares outstanding, etc.
               Required in every Inline XBRL filing. Schema: xbrl.sec.gov/dei/{year}/
  - ecd      : Executive Compensation Disclosure (SEC). Pay-versus-performance tables,
               equity award timing, insider trading data required by Dodd-Frank Section
               953(a). Schema: xbrl.sec.gov/ecd/{year}/
  - cyd      : Cybersecurity Disclosure (SEC). Cybersecurity risk management,
               strategy, and governance disclosures required by SEC rules.
               Covers annual risk assessments (Item 1C) and material incident reports.
               Schema: xbrl.sec.gov/cyd/{year}/
  - ffd      : Form Funding Data (SEC). Structured data for crowdfunding offerings under
               Regulation Crowdfunding (Form C filings). Schema: xbrl.sec.gov/ffd/{year}/
  - ifrs     : International Financial Reporting Standards (IFRS Foundation). Full IFRS
               taxonomy for foreign private issuers filing with the SEC using IFRS.
               Schema: xbrl.ifrs.org/taxonomy/{date}/full_ifrs/
  - rxp      : Resource Extraction Payments (SEC). Disclosure of payments made to
               governments for commercial development of oil, natural gas, or minerals,
               per Exchange Act Section 13(q). Schema: xbrl.sec.gov/rxp/{year}/
  - spac     : Special Purpose Acquisition Company (SEC). Structured data for SPAC
               registration statements, de-SPAC transactions, and projections required
               under SEC SPAC rules. Schema: xbrl.sec.gov/spac/{year}/

Investment Companies (N-1A, N-2, N-CSR, 485BPOS, 497, N-3, N-4, N-6, etc.)
--------------------------------------------------------------------------
  - cef      : Closed-End Fund (SEC). Annual report data and prospectus information for
               closed-end management investment companies (N-2/N-CSR filers).
               Schema: xbrl.sec.gov/cef/{year}/
  - oef      : Open-End Fund (SEC). Risk/return summary (oef-rr) and shareholder report
               (oef-sr) data for open-end management investment companies (N-1A/485/497).
               Schema: xbrl.sec.gov/oef/{year}/
  - vip      : Variable Insurance Products (SEC). Prospectus data for variable annuity
               and variable life insurance contracts filed on Forms N-3, N-4, and N-6.
               Schema: xbrl.sec.gov/vip/{year}/
  - fnd      : Fund (SEC). Combined fund disclosure framework covering closed-end funds
               (fnd-cef), open-end funds (fnd-oef), and unit investment trusts (fnd-uit).
               Schema: xbrl.sec.gov/fnd/{year}/

Self-Regulatory Organizations (Form 17A-27)
-------------------------------------------
  - sro      : Self-Regulatory Organization (SEC). Structured data for SRO financial
               reports filed on Form 17A-27 (FINRA, exchanges, clearing agencies).
               Schema: xbrl.sec.gov/sro/{year}/

Security-Based Swap Data Repositories & Execution Facilities (Form SBSEF)
-------------------------------------------------------------------------
  - sbs      : Security-Based Swap (SEC). Registration applications, financial resource
               reports, and compliance reports for Security-Based Swap Execution
               Facilities (SBSEFs) and Swap Data Repositories (SDRs).
               Schema: xbrl.sec.gov/sbs/{year}/

Nationally Recognized Statistical Rating Organizations (NRSROs)
---------------------------------------------------------------
  - rocr     : Record of Credit Ratings (SEC). XBRL-format credit rating history
               disclosures required by Exchange Act Rule 17g-7. Not EDGAR-filed;
               posted on NRSRO websites. Schema: xbrl.sec.gov/rocr/2015/

Common / Reference Taxonomies (automatically or explicitly imported)
--------------------------------------------------------------------
  - country  : Country codes (SEC). ISO 3166-1 country identifiers used as dimension
               members in geographic segment reporting. Schema: xbrl.sec.gov/country/
  - currency : Currency codes (SEC). ISO 4217 currency identifiers for monetary item
               tagging and foreign currency disclosures. Schema: xbrl.sec.gov/currency/
  - exch     : Exchange codes (SEC). Stock exchange identifiers (NYSE, NASDAQ, etc.)
               used in dei:SecurityExchangeName. Schema: xbrl.sec.gov/exch/
  - naics    : NAICS codes (SEC). North American Industry Classification System codes
               for industry identification. Schema: xbrl.sec.gov/naics/
  - sic      : SIC codes (SEC). Standard Industrial Classification codes for legacy
               industry identification. Schema: xbrl.sec.gov/sic/
  - stpr     : State/Province codes (SEC). US state and Canadian province identifiers
               used as dimension members in geographic disclosures. Schema: xbrl.sec.gov/stpr/
  - snj      : Subnational Jurisdiction codes (SEC). Additional sub-national geographic
               identifiers beyond stpr. Schema: xbrl.sec.gov/snj/

SEC Taxonomy Reference Links
============================
  - Operating Companies:     https://www.sec.gov/data-research/taxonomies-schemas/standard-taxonomies/operating-companies
  - Investment Companies:    https://www.sec.gov/data-research/taxonomies-schemas/standard-taxonomies/investment-companies
  - Self-Regulatory Orgs:    https://www.sec.gov/data-research/standard-taxonomies/self-regulatory-organizations
  - SBS Repos & Facilities:  https://www.sec.gov/data-research/standard-taxonomies/security-based-swap-data-repositories-and-execution-facilities
  - NRSROs:                  https://www.sec.gov/data-research/standard-taxonomies/nationally-recognized-statistical-rating-organizations
  - EDGAR Taxonomy XML Index: https://www.sec.gov/info/edgar/edgartaxonomies.xml
"""  # noqa: E501

# flake8: noqa: PLR0912, PLR0914

import time
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from io import BytesIO
from typing import Any
from xml.etree.ElementTree import Element, ParseError

import requests
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.app.model.abstract.warning import OpenBBWarning

LINKBASE_FETCH_ATTEMPTS = 3
LINKBASE_RETRY_BACKOFF = 1.0

# Constants for XBRL Namespaces
NS = {
    "link": "http://www.xbrl.org/2003/linkbase",
    "xlink": "http://www.w3.org/1999/xlink",
    "xbrli": "http://www.xbrl.org/2003/instance",
    "xs": "http://www.w3.org/2001/XMLSchema",
    "xsd": "http://www.w3.org/2001/XMLSchema",
}


class TaxonomyStyle(Enum):
    """Defines the style of taxonomy.

    FASB_STANDARD: Taxonomies hosted on xbrl.fasb.org with separate label XML files
        and presentation linkbases in a stm/ subdirectory (us-gaap, srt).
    SEC_EMBEDDED: Taxonomies hosted on xbrl.sec.gov where labels and linkbases
        are embedded within the XSD schema file itself (dei, country, currency,
        stpr, ecd, cyd, cef, oef, vip, fnd, sro, sbs, etc.).
    SEC_STANDALONE: SEC taxonomies that have separate _lab.xsd label files
        alongside the main schema (distinct from embedded linkbase style, used
        by fnd, oef, vip, sbs, rxp, sro which have _lab.xsd files).
    EXTERNAL: Non-SEC/FASB taxonomies such as IFRS hosted on xbrl.ifrs.org.
    STATIC: Taxonomies with fixed schema URLs that do not follow the standard
        {year} versioning pattern (e.g., rocr 2015).
    """

    FASB_STANDARD = auto()
    SEC_EMBEDDED = auto()
    SEC_STANDALONE = auto()
    EXTERNAL = auto()
    STATIC = auto()


class TaxonomyCategory(Enum):
    """The SEC filer category a taxonomy belongs to."""

    OPERATING_COMPANY = "operating_company"
    INVESTMENT_COMPANY = "investment_company"
    SELF_REGULATORY_ORG = "self_regulatory_org"
    SBS_REPOSITORY = "sbs_repository"
    NRSRO = "nrsro"
    COMMON_REFERENCE = "common_reference"


@dataclass
class TaxonomyConfig:
    """Configuration for each taxonomy type.

    Attributes
    ----------
    base_url_template : str
        URL template with ``{year}`` placeholder for the taxonomy root directory.
    style : TaxonomyStyle
        How labels/linkbases are structured (embedded, separate file, etc.).
    label_file_pattern : str
        Relative path pattern (from base URL) to the label linkbase file.
        Use ``{year}`` as a placeholder for the taxonomy year.
    presentation_pattern_regex : str
        Regex to discover available presentation components from directory listings.
        Use ``{year}`` as a placeholder that will be formatted before compilation.
    presentation_file_template : str
        Relative path template for fetching a specific presentation linkbase.
        Use ``{name}`` for the component name and ``{year}`` for the year.
    label : str
        Short human-readable name for display.
    description : str
        Detailed description of what the taxonomy covers and who uses it.
    category : TaxonomyCategory
        The SEC filer category this taxonomy belongs to.
    has_label_linkbase : bool
        Whether the taxonomy has a separate or embedded label linkbase that
        can be parsed for human-readable element labels.
    sec_reference_url : str
        URL to the SEC's taxonomy list page for the relevant filer category.
    """

    base_url_template: str
    style: TaxonomyStyle
    label_file_pattern: str
    presentation_pattern_regex: str
    presentation_file_template: str
    label: str = ""
    description: str = ""
    category: TaxonomyCategory = TaxonomyCategory.OPERATING_COMPANY
    has_label_linkbase: bool = True
    sec_reference_url: str = ""


# ---------------------------------------------------------------------------
# Complete taxonomy registry
# ---------------------------------------------------------------------------

TAXONOMIES: dict[str, TaxonomyConfig] = {
    # ===== FASB Taxonomies (Operating Companies) =====
    "us-gaap": TaxonomyConfig(
        base_url_template="https://xbrl.fasb.org/us-gaap/{year}/",
        style=TaxonomyStyle.FASB_STANDARD,
        label_file_pattern="elts/us-gaap-lab-{year}.xml",
        presentation_pattern_regex=r"us-gaap-stm-([a-zA-Z0-9-]+)-pre-{year}\.xml",
        presentation_file_template="stm/us-gaap-stm-{name}-pre-{year}.xml",
        label="US GAAP",
        description=(
            "US Generally Accepted Accounting Principles taxonomy maintained by FASB. "
            "Defines elements for financial statements (balance sheet, income statement, "
            "cash flows, stockholders' equity) and all required disclosures for domestic "
            "operating companies."
        ),
        category=TaxonomyCategory.OPERATING_COMPANY,
        has_label_linkbase=True,
        sec_reference_url="https://www.sec.gov/data-research/taxonomies-schemas/standard-taxonomies/operating-companies",
    ),
    "srt": TaxonomyConfig(
        base_url_template="https://xbrl.fasb.org/srt/{year}/",
        style=TaxonomyStyle.FASB_STANDARD,
        label_file_pattern="elts/srt-lab-{year}.xml",
        presentation_pattern_regex=r"srt-stm-([a-zA-Z0-9-]+)-pre-{year}\.xml",
        presentation_file_template="stm/srt-stm-{name}-pre-{year}.xml",
        label="SEC Reporting Taxonomy",
        description=(
            "Supplemental taxonomy maintained by FASB for SEC-specific reporting elements "
            "not in US GAAP, such as segment reporting axes, consolidation elimination "
            "items, product/service descriptions, and statistical measures."
        ),
        category=TaxonomyCategory.OPERATING_COMPANY,
        has_label_linkbase=True,
        sec_reference_url="https://www.sec.gov/data-research/taxonomies-schemas/standard-taxonomies/operating-companies",
    ),
    # ===== SEC Taxonomies — Operating Companies =====
    "dei": TaxonomyConfig(
        base_url_template="https://xbrl.sec.gov/dei/{year}/",
        style=TaxonomyStyle.SEC_EMBEDDED,
        label_file_pattern="dei-{year}_lab.xsd",
        presentation_pattern_regex=r"(dei)-{year}_pre\.xsd",
        presentation_file_template="dei-{year}_pre.xsd",
        label="Document & Entity Information",
        description=(
            "Required in every Inline XBRL filing. Contains elements for entity name, "
            "CIK, fiscal year end, filing date, document type, shares outstanding, "
            "trading symbol, and other basic filer metadata."
        ),
        category=TaxonomyCategory.COMMON_REFERENCE,
        has_label_linkbase=True,
        sec_reference_url="https://www.sec.gov/data-research/taxonomies-schemas/standard-taxonomies/operating-companies",
    ),
    "ecd": TaxonomyConfig(
        base_url_template="https://xbrl.sec.gov/ecd/{year}/",
        style=TaxonomyStyle.SEC_EMBEDDED,
        label_file_pattern="ecd-{year}_lab.xsd",
        presentation_pattern_regex=r"(ecd)-{year}_pre\.xsd",
        presentation_file_template="ecd-{year}_pre.xsd",
        label="Executive Compensation Disclosure",
        description=(
            "Pay-versus-performance tables, tabular lists of most important financial "
            "performance measures, equity award timing disclosures, and insider trading "
            "policies required by Dodd-Frank Section 953(a) and related SEC rules."
        ),
        category=TaxonomyCategory.OPERATING_COMPANY,
        has_label_linkbase=False,
        sec_reference_url="https://www.sec.gov/data-research/taxonomies-schemas/standard-taxonomies/operating-companies",
    ),
    "cyd": TaxonomyConfig(
        base_url_template="https://xbrl.sec.gov/cyd/{year}/",
        style=TaxonomyStyle.SEC_EMBEDDED,
        label_file_pattern="cyd-{year}_lab.xsd",
        presentation_pattern_regex=r"(cyd)-{year}_pre\.xsd",
        presentation_file_template="cyd-{year}_pre.xsd",
        label="Cybersecurity Disclosure",
        description=(
            "Cybersecurity risk management, strategy, and governance disclosures "
            "required by SEC rules. Includes structured data for annual risk "
            "management assessments (Item 1C) and material cybersecurity incident "
            "reports (8-K Item 1.05). Covers risk management processes, board "
            "oversight, management roles, and incident details."
        ),
        category=TaxonomyCategory.OPERATING_COMPANY,
        has_label_linkbase=False,
        sec_reference_url="https://www.sec.gov/data-research/taxonomies-schemas/standard-taxonomies/operating-companies",
    ),
    "ffd": TaxonomyConfig(
        base_url_template="https://xbrl.sec.gov/ffd/{year}/",
        style=TaxonomyStyle.SEC_EMBEDDED,
        label_file_pattern="ffd-{year}_lab.xsd",
        presentation_pattern_regex=r"(ffd)-{year}_pre\.xsd",
        presentation_file_template="ffd-{year}_pre.xsd",
        label="Form Funding Data",
        description=(
            "Structured data for crowdfunding offerings under Regulation Crowdfunding "
            "(Form C filings). Also used by investment companies for certain registered "
            "offerings."
        ),
        category=TaxonomyCategory.OPERATING_COMPANY,
        has_label_linkbase=False,
        sec_reference_url="https://www.sec.gov/data-research/taxonomies-schemas/standard-taxonomies/operating-companies",
    ),
    "rxp": TaxonomyConfig(
        base_url_template="https://xbrl.sec.gov/rxp/{year}/",
        style=TaxonomyStyle.SEC_EMBEDDED,
        label_file_pattern="rxp-{year}_lab.xsd",
        presentation_pattern_regex=r"(rxp)-{year}_pre\.xsd",
        presentation_file_template="rxp-{year}_pre.xsd",
        label="Resource Extraction Payments",
        description=(
            "Disclosure of payments made by resource extraction issuers to foreign "
            "governments or the US Federal Government for the commercial development "
            "of oil, natural gas, or minerals, as required by Exchange Act Section 13(q)."
        ),
        category=TaxonomyCategory.OPERATING_COMPANY,
        has_label_linkbase=False,
        sec_reference_url="https://www.sec.gov/data-research/taxonomies-schemas/standard-taxonomies/operating-companies",
    ),
    "spac": TaxonomyConfig(
        base_url_template="https://xbrl.sec.gov/spac/{year}/",
        style=TaxonomyStyle.SEC_EMBEDDED,
        label_file_pattern="spac-{year}_lab.xsd",
        presentation_pattern_regex=r"(spac)-{year}_pre\.xsd",
        presentation_file_template="spac-{year}_pre.xsd",
        label="Special Purpose Acquisition Company",
        description=(
            "Structured data for SPAC registration statements (spac-reg), de-SPAC "
            "transactions (spac-despac), financial projections (spac-proj), and "
            "completed business combinations (spac-com) required under SEC SPAC rules."
        ),
        category=TaxonomyCategory.OPERATING_COMPANY,
        has_label_linkbase=False,
        sec_reference_url="https://www.sec.gov/data-research/taxonomies-schemas/standard-taxonomies/operating-companies",
    ),
    # ===== IFRS Taxonomy (Foreign Private Issuers) =====
    "ifrs": TaxonomyConfig(
        base_url_template="https://xbrl.ifrs.org/taxonomy/{year}/",
        style=TaxonomyStyle.EXTERNAL,
        label_file_pattern="full_ifrs/labels/lab_full_ifrs-en_{year}.xml",
        presentation_pattern_regex=r"",
        presentation_file_template="",
        label="International Financial Reporting Standards",
        description=(
            "Full IFRS taxonomy for foreign private issuers filing with the SEC "
            "using International Financial Reporting Standards. Published annually "
            "by the IFRS Foundation. Contains 5000+ elements organized by IAS/IFRS "
            "standard with presentation, label, and definition linkbases. Components "
            "correspond to individual standards (ias_1, ifrs_7, etc.)."
        ),
        category=TaxonomyCategory.OPERATING_COMPANY,
        has_label_linkbase=True,
        sec_reference_url="https://www.sec.gov/data-research/taxonomies-schemas/standard-taxonomies/operating-companies",
    ),
    # ===== UK FRC Taxonomy Suite =====
    "frc-core": TaxonomyConfig(
        base_url_template="https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/frc-taxonomies/",
        style=TaxonomyStyle.EXTERNAL,
        label_file_pattern="",
        presentation_pattern_regex=r"",
        presentation_file_template="",
        label="FRC Core (UK GAAP / FRS)",
        description=(
            "Core UK financial reporting taxonomy from the Financial Reporting"
            " Council taxonomy suite. Defines the shared elements (statement of"
            " financial position, income statement, equity, cash flows, and"
            " notes) underlying FRS 101, FRS 102, and the UK IFRS extensions"
            " used by UK and Irish companies. Published annually; the basis the"
            " FRC Detailed Profit & Loss and HMRC CT600 computations build on."
        ),
        category=TaxonomyCategory.COMMON_REFERENCE,
        has_label_linkbase=True,
        sec_reference_url="https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/frc-taxonomies/",
    ),
    "frc-dpl": TaxonomyConfig(
        base_url_template="https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/frc-taxonomies/",
        style=TaxonomyStyle.EXTERNAL,
        label_file_pattern="",
        presentation_pattern_regex=r"",
        presentation_file_template="",
        label="FRC Detailed Profit & Loss",
        description=(
            "UK Detailed Profit & Loss taxonomy from the Financial Reporting"
            " Council taxonomy suite, referenced by HMRC Corporation Tax"
            " computations (CT600). Defines the detailed trading, cost-of-sales,"
            " administrative-expense, and other income/expense line items that"
            " expand the FRC core profit-and-loss statement. Bundled in the FRC"
            " suite from 2022 onward; depends on the FRC core taxonomy for"
            " shared UK accounting elements."
        ),
        category=TaxonomyCategory.COMMON_REFERENCE,
        has_label_linkbase=True,
        sec_reference_url="https://www.frc.org.uk/library/standards-codes-policy/accounting-and-reporting/frc-taxonomies/",
    ),
    # ===== SEC Taxonomies — Investment Companies =====
    "cef": TaxonomyConfig(
        base_url_template="https://xbrl.sec.gov/cef/{year}/",
        style=TaxonomyStyle.SEC_EMBEDDED,
        label_file_pattern="cef-{year}_lab.xsd",
        presentation_pattern_regex=r"(cef)-{year}_pre\.xsd",
        presentation_file_template="cef-{year}_pre.xsd",
        label="Closed-End Fund",
        description=(
            "Annual report data and prospectus information for closed-end management "
            "investment companies. Used by N-2 and N-CSR filers for structured fund "
            "disclosures including fee tables, financial highlights, and portfolio data."
        ),
        category=TaxonomyCategory.INVESTMENT_COMPANY,
        has_label_linkbase=False,
        sec_reference_url="https://www.sec.gov/data-research/taxonomies-schemas/standard-taxonomies/investment-companies",
    ),
    "oef": TaxonomyConfig(
        base_url_template="https://xbrl.sec.gov/oef/{year}/",
        style=TaxonomyStyle.SEC_EMBEDDED,
        label_file_pattern="oef-{year}_lab.xsd",
        presentation_pattern_regex=r"oef-(rr|sr)-{year}\.xsd",
        presentation_file_template="oef-{name}-{year}.xsd",
        label="Open-End Fund",
        description=(
            "Risk/return summary (oef-rr) and shareholder report (oef-sr) data for "
            "open-end management investment companies. Used by N-1A, 485BPOS, and 497 "
            "filers. Covers fee tables, performance data, and investment objectives."
        ),
        category=TaxonomyCategory.INVESTMENT_COMPANY,
        has_label_linkbase=False,
        sec_reference_url="https://www.sec.gov/data-research/taxonomies-schemas/standard-taxonomies/investment-companies",
    ),
    "vip": TaxonomyConfig(
        base_url_template="https://xbrl.sec.gov/vip/{year}/",
        style=TaxonomyStyle.SEC_EMBEDDED,
        label_file_pattern="vip-{year}_lab.xsd",
        presentation_pattern_regex=r"vip-(n3|n4|n6)-{year}\.xsd",
        presentation_file_template="vip-{name}-{year}.xsd",
        label="Variable Insurance Products",
        description=(
            "Prospectus data for variable annuity and variable life insurance contracts. "
            "Includes sub-schemas for Forms N-3 (vip-n3), N-4 (vip-n4), and N-6 (vip-n6) "
            "covering fee tables, benefits, and portfolio company information."
        ),
        category=TaxonomyCategory.INVESTMENT_COMPANY,
        has_label_linkbase=False,
        sec_reference_url="https://www.sec.gov/data-research/taxonomies-schemas/standard-taxonomies/investment-companies",
    ),
    "fnd": TaxonomyConfig(
        base_url_template="https://xbrl.sec.gov/fnd/{year}/",
        style=TaxonomyStyle.SEC_STANDALONE,
        label_file_pattern="fnd-{year}_lab.xsd",
        presentation_pattern_regex=r"fnd-(cef|oef|uit)-{year}\.xsd",
        presentation_file_template="fnd-{name}-{year}.xsd",
        label="Fund",
        description=(
            "Combined fund disclosure framework for investment companies. Includes "
            "sub-schemas for closed-end funds (fnd-cef), open-end funds (fnd-oef), "
            "and unit investment trusts (fnd-uit). Has its own label linkbase."
        ),
        category=TaxonomyCategory.INVESTMENT_COMPANY,
        has_label_linkbase=True,
        sec_reference_url="https://www.sec.gov/data-research/taxonomies-schemas/standard-taxonomies/investment-companies",
    ),
    # ===== SEC Taxonomies — Self-Regulatory Organizations =====
    "sro": TaxonomyConfig(
        base_url_template="https://xbrl.sec.gov/sro/{year}/",
        style=TaxonomyStyle.SEC_EMBEDDED,
        label_file_pattern="sro-{year}_lab.xsd",
        presentation_pattern_regex=r"sro-(17ad27)-{year}\.xsd",
        presentation_file_template="sro-{name}-{year}.xsd",
        label="Self-Regulatory Organization",
        description=(
            "Financial reports filed on Form 17A-27 by self-regulatory organizations "
            "(FINRA, national securities exchanges, registered clearing agencies). "
            "Covers audit, financial statements, and regulatory capital data."
        ),
        category=TaxonomyCategory.SELF_REGULATORY_ORG,
        has_label_linkbase=False,
        sec_reference_url="https://www.sec.gov/data-research/standard-taxonomies/self-regulatory-organizations",
    ),
    # ===== SEC Taxonomies — Security-Based Swaps =====
    "sbs": TaxonomyConfig(
        base_url_template="https://xbrl.sec.gov/sbs/{year}/",
        style=TaxonomyStyle.SEC_EMBEDDED,
        label_file_pattern="sbs-{year}_lab.xsd",
        presentation_pattern_regex=r"sbs-(sbsef(?:-(?:cco|com|fex|fin|ocx))?)-{year}\.xsd",
        presentation_file_template="sbs-{name}-{year}.xsd",
        label="Security-Based Swap",
        description=(
            "Registration applications, financial resource reports, and compliance "
            "reports for Security-Based Swap Execution Facilities (SBSEFs) and Swap "
            "Data Repositories (SDRs). Sub-schemas: sbs-sbsef, sbs-sbsef-cco (Chief "
            "Compliance Officer), sbs-sbsef-com (compliance), sbs-sbsef-fex (financial "
            "exhibits), sbs-sbsef-fin (financial resources), sbs-sbsef-ocx (other)."
        ),
        category=TaxonomyCategory.SBS_REPOSITORY,
        has_label_linkbase=False,
        sec_reference_url=(
            "https://www.sec.gov/data-research/standard-taxonomies/"
            "security-based-swap-data-repositories-and-execution-facilities"
        ),
    ),
    # ===== NRSRO Taxonomy =====
    "rocr": TaxonomyConfig(
        base_url_template="https://xbrl.sec.gov/rocr/2015/",
        style=TaxonomyStyle.STATIC,
        label_file_pattern="ratings-lab-2015-03-31.xml",
        presentation_pattern_regex=r"ratings-pre-2015-03-31\.xml",
        presentation_file_template="ratings-pre-2015-03-31.xml",
        label="Record of Credit Ratings",
        description=(
            "Credit rating history disclosures required by Exchange Act Rule 17g-7 for "
            "Nationally Recognized Statistical Rating Organizations (NRSROs). Not filed "
            "via EDGAR; posted on NRSRO websites. Static 2015 taxonomy."
        ),
        category=TaxonomyCategory.NRSRO,
        has_label_linkbase=True,
        sec_reference_url="https://www.sec.gov/data-research/standard-taxonomies/nationally-recognized-statistical-rating-organizations",
    ),
    # ===== Common / Reference Taxonomies =====
    "country": TaxonomyConfig(
        base_url_template="https://xbrl.sec.gov/country/{year}/",
        style=TaxonomyStyle.SEC_EMBEDDED,
        label_file_pattern="country-entire-{year}.xsd",
        presentation_pattern_regex=r"country-{year}_pre\.xsd",
        presentation_file_template="country-{year}_pre.xsd",
        label="Country Codes",
        description=(
            "ISO 3166-1 country identifiers used as dimension members for geographic "
            "segment reporting in SEC filings."
        ),
        category=TaxonomyCategory.COMMON_REFERENCE,
        has_label_linkbase=True,
        sec_reference_url="https://www.sec.gov/data-research/taxonomies-schemas/standard-taxonomies/operating-companies",
    ),
    "currency": TaxonomyConfig(
        base_url_template="https://xbrl.sec.gov/currency/{year}/",
        style=TaxonomyStyle.SEC_EMBEDDED,
        label_file_pattern="currency-entire-{year}.xsd",
        presentation_pattern_regex=r"currency-{year}_pre\.xsd",
        presentation_file_template="currency-{year}_pre.xsd",
        label="Currency Codes",
        description=(
            "ISO 4217 currency identifiers for monetary item tagging and foreign "
            "currency disclosures in SEC filings."
        ),
        category=TaxonomyCategory.COMMON_REFERENCE,
        has_label_linkbase=True,
        sec_reference_url="https://www.sec.gov/data-research/taxonomies-schemas/standard-taxonomies/operating-companies",
    ),
    "exch": TaxonomyConfig(
        base_url_template="https://xbrl.sec.gov/exch/{year}/",
        style=TaxonomyStyle.SEC_EMBEDDED,
        label_file_pattern="exch-entire-{year}.xsd",
        presentation_pattern_regex=r"exch-{year}_pre\.xsd",
        presentation_file_template="exch-{year}_pre.xsd",
        label="Exchange Codes",
        description=(
            "Stock exchange identifiers (NYSE, NASDAQ, CBOE, etc.) used in "
            "dei:SecurityExchangeName elements in SEC filings."
        ),
        category=TaxonomyCategory.COMMON_REFERENCE,
        has_label_linkbase=True,
        sec_reference_url="https://www.sec.gov/data-research/taxonomies-schemas/standard-taxonomies/operating-companies",
    ),
    "naics": TaxonomyConfig(
        base_url_template="https://xbrl.sec.gov/naics/{year}/",
        style=TaxonomyStyle.SEC_EMBEDDED,
        label_file_pattern="naics-entire-{year}.xsd",
        presentation_pattern_regex=r"naics-{year}_pre\.xsd",
        presentation_file_template="naics-{year}_pre.xsd",
        label="NAICS Codes",
        description=(
            "North American Industry Classification System codes for industry "
            "identification and classification in SEC filings."
        ),
        category=TaxonomyCategory.COMMON_REFERENCE,
        has_label_linkbase=True,
        sec_reference_url="https://www.sec.gov/data-research/taxonomies-schemas/standard-taxonomies/operating-companies",
    ),
    "sic": TaxonomyConfig(
        base_url_template="https://xbrl.sec.gov/sic/{year}/",
        style=TaxonomyStyle.SEC_EMBEDDED,
        label_file_pattern="sic-entire-{year}.xsd",
        presentation_pattern_regex=r"sic-{year}_pre\.xsd",
        presentation_file_template="sic-{year}_pre.xsd",
        label="SIC Codes",
        description=(
            "Standard Industrial Classification codes for legacy industry "
            "identification used by SEC for filer categorization."
        ),
        category=TaxonomyCategory.COMMON_REFERENCE,
        has_label_linkbase=True,
        sec_reference_url="https://www.sec.gov/data-research/taxonomies-schemas/standard-taxonomies/operating-companies",
    ),
    "stpr": TaxonomyConfig(
        base_url_template="https://xbrl.sec.gov/stpr/{year}/",
        style=TaxonomyStyle.SEC_EMBEDDED,
        label_file_pattern="stpr-entire-{year}.xsd",
        presentation_pattern_regex=r"stpr-{year}_pre\.xsd",
        presentation_file_template="stpr-{year}_pre.xsd",
        label="State/Province Codes",
        description=(
            "US state and Canadian province identifiers used as dimension members "
            "for geographic disclosures in SEC filings."
        ),
        category=TaxonomyCategory.COMMON_REFERENCE,
        has_label_linkbase=True,
        sec_reference_url="https://www.sec.gov/data-research/taxonomies-schemas/standard-taxonomies/operating-companies",
    ),
    "snj": TaxonomyConfig(
        base_url_template="https://xbrl.sec.gov/snj/{year}/",
        style=TaxonomyStyle.SEC_EMBEDDED,
        label_file_pattern="snj-{year}_doc.xsd",
        presentation_pattern_regex=r"snj-{year}_pre\.xsd",
        presentation_file_template="snj-{year}_pre.xsd",
        label="Subnational Jurisdiction Codes",
        description=(
            "Additional sub-national geographic identifiers beyond stpr, used for "
            "jurisdiction-level disclosures (e.g., resource extraction locations)."
        ),
        category=TaxonomyCategory.COMMON_REFERENCE,
        has_label_linkbase=True,
        sec_reference_url="https://www.sec.gov/data-research/taxonomies-schemas/standard-taxonomies/operating-companies",
    ),
}


def _sec_label_resolver(
    taxonomy: str, *, entire: bool = False, suffix: str = "_lab.xsd"
) -> Callable[[str], str]:
    """Build a URL mapper from an imported SEC schema URL to its label-bearing file."""

    def _resolve(url: str) -> str:
        base, sep, filename = url.rpartition("/")
        if (
            f"{taxonomy}-entire-" in filename
            or "_lab" in filename
            or "-lab-" in filename
            or "_doc" in filename
        ):
            return url
        if "-01-31.xsd" in filename:
            new_name = filename.replace(f"{taxonomy}-", f"{taxonomy}-lab-", 1).replace(
                ".xsd", ".xml"
            )
        elif entire:
            new_name = filename.replace(f"{taxonomy}-", f"{taxonomy}-entire-", 1)
        else:
            new_name = filename.replace(".xsd", suffix)
        return f"{base}{sep}{new_name}"

    return _resolve


# Label URL resolution for imported schemas
TAXONOMY_LABEL_URLS: dict[str, Any] = {
    # FASB taxonomies — separate _lab.xml label files
    "xbrl.fasb.org/us-gaap": lambda url: url.replace(
        "us-gaap-", "us-gaap-lab-"
    ).replace(".xsd", ".xml"),
    "xbrl.fasb.org/srt": lambda url: url.replace("srt-", "srt-lab-").replace(
        ".xsd", ".xml"
    ),
    # SEC taxonomies — separate _lab.xsd files
    "xbrl.sec.gov/dei": _sec_label_resolver("dei"),
    "xbrl.sec.gov/fnd": _sec_label_resolver("fnd"),
    # SEC reference taxonomies — labels are embedded in -entire-{year}.xsd (or _doc.xsd for snj)
    "xbrl.sec.gov/country": _sec_label_resolver("country", entire=True),
    "xbrl.sec.gov/currency": _sec_label_resolver("currency", entire=True),
    "xbrl.sec.gov/stpr": _sec_label_resolver("stpr", entire=True),
    "xbrl.sec.gov/snj": _sec_label_resolver("snj", suffix="_doc.xsd"),
    "xbrl.sec.gov/exch": _sec_label_resolver("exch", entire=True),
    "xbrl.sec.gov/naics": _sec_label_resolver("naics", entire=True),
    "xbrl.sec.gov/sic": _sec_label_resolver("sic", entire=True),
    # Taxonomies without separate label files (labels are in element names only):
    # ecd, cyd, ffd, rxp, spac, cef, oef, vip, sro, sbs
    # FRC core/dpl labels are read from the suite ZIP, not derived from a URL.
}


# IFRS version date mapping (year int → full date string for URLs)
# The IFRS Foundation publishes one taxonomy per year, typically in March,
# but the exact date varies.  Discovered dynamically from edgartaxonomies.xml
# with hardcoded fallbacks for known years.

_IFRS_VERSION_DATES_FALLBACK: dict[int, str] = {
    2025: "2025-03-27",
    2024: "2024-03-27",
    2023: "2023-03-23",
    2022: "2022-03-24",
    2021: "2021-03-24",
    2020: "2020-03-16",
}

# FRC taxonomy suites are published as one ZIP archive per year on frc.org.uk.
# The document identifiers are opaque, so each year's archive is mapped here.
_FRC_SUITE_ZIPS: dict[int, str] = {
    2014: "https://www.frc.org.uk/documents/5849/FRC_Taxomomies_2014_Zip_File.zip",
    2018: "https://www.frc.org.uk/documents/3917/FRC_2018_Taxonomy_v1-0-0_December-2017_Zip_File.zip",
    2019: "https://www.frc.org.uk/documents/5687/FRC_2019_Taxonomy_v1-1-0_Zip_File.zip",
    2021: "https://www.frc.org.uk/documents/3923/FRC_2021_Taxonomy_v1-0-0_Zip_File.zip",
    2022: "https://www.frc.org.uk/documents/969/FRC-2022-Taxonomy.zip",
    2023: "https://www.frc.org.uk/documents/372/The_2023_Taxonomy_suite_v1.0.1.zip",
    2024: "https://www.frc.org.uk/documents/6566/FRC-2024-Taxonomy-v1.0.0_GJp67Do.zip",
    2025: "https://www.frc.org.uk/documents/7759/FRC-2025-Taxonomy-v1.0.0_LK4mek8.zip",
    2026: "https://www.frc.org.uk/documents/8907/FRC-2026-Taxonomy-v1.0.0.zip",
}

# frc-core ships in every suite; the Detailed Profit & Loss (dpl) taxonomy only
# entered the suite in 2022.
_FRC_CORE_YEARS: list[int] = sorted(_FRC_SUITE_ZIPS, reverse=True)
_FRC_DPL_YEARS: list[int] = [year for year in _FRC_CORE_YEARS if year >= 2022]

_FRC_TAXONOMIES: frozenset[str] = frozenset({"frc-core", "frc-dpl"})

# Suite archives are immutable once published; cache them for a week.
_FRC_SUITE_CACHE_TTL: int = 3600 * 24 * 7

# Member resolution within a suite, keyed by taxonomy then file kind. Each value
# is (required-substrings, excluded-substrings) matched against member paths.
# File names vary across releases (e.g. dpl-2022.xsd vs dpl-2024-01-01.xsd, and
# the 2014 core uses a 2014-09-01 date), so members are matched by fragment.
_FRC_MEMBER_FRAGMENTS: dict[str, dict[str, tuple[tuple[str, ...], tuple[str, ...]]]] = {
    "frc-core": {
        "schema": (("core/", "frc-core-", ".xsd"), ("full",)),
        "label": (("core/", "frc-core-", "-label.xml"), ("full",)),
        "presentation": (("core/", "frc-core-", "-presentation.xml"), ("full",)),
    },
    "frc-dpl": {
        "schema": (("dpl/", "dpl-", ".xsd"), ("dpl-core", "full")),
        "label": (("dpl/", "dpl-", "-label.xml"), ("dpl-core", "full")),
        "presentation": (("dpl/", "dpl-", "-presentation.xml"), ("dpl-core", "full")),
    },
}

# Module-level cache populated on first access
_ifrs_version_dates_cache: dict[int, str] | None = None


def _discover_ifrs_dates() -> dict[int, str]:
    """Discover IFRS taxonomy version dates from SEC's edgartaxonomies.xml.

    Parses the IFRS ``<Href>`` entries to extract the date-based directory
    path (e.g. ``2025-03-27``), then maps each to its calendar year.

    Falls back to hardcoded ``_IFRS_VERSION_DATES_FALLBACK`` on failure.
    Results are cached so the network request happens at most once per
    process lifetime.
    """
    import re

    global _ifrs_version_dates_cache  # noqa: PLW0603

    if _ifrs_version_dates_cache is not None:
        return _ifrs_version_dates_cache

    discovered: dict[int, str] = {}
    try:
        from openbb_sec.utils.cache import cached_text

        text = cached_text(
            "https://www.sec.gov/info/edgar/edgartaxonomies.xml",
            expire=3600 * 24 * 7,
        )
        # Extract all IFRS date strings from href URLs
        # e.g. https://xbrl.ifrs.org/taxonomy/2025-03-27/...
        dates = set(re.findall(r"xbrl\.ifrs\.org/taxonomy/(\d{4}-\d{2}-\d{2})/", text))
        for d in dates:
            year = int(d[:4])
            discovered[year] = d
    except Exception:  # noqa: S110
        pass

    # Merge: discovered dates take precedence, fallback fills gaps
    merged = {**_IFRS_VERSION_DATES_FALLBACK, **discovered}
    _ifrs_version_dates_cache = merged
    return merged


def get_ifrs_version_dates() -> dict[int, str]:
    """Return the IFRS year → date mapping, discovering new years automatically."""
    return _discover_ifrs_dates()


# ---------------------------------------------------------------------------
# IFRS standard names (IAS, IFRS, IFRIC, SIC)
# ---------------------------------------------------------------------------
IFRS_STANDARD_NAMES: dict[str, str] = {
    "ias_1": "IAS 1 — Presentation of Financial Statements",
    "ias_2": "IAS 2 — Inventories",
    "ias_7": "IAS 7 — Statement of Cash Flows",
    "ias_8": "IAS 8 — Accounting Policies, Changes in Accounting Estimates and Errors",
    "ias_10": "IAS 10 — Events After the Reporting Period",
    "ias_12": "IAS 12 — Income Taxes",
    "ias_16": "IAS 16 — Property, Plant and Equipment",
    "ias_19": "IAS 19 — Employee Benefits",
    "ias_20": "IAS 20 — Government Grants and Disclosure of Government Assistance",
    "ias_21": "IAS 21 — The Effects of Changes in Foreign Exchange Rates",
    "ias_23": "IAS 23 — Borrowing Costs",
    "ias_24": "IAS 24 — Related Party Disclosures",
    "ias_26": "IAS 26 — Accounting and Reporting by Retirement Benefit Plans",
    "ias_27": "IAS 27 — Separate Financial Statements",
    "ias_28": "IAS 28 — Investments in Associates and Joint Ventures",
    "ias_29": "IAS 29 — Financial Reporting in Hyperinflationary Economies",
    "ias_32": "IAS 32 — Financial Instruments: Presentation",
    "ias_33": "IAS 33 — Earnings per Share",
    "ias_34": "IAS 34 — Interim Financial Reporting",
    "ias_36": "IAS 36 — Impairment of Assets",
    "ias_37": "IAS 37 — Provisions, Contingent Liabilities and Contingent Assets",
    "ias_38": "IAS 38 — Intangible Assets",
    "ias_39": "IAS 39 — Financial Instruments: Recognition and Measurement",
    "ias_40": "IAS 40 — Investment Property",
    "ias_41": "IAS 41 — Agriculture",
    "ifrs_1": "IFRS 1 — First-time Adoption of IFRS",
    "ifrs_2": "IFRS 2 — Share-based Payment",
    "ifrs_3": "IFRS 3 — Business Combinations",
    "ifrs_4": "IFRS 4 — Insurance Contracts (superseded by IFRS 17)",
    "ifrs_5": "IFRS 5 — Non-current Assets Held for Sale and Discontinued Operations",
    "ifrs_6": "IFRS 6 — Exploration for and Evaluation of Mineral Resources",
    "ifrs_7": "IFRS 7 — Financial Instruments: Disclosures",
    "ifrs_8": "IFRS 8 — Operating Segments",
    "ifrs_9": "IFRS 9 — Financial Instruments",
    "ifrs_10": "IFRS 10 — Consolidated Financial Statements",
    "ifrs_11": "IFRS 11 — Joint Arrangements",
    "ifrs_12": "IFRS 12 — Disclosure of Interests in Other Entities",
    "ifrs_13": "IFRS 13 — Fair Value Measurement",
    "ifrs_14": "IFRS 14 — Regulatory Deferral Accounts",
    "ifrs_15": "IFRS 15 — Revenue from Contracts with Customers",
    "ifrs_16": "IFRS 16 — Leases",
    "ifrs_17": "IFRS 17 — Insurance Contracts",
    "ifrs_18": "IFRS 18 — Presentation and Disclosure in Financial Statements",
    "ifrs_19": "IFRS 19 — Subsidiaries without Public Accountability: Disclosures",
    "ifric_2": "IFRIC 2 — Members' Shares in Co-operative Entities",
    "ifric_5": "IFRIC 5 — Rights to Interests from Decommissioning Funds",
    "ifric_14": "IFRIC 14 — The Limit on a Defined Benefit Asset",
    "ifric_17": "IFRIC 17 — Distributions of Non-cash Assets to Owners",
    "ifric_19": "IFRIC 19 — Extinguishing Financial Liabilities with Equity Instruments",
    "sic_29": "SIC-29 — Service Concession Arrangements: Disclosures",
}

# ---------------------------------------------------------------------------
# SEC component known names (for taxonomies where role IDs ≠ component names)
# ---------------------------------------------------------------------------
SEC_COMPONENT_NAMES: dict[str, dict[str, dict[str, str | None]]] = {
    "oef": {
        "rr": {
            "label": "Risk/Return Summary (Form N-1A)",
            "description": (
                "Risk/Return Summary prospectus disclosures for open-end "
                "mutual funds (Form N-1A), including investment objectives, "
                "fees and expenses, performance, and risk factors."
            ),
            "category": "disclosure",
        },
        "sr": {
            "label": "Shareholder Reports (Form N-CSR)",
            "description": (
                "Annual and semi-annual shareholder report disclosures "
                "(Form N-CSR), including fund performance, holdings, "
                "management discussion, and fund statistics."
            ),
            "category": "disclosure",
        },
    },
    "vip": {
        "n3": {
            "label": "Form N-3 (Variable Annuity Accounts)",
            "description": (
                "Registration statement for separate accounts organized "
                "as management investment companies offering variable "
                "annuity contracts."
            ),
            "category": "document",
        },
        "n4": {
            "label": "Form N-4 (Variable Annuity — UIT)",
            "description": (
                "Registration statement for separate accounts organized "
                "as unit investment trusts offering variable annuity contracts."
            ),
            "category": "document",
        },
        "n6": {
            "label": "Form N-6 (Variable Life Insurance — UIT)",
            "description": (
                "Registration statement for separate accounts organized "
                "as unit investment trusts offering variable life insurance "
                "policies."
            ),
            "category": "document",
        },
    },
    "fnd": {
        "cef": {
            "label": "Closed-End Fund Disclosures",
            "description": (
                "Inline XBRL disclosures for closed-end management "
                "investment companies (Forms N-2, N-CSR, N-CEN)."
            ),
            "category": "disclosure",
        },
        "oef": {
            "label": "Open-End Fund Disclosures",
            "description": (
                "Inline XBRL disclosures for open-end management "
                "investment companies (Forms N-1A, N-CSR, N-CEN)."
            ),
            "category": "disclosure",
        },
        "uit": {
            "label": "Unit Investment Trust Disclosures",
            "description": (
                "Inline XBRL disclosures for unit investment trusts (Forms S-6, N-CEN)."
            ),
            "category": "disclosure",
        },
    },
    "sbs": {
        "sbsef": {
            "label": "SBS Entity Filings (All)",
            "description": (
                "Aggregated security-based swap entity filings covering "
                "all sub-components (CCO, compliance, financial, execution, "
                "other compliance)."
            ),
            "category": "disclosure",
        },
        "sbsef-cco": {
            "label": "Chief Compliance Officer Report",
            "description": (
                "Annual report from the Chief Compliance Officer of a "
                "security-based swap entity regarding the entity's compliance "
                "with SEC regulations."
            ),
            "category": "disclosure",
        },
        "sbsef-com": {
            "label": "Compliance Questionnaire",
            "description": (
                "Compliance questionnaire filings for security-based swap "
                "entities covering regulatory compliance status."
            ),
            "category": "disclosure",
        },
        "sbsef-fex": {
            "label": "Financial Exhibits",
            "description": (
                "Financial condition exhibits filed by security-based swap "
                "entities including statements of financial condition."
            ),
            "category": "disclosure",
        },
        "sbsef-fin": {
            "label": "Financial Reports",
            "description": (
                "Financial reports and condition disclosures for "
                "security-based swap entities."
            ),
            "category": "disclosure",
        },
        "sbsef-ocx": {
            "label": "Other Compliance Exhibits",
            "description": (
                "Additional compliance exhibits and operational disclosures "
                "for security-based swap entities."
            ),
            "category": "disclosure",
        },
    },
}


def _resolve_ifrs_url(year: int, path: str = "") -> str:
    """Resolve a URL for the IFRS taxonomy given a year integer.

    Parameters
    ----------
    year : int
        The taxonomy year (e.g. 2025).
    path : str
        Optional path to append to the base URL.

    Returns
    -------
    str
        The full URL with the date-based directory, e.g.
        ``https://xbrl.ifrs.org/taxonomy/2025-03-27/{path}``
    """
    ifrs_dates = get_ifrs_version_dates()
    date = ifrs_dates.get(year)
    if not date:
        raise OpenBBError(
            f"IFRS taxonomy year {year} is not available. "
            f"Known years: {sorted(ifrs_dates.keys(), reverse=True)}"
        )
    base = f"https://xbrl.ifrs.org/taxonomy/{date}/"
    return f"{base}{path}" if path else base


def get_label_url_for_import(schema_location: str) -> str | None:
    """
    Given a schema import location (e.g., https://xbrl.fasb.org/us-gaap/2025/elts/us-gaap-2025.xsd),
    return the URL to its label linkbase file, or None if no separate label file exists.
    """
    for pattern, url_func in TAXONOMY_LABEL_URLS.items():
        if pattern in schema_location:
            return url_func(schema_location)
    return None


@dataclass
class XBRLNode:
    """Represents a single line item in a financial statement presentation."""

    element_id: str  # e.g., 'us-gaap_Assets'
    label: str  # e.g., 'Assets'
    order: float  # e.g., 1.0
    level: int  # Indentation level
    parent_id: str | None  # Parent element ID
    preferred_label: str | None = (
        None  # e.g. 'http://www.xbrl.org/2003/role/terseLabel'
    )
    documentation: str | None = None  # Full XBRL documentation/definition text
    xbrl_type: str | None = None  # e.g. 'monetaryItemType', 'textBlockItemType'
    period_type: str | None = None  # 'instant' or 'duration'
    balance_type: str | None = None  # 'credit' or 'debit'
    abstract: bool = False  # True for grouping/heading elements
    substitution_group: str | None = None  # 'item', 'dimensionItem', 'hypercubeItem'
    nillable: bool | None = None  # Whether the element can be nil
    children: list["XBRLNode"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert the node and its children to a dictionary."""
        return {
            "element_id": self.element_id,
            "label": self.label,
            "documentation": self.documentation,
            "order": self.order,
            "level": self.level,
            "preferred_label": self.preferred_label,
            "xbrl_type": self.xbrl_type,
            "period_type": self.period_type,
            "balance_type": self.balance_type,
            "abstract": self.abstract,
            "substitution_group": self.substitution_group,
            "nillable": self.nillable,
            "children": [child.to_dict() for child in self.children],
        }


class FASBClient:
    """Handles interaction with XBRL websites (FASB and SEC)."""

    def __init__(self):
        """Initialize the client."""
        # Cache: dir_url → list of filenames (just the filename, not full URL)
        self._dir_cache: dict[str, list[str]] = {}
        # Cache: year → raw FRC suite ZIP bytes (members read lazily on demand)
        self._frc_suite_cache: dict[int, bytes] = {}

    def list_files(self, dir_url: str) -> list[str]:
        """Return the list of filenames in a remote directory.

        Fetches the directory listing HTML page (caching per URL) and
        extracts every ``href="<filename>"`` that looks like an actual
        file (not a parent link, not an absolute URL).

        Parameters
        ----------
        dir_url : str
            URL of the directory (should end with ``/``).

        Returns
        -------
        list[str]
            Sorted list of filenames present in that directory.
        """
        import re

        if not dir_url.endswith("/"):
            dir_url += "/"

        if dir_url not in self._dir_cache:
            html = self._fetch_url_content(dir_url)
            # Pull every href value that is a plain filename (no slash prefix,
            # no absolute URL, no "../" parent link).
            raw = re.findall(r'href="([^"]+)"', html)
            files = sorted(
                f
                for f in raw
                if f
                and not f.startswith("/")
                and not f.startswith("http")
                and not f.startswith("?")
                and f != "../"
            )
            self._dir_cache[dir_url] = files

        return self._dir_cache[dir_url]

    def find_file(self, dir_url: str, *fragments: str) -> str | None:
        """Find a file in a directory whose name contains ALL given fragments.

        This does exact substring matching on the real filename list — no
        regex, no guessing.  The fragments are AND-ed: the filename must
        contain every one of them.

        Parameters
        ----------
        dir_url : str
            URL of the directory to search.
        *fragments : str
            One or more substrings that must all appear in the filename.

        Returns
        -------
        str | None
            Full URL to the matching file, or ``None`` if not found.
        """
        if not dir_url.endswith("/"):
            dir_url += "/"

        try:
            files = self.list_files(dir_url)
        except Exception:
            return None

        for fname in files:
            if all(frag in fname for frag in fragments):
                return f"{dir_url}{fname}"
        return None

    def get_available_years(self, taxonomy: str, config: TaxonomyConfig) -> list[int]:
        """Scrapes the base directory to find available taxonomy years."""
        import re

        if config.style == TaxonomyStyle.STATIC:
            # Static taxonomies (e.g., rocr 2015) embed the year in the URL.
            m = re.search(r"/(\d{4})/", config.base_url_template)
            return [int(m.group(1))] if m else []

        if config.style == TaxonomyStyle.EXTERNAL:
            # IFRS uses date-based versioning; discover from edgartaxonomies.xml
            if taxonomy == "ifrs":
                return sorted(get_ifrs_version_dates().keys(), reverse=True)
            # FRC suites: years sourced from the per-year suite ZIP map.
            if taxonomy == "frc-core":
                return list(_FRC_CORE_YEARS)
            if taxonomy == "frc-dpl":
                return list(_FRC_DPL_YEARS)
            return []

        base_root = config.base_url_template.split("{year}")[0]

        try:
            content = self._fetch_url_content(base_root)
            years = re.findall(r'href="(\d{4})/"', content)
            return sorted([int(y) for y in years], reverse=True)
        except Exception as e:
            raise OpenBBError(
                f"Failed to fetch available years for {taxonomy}: {e}"
            ) from e

    def get_components_for_year(self, year: int, config: TaxonomyConfig) -> list[str]:
        """Discovery of available components (statements/disclosures).

        For FASB_STANDARD taxonomies, scans the stm/ directory for presentation files.
        For SEC_EMBEDDED/SEC_STANDALONE taxonomies, scans the root directory.
        For EXTERNAL (IFRS), parses the entry-point XSD for standard sub-schemas.
        For STATIC taxonomies, returns a fixed list.
        """
        import re

        if config.style == TaxonomyStyle.STATIC:
            return ["standard"]

        if config.style == TaxonomyStyle.EXTERNAL:
            # IFRS: Parse entry-point XSD to discover per-standard components
            if "ifrs" in config.base_url_template:
                try:
                    ep_url = _resolve_ifrs_url(
                        year,
                        f"full_ifrs_entry_point_{get_ifrs_version_dates()[year]}.xsd",
                    )
                    content = self._fetch_url_content(ep_url)
                    # Extract standard names from schemaLocation imports
                    # e.g. full_ifrs/linkbases/ias_1/rol_ias_1_2025-03-27.xsd
                    pattern = r"full_ifrs/linkbases/([a-z]+_\d+)/rol_"
                    standards = sorted(set(re.findall(pattern, content)))
                    return standards if standards else ["standard"]
                except Exception as e:
                    raise OpenBBError(
                        f"Failed to fetch IFRS components for {year}: {e}"
                    ) from e
            # Non-IFRS external taxonomies (e.g. FRC core/dpl): single component
            return ["standard"]

        base_url = config.base_url_template.format(year=year)

        if config.style == TaxonomyStyle.FASB_STANDARD:
            stm_url = f"{base_url}stm/"
            try:
                files = self.list_files(stm_url)
                # Extract component names from actual presentation filenames.
                # Files look like: us-gaap-stm-{comp}-pre-{date}.xml
                components: set[str] = set()
                prefix = config.presentation_file_template.split("{name}")[0]
                # e.g. "stm/us-gaap-stm-" → we strip "stm/" to get "us-gaap-stm-"
                if prefix.startswith("stm/"):
                    prefix = prefix[4:]
                for fname in files:
                    if "-pre-" in fname and fname.startswith(prefix):
                        rest = fname[len(prefix) :]
                        # rest = "soc-pre-2023.xml" or "soc-pre-2019-01-31.xml"
                        comp = rest.split("-pre-")[0]
                        if comp:
                            components.add(comp)
                return sorted(components)
            except Exception as e:
                raise OpenBBError(f"Failed to fetch components for {year}: {e}") from e

        if config.style in (
            TaxonomyStyle.SEC_EMBEDDED,
            TaxonomyStyle.SEC_STANDALONE,
        ):
            try:
                files = self.list_files(base_url)
                # Extract component names from actual presentation / sub-schema files.
                # Use the regex to pull component names out of real filenames.
                components: set[str] = set()
                for fname in files:
                    # Try the configured regex (replace {year} with a catch-all date pattern)
                    if config.presentation_pattern_regex:
                        yr_pat = rf"{year}(?:-\d{{2}}-\d{{2}})?"
                        pattern = config.presentation_pattern_regex.format(
                            year=yr_pat,
                        )
                        m = re.match(pattern, fname)
                        if m:
                            components.add(m.group(1))
                if components:
                    return sorted(components)
                # Fallback: if any file mentions this year, it's a single-component taxonomy
                if any(str(year) in f for f in files):
                    return ["standard"]
                return []
            except Exception:
                return []

        return []  # pragma: no cover - all five TaxonomyStyle members (STATIC, EXTERNAL, FASB_STANDARD, SEC_EMBEDDED, SEC_STANDALONE) return above, so this final fallthrough is unreachable

    def fetch_file(self, url: str) -> BytesIO:
        """Download a file as an in-memory byte stream."""
        from openbb_sec.utils.cache import cached_bytes

        try:
            return BytesIO(cached_bytes(url))
        except Exception as e:
            raise OpenBBError(f"Failed to fetch {url}: {e}") from e

    def _fetch_url_content(self, url: str) -> str:
        """Get directory listing content."""
        from openbb_sec.utils.cache import cached_text

        return cached_text(url, expire=3600 * 24 * 7)

    def _frc_suite_bytes(self, year: int) -> bytes:
        """Return the FRC taxonomy suite ZIP bytes for ``year``.

        The compressed archive is persisted in the SEC disk cache (shared across
        processes) and memoized in-memory per client. The in-memory copy avoids
        re-reading ~5 MB from disk on each of the many member lookups a single
        ``get_structure`` call performs; members are decompressed lazily so the
        unused FRS/IFRS/reports trees are never expanded.

        Parameters
        ----------
        year : int
            The FRC suite year to load.

        Returns
        -------
        bytes
            The raw ZIP archive bytes.
        """
        from openbb_sec.utils.cache import cached_bytes

        if year in self._frc_suite_cache:
            return self._frc_suite_cache[year]

        url = _FRC_SUITE_ZIPS.get(year)
        if not url:
            raise OpenBBError(f"No FRC taxonomy suite is mapped for year {year}.")

        raw = cached_bytes(url, expire=_FRC_SUITE_CACHE_TTL)
        self._frc_suite_cache[year] = raw
        return raw

    @staticmethod
    def _frc_relpath(name: str) -> str:
        """Strip the release-specific suite root directory from a member name."""
        parts = name.split("/", 1)
        return parts[1] if len(parts) == 2 else parts[0]

    def find_frc_member(
        self, year: int, *fragments: str, exclude: tuple[str, ...] = ()
    ) -> str | None:
        """Find a suite member whose relative path contains all ``fragments``.

        Parameters
        ----------
        year : int
            The FRC suite year.
        *fragments : str
            Substrings that must all appear in the member's relative path.
        exclude : tuple[str, ...]
            Substrings that must not appear in the member's relative path.

        Returns
        -------
        str | None
            The matching member's relative path, or ``None`` if not found.
        """
        import zipfile

        with zipfile.ZipFile(BytesIO(self._frc_suite_bytes(year))) as archive:
            for name in sorted(archive.namelist()):
                rel = self._frc_relpath(name)
                if (
                    rel
                    and all(frag in rel for frag in fragments)
                    and not any(bad in rel for bad in exclude)
                ):
                    return rel
        return None

    def fetch_frc_member(self, year: int, relpath: str) -> BytesIO:
        """Return a suite member as an in-memory byte stream.

        Parameters
        ----------
        year : int
            The FRC suite year.
        relpath : str
            The member's path relative to the suite root.

        Returns
        -------
        BytesIO
            The member's bytes.
        """
        import zipfile

        with zipfile.ZipFile(BytesIO(self._frc_suite_bytes(year))) as archive:
            for name in archive.namelist():
                if self._frc_relpath(name) == relpath:
                    return BytesIO(archive.read(name))
        raise OpenBBError(f"FRC suite {year} has no member {relpath!r}.")


# Additional namespaces for XSD parsing
XSD_NS = {
    **NS,
    "xsd": "http://www.w3.org/2001/XMLSchema",
    "xbrli": "http://www.xbrl.org/2003/instance",
}


class XBRLParser:
    """Parses XML/XSD files into usable structures."""

    def __init__(self, labels: dict[str, str] | None = None):
        """Initialize the parser with an optional labels dictionary."""
        self.labels = labels or {}
        self.documentation: dict[str, str] = {}
        self.element_properties: dict[str, dict[str, Any]] = {}
        self.linkbase_errors: dict[str, str] = {}

    def _get_xml_root(self, file_content: str | BytesIO) -> Element | None:
        from defusedxml.ElementTree import parse

        return parse(file_content).getroot()

    @staticmethod
    def _is_transient_fetch_error(exc: OSError) -> bool:
        """Return whether a failed download is worth retrying.

        Parameters
        ----------
        exc : OSError
            The download error.

        Returns
        -------
        bool
            True for timeouts, connection errors, HTTP 429, and HTTP 5xx.
        """
        if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
            return True
        response = getattr(exc, "response", None)
        return (
            isinstance(exc, requests.HTTPError)
            and response is not None
            and (response.status_code == 429 or response.status_code >= 500)
        )

    def _fetch_filing_document(self, url: str) -> bytes:
        """Download a filing document, retrying transient failures.

        Parameters
        ----------
        url : str
            The document URL.

        Returns
        -------
        bytes
            The document body.

        Raises
        ------
        OSError
            If the download fails permanently or on the final attempt.
        """
        from openbb_sec.utils.cache import cached_bytes
        from openbb_sec.utils.definitions import HEADERS as SEC_HEADERS

        for attempt in range(LINKBASE_FETCH_ATTEMPTS - 1):
            try:
                return cached_bytes(url, headers=SEC_HEADERS)
            except OSError as exc:
                if not self._is_transient_fetch_error(exc):
                    raise
                time.sleep(LINKBASE_RETRY_BACKOFF * 2**attempt)
        return cached_bytes(url, headers=SEC_HEADERS)

    def _load_filing_document(self, kind: str, url: str) -> Element | None:
        """Download and parse a filing document, warning when it is unavailable.

        Parameters
        ----------
        kind : str
            The document kind, ``schema``, ``label``, or ``presentation``.
        url : str
            The document URL.

        Returns
        -------
        Element | None
            The document root, or None when it could not be downloaded or parsed.
        """
        try:
            return self._get_xml_root(BytesIO(self._fetch_filing_document(url)))
        except (OSError, ParseError, ValueError) as exc:
            reason = f"{type(exc).__name__}: {exc}"
            self.linkbase_errors[kind] = reason
            warnings.warn(
                f"Could not load the filing's {kind} document from {url}: {reason}",
                OpenBBWarning,
                stacklevel=3,
            )
            return None

    @staticmethod
    def _parse_order(value: str | None) -> float | None:
        """Parse a presentation arc ``order``, ignoring invalid values.

        Parameters
        ----------
        value : str | None
            The ``order`` attribute.

        Returns
        -------
        float | None
            The order, or None when missing or not numeric.
        """
        try:
            return float(value) if value else None
        except ValueError:
            return None

    def parse_schema(
        self, file_content: BytesIO
    ) -> tuple[
        dict[str, dict[str, Any]],
        list[dict[str, Any]],
        Any | None,
        list[dict[str, str]],
    ]:
        """Parse a XBRL schema (.xsd) file.

        Parameters
        ----------
        file_content : BytesIO
            The content of the XSD file as a byte stream.

        Returns
        -------
        tuple[dict[str, dict[str, Any]], list[dict[str, Any]], Any | None, list[dict[str, str]]]
            - elements: dict mapping element_id -> {name, xbrl_type, xsi_nil, period_type, balance_type}
            - roles: list of role definitions with {name, short_name, document_number, group, sub_group, long_name}
            - embedded_linkbase: The embedded linkbase element if present (for labels), or None
            - imports: list of {namespace, schemaLocation} for imported taxonomies
        """
        try:
            root = self._get_xml_root(file_content)

            if root is None:
                raise ValueError("Failed to parse XML schema: root is None")

            elements: dict[str, dict[str, Any]] = {}
            roles: list[dict[str, Any]] = []
            embedded_linkbase = None
            imports: list[dict[str, str]] = []

            # "xsd" and "xs" are interchangeable prefixes for the same XML
            # Schema namespace, and ElementTree.findall() matches by namespace
            # URI -- so collapse them to the unique set of URIs. Iterating the
            # raw prefix list processes identical nodes twice, which collected
            # every import and role type a second time.
            xsd_ns_uris = {
                XSD_NS.get(prefix, "http://www.w3.org/2001/XMLSchema")
                for prefix in ("xsd", "xs")
            }

            # Parse imports to identify external taxonomies
            for ns_uri in xsd_ns_uris:
                for imp in root.findall(f"{{{ns_uri}}}import"):
                    namespace = imp.get("namespace", "")
                    schema_location = imp.get("schemaLocation", "")
                    if namespace and schema_location:
                        imports.append(
                            {"namespace": namespace, "schemaLocation": schema_location}
                        )

            # Parse elements across the XML Schema namespace
            for ns_uri in xsd_ns_uris:
                for elem in root.findall(f".//{{{ns_uri}}}element"):
                    elem_id = elem.get("id")
                    if not elem_id:
                        continue

                    elem_type = elem.get("type", "")
                    sub_group_raw = elem.get("substitutionGroup", "")
                    elements[elem_id] = {
                        "name": elem.get("name"),
                        "xbrl_type": elem_type.split(":")[-1] if elem_type else None,
                        "xsi_nil": elem.get("nillable"),
                        "period_type": elem.get(f"{{{XSD_NS['xbrli']}}}periodType"),
                        "balance_type": elem.get(f"{{{XSD_NS['xbrli']}}}balance"),
                        "abstract": elem.get("abstract") == "true",
                        "substitution_group": (
                            sub_group_raw.split(":")[-1] if sub_group_raw else None
                        ),
                    }

            # Parse role types from annotation/appinfo
            for ns_uri in xsd_ns_uris:
                for role_type in root.findall(
                    f".//{{{ns_uri}}}annotation/{{{ns_uri}}}appinfo/{{{NS['link']}}}roleType"
                ):
                    role_id = role_type.get("id")

                    # Get definition text
                    definition_elem = role_type.find(f"{{{NS['link']}}}definition")
                    definition = (
                        definition_elem.text
                        if definition_elem is not None and definition_elem.text
                        else ""
                    )

                    # Parse definition format: "doc_num - type - subtype - name" or "doc_num - type - name"
                    parts = definition.split(" - ")
                    if len(parts) >= 3:
                        roles.append(
                            {
                                "name": role_id,
                                "short_name": parts[-1],
                                "document_number": parts[0],
                                "group": parts[1].lower() if len(parts) > 1 else "",
                                "sub_group": parts[2] if len(parts) > 3 else None,
                                "long_name": definition,
                            }
                        )

                # Check for embedded linkbase
                for linkbase in root.findall(
                    f".//{{{ns_uri}}}annotation/{{{ns_uri}}}appinfo/{{{NS['link']}}}linkbase"
                ):
                    embedded_linkbase = linkbase
                    break

            return elements, roles, embedded_linkbase, imports

        except Exception as e:
            raise OpenBBError(f"Failed to parse schema: {e}") from e

    def parse_schema_elements(self, file_content: BytesIO) -> list[XBRLNode]:
        """Extract elements from an XSD schema as a flat list of XBRLNode.

        This is used for reference/enumeration taxonomies (exch, country,
        currency, naics, sic, stpr, snj) that define flat element lists
        without any presentation linkbase hierarchy.

        Parameters
        ----------
        file_content : BytesIO
            The content of the XSD schema file.

        Returns
        -------
        list[XBRLNode]
            A flat list of XBRLNode objects (level=0, no children) for each
            non-abstract ``<xs:element>`` found, or all elements if every
            element is abstract.
        """
        try:
            root = self._get_xml_root(file_content)
            if root is None:
                raise ValueError("Failed to parse XML schema: root is None")

            nodes: list[XBRLNode] = []
            order_counter = 1.0

            for prefix in ["xs", "xsd"]:
                ns_uri = XSD_NS.get(prefix, "http://www.w3.org/2001/XMLSchema")
                for elem in root.findall(f"{{{ns_uri}}}element"):
                    elem_id = elem.get("id", "")
                    elem_name = elem.get("name", "")
                    if not elem_name:
                        continue

                    label = self.labels.get(elem_id, elem_name) or elem_name
                    doc = self.documentation.get(elem_id)
                    props = self.element_properties.get(elem_id, {})
                    elem_type = elem.get("type", "")
                    sub_group_raw = elem.get("substitutionGroup", "")
                    nodes.append(
                        XBRLNode(
                            element_id=elem_id,
                            label=label,
                            order=order_counter,
                            level=0,
                            parent_id=None,
                            preferred_label=None,
                            documentation=doc,
                            xbrl_type=props.get("xbrl_type")
                            or (elem_type.split(":")[-1] if elem_type else None),
                            period_type=props.get("period_type")
                            or elem.get(f"{{{XSD_NS['xbrli']}}}periodType"),
                            balance_type=props.get("balance_type")
                            or elem.get(f"{{{XSD_NS['xbrli']}}}balance"),
                            abstract=props.get(
                                "abstract", elem.get("abstract") == "true"
                            ),
                            substitution_group=props.get("substitution_group")
                            or (
                                sub_group_raw.split(":")[-1] if sub_group_raw else None
                            ),
                            nillable=props.get(
                                "nillable",
                                (
                                    elem.get("nillable") == "true"
                                    if elem.get("nillable")
                                    else None
                                ),
                            ),
                            children=[],
                        )
                    )
                    order_counter += 1.0

                if nodes:
                    break  # found elements with this prefix, skip the other

            return nodes
        except Exception as e:
            raise OpenBBError(f"Failed to parse schema elements: {e}") from e

    def parse_label_linkbase(
        self, file_content: BytesIO, style: TaxonomyStyle
    ) -> dict[str, Any]:
        """Update internal labels from a label linkbase file content.

        Parameters
        ----------
        file_content : BytesIO
            The content of the label linkbase file as a byte stream.
        style : TaxonomyStyle
            The style of taxonomy to determine how to find the linkbase (embedded vs standard).

        Returns
        -------
        dict[str, Any]
            A dictionary mapping element_id to a dict of label roles and their corresponding text.
        """
        try:
            root = self._get_xml_root(file_content)

            if root is None:
                raise ValueError("Failed to parse XML label linkbase: root is None")

            # If embedded, find the linkbase inside annotations
            target_root = root
            if style == TaxonomyStyle.SEC_EMBEDDED and root.tag.endswith("schema"):
                # Find annotation/appinfo/link:linkbase
                found_lb = False
                for node in root.findall(".//link:linkbase", NS):
                    target_root = node
                    found_lb = True
                    break
                if not found_lb:
                    warnings.warn("No embedded linkbase found in XSD labels.")
                    return {}

            loc_map = {}
            for loc in target_root.findall(".//link:loc", NS):
                href = loc.get(f"{{{NS['xlink']}}}href")
                label_key = loc.get(f"{{{NS['xlink']}}}label")
                if href and "#" in href:
                    loc_map[label_key] = href.split("#")[1]

            xml_lang_attr = "{http://www.w3.org/XML/1998/namespace}lang"
            resource_map: dict[str | None, dict[str, str | None]] = {}
            for res in target_root.findall(".//link:label", NS):
                # English-only: skip non-English label resources (e.g. the Welsh
                # entries in the bilingual UK FRC linkbases). Resources with no
                # xml:lang (most US/SEC taxonomies) are kept.
                lang = res.get(xml_lang_attr)
                if lang and not lang.lower().startswith("en"):
                    continue
                role = res.get(f"{{{NS['xlink']}}}role")
                # Simplify role to short name (e.g. terseLabel)
                role_short = role.split("/")[-1] if role else "label"
                label_key = res.get(f"{{{NS['xlink']}}}label")

                if label_key not in resource_map:
                    resource_map[label_key] = {}
                resource_map[label_key][role_short] = res.text

            new_labels: dict[str, dict[str, str | None]] = {}
            for arc in target_root.findall(".//link:labelArc", NS):
                from_loc = arc.get(f"{{{NS['xlink']}}}from")
                to_label = arc.get(f"{{{NS['xlink']}}}to")

                if from_loc in loc_map and to_label in resource_map:
                    element_id = loc_map[from_loc]
                    label_data = resource_map[to_label]

                    # Update standard labels store (simple string)
                    if "label" in label_data:
                        self.labels[element_id] = label_data["label"]  # ty: ignore[invalid-assignment]
                    elif "documentation" not in label_data and list(
                        label_data.values()
                    ):
                        self.labels[element_id] = list(label_data.values())[0]  # ty: ignore[invalid-assignment]

                    # Update documentation store
                    if "documentation" in label_data:
                        self.documentation[element_id] = label_data["documentation"]  # ty: ignore[invalid-assignment]

                    if element_id not in new_labels:
                        new_labels[element_id] = {}
                    new_labels[element_id].update(label_data)

            # Note: We don't update self.labels with the dictionary structure to avoid breaking
            # simple usage in XBRLManager, but the caller of this method gets the rich dict.
            return new_labels
        except Exception as e:
            raise OpenBBError(f"Failed to parse label linkbase: {e}") from e

    def parse_reference_linkbase(self, file_content: BytesIO) -> int:
        """Parse reference links from an XSD and use them as fallback documentation.

        SEC taxonomies like CYD, ECD, OEF, SBS, SPAC, SRO, and FND
        publish ``referenceLink`` elements in their main XSD with
        regulatory citation data (Publisher, Name, Section, etc.) but
        no ``role/documentation`` labels.  This method extracts those
        references and formats them as compact citation strings, storing
        them in ``self.documentation`` for elements that don't already
        have documentation.

        Parameters
        ----------
        file_content : BytesIO
            The content of the XSD schema file.

        Returns
        -------
        int
            The number of new documentation entries added.
        """
        try:
            root = self._get_xml_root(file_content)
            if root is None:
                return 0

            ref_links = list(root.iter(f"{{{NS['link']}}}referenceLink"))
            if not ref_links:
                return 0

            # Build loc map (label → element_id)
            loc_map: dict[str, str] = {}
            for ref_link in ref_links:
                for loc in ref_link.findall("link:loc", NS):
                    label_key = loc.get(f"{{{NS['xlink']}}}label", "")
                    href = loc.get(f"{{{NS['xlink']}}}href", "")
                    if href and "#" in href:
                        loc_map[label_key] = href.split("#")[1]

            # Build resource map (label → list of citation parts)
            resource_map: dict[str, list[dict[str, str]]] = {}
            for ref_link in ref_links:
                for ref in ref_link.findall("link:reference", NS):
                    label_key = ref.get(f"{{{NS['xlink']}}}label", "")
                    parts: dict[str, str] = {}
                    for child in ref:
                        tag = (
                            child.tag.split("}")[-1] if "}" in child.tag else child.tag
                        )
                        if child.text:
                            parts[tag] = child.text.strip()
                    if parts:
                        resource_map.setdefault(label_key, []).append(parts)

            # Build arc map (element_id → resource labels)
            elem_refs: dict[str, list[dict[str, str]]] = {}
            for ref_link in ref_links:
                for arc in ref_link.findall("link:referenceArc", NS):
                    from_loc = arc.get(f"{{{NS['xlink']}}}from", "")
                    to_ref = arc.get(f"{{{NS['xlink']}}}to", "")
                    element_id = loc_map.get(from_loc)
                    ref_parts_list = resource_map.get(to_ref, [])
                    if element_id and ref_parts_list:
                        elem_refs.setdefault(element_id, []).extend(ref_parts_list)

            # Format citations and store as documentation fallback
            count = 0
            for element_id, refs in elem_refs.items():
                if element_id in self.documentation:
                    continue  # Don't overwrite real documentation

                citations: list[str] = []
                for parts in refs:
                    name = parts.get("Name", "")
                    section = parts.get("Section", "")
                    if not name:
                        continue
                    cite = name
                    if section:
                        cite += f" §{section}"
                    # Append subsection/paragraph/subparagraph
                    sub = parts.get("Subsection", "")
                    para = parts.get("Paragraph", "")
                    subpara = parts.get("Subparagraph", "")
                    suffix_parts = [p for p in [sub, para, subpara] if p]
                    if suffix_parts:
                        cite += "(" + ")(".join(suffix_parts) + ")"
                    citations.append(cite)

                if citations:
                    # Deduplicate while preserving order
                    seen: set[str] = set()
                    unique: list[str] = []
                    for c in citations:
                        if c not in seen:
                            seen.add(c)
                            unique.append(c)
                    self.documentation[element_id] = "Ref: " + "; ".join(unique)
                    count += 1

            return count
        except Exception:  # noqa: BLE001
            return 0

    def load_schema_element_properties(self, file_content: BytesIO) -> int:
        """Parse element properties from an XSD schema and store them.

        Extracts xbrl_type, period_type, balance_type, abstract,
        substitution_group, and nillable for every ``<xs:element>``
        and merges them into ``self.element_properties``.

        Parameters
        ----------
        file_content : BytesIO
            The content of the XSD schema file.

        Returns
        -------
        int
            The number of new element properties loaded.
        """
        try:
            root = self._get_xml_root(file_content)
            if root is None:
                return 0

            count = 0
            for prefix in ["xsd", "xs"]:
                ns_uri = XSD_NS.get(prefix, "http://www.w3.org/2001/XMLSchema")
                for elem in root.findall(f".//{{{ns_uri}}}element"):
                    elem_id = elem.get("id")
                    if not elem_id or elem_id in self.element_properties:
                        continue

                    elem_type = elem.get("type", "")
                    sub_group_raw = elem.get("substitutionGroup", "")
                    nillable_raw = elem.get("nillable")
                    self.element_properties[elem_id] = {
                        "xbrl_type": (elem_type.split(":")[-1] if elem_type else None),
                        "period_type": elem.get(f"{{{XSD_NS['xbrli']}}}periodType"),
                        "balance_type": elem.get(f"{{{XSD_NS['xbrli']}}}balance"),
                        "abstract": elem.get("abstract") == "true",
                        "substitution_group": (
                            sub_group_raw.split(":")[-1] if sub_group_raw else None
                        ),
                        "nillable": (
                            nillable_raw == "true" if nillable_raw is not None else None
                        ),
                    }
                    count += 1
            return count
        except Exception:  # noqa: S112
            return 0

    def parse_presentation(
        self, file_content: BytesIO, style: TaxonomyStyle
    ) -> list[XBRLNode]:
        """Parse a presentation linkbase into a hierarchical tree.

        Parameters
        ----------
        file_content : BytesIO
            The content of the presentation linkbase file as a byte stream.
        style : TaxonomyStyle
            The style of taxonomy to determine how to find the linkbase (embedded vs standard).

        Returns
        -------
        list[XBRLNode]
            A list of root XBRLNode objects representing the hierarchical structure of the presentation.
        """
        try:
            root = self._get_xml_root(file_content)

            if root is None:
                raise ValueError("Failed to parse XML presentation: root is None")

            # If embedded, find the linkbase inside annotations
            target_root = root
            if style == TaxonomyStyle.SEC_EMBEDDED and root.tag.endswith("schema"):
                found_lb = False
                for node in root.findall(".//link:linkbase", NS):
                    target_root = node
                    found_lb = True
                    break
                if not found_lb:
                    warnings.warn("No embedded linkbase found in XSD presentation.")
                    return []

            loc_map = {}
            for loc in target_root.findall(".//link:loc", NS):
                href = loc.get(f"{{{NS['xlink']}}}href")
                label = loc.get(f"{{{NS['xlink']}}}label")
                if href and "#" in href:
                    # SEC locators often point to local files, e.g., "dei-2024.xsd#element"
                    # We just want "element"
                    loc_map[label] = href.split("#")[1]

            relationships = []
            for arc in target_root.findall(".//link:presentationArc", NS):
                parent_loc = arc.get(f"{{{NS['xlink']}}}from")
                child_loc = arc.get(f"{{{NS['xlink']}}}to")
                order = float(arc.get("order", "1.0"))
                preferred_label = arc.get("preferredLabel")

                if parent_loc in loc_map and child_loc in loc_map:
                    relationships.append(
                        {
                            "parent": loc_map[parent_loc],
                            "child": loc_map[child_loc],
                            "order": order,
                            "preferred_label": preferred_label,
                        }
                    )

            # Build Tree
            all_children = set(r["child"] for r in relationships)
            all_parents = set(r["parent"] for r in relationships)
            roots = list(all_parents - all_children)

            def build_node(element_id, level=0, parent_id=None, preferred_label=None):
                """Recursively build a node and its children."""
                label = self.labels.get(element_id, element_id) or element_id
                doc = self.documentation.get(element_id)
                props = self.element_properties.get(element_id, {})
                node = XBRLNode(
                    element_id=element_id,
                    label=label,
                    order=0,
                    level=level,
                    parent_id=parent_id,
                    preferred_label=preferred_label,
                    documentation=doc,
                    xbrl_type=props.get("xbrl_type"),
                    period_type=props.get("period_type"),
                    balance_type=props.get("balance_type"),
                    abstract=props.get("abstract", False),
                    substitution_group=props.get("substitution_group"),
                    nillable=props.get("nillable"),
                    children=[],
                )

                my_children_rels = [
                    r for r in relationships if r["parent"] == element_id
                ]

                def _order_key(rel: dict[str, Any]) -> float:
                    order = rel.get("order")
                    if isinstance(order, (int, float)):
                        return float(order)
                    return float("inf")

                my_children_rels.sort(key=_order_key)

                for rel in my_children_rels:
                    child_node = build_node(
                        rel["child"],
                        level + 1,
                        element_id,
                        rel["preferred_label"],
                    )
                    child_node.order = rel["order"]
                    node.children.append(child_node)

                return node

            return [build_node(r) for r in roots]

        except Exception as e:
            raise OpenBBError(f"Failed to parse presentation linkbase: {e}") from e

    def parse_calculation(
        self, file_content: BytesIO, style: TaxonomyStyle
    ) -> dict[str, dict[str, Any]]:
        """Parse a calculation linkbase into a dictionary of element relationships.

        Calculation linkbases define how line items sum up, e.g.: Assets = CurrentAssets + NoncurrentAssets

        Parameters
        ----------
        file_content : BytesIO
            The content of the calculation linkbase file as a byte stream.
        style : TaxonomyStyle
            The style of taxonomy to determine how to find the linkbase (embedded vs standard).

        Returns
        -------
        dict[str, dict[str, Any]]
            A dictionary mapping child element_id to a dict with keys:
            - order: The order attribute from the arc (float)
            - weight: The weight attribute from the arc (float, usually 1 or -1)
            - parent_tag: The parent element_id that this child rolls up to
        """
        try:
            root = self._get_xml_root(file_content)

            if root is None:
                raise ValueError("Failed to parse XML calculation: root is None")

            # If embedded, find the linkbase inside annotations
            target_root = root
            if style == TaxonomyStyle.SEC_EMBEDDED and root.tag.endswith("schema"):
                found_lb = False
                for node in root.findall(".//link:linkbase", NS):
                    target_root = node
                    found_lb = True
                    break
                if not found_lb:
                    warnings.warn("No embedded linkbase found in XSD calculation.")
                    return {}

            # Build locator map: label -> element_id
            loc_map = {}
            for loc in target_root.findall(".//link:loc", NS):
                href = loc.get(f"{{{NS['xlink']}}}href")
                label = loc.get(f"{{{NS['xlink']}}}label")
                if href and "#" in href:
                    loc_map[label] = href.split("#")[1]

            # Parse calculation arcs
            calculations = {}
            for calc_link in target_root.findall(".//link:calculationLink", NS):
                for arc in calc_link.findall("link:calculationArc", NS):
                    parent_loc = arc.get(f"{{{NS['xlink']}}}from")
                    child_loc = arc.get(f"{{{NS['xlink']}}}to")
                    order = float(arc.get("order", "1.0"))
                    weight = float(arc.get("weight", "1"))

                    if parent_loc in loc_map and child_loc in loc_map:
                        child_id = loc_map[child_loc]
                        parent_id = loc_map[parent_loc]

                        calculations[child_id] = {
                            "order": order,
                            "weight": weight,
                            "parent_tag": parent_id,
                        }

            return calculations

        except Exception as e:
            raise OpenBBError(f"Failed to parse calculation linkbase: {e}") from e

    @staticmethod
    def _build_ns_prefix_map(raw_content: bytes) -> dict[str, str]:
        """Build a namespace URI → prefix map from xmlns declarations.

        Parses ``xmlns:prefix="uri"`` declarations from the raw XML
        content to create an authoritative mapping of namespace URIs
        to their declared prefixes.

        Parameters
        ----------
        raw_content : bytes
            The raw byte content of the XML document.

        Returns
        -------
        dict[str, str]
            Mapping of namespace URI → prefix (e.g.,
            ``"http://xbrl.sec.gov/ecd/2024"`` → ``"ecd"``).
        """
        import re

        # Parse xmlns declarations from the first portion of the document
        header = raw_content[:10000].decode("utf-8", errors="replace")
        ns_map: dict[str, str] = {}
        for match in re.finditer(r'xmlns:([\w-]+)=["\']([^"\']+)["\']', header):
            prefix, uri = match.group(1), match.group(2)
            ns_map[uri] = prefix
        return ns_map

    @staticmethod
    def _resolve_ns_prefix(ns_uri: str, ns_prefix_map: dict[str, str]) -> str:
        """Resolve a namespace URI to its prefix.

        Uses the document's xmlns declarations first, then falls back
        to well-known patterns, and finally extracts the semantic
        segment from the URI path.

        Parameters
        ----------
        ns_uri : str
            The full namespace URI (without braces).
        ns_prefix_map : dict[str, str]
            Mapping of namespace URI → prefix from xmlns declarations.

        Returns
        -------
        str
            The resolved prefix string.
        """
        # 1. Direct lookup from xmlns declarations
        if ns_uri in ns_prefix_map:
            return ns_prefix_map[ns_uri]

        # 2. Well-known patterns
        if "us-gaap" in ns_uri:
            return "us-gaap"
        if "xbrl.sec.gov/dei" in ns_uri:
            return "dei"
        if "fasb.org/srt" in ns_uri:
            return "srt"

        # 3. Heuristic: for URIs like http://xbrl.sec.gov/ecd/2024,
        #    take the segment before the trailing year/date
        import re

        parts = ns_uri.rstrip("/").split("/")
        # Walk backwards past date-like segments to find the semantic name.
        # Matches: 2024, 2024-01, 2024-01-15, 20240928
        for part in reversed(parts):
            if not re.match(r"^\d{4}(-?\d{2}(-?\d{2})?)?$", part):
                return part

        return parts[-1] if parts else "unknown"

    @staticmethod
    def _resolve_measure(measure_text: str) -> str:
        """Resolve an XBRL measure text to a clean representation.

        Strips namespace prefixes and normalizes common measures.

        Parameters
        ----------
        measure_text : str
            Raw measure text, e.g. "iso4217:USD" or "xbrli:shares".

        Returns
        -------
        str
            Cleaned measure string.
        """
        if not measure_text:
            return ""
        text = measure_text.strip()
        # Common XBRL standard measures
        if text.startswith("iso4217:"):
            return text  # Keep currency prefix for clarity: iso4217:USD
        if text in ("xbrli:shares", "shares"):
            return "shares"
        if text in ("xbrli:pure", "pure"):
            return "pure"
        # For company-specific measures (e.g., aapl:Vendor), keep as-is
        return text

    def _parse_units(self, root: Element) -> dict[str, str]:
        """Parse xbrli:unit definitions from an XBRL instance document.

        Handles both simple units (single measure) and compound units
        (divide with numerator/denominator).

        Parameters
        ----------
        root : ET.Element
            The root element of the parsed XBRL instance document.

        Returns
        -------
        dict[str, str]
            A dictionary mapping unit IDs to their resolved measure strings.
            Simple units: "iso4217:USD", "shares", "pure"
            Compound units: "iso4217:USD / shares"
        """
        xbrli_ns = "http://www.xbrl.org/2003/instance"
        units: dict[str, str] = {}

        for unit_elem in root.findall(f".//{{{xbrli_ns}}}unit"):
            unit_id = unit_elem.get("id")
            if not unit_id:
                continue

            # Simple unit: <measure>iso4217:USD</measure>
            measure = unit_elem.find(f"{{{xbrli_ns}}}measure")
            if measure is not None and measure.text:
                units[unit_id] = self._resolve_measure(measure.text)
                continue

            # Compound unit: <divide><unitNumerator><measure>...</unitDenominator>
            divide = unit_elem.find(f"{{{xbrli_ns}}}divide")
            if divide is not None:
                numerator = divide.find(f"{{{xbrli_ns}}}unitNumerator")
                denominator = divide.find(f"{{{xbrli_ns}}}unitDenominator")

                num_measures = []
                den_measures = []

                if numerator is not None:
                    for m in numerator.findall(f"{{{xbrli_ns}}}measure"):
                        if m.text:
                            num_measures.append(self._resolve_measure(m.text))
                if denominator is not None:
                    for m in denominator.findall(f"{{{xbrli_ns}}}measure"):
                        if m.text:
                            den_measures.append(self._resolve_measure(m.text))

                num_str = " * ".join(num_measures) if num_measures else "?"
                den_str = " * ".join(den_measures) if den_measures else "?"
                units[unit_id] = f"{num_str} / {den_str}"
                continue

            # Fallback: unknown structure, store the unit_id itself
            units[unit_id] = unit_id

        return units

    def _parse_filing_labels(
        self, root: Element, base_url: str
    ) -> tuple[
        dict[str, dict[str, str]],
        dict[str, list[dict[str, Any]]],
    ]:
        """Discover and parse label/presentation linkbases from a filing.

        Follows the instance document's schemaRef → company schema →
        linkbaseRef chain to find and parse the label and presentation
        linkbase files for the filing.

        Parameters
        ----------
        root : Element
            The parsed root element of the XBRL instance document.
        base_url : str
            The base URL of the filing directory (ending with ``/``),
            used to resolve relative linkbase references.

        Returns
        -------
        tuple[dict[str, dict[str, str]], dict[str, list[dict[str, Any]]]]
            - labels_map: element_id → dict of role_short → label_text.
              Roles include ``label``, ``terseLabel``, ``totalLabel``,
              ``negatedLabel``, ``verboseLabel``, ``periodStartLabel``,
              ``periodEndLabel``, ``documentation``, etc.
            - presentation_map: element_id → list of dicts, each with
              ``table`` (role short name), ``parent`` (parent element_id),
              ``order`` (float), and ``preferred_label`` (role short name).
        """
        link_ns = "http://www.xbrl.org/2003/linkbase"
        xlink_ns = "http://www.w3.org/1999/xlink"
        labels_map: dict[str, dict[str, str]] = {}
        presentation_map: dict[str, list[dict[str, Any]]] = {}
        schema_href = None

        for ref in root.findall(f".//{{{link_ns}}}schemaRef"):
            schema_href = ref.get(f"{{{xlink_ns}}}href")

            if schema_href:
                break

        if not schema_href:
            return labels_map, presentation_map

        from urllib.parse import urljoin

        schema_url = (
            schema_href
            if schema_href.startswith("http")
            else urljoin(base_url, schema_href)
        )
        schema_root = self._load_filing_document("schema", schema_url)

        if schema_root is None:
            return labels_map, presentation_map

        label_url = None
        pre_url = None

        for ref in schema_root.findall(f".//{{{link_ns}}}linkbaseRef"):
            role = ref.get(f"{{{xlink_ns}}}role", "")
            href = ref.get(f"{{{xlink_ns}}}href", "")

            if not href:
                continue
            full_url = href if href.startswith("http") else urljoin(schema_url, href)

            if "labelLinkbaseRef" in role or "labelLinkbase" in role:
                label_url = full_url
            elif "presentationLinkbaseRef" in role or "presentationLinkbase" in role:
                pre_url = full_url

        lab_root = self._load_filing_document("label", label_url) if label_url else None

        if lab_root is not None:
            loc_map: dict[str, str] = {}

            for loc in lab_root.findall(f".//{{{link_ns}}}loc"):
                href = loc.get(f"{{{xlink_ns}}}href", "")
                loc_label = loc.get(f"{{{xlink_ns}}}label", "")

                if href and "#" in href:
                    loc_map[loc_label] = href.split("#")[1]

            resource_map: dict[str, dict[str, str]] = {}

            for res in lab_root.findall(f".//{{{link_ns}}}label"):
                role = res.get(f"{{{xlink_ns}}}role", "")
                role_short = role.split("/")[-1] if role else "label"
                res_label = res.get(f"{{{xlink_ns}}}label", "")

                if res_label not in resource_map:
                    resource_map[res_label] = {}

                resource_map[res_label][role_short] = res.text or ""

            for arc in lab_root.findall(f".//{{{link_ns}}}labelArc"):
                from_loc = arc.get(f"{{{xlink_ns}}}from", "")
                to_label = arc.get(f"{{{xlink_ns}}}to", "")

                if from_loc in loc_map and to_label in resource_map:
                    elem_id = loc_map[from_loc]

                    if elem_id not in labels_map:
                        labels_map[elem_id] = {}

                    labels_map[elem_id].update(resource_map[to_label])

        pre_root = (
            self._load_filing_document("presentation", pre_url) if pre_url else None
        )

        if pre_root is not None:
            for plink in pre_root.findall(f".//{{{link_ns}}}presentationLink"):
                role = plink.get(f"{{{xlink_ns}}}role", "")
                role_short = role.split("/")[-1] if role else ""
                pre_loc_map: dict[str, str] = {}

                for loc in plink.findall(f"{{{link_ns}}}loc"):
                    href = loc.get(f"{{{xlink_ns}}}href", "")
                    loc_label = loc.get(f"{{{xlink_ns}}}label", "")
                    if href and "#" in href:
                        pre_loc_map[loc_label] = href.split("#")[1]

                for arc in plink.findall(f"{{{link_ns}}}presentationArc"):
                    child_id = pre_loc_map.get(arc.get(f"{{{xlink_ns}}}to", ""))

                    if child_id is not None:
                        pref = arc.get("preferredLabel", "")
                        presentation_map.setdefault(child_id, []).append(
                            {
                                "table": role_short,
                                "parent": pre_loc_map.get(
                                    arc.get(f"{{{xlink_ns}}}from", "")
                                ),
                                "order": self._parse_order(arc.get("order")),
                                "preferred_label": (
                                    pref.split("/")[-1] if pref else None
                                ),
                            }
                        )

        return labels_map, presentation_map

    def parse_instance(
        self,
        file_content: BytesIO,
        base_url: str | None = None,
    ) -> tuple[
        dict[str, dict[str, Any]],
        dict[str, str],
        dict[str, list[dict[str, Any]]],
    ]:
        """Parse an XBRL instance document.

        Parameters
        ----------
        file_content : BytesIO
            The content of the XBRL instance document as a byte stream.
        base_url : str | None
            The base URL of the filing directory (ending with ``/``).
            When provided, the parser automatically discovers and parses
            the filing's label and presentation linkbases to resolve
            human-readable labels and documentation for each fact.

        Returns
        -------
        tuple[dict, dict, dict]
            A tuple containing:
            - contexts: A dictionary mapping context IDs to their details
              (entity, period_type, start, end, and any dimensional qualifiers).
            - units: A dictionary mapping unit IDs to their resolved measure
              strings (e.g., "iso4217:USD", "shares", "iso4217:USD / shares").
            - facts: A dictionary mapping element tags to a list of fact
              instances. Each fact is fully resolved with: tag, label,
              documentation, entity, period_type, start, end, dimensions,
              unit, decimals, value, and a ``presentation`` list describing
              each table appearance (table, parent, order, preferred_label).
        """
        try:
            root = self._get_xml_root(file_content)

            if root is None:
                raise ValueError("Failed to parse XML instance document: root is None")

            xbrli_ns = "http://www.xbrl.org/2003/instance"
            xbrldi_ns = "http://xbrl.org/2006/xbrldi"

            # Build namespace prefix map from xmlns declarations for
            # accurate tag normalization (handles company extensions, SEC
            # taxonomies like ecd, country, etc.)
            file_content.seek(0)
            ns_prefix_map = self._build_ns_prefix_map(file_content.read())

            contexts: dict[str, dict[str, Any]] = {}
            facts: dict[str, list[dict[str, Any]]] = {}

            # Parse unit definitions first so we can resolve unitRef in facts
            units = self._parse_units(root)

            # Load filing-level labels and presentation hierarchy
            labels_map: dict[str, dict[str, str]] = {}
            presentation_map: dict[str, list[dict[str, Any]]] = {}
            if base_url is not None:
                labels_map, presentation_map = self._parse_filing_labels(root, base_url)

            # Parse contexts - extract entity, period, and dimensions
            for context in root.findall(f".//{{{xbrli_ns}}}context"):
                context_id = context.get("id")
                if not context_id:
                    continue

                ctx_data: dict[str, Any] = {}

                # Entity identifier (CIK)
                entity = context.find(f"{{{xbrli_ns}}}entity")
                if entity is not None:
                    identifier = entity.find(f"{{{xbrli_ns}}}identifier")
                    if identifier is not None and identifier.text:
                        ctx_data["entity"] = identifier.text.strip()

                # Period
                period = context.find(f"{{{xbrli_ns}}}period")
                if period is not None:
                    instant = period.find(f"{{{xbrli_ns}}}instant")
                    start_date = period.find(f"{{{xbrli_ns}}}startDate")
                    end_date = period.find(f"{{{xbrli_ns}}}endDate")
                    forever = period.find(f"{{{xbrli_ns}}}forever")

                    if instant is not None:
                        ctx_data["period_type"] = "instant"
                        ctx_data["start"] = None
                        ctx_data["end"] = instant.text
                    elif forever is not None:
                        ctx_data["period_type"] = "forever"
                        ctx_data["start"] = None
                        ctx_data["end"] = None
                    else:
                        ctx_data["period_type"] = "duration"
                        ctx_data["start"] = (
                            start_date.text if start_date is not None else None
                        )
                        ctx_data["end"] = (
                            end_date.text if end_date is not None else None
                        )

                # Dimensions from segment (most common) or scenario
                dimensions: dict[str, str] = {}
                segment = (
                    entity.find(f"{{{xbrli_ns}}}segment")
                    if entity is not None
                    else None
                )
                scenario = context.find(f"{{{xbrli_ns}}}scenario")

                for container in (segment, scenario):
                    if container is None:
                        continue
                    # Explicit dimensions: <xbrldi:explicitMember dimension="axis">member</xbrldi:explicitMember>
                    for explicit in container.findall(f"{{{xbrldi_ns}}}explicitMember"):
                        dim = explicit.get("dimension", "")
                        val = (explicit.text or "").strip()
                        if dim and val:
                            dimensions[dim] = val
                    # Typed dimensions
                    # <xbrldi:typedMember dimension="axis"><ns:value>text</ns:value></xbrldi:typedMember>
                    for typed in container.findall(f"{{{xbrldi_ns}}}typedMember"):
                        dim = typed.get("dimension", "")
                        if dim:
                            for child in typed:
                                child_tag = (
                                    child.tag.split("}")[-1]
                                    if "}" in child.tag
                                    else child.tag
                                )
                                dimensions[dim] = (
                                    f"{child_tag}:{child.text}"
                                    if child.text
                                    else child_tag
                                )

                if dimensions:
                    ctx_data["dimensions"] = dimensions

                contexts[context_id] = ctx_data

            # Parse facts - iterate all elements and extract those with contextRef
            for elem in root.iter():
                context_ref = elem.get("contextRef")
                if context_ref is None:
                    continue

                # Get the tag name, normalizing namespace URI to prefix
                tag = elem.tag

                if "}" in tag:
                    ns, local = tag.rsplit("}", 1)
                    ns = ns[1:]  # Remove leading {
                    prefix = self._resolve_ns_prefix(ns, ns_prefix_map)
                    tag = f"{prefix}_{local}"
                else:
                    tag = tag.replace(":", "_")

                # Resolve unitRef to actual measure string
                unit_ref = elem.get("unitRef")
                resolved_unit = units.get(unit_ref, unit_ref) if unit_ref else None

                # Resolve context_ref to inline period/entity/dimensions
                ctx = contexts.get(context_ref, {})

                # Resolve labels from the filing's label linkbase
                elem_labels = labels_map.get(tag, {})
                label = elem_labels.get("label") or tag
                documentation = elem_labels.get("documentation")

                # Presentation metadata (table, parent, order, preferred_label)
                pres_entries = presentation_map.get(tag)

                fact_data: dict[str, Any] = {
                    "tag": tag,
                    "label": label,
                    "documentation": documentation,
                    "context_ref": context_ref,
                    "fact_id": elem.get("id"),
                    "entity": ctx.get("entity"),
                    "period_type": ctx.get("period_type"),
                    "start": ctx.get("start"),
                    "end": ctx.get("end"),
                    "unit": resolved_unit,
                    "decimals": elem.get("decimals"),
                    "value": elem.text,
                }

                # Only include dimensions key if present; resolve member labels
                dims = ctx.get("dimensions")

                if dims:
                    resolved_dims: dict[str, dict[str, Any]] = {}

                    for axis, member in dims.items():
                        # Normalize member to underscore format for label lookup
                        member_key = member.replace(":", "_")
                        member_labels = labels_map.get(member_key, {})
                        member_label = member_labels.get("label", member)
                        resolved_dims[axis] = {
                            "member": member,
                            "label": member_label,
                        }

                    fact_data["dimensions"] = resolved_dims

                if pres_entries:
                    fact_data["presentation"] = pres_entries

                if tag not in facts:
                    facts[tag] = []

                facts[tag].append(fact_data)

            return contexts, units, facts

        except Exception as e:
            raise OpenBBError(f"Failed to parse instance document: {e}") from e


class XBRLManager:
    """Main entry point for accessing XBRL Taxonomies."""

    def __init__(self):
        """Initialize the manager with a client and parser."""
        self.client = FASBClient()
        self.parser = XBRLParser()
        self._labels_loaded_for: set[tuple[str, int]] = set()
        self._properties_loaded_for: set[tuple[str, int]] = set()

    def _frc_member(self, taxonomy: str, year: int, kind: str) -> str | None:
        """Resolve an FRC suite member path for a taxonomy and file kind.

        Parameters
        ----------
        taxonomy : str
            Either ``"frc-core"`` or ``"frc-dpl"``.
        year : int
            The FRC suite year.
        kind : str
            One of ``"schema"``, ``"label"``, or ``"presentation"``.

        Returns
        -------
        str | None
            The matching member's relative path, or ``None`` if absent.
        """
        fragments, exclude = _FRC_MEMBER_FRAGMENTS[taxonomy][kind]
        return self.client.find_frc_member(year, *fragments, exclude=exclude)

    def _ensure_element_properties(self, taxonomy: str, year: int):
        """Load element properties (type, periodType, balance, etc.) for a taxonomy.

        Fetches the main schema XSD for the taxonomy and extracts element
        attributes into ``self.parser.element_properties``.
        """
        if (taxonomy, year) in self._properties_loaded_for:
            return

        config = TAXONOMIES.get(taxonomy)
        if not config:
            return

        if config.style == TaxonomyStyle.EXTERNAL and taxonomy in _FRC_TAXONOMIES:
            member = self._frc_member(taxonomy, year, "schema")
            if member:
                try:
                    content = self.client.fetch_frc_member(year, member)
                    if self.parser.load_schema_element_properties(content) > 0:
                        self._properties_loaded_for.add((taxonomy, year))
                except Exception:  # noqa: S110
                    pass
            return

        urls: list[str] = []

        if config.style == TaxonomyStyle.EXTERNAL and taxonomy == "ifrs":
            date = get_ifrs_version_dates().get(year)
            if date:
                urls.append(
                    f"https://xbrl.ifrs.org/taxonomy/{date}"
                    f"/full_ifrs/full_ifrs-cor_{date}.xsd"
                )
        elif config.style == TaxonomyStyle.STATIC:
            urls.append(config.base_url_template + config.label_file_pattern)
        else:
            base_url = config.base_url_template.format(year=year)
            if config.style == TaxonomyStyle.FASB_STANDARD:
                elts_url = f"{base_url}elts/"
                found = self.client.find_file(
                    elts_url, f"{taxonomy}-", str(year), ".xsd"
                ) or self.client.find_file(elts_url, taxonomy, str(year), ".xsd")
                if found:
                    urls.append(found)
            else:
                for frags in [
                    (f"{taxonomy}-", str(year), ".xsd"),
                    (f"{taxonomy}-entire-", str(year), ".xsd"),
                    (taxonomy, str(year), ".xsd"),
                ]:
                    found = self.client.find_file(base_url, *frags)
                    if found:
                        urls.append(found)

        for url in urls:
            try:
                content = self.client.fetch_file(url)
                loaded = self.parser.load_schema_element_properties(content)
                if loaded > 0:
                    self._properties_loaded_for.add((taxonomy, year))
                    return
            except Exception:  # noqa: S112
                continue

    def _get_roles_for_taxonomy(self, taxonomy: str, year: int) -> list[dict[str, Any]]:
        """Fetch role definitions for a taxonomy to enrich component listings.

        Returns a list of dicts with keys:
        name, short_name, document_number, group, sub_group, long_name.
        """
        config = TAXONOMIES.get(taxonomy)
        if not config:
            return []

        urls: list[str] = []
        if config.style == TaxonomyStyle.FASB_STANDARD:
            base_url = config.base_url_template.format(year=year)
            short = taxonomy.replace("-gaap", "")
            elts_url = f"{base_url}elts/"
            found_roles = self.client.find_file(
                elts_url, f"{short}-roles-", str(year), ".xsd"
            ) or self.client.find_file(elts_url, "roles", str(year), ".xsd")
            if found_roles:
                urls.append(found_roles)
            found_main = self.client.find_file(
                elts_url, f"{taxonomy}-", str(year), ".xsd"
            ) or self.client.find_file(elts_url, taxonomy, str(year), ".xsd")
            if found_main:
                urls.append(found_main)
        elif config.style in (
            TaxonomyStyle.SEC_EMBEDDED,
            TaxonomyStyle.SEC_STANDALONE,
        ):
            base_url = config.base_url_template.format(year=year)
            for frags in [
                (f"{taxonomy}-{year}", ".xsd"),
                (f"{taxonomy}-entire-", str(year), ".xsd"),
                (f"{taxonomy}-sub-", str(year), ".xsd"),
            ]:
                found = self.client.find_file(base_url, *frags)
                if found:
                    urls.append(found)
        elif config.style == TaxonomyStyle.STATIC:
            urls.append(config.base_url_template + config.label_file_pattern)

        for url in urls:
            try:
                content = self.client.fetch_file(url)
                _, roles, _, _ = self.parser.parse_schema(content)
                if roles:
                    return roles
            except Exception:  # noqa: S112
                continue
        return []

    def get_components_metadata(self, taxonomy: str, year: int) -> list[dict[str, Any]]:
        """Get component listing with rich metadata.

        Returns a list of dicts suitable for direct output, with keys:
        name, label, description, category, url.

        Handles three enrichment strategies:
        1. FASB (us-gaap, srt): role IDs match component names directly
        2. IFRS: fetch each standard's role file + known names dictionary
        3. SEC multi-component: fetch roles from main schema and match by
           cross-referencing which roles appear in each component's
           presentation file
        """
        import re

        config = TAXONOMIES.get(taxonomy)

        if not config:
            return []

        components = self.list_available_components(taxonomy, year)

        if not components:
            return []

        # --- Strategy 1: FASB --- role IDs match component names ---
        if config.style == TaxonomyStyle.FASB_STANDARD:
            roles = self._get_roles_for_taxonomy(taxonomy, year)
            role_by_name: dict[str, dict[str, Any]] = {r["name"]: r for r in roles}
            results: list[dict[str, Any]] = []

            # Industry prefix labels for early years (e.g. 2011) where
            # component names carry an industry prefix like "basi-", "bd-",
            # "ci-", "ins-", "re-" that does NOT appear in the role names.
            _industry_prefixes: dict[str, str] = {
                "basi": "Basic",
                "bd": "Broker-Dealer",
                "ci": "Commercial & Industrial",
                "ins": "Insurance",
                "re": "Real Estate",
            }

            for comp in components:
                role = role_by_name.get(comp)
                prefix_label = ""

                # If no direct match, try stripping the first segment as an
                # industry prefix (e.g. "basi-com" -> "com").
                if role is None and "-" in comp:
                    prefix, rest = comp.split("-", 1)
                    role = role_by_name.get(rest)
                    if role is not None:
                        prefix_label = _industry_prefixes.get(prefix, prefix.upper())

                if role:
                    short = role.get("short_name", comp)
                    label = f"{short} ({prefix_label})" if prefix_label else short
                    results.append(
                        {
                            "name": comp,
                            "label": label,
                            "description": role.get("long_name"),
                            "category": role.get("group"),
                            "url": None,
                        }
                    )
                else:
                    results.append(
                        {
                            "name": comp,
                            "label": comp,
                            "description": None,
                            "category": None,
                            "url": None,
                        }
                    )

            return results

        # --- Strategy 2: IFRS — per-standard role files + known names ---
        if config.style == TaxonomyStyle.EXTERNAL and taxonomy == "ifrs":
            date = get_ifrs_version_dates().get(year)
            results = []

            for comp in components:
                label = IFRS_STANDARD_NAMES.get(comp, comp.replace("_", " ").upper())
                description = None
                category = None

                # Try to fetch the role file for this standard
                if date:
                    role_url = (
                        f"https://xbrl.ifrs.org/taxonomy/{date}"
                        f"/full_ifrs/linkbases/{comp}/rol_{comp}_{date}.xsd"
                    )
                    try:
                        content = self.client.fetch_file(role_url)
                        _, roles_list, _, _ = self.parser.parse_schema(content)

                        if roles_list:
                            # Use the first role's definition as description
                            descriptions = [r.get("long_name", "") for r in roles_list]
                            description = "; ".join(d for d in descriptions[:5] if d)
                            # Determine category from definition text
                            first_def = roles_list[0].get("long_name", "")

                            if "Statement" in first_def:
                                category = "statement"
                            elif "Notes" in first_def:
                                category = "notes"
                            else:
                                category = "disclosure"
                    except Exception:  # noqa: S110
                        pass

                results.append(
                    {
                        "name": comp,
                        "label": label,
                        "description": description or label,
                        "category": category,
                        "url": None,
                    }
                )
            return results

        # --- Strategy 3: SEC multi-component ---
        # Fetch all roles from the main schema, then map roles to components
        # by checking which presentation file uses which role URIs.
        all_roles = self._get_roles_for_taxonomy(taxonomy, year)
        role_by_uri: dict[str, dict[str, Any]] = {}

        for r in all_roles:
            # Build expected role URI patterns
            role_by_uri[r["name"].lower()] = r

        base_url = config.base_url_template.format(year=year)
        results = []

        for comp in components:
            # Try to find which roles this component uses
            comp_roles: list[dict[str, Any]] = []

            # Fetch the component's presentation/schema file to find roleRefs
            comp_urls = []
            found_tc = self.client.find_file(
                base_url, f"{taxonomy}-{comp}-", str(year), ".xsd"
            )
            if found_tc:
                comp_urls.append(found_tc)
            found_c = self.client.find_file(base_url, f"{comp}-{year}", ".xsd")
            if found_c:
                comp_urls.append(found_c)
            if not comp_urls:
                # Broader search: any file containing the component name
                found_broad = self.client.find_file(base_url, comp, str(year), ".xsd")
                if found_broad:
                    comp_urls.append(found_broad)

            for comp_url in comp_urls:
                try:
                    content = self.client.fetch_file(comp_url)
                    resp_text = content.read().decode("utf-8", errors="replace")
                    # Find roleURI references in this file
                    role_uris = re.findall(r'roleURI="([^"]*)"', resp_text)
                    pres_roles = re.findall(
                        r'<link:presentationLink[^>]*role="([^"]*)"',
                        resp_text,
                    )
                    # Match URIs to our known roles
                    used_uris = set(role_uris + pres_roles)

                    for uri in used_uris:
                        # Extract role short name from URI
                        # e.g. http://xbrl.sec.gov/rr/role/RiskReturn -> RiskReturn
                        short = uri.rstrip("/").rsplit("/", 1)[-1]
                        role = role_by_uri.get(short.lower())

                        if role:
                            comp_roles.append(role)

                    if comp_roles:
                        break
                except Exception:  # noqa: S112
                    continue

            if comp_roles:
                # Sort by document number and show a summary
                comp_roles.sort(key=lambda x: x.get("document_number", "999999"))
                first = comp_roles[0]
                # Build description from all role long names
                description_parts = [r.get("long_name", "") for r in comp_roles]
                results.append(
                    {
                        "name": comp,
                        "label": (
                            first.get("short_name", comp)
                            if len(comp_roles) == 1
                            else f"{comp_roles[0].get('short_name', comp)} (+{len(comp_roles) - 1} more)"
                        ),
                        "description": "; ".join(d for d in description_parts[:5] if d),
                        "category": first.get("group"),
                        "url": None,
                    }
                )
            else:
                # Fallback to known names
                known = SEC_COMPONENT_NAMES.get(taxonomy, {}).get(comp)

                if known:
                    results.append(
                        {
                            "name": comp,
                            "label": known["label"],
                            "description": known.get("description", known["label"]),
                            "category": known.get("category"),
                            "url": None,
                        }
                    )
                else:
                    results.append(
                        {
                            "name": comp,
                            "label": comp.upper(),
                            "description": None,
                            "category": None,
                            "url": None,
                        }
                    )

        return results

    def _ensure_labels(self, taxonomy: str, year: int):
        """Load labels and documentation for the given taxonomy/year.

        Tries multiple label sources in order of quality:
        1. The configured label_file_pattern (_lab.xsd or _lab.xml)
        2. The *-entire-{year}.xsd file (has standard role/label)
        3. The *-sub-{year}.xsd file (some taxonomies like ecd)
        4. The *_doc.xsd file (has role/documentation labels)
        5. The main *-{year}.xsd file (may have embedded linkbase)

        For FASB taxonomies, also loads the dedicated *-doc-{year}.xml
        documentation file (separate from the label file).
        """

        if (taxonomy, year) in self._labels_loaded_for:
            return

        config = TAXONOMIES.get(taxonomy)

        if not config:
            return

        # --- IFRS: dedicated label/doc loading ---
        if config.style == TaxonomyStyle.EXTERNAL and taxonomy == "ifrs":
            date = get_ifrs_version_dates().get(year)

            if not date:
                return

            base = f"https://xbrl.ifrs.org/taxonomy/{date}"
            ifrs_label_urls = [
                f"{base}/full_ifrs/labels/lab_full_ifrs-en_{date}.xml",
                f"{base}/full_ifrs/labels/lab_ias_1-en_{date}.xml",
                f"{base}/full_ifrs/labels/doc_full_ifrs-en_{date}.xml",
                f"{base}/full_ifrs/labels/doc_ias_1-en_{date}.xml",
            ]
            loaded_any = False

            for url in ifrs_label_urls:
                try:
                    labels_before = len(self.parser.labels)
                    docs_before = len(self.parser.documentation)
                    content = self.client.fetch_file(url)

                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        self.parser.parse_label_linkbase(
                            content, TaxonomyStyle.FASB_STANDARD
                        )

                    if (
                        len(self.parser.labels) > labels_before
                        or len(self.parser.documentation) > docs_before
                    ):
                        loaded_any = True
                except Exception:  # noqa: S112
                    continue

            if loaded_any:
                self._labels_loaded_for.add((taxonomy, year))

            return

        # --- FRC core / dpl: read the label linkbase from the suite ZIP ---
        if config.style == TaxonomyStyle.EXTERNAL and taxonomy in _FRC_TAXONOMIES:
            member = self._frc_member(taxonomy, year, "label")
            if member:
                try:
                    content = self.client.fetch_frc_member(year, member)
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        self.parser.parse_label_linkbase(
                            content, TaxonomyStyle.SEC_EMBEDDED
                        )
                    if self.parser.labels:
                        self._labels_loaded_for.add((taxonomy, year))
                except Exception:  # noqa: S110
                    pass

            return

        # Build list of candidate URLs to try
        urls_to_try: list[str] = []

        if config.style == TaxonomyStyle.STATIC:
            urls_to_try.append(config.base_url_template + config.label_file_pattern)
        else:
            base_url = config.base_url_template.format(year=year)

            # Primary: resolve label file from directory listing
            if config.label_file_pattern:
                if config.style == TaxonomyStyle.FASB_STANDARD:
                    # FASB: labels in elts/ subdir
                    found = self.client.find_file(
                        f"{base_url}elts/", taxonomy, "lab", str(year)
                    ) or self.client.find_file(f"{base_url}elts/", "lab", str(year))
                    if found:
                        urls_to_try.append(found)
                else:
                    # SEC: find the label file (any naming convention)
                    if "-entire-" in config.label_file_pattern:
                        found = self.client.find_file(
                            base_url, f"{taxonomy}-entire-", str(year), ".xsd"
                        ) or self.client.find_file(base_url, taxonomy, "lab", str(year))
                    else:
                        found = self.client.find_file(
                            base_url, taxonomy, "lab", str(year)
                        ) or self.client.find_file(base_url, "lab", str(year))
                    if found:
                        urls_to_try.append(found)

            # Fallbacks for SEC taxonomies
            if config.style != TaxonomyStyle.FASB_STANDARD:
                for frags in [
                    (f"{taxonomy}-{year}", ".xsd"),
                    (f"{taxonomy}-entire-", str(year), ".xsd"),
                    (f"{taxonomy}-sub-", str(year), ".xsd"),
                    (f"{taxonomy}-std-", str(year)),
                    (taxonomy, "doc", str(year)),
                ]:
                    found = self.client.find_file(base_url, *frags)
                    if found:
                        urls_to_try.append(found)

        loaded_any = False

        for url in urls_to_try:
            try:
                labels_before = len(self.parser.labels)
                docs_before = len(self.parser.documentation)
                content = self.client.fetch_file(url)

                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    self.parser.parse_label_linkbase(
                        content, TaxonomyStyle.SEC_EMBEDDED
                    )

                if (
                    len(self.parser.labels) > labels_before
                    or len(self.parser.documentation) > docs_before
                ):
                    loaded_any = True
            except Exception:  # noqa: S112
                continue

        # Load dedicated documentation files (labels and docs are often
        # in separate files).  FASB uses *-doc-{year}.xml; SEC uses
        # *_doc.xsd (already included in urls_to_try above).
        doc_urls: list[str] = []
        if config.style == TaxonomyStyle.FASB_STANDARD:
            base_url = config.base_url_template.format(year=year)
            found_doc = self.client.find_file(
                f"{base_url}elts/", taxonomy, "doc", str(year)
            ) or self.client.find_file(f"{base_url}elts/", "doc", str(year))
            if found_doc:
                doc_urls.append(found_doc)

        for url in doc_urls:
            try:
                docs_before = len(self.parser.documentation)
                content = self.client.fetch_file(url)

                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    self.parser.parse_label_linkbase(
                        content, TaxonomyStyle.FASB_STANDARD
                    )

                if len(self.parser.documentation) > docs_before:
                    loaded_any = True
            except Exception:  # noqa: S112
                continue

        if loaded_any:
            self._labels_loaded_for.add((taxonomy, year))

        # For FASB taxonomies, fallback is not needed — the _lab.xml should work
        if config.style == TaxonomyStyle.FASB_STANDARD and not self.parser.labels:
            warnings.warn(f"Could not load standard labels for {taxonomy} {year}")

        # Reference fallback: SEC taxonomies (CYD, ECD, OEF, SBS, SPAC,
        # SRO, FND, etc.) often have no role/documentation labels but do
        # embed referenceLink elements with regulatory citations.  Parse
        # those as fallback documentation for elements still missing docs.
        if config.style in (
            TaxonomyStyle.SEC_EMBEDDED,
            TaxonomyStyle.SEC_STANDALONE,
        ):
            base_url = config.base_url_template.format(year=year)
            found_ref = self.client.find_file(
                base_url, f"{taxonomy}-{year}", ".xsd"
            ) or self.client.find_file(base_url, taxonomy, "ref", str(year))
            if not found_ref:
                # Broader: any .xsd containing the taxonomy name and year
                found_ref = self.client.find_file(base_url, taxonomy, str(year), ".xsd")
            ref_url = found_ref

            if ref_url:
                try:
                    ref_content = self.client.fetch_file(ref_url)
                    self.parser.parse_reference_linkbase(ref_content)
                except Exception:  # noqa: S110
                    pass

    def _load_frc_core_labels(self, year: int):
        """Load FRC core taxonomy labels for frc-dpl cross-namespace resolution.

        The Detailed Profit & Loss taxonomy references elements from the FRC
        core taxonomy (``core_*`` prefix). This loads the FRC core label
        linkbase from the suite ZIP so those elements get human-readable
        labels in the presentation output.
        """
        frc_key = ("frc-core", year)

        if frc_key in self._labels_loaded_for:
            return

        member = self._frc_member("frc-core", year, "label")
        if not member:
            return

        try:
            labels_before = len(self.parser.labels)
            content = self.client.fetch_frc_member(year, member)

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self.parser.parse_label_linkbase(content, TaxonomyStyle.SEC_EMBEDDED)

            if len(self.parser.labels) > labels_before:
                self._labels_loaded_for.add(frc_key)
        except Exception:  # noqa: S110
            pass

    def _parse_entire_file(
        self, taxonomy: str, year: int, config: TaxonomyConfig
    ) -> list[XBRLNode]:
        """Parse a taxonomy's *-entire-{year}.xsd, following xs:import if needed.

        SEC taxonomies publish an ``-entire-`` XSD that either:
        1. Embeds presentation, label, and definition linkbases directly
           (cyd, vip, country, currency, exch, naics, sic, stpr), or
        2. Acts as an import wrapper referencing ``-sub-``, ``-pre-``, or
           component XSDs that contain the actual linkbases (ecd, ffd, rxp,
           spac, cef, oef, fnd, sro, sbs, snj).

        This method handles both cases by first trying direct parsing, then
        resolving local imports and aggregating their presentation trees.

        Parameters
        ----------
        taxonomy : str
            The taxonomy key (e.g. ``'cyd'``, ``'ecd'``).
        year : int
            The taxonomy year.
        config : TaxonomyConfig
            The taxonomy's configuration.

        Returns
        -------
        list[XBRLNode]
            Parsed presentation tree, or empty list if the ``-entire-`` file
            is not available.
        """
        from urllib.parse import urljoin

        base_url = config.base_url_template.format(year=year)
        found = self.client.find_file(
            base_url, f"{taxonomy}-entire-", str(year), ".xsd"
        )
        if not found:
            return []  # No -entire- file in the directory listing
        entire_url = found

        try:
            content = self.client.fetch_file(entire_url)
        except Exception:
            return []  # No -entire- file available

        # Try direct parse (works when linkbases are embedded directly)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            nodes = self.parser.parse_presentation(content, config.style)
        if nodes:
            return nodes

        # Direct parse returned nothing — follow xs:import references.
        content.seek(0)
        _, _, _, imports = self.parser.parse_schema(content)

        all_nodes: list[XBRLNode] = []
        for imp in imports:
            loc = imp.get("schemaLocation", "")
            # Only follow local imports (not external XBRL/FASB specs)
            if loc.startswith("http") or not loc:
                continue
            import_url = urljoin(entire_url, loc)
            try:
                sub_content = self.client.fetch_file(import_url)
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    sub_nodes = self.parser.parse_presentation(
                        sub_content, config.style
                    )
                all_nodes.extend(sub_nodes)
            except Exception:  # noqa: S112
                continue
        return all_nodes

    def _get_frc_structure(self, taxonomy: str, year: int) -> list[XBRLNode]:
        """Parse an FRC taxonomy's structure from the suite ZIP.

        frc-dpl uses its compact presentation linkbase for hierarchy. frc-core's
        presentation linkbase spans the entire UK GAAP suite and is too large to
        traverse, so its elements are returned as a flat list from the schema.
        Labels and element properties are loaded beforehand by ``get_structure``.

        Parameters
        ----------
        taxonomy : str
            Either ``"frc-core"`` or ``"frc-dpl"``.
        year : int
            The FRC suite year.

        Returns
        -------
        list[XBRLNode]
            A presentation tree (frc-dpl) or a flat element list (frc-core).
        """
        nodes: list[XBRLNode] = []

        if taxonomy == "frc-dpl":
            presentation = self._frc_member(taxonomy, year, "presentation")
            if presentation:
                try:
                    content = self.client.fetch_frc_member(year, presentation)
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        nodes = self.parser.parse_presentation(
                            content, TaxonomyStyle.SEC_EMBEDDED
                        )
                except Exception:  # noqa: S110
                    pass

        if not nodes:
            schema = self._frc_member(taxonomy, year, "schema")
            if schema:
                content = self.client.fetch_frc_member(year, schema)
                nodes = self.parser.parse_schema_elements(content)

        return nodes

    def _get_ifrs_structure(self, year: int, component: str) -> list[XBRLNode]:
        """Get the parsed IFRS presentation structure for a given component.

        IFRS has a fundamentally different structure from SEC/FASB taxonomies:
        - Hosted on ``xbrl.ifrs.org`` with date-based versioning
        - Presentation linkbases are split across 50+ per-standard XML files
        - A single entry-point XSD references all files

        For a specific standard component (e.g. ``ias_1``, ``ifrs_7``):
            Fetches that standard's presentation linkbase files and builds
            the presentation hierarchy.

        For ``standard`` or any unrecognised component:
            Falls back to the core XSD's flat element list (5000+ elements).

        Parameters
        ----------
        year : int
            The taxonomy year (e.g. 2025).
        component : str
            An IFRS standard identifier (``ias_1``, ``ifrs_7``, …),
            or ``"standard"`` for the full flat element list.

        Returns
        -------
        list[XBRLNode]
            Hierarchical presentation tree (for a specific standard) or
            flat element list (for ``standard``).
        """
        import re
        from urllib.parse import urljoin

        ifrs_dates = get_ifrs_version_dates()
        date = ifrs_dates.get(year)
        if not date:
            raise OpenBBError(
                f"IFRS taxonomy not available for year {year}. "
                f"Known years: {sorted(ifrs_dates.keys(), reverse=True)}"
            )

        # For a specific standard, fetch its presentation linkbase files
        if component != "standard":
            ep_url = _resolve_ifrs_url(year, f"full_ifrs_entry_point_{date}.xsd")
            try:
                ep_content = self.client.fetch_file(ep_url)
                ep_text = ep_content.read().decode("utf-8", errors="replace")
            except Exception as e:
                raise OpenBBError(
                    f"Failed to fetch IFRS entry point for {year}: {e}"
                ) from e

            # Find all presentationLinkbaseRef hrefs for this standard
            # e.g. full_ifrs/linkbases/ias_1/pre_ias_1_2025-03-27_role-210000.xml
            pres_pattern = re.compile(
                rf'href="(full_ifrs/linkbases/{re.escape(component)}/pre_[^"]+\.xml)"'
            )
            pres_hrefs = pres_pattern.findall(ep_text)

            # Also include dimension presentation files if this is the
            # dimensions component or if specifically requested
            if not pres_hrefs:
                # Try dimension presentations
                dim_pattern = re.compile(
                    r'href="(full_ifrs/dimensions/pre_[^"]+\.xml)"'
                )
                pres_hrefs = dim_pattern.findall(ep_text)

            all_nodes: list[XBRLNode] = []
            for href in pres_hrefs:
                full_url = urljoin(ep_url, href)
                try:
                    content = self.client.fetch_file(full_url)
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        nodes = self.parser.parse_presentation(
                            content, TaxonomyStyle.FASB_STANDARD
                        )
                    all_nodes.extend(nodes)
                except Exception:  # noqa: S112
                    continue

            if all_nodes:
                return all_nodes

        # Fallback: flat element list from the core XSD
        core_url = _resolve_ifrs_url(year, f"full_ifrs/full_ifrs-cor_{date}.xsd")
        try:
            core_content = self.client.fetch_file(core_url)
            return self.parser.parse_schema_elements(core_content)
        except Exception as e:
            raise OpenBBError(
                f"Failed to fetch IFRS core schema for {year}: {e}"
            ) from e

    def get_structure(self, taxonomy: str, year: int, component: str) -> list[XBRLNode]:
        """Get the parsed presentation structure of a taxonomy component.

        Parameters
        ----------
        taxonomy : str
            The taxonomy key (e.g., 'us-gaap', 'dei', 'ecd', 'cyd').
        year : int
            The year of the taxonomy (e.g., 2024).
        component : str
            The component to retrieve (e.g., 'soi', 'bs' for us-gaap,
            'standard' for dei/ecd/cyd, 'rr'/'sr' for oef, 'n3'/'n4'/'n6' for vip).

        Returns
        -------
        list[XBRLNode]
            A list of XBRLNode objects representing the hierarchical
            presentation structure of the component.
        """

        config = TAXONOMIES.get(taxonomy)
        if not config:
            raise ValueError(
                f"Unsupported taxonomy: {taxonomy}. "
                f"Available: {', '.join(sorted(TAXONOMIES.keys()))}"
            )

        self._ensure_labels(taxonomy, year)
        self._ensure_element_properties(taxonomy, year)

        # FASB taxonomies reference elements from srt, dei, country, and currency;
        # load those labels and properties as well so cross-taxonomy references resolve.
        if config.style == TaxonomyStyle.FASB_STANDARD:
            for dep in ("srt", "dei", "country", "currency"):
                if dep in TAXONOMIES:
                    self._ensure_labels(dep, year)
                    self._ensure_element_properties(dep, year)

        # FRC dpl references elements from FRC core (core_* namespace);
        # load FRC core labels so cross-taxonomy references resolve.
        if taxonomy == "frc-dpl":
            self._load_frc_core_labels(year)

        # --- IFRS: per-standard or flat-element structure ---
        if config.style == TaxonomyStyle.EXTERNAL and taxonomy == "ifrs":
            return self._get_ifrs_structure(year, component)

        # --- FRC core / dpl: parse the presentation/schema from the suite ZIP ---
        if config.style == TaxonomyStyle.EXTERNAL and taxonomy in _FRC_TAXONOMIES:
            return self._get_frc_structure(taxonomy, year)

        # --- Determine the URL to fetch ---

        if config.style == TaxonomyStyle.STATIC:
            full_url = config.base_url_template + config.presentation_file_template
        elif config.style == TaxonomyStyle.FASB_STANDARD:
            base_url = config.base_url_template.format(year=year)
            stm_url = f"{base_url}stm/"
            # Resolve actual filename from directory listing — try
            # progressively broader fragment sets to handle different
            # naming conventions across years.
            found = (
                self.client.find_file(
                    stm_url,
                    f"{taxonomy}-stm-{component}-pre-",
                    str(year),
                )
                or self.client.find_file(
                    stm_url,
                    component,
                    "-pre-",
                    str(year),
                )
                or self.client.find_file(
                    stm_url,
                    component,
                    "pre",
                    str(year),
                )
            )
            if not found:
                raise OpenBBError(
                    f"No presentation file found for {taxonomy}/{year}/{component}. "
                    f"Available files in stm/: {[f for f in self.client.list_files(stm_url) if component in f]}"
                )
            full_url = found
        elif component == "standard" and config.style in (
            TaxonomyStyle.SEC_EMBEDDED,
            TaxonomyStyle.SEC_STANDALONE,
        ):
            # For "standard" SEC components, use the *-entire-{year}.xsd
            # which contains (or imports) the full presentation hierarchy.
            # _parse_entire_file handles both direct-embed and import-wrapper.
            try:
                nodes = self._parse_entire_file(taxonomy, year, config)
                if nodes:
                    return nodes
            except Exception:  # noqa: S110
                pass

            # Fall back to the main schema and flat element extraction
            # (reference taxonomies: country, currency, exch, etc.)
            base_url = config.base_url_template.format(year=year)
            found = self.client.find_file(
                base_url, f"{taxonomy}-{year}", ".xsd"
            ) or self.client.find_file(base_url, taxonomy, str(year), ".xsd")
            if not found:
                raise OpenBBError(
                    f"No schema file found for {taxonomy}/{year} in listing."
                )
            full_url = found
        else:
            base_url = config.base_url_template.format(year=year)
            # Resolve actual file from directory listing — try
            # progressively broader fragment sets.
            found = (
                self.client.find_file(
                    base_url,
                    f"{taxonomy}-{component}-",
                    str(year),
                )
                or self.client.find_file(
                    base_url,
                    f"{taxonomy}-{component}-pre-",
                    str(year),
                )
                or self.client.find_file(
                    base_url,
                    component,
                    str(year),
                )
            )
            if not found:
                raise OpenBBError(
                    f"No presentation file found for {taxonomy}/{year}/{component}. "
                    f"Check available components with list_available_components()."
                )
            full_url = found

        try:
            content = self.client.fetch_file(full_url)

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                nodes = self.parser.parse_presentation(content, config.style)

            # Flat element fallback for reference/enumeration taxonomies
            # that have no presentation linkbase at all.
            if not nodes and config.style in (
                TaxonomyStyle.SEC_EMBEDDED,
                TaxonomyStyle.SEC_STANDALONE,
            ):
                if full_url.endswith(".xsd"):
                    content.seek(0)
                    nodes = self.parser.parse_schema_elements(content)
                else:
                    base_url = config.base_url_template.format(year=year)
                    found_schema = self.client.find_file(
                        base_url, f"{taxonomy}-{year}", ".xsd"
                    ) or self.client.find_file(base_url, taxonomy, str(year), ".xsd")
                    if found_schema:
                        schema_content = self.client.fetch_file(found_schema)
                        nodes = self.parser.parse_schema_elements(schema_content)

            # Aggregation: if a component is an empty wrapper that only
            # imports sub-schemas (e.g. sbs "sbsef" imports sbsef-cco,
            # sbsef-com, etc.), aggregate from child components.
            if not nodes:
                all_comps = self.list_available_components(taxonomy, year)
                children = [
                    c
                    for c in all_comps
                    if c != component and c.startswith(f"{component}-")
                ]
                if children:
                    for child in children:
                        child_nodes = self.get_structure(taxonomy, year, child)
                        nodes.extend(child_nodes)

            return nodes

        except Exception as e:
            raise OpenBBError(
                f"Failed to get structure for {taxonomy} {year} {component}: {e}"
            ) from e

    def list_available_taxonomies(
        self, category: TaxonomyCategory | str | None = None
    ) -> dict[str, dict[str, str]]:
        """List all registered taxonomies with their labels and descriptions.

        Parameters
        ----------
        category : TaxonomyCategory | str | None
            If provided, filter to only taxonomies in this category.
            Accepts a TaxonomyCategory enum or its string value
            (e.g., "operating_company", "investment_company").

        Returns
        -------
        dict[str, dict[str, str]]
            A dictionary mapping taxonomy keys to their metadata
            (label, description, category, style, sec_reference_url).
        """
        cat_filter: TaxonomyCategory | None = None

        if category is not None:
            if isinstance(category, str):
                try:
                    cat_filter = TaxonomyCategory(category)
                except ValueError:
                    valid = [c.value for c in TaxonomyCategory]
                    raise ValueError(
                        f"Invalid category: {category!r}. Valid values: {valid}"
                    ) from None
            else:
                cat_filter = category

        result = {}

        for key, config in TAXONOMIES.items():
            if cat_filter is not None and config.category != cat_filter:
                continue

            result[key] = {
                "label": config.label,
                "description": config.description,
                "category": config.category.value,
                "style": config.style.name,
                "has_label_linkbase": str(config.has_label_linkbase),
                "sec_reference_url": config.sec_reference_url,
            }

        return result

    def list_available_components(self, taxonomy: str, year: int) -> list[str]:
        """List available components for a given taxonomy and year.

        Parameters
        ----------
        taxonomy : str
            The taxonomy to check (e.g., 'us-gaap', 'srt', 'dei').
        year : int
            The year of the taxonomy to check (e.g., 2024).

        Returns
        -------
        list[str]
            A list of available component names (e.g., ['soi', 'bs'] for us-gaap).
        """
        config = TAXONOMIES.get(taxonomy)

        if not config:
            return []

        return self.client.get_components_for_year(year, config)

    def get_available_years(self, taxonomy: str) -> list[int]:
        """List available years for a given taxonomy.

        Parameters
        ----------
        taxonomy : str
            The taxonomy to check (e.g., 'us-gaap', 'srt', 'dei').

        Returns
        -------
        list[int]
            A list of available years (e.g., [2024, 2023, 2022]).
        """
        config = TAXONOMIES.get(taxonomy)

        if not config:
            return []

        return self.client.get_available_years(taxonomy, config)
