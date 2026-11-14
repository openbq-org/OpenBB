"""Non-XBRL Statement Parser - An independent module for parsing pre-XBRL, and non-XBRL SEC filings."""

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bs4 import BeautifulSoup
    from pandas import DataFrame


def parse_non_xbrl_statement(
    html_content: str,
    statement_type: str = "income",
) -> tuple["DataFrame", "DataFrame"]:
    """
    Parse financial statements from non-XBRL HTML filings.

    Parameters
    ----------
    html_content : str
        The raw HTML content of the filing document.
    statement_type : str
        Type of statement to extract: 'income', 'balance', 'cash', 'equity'

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        A tuple of (statement_df, meta_df).
        - statement_df: One row per line item, columns for label + each period's value
        - meta_df: Metadata about the statement (title, periods, scale, etc.)
    """
    from bs4 import BeautifulSoup
    from pandas import DataFrame

    # Route SGML content to specialized parser
    if _is_sgml_content(html_content):
        return _parse_sgml_statement(html_content, statement_type)

    soup = BeautifulSoup(html_content, "html.parser")

    # Find the statement table based on keywords
    statement_keywords = _get_statement_keywords(statement_type)

    # Get all tables
    all_tables = soup.find_all("table")

    best_table = None
    best_score = 0

    for table in all_tables:
        table_text = table.get_text(separator=" ", strip=True).lower()

        # Score based on keyword matches
        score = sum(1 for kw in statement_keywords if kw.lower() in table_text)

        # Skip tables that are likely table of contents or index
        if score > 0:
            # Skip tables that look like table of contents
            if "page no" in table_text or "item 1:" in table_text:
                # This is probably a TOC - penalize heavily
                score = max(0, score - 5)
                if score <= 0:
                    continue

            # Must have substantial numeric content (at least 10 numbers)
            numbers = re.findall(r"\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\b", table_text)
            if len(numbers) < 10:
                continue

            # Bonus score for having scale indicator (in millions, etc.)
            if (
                "in millions" in table_text
                or "in thousands" in table_text
                or "in billions" in table_text
            ):
                score += 2

            # Bonus for having dollar signs (actual values)
            dollar_count = table_text.count("$")
            if dollar_count > 5:
                score += 1

            # Bonus for more numbers (more data)
            if len(numbers) > 30:
                score += 1

        if score > best_score:
            best_table = table
            best_score = score

    if best_table is None:
        return DataFrame(), DataFrame()

    # Extract data from the table
    result = _extract_table_data(best_table)
    if result is None:
        return DataFrame(), DataFrame()

    line_items, periods, multiplier, title = result

    if not line_items:  # pragma: no cover  # reason: _extract_table_data returns None when line_items is empty, so this is never empty here
        return DataFrame(), DataFrame()

    # Build the statement DataFrame - one row per line item
    statement_df = _build_statement_dataframe(line_items, periods, multiplier)

    # Build the metadata DataFrame
    meta_df = _build_meta_dataframe(title, periods, multiplier)

    return statement_df, meta_df


def _get_statement_keywords(statement_type: str) -> list[str]:
    """Get keywords to identify statement type."""
    keywords = {
        "income": [
            "statements of earnings",
            "statements of income",
            "statements of operations",
            "net earnings",
            "net income",
            "total revenues",
        ],
        "balance": [
            "balance sheet",
            "financial condition",
            "financial position",
            "total assets",
            "total liabilities",
            "stockholders equity",
            "shareholders equity",
            "cash and cash equivalents",
        ],
        "cash": [
            "cash flows",
            "operating activities",
            "investing activities",
            "financing activities",
        ],
        "equity": [
            "stockholders equity",
            "shareholders equity",
            "changes in equity",
        ],
    }
    return keywords.get(statement_type, keywords["income"])


def _detect_multiplier(table) -> tuple[int, str]:
    """
    Detect value multiplier from table text.

    Returns (multiplier, scale_name).
    """
    table_text = table.get_text(separator=" ", strip=True).lower()

    if "in millions" in table_text or "(millions)" in table_text:
        return 1_000_000, "millions"

    if "in thousands" in table_text or "(thousands)" in table_text:
        return 1_000, "thousands"

    if "in billions" in table_text or "(billions)" in table_text:
        return 1_000_000_000, "billions"

    return 1, "units"


def _extract_table_data(
    table,
) -> tuple[list[dict], list[str], int, str | None] | None:
    """
    Extract structured data from a financial table.

    Returns tuple of (line_items, periods, multiplier, title) or None.
    Each line_item is a dict with 'label', 'section', and 'values' (list of floats).
    """
    rows = table.find_all("tr")
    if len(rows) < 5:
        return None

    multiplier, _ = _detect_multiplier(table)

    # Parse header rows to get period labels
    periods = _extract_periods(rows[:20])
    # Don't use placeholder garbage - if no headers found, we'll figure it out from data
    if not periods:
        # Count actual value columns from first few data rows
        for row in rows[1:10]:
            cells = row.find_all(["td", "th"])
            cell_texts = [_clean_cell_text(c) for c in cells]
            values = [
                c
                for c in cell_texts
                if c
                and re.match(r"^[\d,.\$\(\)-]+$", c.replace(",", "").replace("$", ""))
            ]
            if len(values) >= 2:
                periods = [f"Col {i + 1}" for i in range(len(values))]
                break
        if not periods:
            periods = ["Value"]

    num_periods = len(periods)

    # Parse data rows
    line_items = []
    current_section = None
    title = None

    for row in rows:
        cells = row.find_all(["td", "th"])

        # Skip rows with too many cells (corrupted)
        if len(cells) > 50 or len(cells) == 0:
            continue

        cell_texts = [_clean_cell_text(c) for c in cells]

        # Skip empty rows
        if not any(cell_texts):
            continue

        # Skip header rows that contain period labels (e.g., "Year Ended June 30" with years)
        row_text = " ".join(cell_texts).lower()
        if _is_header_row(row_text, cell_texts):
            continue

        # Check for section header (single non-empty cell, ends with : or no numbers)
        non_empty = [c for c in cell_texts if c]
        if len(non_empty) == 1:
            text = non_empty[0].rstrip(":")
            if text and not re.search(r"\d", text) and len(text) < 100:
                current_section = text
                continue

        # Try to parse as data row
        parsed = _parse_data_row(cell_texts, num_periods)
        if parsed:
            label, values, skip_multiplier = parsed
            line_items.append(
                {
                    "label": label,
                    "section": current_section,
                    "values": values,
                    "skip_multiplier": skip_multiplier,
                }
            )

    if not line_items:
        return None

    return line_items, periods, multiplier, title


def _is_header_row(row_text: str, cell_texts: list[str]) -> bool:
    """
    Detect if a row is a header row that should be skipped.

    Header rows contain period descriptions like "Year Ended June 30"
    combined with year numbers like "1999", "2000", etc.
    """
    # Check for period descriptor phrases
    period_phrases = [
        "year ended",
        "years ended",
        "months ended",
        "month ended",
        "quarter ended",
        "quarters ended",
        "fiscal year",
        "fiscal years",
        "in millions",
        "in thousands",
        "in billions",
        "(except",
        "except per share",
    ]

    has_period_phrase = any(phrase in row_text for phrase in period_phrases)

    # Check if row contains standalone year numbers (4-digit years)
    year_pattern = r"\b(19|20)\d{2}\b"
    years_in_row = re.findall(year_pattern, " ".join(cell_texts))
    has_multiple_years = len(years_in_row) >= 2

    # It's a header if it has period phrases OR multiple years as standalone values
    if has_period_phrase:
        return True

    if has_multiple_years:
        # Check if the years appear as separate cell values (not embedded in text)
        standalone_years = 0
        for text in cell_texts:
            t = text.strip()
            # Year with optional footnote like "2001(2)" or "2001"
            if re.match(r"^(19|20)\d{2}(\s*\(\d+\))?$", t):
                standalone_years += 1
        if standalone_years >= 2:
            return True

    return False


def _extract_periods(header_rows) -> list[str]:
    """
    Extract column headers from header rows.

    Looks for patterns like:
    - Row with "Three Months Ended May" / "Six Months Ended May"
    - Row with years "1999" / "1998" / "1999" / "1998"
    - Row with column titles like "GROSS CARRYING AMOUNT", "NET VALUE"

    Combines them into full period labels.
    """
    period_prefixes = []  # e.g., ["Three Months Ended May", "Six Months Ended May"]
    years = []  # e.g., ["1999", "1998", "1999", "1998"]
    column_headers = []  # Non-period headers like "GROSS CARRYING AMOUNT"

    for row in header_rows:
        cells = row.find_all(["td", "th"])
        if len(cells) > 50:
            continue

        cell_texts = [_clean_cell_text(c) for c in cells]
        non_empty = [c for c in cell_texts if c]

        if not non_empty:
            continue

        row_text = " ".join(non_empty)

        # Look for period descriptions (e.g., "Three Months Ended")
        if re.search(r"(months? ended|year ended|quarter ended)", row_text, re.I):
            period_prefixes = [
                c for c in non_empty if re.search(r"(months?|year|quarter)", c, re.I)
            ]

        # Look for years
        year_matches = re.findall(r"\b((?:19|20)\d{2})\b", row_text)
        if len(year_matches) >= 2 and not years:
            years = year_matches

        # Look for column headers (not years, not empty, likely uppercase or title case)
        # These are headers like "GROSS CARRYING AMOUNT", "BALANCE", "ADDITIONS"
        if not column_headers:
            header_keywords = [
                "amount",
                "balance",
                "value",
                "gross",
                "net",
                "carrying",
                "accumulated",
                "additions",
                "segment",
                "adjustments",
                "divestitures",
                "translation",
            ]

            potential_headers = []
            has_keyword = False
            for c in non_empty:
                # Skip if it's just a year
                if re.match(r"^(19|20)\d{2}$", c):
                    continue
                # Skip if it's a number
                if re.match(r"^[\d,.\$\(\)-]+$", c.replace(",", "")):
                    continue
                # Skip very short text
                if len(c) < 3:
                    continue
                # Skip common non-header text
                if c.lower() in ("$", "for the", "at"):
                    continue
                potential_headers.append(c)
                # Check if this header contains keywords
                if any(kw in c.lower() for kw in header_keywords):
                    has_keyword = True

            # If we found headers with keywords, use them (skip first column which is usually row labels)
            if has_keyword and len(potential_headers) >= 2:
                # First column is usually the row label header, skip it
                column_headers = (
                    potential_headers[1:]
                    if len(potential_headers) > 2
                    else potential_headers
                )

    # Combine prefixes with years
    if period_prefixes and years:
        # Match prefixes to years
        periods = []
        prefix_idx = 0
        for i, year in enumerate(years):
            if prefix_idx < len(period_prefixes):
                prefix = period_prefixes[prefix_idx]
                periods.append(f"{prefix} {year}")
                # Advance prefix index every 2 years (assuming 2 years per period type)
                if (i + 1) % 2 == 0:
                    prefix_idx += 1
            else:
                periods.append(year)
        return periods
    elif column_headers:
        # Prefer column headers over bare years
        return column_headers
    elif years:
        return years

    return []


def _clean_cell_text(cell) -> str:
    """Extract clean text from a cell."""
    text = cell.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _is_bullet_table(table_elem) -> bool:
    """Check if table is a bullet list (• in first column)."""
    rows = table_elem.find_all("tr")
    bullet_count = 0
    for row in rows[:5]:  # Check first 5 rows
        cells = row.find_all("td")
        if cells:
            first_cell = cells[0].get_text(strip=True)
            if first_cell in ("•", "&#149;", "*", "-", "—"):
                bullet_count += 1
    return bullet_count >= 1


def _extract_bullet_list(table_elem) -> str | None:
    """Extract bullet list from table format."""
    bullets = []
    rows = table_elem.find_all("tr")
    for row in rows:
        cells = row.find_all("td")
        if len(cells) >= 2:
            first_cell = cells[0].get_text(strip=True)
            if first_cell in ("•", "&#149;", "*", "-", "—", ""):
                text = " ".join(
                    c.get_text(separator=" ", strip=True) for c in cells[1:]
                )
                text = _clean_html_entities(text)
                text = re.sub(r"\s+", " ", text).strip()
                if text and len(text) > 5:
                    bullets.append(f"- {text}")
    return "\n\n".join(bullets) if bullets else None


def _is_financial_table(table_elem) -> bool:
    """Check if table has numeric data (financial table)."""
    text = table_elem.get_text()
    # Count numbers with commas (financial values)
    numbers = re.findall(r"\d{1,3}(?:,\d{3})+", text)
    return len(numbers) >= 3


def _get_direct_text(elem) -> str:
    """Get text from direct children only, not nested P or TABLE."""
    from bs4.element import NavigableString

    parts = []
    for child in elem.children:
        if isinstance(child, NavigableString):
            text = str(child).strip()
            if text:
                parts.append(text)
        elif hasattr(child, "name") and child.name not in ["p", "table"]:
            text = child.get_text(strip=True)
            if text:
                parts.append(text)
    return " ".join(parts)


def _clean_paragraph_text(text: str) -> str | None:  # noqa: PLR0911
    """Clean paragraph text for disclosure extraction."""
    if not text:
        return None
    text = _clean_html_entities(text)
    # Skip boilerplate and very short text
    if re.match(r"^\d+$", text):
        return None
    if len(text) < 5:
        return None
    if text in ("(UNAUDITED)", "(Continued)") or text.endswith("(Continued)"):
        return None
    if "PAGEBREAK" in text:
        return None
    # Skip page headers/footers
    if "page" in text.lower() and len(text) < 50:
        return None
    # Skip garbled table data (cells concatenated without spaces)
    if re.search(r"19\d{2}19\d{2}", text):
        return None
    if re.search(r"\$[\d,]+\$[\d,]+", text):
        return None
    if text.count("$") > 3:
        return None
    text = re.sub(r"\s+", " ", text)
    return text


def _is_section_header(elem) -> bool:
    """Check if P element is a section header (short bold text only)."""
    # Get direct B tags
    b_tags = [c for c in elem.children if hasattr(c, "name") and c.name == "b"]
    if len(b_tags) != 1:
        return False
    b_text = b_tags[0].get_text(strip=True)
    # Check length and that it's the only content
    direct_text = _get_direct_text(elem)
    if direct_text == b_text and 3 < len(b_text) < 60:
        # Exclude numbered items like "1. Former Partner..."
        return not re.match(r"^\d+\.", b_text)
    return False


def _parse_data_row(
    cell_texts: list[str], expected_values: int
) -> tuple[str, list[float | None], bool] | None:
    """
    Parse a row into (label, values, is_per_share).

    Returns None if not a valid data row.
    is_per_share indicates if values should NOT have multiplier applied.
    """
    if not cell_texts:
        return None

    label = None
    values = []
    pending_negative = None  # Track numbers like "(14" waiting for ")"

    for cell in cell_texts:
        if not cell or cell in ("$", "—", "-", ""):
            continue

        # Handle closing paren for negative number from previous cell
        if cell == ")" and pending_negative is not None:
            values.append(-float(pending_negative))
            pending_negative = None
            continue

        # Check for opening paren negative like "(14"
        if cell.startswith("(") and not cell.endswith(")"):
            # Try to parse the number part
            num_part = cell[1:].replace(",", "")
            try:
                pending_negative = float(num_part)
                continue
            except ValueError:
                pass

        # Try to parse as number
        num = _parse_number(cell)
        if num is not None:
            values.append(num)
        elif label is None:
            # First text is the label
            label = cell

    # Must have a label
    if label is None:
        return None

    # Label sanity check - reject labels that are too long or contain embedded data
    if len(label) > 100:
        return None

    # Skip malformed labels that contain numbers (corrupted nested cells)
    # e.g., "Basic 474,712,271 474,712,271 Diluted 479,908,301"
    if re.search(r"\d{3},\d{3}", label):
        return None

    # Must have at least 1 value
    if not values:
        return None

    # Detect per-share items (EPS, etc.) - don't apply multiplier
    label_lower = label.lower()
    is_per_share = any(
        kw in label_lower for kw in ["per share", "basic", "diluted", "eps"]
    )

    # Detect share count items - don't apply multiplier
    is_share_count = any(
        kw in label_lower
        for kw in ["shares", "share count", "units issued", "units outstanding"]
    )

    # Skip multiplier for per-share or share count items
    skip_multiplier = is_per_share or is_share_count

    # Pad or truncate values to expected count
    if len(values) < expected_values:
        values.extend([None] * (expected_values - len(values)))
    elif len(values) > expected_values:
        values = values[:expected_values]

    return label, values, skip_multiplier


def _parse_number(text: str) -> float | None:
    """Parse text as a number, handling parentheses for negatives."""
    if not text:
        return None

    text = text.strip()

    # Handle parentheses for negative
    is_negative = text.startswith("(") and text.endswith(")")
    if is_negative:
        text = text[1:-1]

    # Remove commas
    cleaned = text.replace(",", "")

    # Must be numeric
    if not re.match(r"^-?\d+(\.\d+)?$", cleaned):
        return None

    value = float(cleaned)
    if is_negative:
        value = -value
    return value


def _build_statement_dataframe(
    line_items: list[dict], periods: list[str], multiplier: int
) -> "DataFrame":
    """
    Build a DataFrame in long format matching XBRL output structure.

    Columns: order, tag, parent_tag, preferred_label, balance, weight, decimals,
             context_ref, period_beginning, period_ending, unit, label, value

    Each (line_item, period) combination becomes one row.
    Values are multiplied by the scale factor (except per-share items).
    """
    from pandas import DataFrame

    rows = []

    for order, item in enumerate(line_items, start=1):
        label = item["label"]
        section = item["section"]
        values = item["values"]
        skip_multiplier = item.get("skip_multiplier", False)

        # Apply multiplier unless per-share or share count
        scale = 1 if skip_multiplier else multiplier

        # Determine unit based on label
        label_lower = label.lower() if label else ""
        _shares_pos = label_lower.find("shares")
        _per_pos = label_lower.find("per")
        is_share_count = _shares_pos >= 0 and (_per_pos < 0 or _shares_pos < _per_pos)
        is_per_share = not is_share_count and (
            bool(re.search(r"\bper\b.*\bshare\b", label_lower)) or "eps" in label_lower
        )
        if is_per_share:
            unit = "USD/shares"
        elif is_share_count:
            unit = "shares"
        else:
            unit = "USD"

        # Create one row per period
        for i, period in enumerate(periods):
            value = (
                values[i] * scale if i < len(values) and values[i] is not None else None
            )

            # Parse period_ending from period string (extract year)
            period_ending = _extract_period_ending(period)

            rows.append(
                {
                    "order": order,
                    "tag": None,  # No XBRL tag for non-XBRL filings
                    "parent_tag": section,  # Section heading is the parent
                    "preferred_label": None,
                    "balance": None,
                    "weight": None,
                    "decimals": None,
                    "context_ref": period,  # Use full period description
                    "period_beginning": None,  # Could be derived for income/cash statements
                    "period_ending": period_ending,
                    "unit": unit,
                    "label": label,
                    "value": value,
                }
            )

    return DataFrame(rows)


def _extract_period_ending(period: str) -> str | None:
    """Extract a date string from a period label like 'Year Ended June 30 2003'."""
    # Try to find a 4-digit year
    year_match = re.search(r"\b(19|20)\d{2}\b", period)
    if not year_match:
        return None

    year = year_match.group(0)

    # Try to find month
    months = {
        "january": "01",
        "february": "02",
        "march": "03",
        "april": "04",
        "may": "05",
        "june": "06",
        "july": "07",
        "august": "08",
        "september": "09",
        "october": "10",
        "november": "11",
        "december": "12",
        "jan": "01",
        "feb": "02",
        "mar": "03",
        "apr": "04",
        "jun": "06",
        "jul": "07",
        "aug": "08",
        "sep": "09",
        "oct": "10",
        "nov": "11",
        "dec": "12",
    }

    period_lower = period.lower()
    for month_name, month_num in months.items():
        if month_name in period_lower:
            # Try to find day
            day_match = re.search(rf"{month_name}\s+(\d{{1,2}})", period_lower)
            if day_match:
                day = day_match.group(1).zfill(2)
            else:
                # Default to end of month
                day = "30" if month_num in ("04", "06", "09", "11") else "31"
                if month_num == "02":
                    day = "28"
            return f"{year}-{month_num}-{day}"

    # Just return year-12-31 as default (fiscal year end)
    return f"{year}-12-31"


def _build_meta_dataframe(
    title: str | None, periods: list[str], multiplier: int
) -> "DataFrame":
    """Build metadata DataFrame."""
    from pandas import DataFrame

    if multiplier == 1_000_000_000:
        scale = "billions"
    elif multiplier == 1_000_000:
        scale = "millions"
    elif multiplier == 1_000:
        scale = "thousands"
    else:
        scale = "units"

    return DataFrame(
        {
            "title": [title or "Financial Statement"],
            "periods": [periods],
            "num_periods": [len(periods)],
            "is_xbrl": [False],
            "source": ["HTML Table"],
            "scale": [scale],
            "multiplier": [multiplier],
        }
    )


def find_all_statements(
    html_content: str,
) -> dict[str, tuple["DataFrame", "DataFrame"]]:
    """
    Find and parse all financial statements in a filing.

    Returns a dict mapping statement type to (data_df, meta_df).
    """
    results = {}

    for stmt_type in ["income", "balance", "cash", "equity"]:
        data_df, meta_df = parse_non_xbrl_statement(html_content, stmt_type)
        if not data_df.empty:
            results[stmt_type] = (data_df, meta_df)

    return results


def extract_toc(html_content: str) -> dict[str, str]:
    """
    Extract table of contents from a non-XBRL filing.

    Returns a dict mapping item numbers (e.g., '1', '1A', '7') to titles.
    Also captures PART I/II and sub-items under Item 1 for financial statements.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html_content, "html.parser")
    toc_dict: dict = {}

    # Valid SEC filing item numbers: 1-15 with optional A/B/C suffix
    # Excludes regulatory references like Item 405, Item 601
    valid_item_pattern = re.compile(
        r"^ITEM\s*(1[0-5]?|[2-9])(A|B|C)?[.:]?$", re.IGNORECASE
    )

    # Method 1: Group links by href - TOC has "ITEM 1." in one cell and title in another
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

    # Find pairs: one text matches "ITEM X." pattern, another is the title
    for href, texts in href_to_texts.items():
        item_num = None
        title = None
        for text in texts:
            # Check if it's a valid item number pattern
            item_match = valid_item_pattern.match(text.strip())
            if item_match:
                num = item_match.group(1)
                suffix = item_match.group(2) or ""
                item_num = f"{num}{suffix}".upper()
            elif (
                text
                and not re.match(r"^\d+$", text)  # Not just a page number
                and title is None
                and len(text) > 5
            ):
                # Skip short words like "of" that are fragments
                title = text

        if item_num and title and item_num not in toc_dict:
            toc_dict[item_num] = title

    # Method 2: Parse table-based TOC (common in pre-2000 filings)
    if not toc_dict:
        toc_dict = _extract_toc_from_table(soup)

    # Method 3: Fall back to text pattern matching
    if not toc_dict:
        text = soup.get_text(separator="\n", strip=True)
        # Look for patterns like "ITEM 1. BUSINESS" or "ITEM 1A. RISK FACTORS"
        # Only match valid item numbers (1-15 with optional A/B/C suffix)
        matches = re.findall(
            r"ITEM\s+(1[0-5]?|[2-9])(A|B|C)?[\.\s]+([A-Z][A-Z\s,\-\']+?)(?:\n|$)",
            text,
            re.IGNORECASE,
        )
        for num, suffix, title in matches:
            item_num = f"{num}{suffix or ''}".upper()
            if item_num not in toc_dict:
                toc_dict[item_num] = title.strip()

    # Method 4: SGML-specific TOC extraction - try when no results or sparse results
    if _is_sgml_content(html_content) and len(toc_dict) < 4:
        sgml_toc = _extract_toc_sgml(html_content)
        if sgml_toc and len(sgml_toc) > len(toc_dict):
            toc_dict = sgml_toc
        elif sgml_toc:
            for k, v in sgml_toc.items():
                if k not in toc_dict:
                    toc_dict[k] = v

    return toc_dict


def _extract_toc_from_table(soup: "BeautifulSoup") -> dict:
    """
    Extract TOC from table-based layout (common in older SEC filings).

    Looks for tables containing PART I/II and Item patterns with page numbers.
    """
    toc_dict: dict = {}
    current_part = "I"  # Default to Part I

    # Find tables that contain TOC markers
    for table in soup.find_all("table"):
        table_text = table.get_text()
        if "PART I" not in table_text.upper() and "Item" not in table_text:
            continue

        # Process each row
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            cell_texts = [c.get_text(strip=True) for c in cells]
            # Filter out empty cells and deduplicate
            cell_texts = list(dict.fromkeys([t for t in cell_texts if t]))

            if not cell_texts:
                continue

            # Only process "clean" rows - those with 2-3 short cells
            # Rows with many cells are complex nested structures
            short_cells = [t for t in cell_texts if len(t) <= 100]
            if len(cell_texts) > 5:
                # This is a complex row with many cells - only use the last few clean ones
                # The pattern in these tables is that the last 2-3 cells are the "clean" values
                short_cells = [t for t in cell_texts if len(t) <= 100][-5:]
                cell_texts = short_cells

            # Check for PART pattern in this clean set
            for text in cell_texts:
                # Skip cells that are too long to be just "PART X:"
                if len(text) > 20:
                    continue
                part_match = re.match(
                    r"PART\s+(I{1,2}|[12])\s*:?$",
                    text.replace("\xa0", " "),
                    re.IGNORECASE,
                )
                if part_match:
                    part_num = part_match.group(1)
                    # Normalize to Roman numerals
                    if part_num == "1":
                        part_num = "I"
                    elif part_num == "2":
                        part_num = "II"
                    # Only update current_part if this looks like a primary row
                    # (not a row that just happens to have PART II in nested cells)
                    has_title_cell = any(
                        len(t) < 50 and not t.isdigit() and t != text
                        for t in cell_texts
                    )
                    if has_title_cell and len(short_cells) <= 5:
                        current_part = part_num
                        # Find the part title in remaining cells
                        for other_text in cell_texts:
                            if (
                                other_text != text
                                and not other_text.isdigit()
                                and len(other_text) < 50
                            ):
                                clean_title = other_text.replace("\n", " ").strip()
                                clean_title = re.sub(r"\s+", " ", clean_title)
                                if clean_title and len(clean_title) > 3:
                                    toc_dict[f"PART_{part_num}"] = clean_title
                                    break
                    break

            # Look for clean rows with [Item X:, Title, Page] pattern
            # These appear as short rows at the end of complex nested cells
            if len(cell_texts) >= 2 and len(cell_texts) <= 5:
                # Check for Item pattern
                for i, text in enumerate(cell_texts):
                    # Skip cells that are too long
                    if len(text) > 15:
                        continue
                    # Match "Item X:" pattern (with non-breaking space)
                    item_match = re.match(
                        r"Item\s*(\d+[A-Za-z]?)\s*:?$",
                        text.replace("\xa0", " "),
                        re.IGNORECASE,
                    )
                    if item_match and i + 1 < len(cell_texts):
                        item_num = item_match.group(1).upper()
                        # Next cell should be the title (not a page number)
                        title = (
                            cell_texts[i + 1]
                            .replace("\n", " ")
                            .replace("\t", " ")
                            .strip()
                        )
                        # Clean up multi-line titles
                        title = re.sub(r"\s+", " ", title)
                        # Skip if it looks like page number or garbage
                        if title and not title.isdigit() and len(title) > 3:
                            # Truncate at page number if embedded
                            if re.search(r"\d{2}$", title):
                                title = re.sub(r"\d+$", "", title).strip()
                            # Use part prefix for Part II items to disambiguate
                            key = f"II_{item_num}" if current_part == "II" else item_num
                            if key not in toc_dict:
                                toc_dict[key] = title
                        break

    return toc_dict


def _find_notes_in_section(html_content: str) -> list:
    """
    Find notes within the Notes to Financial Statements section.

    Uses the TOC to identify note letters and titles, then finds where
    each note's content actually starts.
    Returns list of tuples: (content_start_pos, note_id, title, content_end_pos)
    """
    matches = []

    # Find the Notes to Financial Statements section
    notes_match = re.search(
        r"Notes?\s+to\s+(?:Consolidated\s+)?Financial\s+Statements?",
        html_content,
        re.IGNORECASE,
    )
    if not notes_match:
        return matches

    notes_start = notes_match.start()

    # First, find note entries in the TOC (wide cells with letter + title)
    # TOC pattern: cell with letter, cell with title, cell with page number
    toc_pattern = re.compile(
        r"<td[^>]*>\s*<p[^>]*>\s*(?:<font[^>]*>)?\s*([A-Z])\s*(?:</font>)?\s*</p>\s*</td>\s*"
        r'<td[^>]*width="8[0-9]%"[^>]*>.*?<font[^>]*>([^<]{5,80})</font>',
        re.IGNORECASE | re.DOTALL,
    )

    # Build list of (letter, title) from TOC
    toc_notes = []
    seen_letters = set()
    for m in toc_pattern.finditer(html_content[notes_start : notes_start + 50000]):
        letter = m.group(1).upper()
        title = m.group(2).strip()
        title = re.sub(r"\s+", " ", title)
        title = _clean_html_entities(title)
        if letter not in seen_letters and len(title) >= 5:
            seen_letters.add(letter)
            toc_notes.append((letter, title))

    if not toc_notes:
        return matches

    # Now find where each note's content actually starts
    # Look for bold headers like "A. Significant Accounting Policies"
    for letter, title in toc_notes:
        # Search for the actual note header in content (after TOC)
        # Pattern: bold letter followed by period and title
        content_pattern = re.compile(
            rf"<b[^>]*>\s*(?:<font[^>]*>)?\s*{letter}\.\s+[^<]*(?:</font>)?\s*</b>",
            re.IGNORECASE,
        )
        # Search after position 100000 (skip TOC area)
        search_start = notes_start + 100000
        m = content_pattern.search(html_content[search_start:])
        if m:
            content_start = search_start + m.end()
            matches.append((content_start, letter, title, None))  # end_pos filled later

    # Fill in end positions (each note ends where next begins)
    for i, match in enumerate(matches):
        next_start = matches[i + 1][0] if i + 1 < len(matches) else None
        matches[i] = (match[0], match[1], match[2], next_start)

    return matches


def extract_text_blocks(html_content: str) -> dict[str, dict]:
    """
    Extract text blocks (notes/disclosures) from a non-XBRL filing.

    These are the Notes to Financial Statements - the footnotes that
    explain the numbers in the financial statements.

    Returns a dict mapping note identifiers to their text content,
    with structure matching XBRL text_blocks: {key: {"name": ..., "text": ...}}
    """
    from bs4 import BeautifulSoup

    text_blocks: dict = {}

    # Route SGML content to specialized parser
    if _is_sgml_content(html_content):
        return _extract_text_blocks_sgml(html_content)

    # Strategy 1: Find "Note X. Title" pattern (common in many filings)
    note_pattern = re.compile(
        r"<[Bb]>Note\s*(\d+)[.\s](?:&nbsp;)?([^<]+)</[Bb]>", re.IGNORECASE
    )

    matches = list(note_pattern.finditer(html_content))

    # Strategy 2: Find Notes section and extract note headers from wide cells
    if not matches:
        matches = _find_notes_in_section(html_content)

    if not matches:
        return text_blocks

    # Extract each note section
    for i, match in enumerate(matches):
        # Handle both regex match objects and tuples
        if hasattr(match, "group"):
            note_id = match.group(1)
            title = match.group(2).strip()
            title = title.replace("&nbsp;", " ").replace("&#151;", "—")
            title = re.sub(r"&\w+;", "", title)
            start_pos: int = match.end()
            next_start = matches[i + 1].start() if i + 1 < len(matches) else None
        else:
            # Tuple: (content_start_pos, note_id, title, content_end_pos)
            _start_pos, note_id, title, next_start = match
            start_pos = int(_start_pos)  # Ensure int type

        # Get HTML from end of this match to start of next note
        if next_start:
            end_pos = next_start
        else:
            # Last note - find end at Review Report, Item 2, or PART II
            # Various patterns for Item 2 header
            end_patterns = [
                r"<[Bb]>Review Report",
                r"<[Bb]>Item\s*(?:&nbsp;)?2[:\s.]",
                r"<[Bb]>PART\s+II",
            ]
            earliest_end = len(html_content)
            for pattern in end_patterns:
                end_match = re.search(pattern, html_content[start_pos:], re.IGNORECASE)
                if end_match:
                    pos = start_pos + end_match.start()
                    earliest_end = min(earliest_end, pos)
            end_pos = earliest_end

        # Extract the HTML section
        section_html = html_content[start_pos:end_pos]

        # Parse this section - process elements in order
        soup = BeautifulSoup(section_html, "html.parser")

        # Process content in document order
        content_parts: list[str] = []
        tables_data: list[dict] = []
        processed_tables: set[int] = set()
        processed_texts: set[str] = set()

        # Process elements in document order
        for elem in soup.find_all(["p", "table"]):
            if elem.name == "table":
                if elem.find_parent("table"):
                    continue
                # Process table
                table_id = id(elem)
                if (
                    table_id in processed_tables
                ):  # pragma: no cover  # reason: find_all yields each table once per pass, so a duplicate id is never seen
                    continue
                processed_tables.add(table_id)

                # Check for bullet list first
                if _is_bullet_table(elem):
                    result = _extract_bullet_list(elem)
                else:
                    # Parse table using financial statement logic
                    headers, data_rows = _parse_html_table_for_notes(elem)
                    if data_rows:
                        tables_data.append({"headers": headers, "data": data_rows})
                        result = _table_to_markdown_notes(headers, data_rows)
                    else:
                        result = None

                # Add content avoiding duplicates
                if result:
                    text_key = result[:200] if len(result) > 200 else result
                    if text_key not in processed_texts:
                        content_parts.append(result)
                        processed_texts.add(text_key)

            elif elem.name == "p":
                if elem.find_parent("table"):
                    continue
                # Get direct text only (handles nested P in malformed HTML)
                text = _get_direct_text(elem)
                text = _clean_paragraph_text(text)
                # Add content avoiding duplicates
                if text:
                    text_key = text[:200] if len(text) > 200 else text
                    if text_key not in processed_texts:
                        content_parts.append(text)
                        processed_texts.add(text_key)

        # Join with proper spacing
        full_text = "\n\n".join(content_parts)

        key = f"note_{note_id}"
        text_blocks[key] = {
            "name": title,
            "disclosure": [key],
            "text": full_text,
        }
        if tables_data:
            text_blocks[key]["tables"] = tables_data

    return text_blocks


def _is_sgml_content(content: str) -> bool:
    """Detect whether content is SGML-formatted (pre-2000 SEC filings).

    SGML filings use <PAGE> markers and <TABLE>/<S>/<C> tags for tables,
    with plain text for everything else (no <html>, <body>, <p>, <div>).
    """
    has_sgml_markers = bool(re.search(r"<PAGE>", content))
    has_sgml_tables = bool(re.search(r"<S>\s+<C>", content))
    lacks_html = not bool(
        re.search(r"<(?:html|body|div|span)\b", content, re.IGNORECASE)
    )
    return (has_sgml_markers or has_sgml_tables) and lacks_html


def _sgml_to_text(content: str) -> str:
    """Convert SGML content to clean plain text, preserving structure."""
    # Normalize page breaks
    text = re.sub(r"<PAGE>\s*", "\n\n", content)
    # Convert SGML tables to readable text
    text = _convert_sgml_tables(text)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    text = _clean_html_entities(text)
    # Collapse excessive blank lines
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text


def _convert_sgml_tables(content: str) -> str:
    """Convert SGML <TABLE>/<S>/<C>...</TABLE> blocks to Markdown tables.

    Uses the <S>/<C> column-position information to split each
    data line into label and value columns, then renders a Markdown table.
    """

    def _format_table(match: re.Match) -> str:  # noqa: PLR0912
        block = match.group(1)  # content between <TABLE> and </TABLE>
        raw_lines = block.split("\n")

        # Find the <S>...<C>... format line and extract column positions
        col_positions: list[int] = []
        format_idx: int | None = None
        for i, raw_line in enumerate(raw_lines):
            if "<S>" in raw_line and "<C>" in raw_line:
                format_idx = i
                for cm in re.finditer(r"<C>", raw_line):
                    col_positions.append(cm.start())
                break

        label_end = col_positions[0] if col_positions else None
        num_val_cols = len(col_positions) or 1

        # Header area (caption, title, etc.) -- rendered as plain text above
        header_end = format_idx if format_idx is not None else 0
        header_lines: list[str] = []
        for hl in raw_lines[:header_end]:
            cleaned = re.sub(r"<[^>]+>", "", hl).strip()
            if cleaned:
                header_lines.append(cleaned)

        # Data lines (after the format line)
        data_start = (format_idx + 1) if format_idx is not None else 0

        val_re = re.compile(
            r"(\(\s*\$?\s*(?:\d[\d,]*(?:\.\d+)?|\.\d+)\s*\)"
            r"|\$\s*\d[\d,]*(?:\.\d+)?"
            r"|\$\s*\.\d+"
            r"|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b"
            r"|--+)"
        )

        # Collect rows as (label, [val_strings])
        rows: list[tuple[str, list[str]]] = []
        for raw_line in raw_lines[data_start:]:
            line = re.sub(r"<[^>]+>", "", raw_line)
            stripped = line.strip()
            if not stripped or re.match(r"^[-=_\s$]+$", stripped):
                continue

            if label_end is not None:
                # Drop dot leaders ("Power Macintosh......  $11") from labels.
                label = re.sub(r"\.{2,}", "", line[:label_end]).strip()
                value_zone = line[label_end:]
            else:
                label = stripped
                value_zone = stripped

            vals = [m.group(0).strip() for m in val_re.finditer(value_zone)]
            # Section headers (ending with ":") with no values get a row
            if label or vals:
                rows.append((label, vals))

        if not rows:
            # No parseable data -- fall back to plain header text
            return "\n" + "\n".join(header_lines) + "\n" if header_lines else ""

        # Build column headers from header_lines if they contain period info
        col_headers: list[str] = []
        for hl in header_lines:
            # Check if line has period-like info (dates, years)
            if re.search(
                r"(?:January|February|March|April|May|June|July|August|"
                r"September|October|November|December|\b\d{4}\b)",
                hl,
                re.IGNORECASE,
            ):
                # Split by large whitespace gaps to get column headers
                parts = re.split(r"\s{3,}", hl.strip())
                if len(parts) >= num_val_cols:
                    col_headers = [p.strip() for p in parts[-num_val_cols:]]
                    break

        if not col_headers:
            col_headers = [f"Col {i + 1}" for i in range(num_val_cols)]

        # Non-period header lines rendered as plain text before the table
        pre_lines: list[str] = []
        for hl in header_lines:
            # Skip rule lines (rows of dashes/underscores used as underlines).
            if re.fullmatch(r"[-=_.\s]+", hl):
                continue
            if not any(ch == hl.strip() or ch in hl for ch in col_headers):
                pre_lines.append(hl)

        # Build Markdown table
        md_lines: list[str] = []

        # Header row
        md_lines.append("| |" + "|".join(f" {h} " for h in col_headers) + "|")
        # Separator row (left-align label, right-align values)
        md_lines.append("|:---|" + "|".join("---:" for _ in col_headers) + "|")

        for label, vals in rows:
            # Pad or trim vals to match column count
            padded = list(vals)
            while len(padded) < num_val_cols:
                padded.insert(0, "")
            padded = padded[-num_val_cols:]

            # Section headers (ending with ":") -- bold
            display_label = f"**{label}**" if label.endswith(":") else label

            md_lines.append(
                f"| {display_label} |" + "|".join(f" {v} " for v in padded) + "|"
            )

        result_parts = pre_lines + ([""] if pre_lines else []) + md_lines
        return "\n\n" + "\n".join(result_parts) + "\n\n"

    return re.sub(r"<TABLE>(.*?)</TABLE>", _format_table, content, flags=re.DOTALL)


def _extract_items_sgml(content: str) -> dict[str, dict]:
    """Extract filing items from SGML/plain-text formatted content.

    Old SEC filings have plain-text ITEM headers like:
        ITEM 1.  FINANCIAL STATEMENTS
        ITEM 2.  MANAGEMENT'S DISCUSSION AND ANALYSIS
    and PART markers like:
        PART I
        PART II
    """
    text = _sgml_to_text(content)
    items: dict = {}

    # Find PART boundaries (positions in text)
    part_positions: list[tuple[int, str]] = []
    for m in re.finditer(
        r"^[ \t]*PART\s+(I{1,3}|[1-3])\s*[-.\s]*\n",
        text,
        re.MULTILINE | re.IGNORECASE,
    ):
        part_val = m.group(1).upper()
        if part_val in ("1",):
            part_val = "I"
        elif part_val in ("2",):
            part_val = "II"
        elif part_val in ("3",):
            part_val = "III"
        part_positions.append((m.start(), part_val))

    # Find ITEM headers -- require they appear on their own line
    # Match: "ITEM 1.  FINANCIAL STATEMENTS" or "Item 2: MD&A"
    item_pattern = re.compile(
        r"^[ \t]*ITEM\s+(\d+[A-Za-z]?)\s*[.:\s]\s*(.+?)[ \t]*$",
        re.IGNORECASE | re.MULTILINE,
    )

    raw_matches = list(item_pattern.finditer(text))
    if not raw_matches:
        return items

    # Distinguish TOC entries from actual section headers.
    # TOC entries typically end with a page number and cluster together.
    # Actual headers are spaced apart and followed by content.
    toc_end = 0
    if len(raw_matches) >= 4:
        # Check if the first batch of matches are closely packed (TOC)
        gaps = [
            raw_matches[i + 1].start() - raw_matches[i].end()
            for i in range(min(len(raw_matches) - 1, 6))
        ]
        avg_gap = sum(gaps) / len(gaps) if gaps else 0
        if avg_gap < 300:
            # These are TOC entries -- find where the TOC ends
            for i, gap in enumerate(gaps):
                if gap > 500:
                    toc_end = raw_matches[i].end()
                    break
            else:
                # All closely packed -- the whole first group is TOC
                # Use the midpoint of the document as a heuristic
                toc_end = raw_matches[len(gaps)].end()

    # Filter to actual section headers (after TOC)
    matches = []
    for m in raw_matches:
        if m.start() < toc_end:
            continue
        item_num = m.group(1).upper()
        title = m.group(2).strip()
        # Skip lines that end with just a page number (TOC remnants)
        if re.match(r"^.{0,50}\d{1,3}\s*$", title):
            continue
        # Skip cross-references in running text ("...Item 7 of Form 10-K under
        # ..."): a real section title starts with a capitalized word, never a
        # lowercase continuation word.
        if title[:1].islower():
            continue
        # Clean trailing dots/spaces from title
        title = re.sub(r"[.\s]+$", "", title)
        if not title:
            continue
        matches.append((m.start(), item_num, title))

    if not matches:
        return items

    # Determine PART for each item based on part_positions
    def _get_part(pos: int) -> str:
        current = "I"
        for p_pos, p_val in part_positions:
            if p_pos <= pos:
                current = p_val
            else:
                break
        return current

    # Also track seen items for fallback part detection
    seen_items: set[str] = set()

    for i, (pos, item_num, item_title) in enumerate(matches):
        title = item_title
        part = _get_part(pos)
        # Fallback: if we see the same item number again, it's Part II
        if item_num in seen_items and part == "I":
            part = "II"
        seen_items.add(item_num)

        # Extract text between this item and the next
        end_pos = matches[i + 1][0] if i + 1 < len(matches) else len(text)
        section_text = text[pos:end_pos]

        # Remove the header line itself
        header_end = section_text.find("\n")
        if header_end > 0:
            section_text = section_text[header_end + 1 :]
            # A long item title wraps onto the next line ("...AND RESULTS\nOF
            # OPERATIONS"). When the line right after the header (no blank
            # between) is a short all-caps continuation, fold it into the title
            # so it does not leak to the top of the body.
            cont = re.match(
                r"[ \t]*([A-Z][A-Z &/'.\-]{2,40})[ \t]*\n\s*\n", section_text
            )
            if cont:
                title = f"{title} {cont.group(1).strip()}".strip()
                section_text = section_text[cont.end() :]

        # Clean up
        section_text = re.sub(r"\n{3,}", "\n\n", section_text).strip()

        key = f"item_II_{item_num}" if part == "II" else f"item_{item_num}"
        items[key] = {
            "name": title or _get_item_default_name(item_num, part),
            "part": part,
            "item_num": item_num,
            "text": section_text,
        }

    return items


def _extract_toc_sgml(content: str) -> dict[str, str]:
    """Extract table of contents from SGML-formatted content.

    Handles plain-text TOCs where ITEM entries are closely packed lines
    with page numbers, like:
        ITEM 1.  FINANCIAL STATEMENTS                        1
        ITEM 2.  MANAGEMENT'S DISCUSSION AND ANALYSIS       10
    """
    text = _sgml_to_text(content)
    toc_dict: dict = {}
    current_part = "I"

    # Find PART markers
    for m in re.finditer(
        r"^[ \t]*PART\s+(I{1,3}|[1-3])\s*$",
        text,
        re.MULTILINE | re.IGNORECASE,
    ):
        part_val = m.group(1).upper()
        if part_val == "2":
            part_val = "II"
        elif part_val == "1":
            part_val = "I"

    # Find ITEM entries that look like TOC lines (have trailing page numbers)
    toc_pattern = re.compile(
        r"^[ \t]*ITEM\s+(\d+[A-Za-z]?)\s*[.:\s]\s*(.+?)\s+(\d{1,3})\s*$",
        re.IGNORECASE | re.MULTILINE,
    )

    for m in toc_pattern.finditer(text):
        item_num = m.group(1).upper()
        title = m.group(2).strip()
        title = re.sub(r"[.\s]+$", "", title)
        if title and len(title) > 3:
            # Check for preceding PART marker
            preceding = text[max(0, m.start() - 200) : m.start()]
            part_match = re.search(r"PART\s+(I{1,3}|[1-3])", preceding, re.IGNORECASE)
            if part_match:
                p = part_match.group(1).upper()
                if p in ("2", "II"):
                    current_part = "II"
                elif p in ("1", "I"):
                    current_part = "I"

            key = f"II_{item_num}" if current_part == "II" else item_num
            if key not in toc_dict:
                toc_dict[key] = title

    return toc_dict


def _find_best_sgml_table(content: str, statement_type: str) -> list[tuple[str, int]]:
    """Find SGML TABLE blocks that match the requested statement type.

    Returns a list of (block_text, start_position) tuples in document
    order. All tables scoring above 50% of the best match are included
    so that multi-part statements (e.g. balance sheet split into Assets
    and Liabilities tables) are captured.

    Parameters
    ----------
    content : str
        The raw SGML content of the filing document.
    statement_type : str
        Type of statement to extract: 'income', 'balance', 'cash', 'equity'

    Returns
    -------
    list[tuple[str, int]]
        List of (block_text, start_position) tuples. start_position is the
        index into content where <TABLE> begins, so callers can inspect
        preceding text for title / multiplier info.
    """
    keywords = _get_statement_keywords(statement_type)
    negative_keywords = _get_negative_keywords(statement_type)

    candidates: list[tuple[str, int, int]] = []  # (block, pos, score)

    for m in re.finditer(r"<TABLE>(.*?)</TABLE>", content, re.DOTALL | re.IGNORECASE):
        block = m.group(1)
        text = re.sub(r"<[^>]+>", " ", block).lower()
        text = re.sub(r"\s+", " ", text)

        preamble_start = max(0, m.start() - 600)
        preamble = re.sub(r"<[^>]+>", " ", content[preamble_start : m.start()]).lower()
        combined = preamble + " " + text

        if any(nk in combined for nk in negative_keywords):
            continue

        score = sum(1 for kw in keywords if kw.lower() in combined)
        if score <= 0:
            continue

        numbers = re.findall(r"\d{1,3}(?:,\d{3})+", text)
        if len(numbers) < 5:
            continue

        total_score = score + len(numbers) // 10
        candidates.append((block, m.start(), total_score))

    if not candidates:
        return []

    best_score = max(c[2] for c in candidates)
    threshold = best_score * 0.5
    results = [(blk, pos) for blk, pos, sc in candidates if sc >= threshold]
    results.sort(key=lambda x: x[1])
    return results


def _extract_table_subtitle(preamble: str, header_text: str) -> str | None:
    """Extract a balance-sheet section subtitle from a table preamble/header.

    Looks for standalone lines like ASSETS or
    LIABILITIES AND SHAREHOLDERS' EQUITY that identify which part
    of a multi-table statement this block covers.

    Parameters
    ----------
    preamble : str
        Plain text preceding the <TABLE> tag.
    header_text : str
        Plain text from the table header area (before the <S>/<C> line).

    Returns
    -------
    str or None
        Title-cased subtitle, e.g. "Assets", or None if not found.
    """
    combined = preamble + "\n" + header_text
    m = re.search(
        r"^\s*"
        r"(LIABILITIES\s+AND\s+(?:SHAREHOLDERS?|STOCKHOLDERS?)[''\u2019]?S?\s+EQUITY"
        r"|(?:CURRENT\s+)?LIABILITIES"
        r"|(?:CURRENT\s+)?ASSETS"
        r"|(?:SHAREHOLDERS?|STOCKHOLDERS?)[''\u2019]?S?\s+EQUITY)"
        r"\s*$",
        combined,
        re.IGNORECASE | re.MULTILINE,
    )
    if m:
        raw = re.sub(r"\s+", " ", m.group(1).strip())
        # Title-case but keep small words lowercase
        return raw.title().replace(" And ", " and ").replace("'S", "'s")
    return None


def _extract_block_line_items(  # noqa: PLR0912
    block_text: str,
    num_cols: int,
    fallback_total_label: str | None = None,
) -> tuple[list[dict], int | None, int | None]:
    """Parse line items from a single SGML <TABLE> block.

    Parameters
    ----------
    block_text : str
        Content between <TABLE> and </TABLE> tags.
    num_cols : int
        Expected number of value columns (from the primary table's <C> count).
        Overridden if this block has its own <S>/<C> format line.
    fallback_total_label : str or None
        Label for value lines with an empty label zone (grand totals).
        Typically the table subtitle, e.g. "Assets".

    Returns
    -------
    tuple[list[dict], int or None, int or None]
        (line_items, label_end_pos, format_line_idx) where each
        line_item is a dict with label, section, values, skip_multiplier.
    """
    raw_lines = block_text.split("\n")
    col_positions: list[int] = []
    format_line_idx: int | None = None

    for i, raw_line in enumerate(raw_lines):
        if "<S>" in raw_line and "<C>" in raw_line:
            format_line_idx = i
            for m in re.finditer(r"<C>", raw_line):
                col_positions.append(m.start())
            break

    block_num_cols = len(col_positions) or num_cols
    label_end_pos = col_positions[0] if col_positions else None

    data_start = (
        (format_line_idx + 1)
        if format_line_idx is not None
        else min(10, len(raw_lines))
    )
    data_lines = raw_lines[data_start:]

    value_re = re.compile(
        r"(\(\s*\$?\s*(?:\d[\d,]*(?:\.\d+)?|\.\d+)\s*\)"
        r"|\$\s*\d[\d,]*(?:\.\d+)?"
        r"|\$\s*\.\d+"
        # Plain numbers, with or without comma groups ("314", "6,134", "4.20").
        # The word boundary excludes bare four-digit years.
        r"|\b\d{1,3}(?:,\d{3})*(?:\.\d+)?\b"
        r"|--+)"
    )

    line_items: list[dict] = []
    section: str | None = None
    label_buffer: list[str] = []

    for raw_line in data_lines:
        line = re.sub(r"<[^>]+>", "", raw_line)
        stripped = line.strip()

        if not stripped:
            if label_buffer:
                combined = " ".join(label_buffer)
                if combined.rstrip().endswith(
                    ":"
                ):  # pragma: no cover  # reason: colon-terminated lines go to the section branch, never the buffer, so combined never ends with ":"
                    section = combined.rstrip(":").strip()
                label_buffer = []
            continue

        if re.match(r"^[-=_\s$]+$", stripped):
            label_buffer = []
            continue

        lower = stripped.lower()
        if "see accompanying" in lower or "see notes" in lower:
            continue

        if label_end_pos is not None:
            label_zone = line[:label_end_pos].strip()
            value_zone = line[label_end_pos:]
        else:
            label_zone = stripped
            value_zone = stripped

        val_matches = list(value_re.finditer(value_zone))
        val_matches = [
            m
            for m in val_matches
            if not re.match(r"^(19|20)\d{2}$", m.group(0).strip())
        ]

        has_real_values = bool(val_matches) and any(
            _parse_sgml_value(m.group(0)) is not None for m in val_matches
        )
        has_dashes = bool(val_matches) and all(
            re.match(r"^--+$", m.group(0).strip()) for m in val_matches
        )

        if has_real_values or has_dashes:
            if label_buffer:
                parts = label_buffer + ([label_zone] if label_zone else [])
                full_label = " ".join(parts)
                label_buffer = []
            else:
                full_label = label_zone

            # Drop dot leaders ("Cash and cash equivalents......  $11").
            full_label = re.sub(r"\.{2,}", "", full_label)
            full_label = re.sub(r"\s+", " ", full_label).strip()
            if not full_label:
                # Empty label zone → grand total for the table, not a
                # section subtotal.  Use the table subtitle if available.
                if fallback_total_label:
                    full_label = f"Total {fallback_total_label}"
                elif section:
                    full_label = f"Total {section}"
                else:
                    full_label = "Total"

            values: list[float | None] = []
            for m in val_matches:
                values.append(_parse_sgml_value(m.group(0)))

            if len(values) > block_num_cols:
                values = values[-block_num_cols:]
            while len(values) < block_num_cols:
                values.insert(0, None)
            values = values[:block_num_cols]

            label_lower = full_label.lower()
            # Only per-share dollar amounts skip the multiplier.
            # Share counts ("shares used", "shares outstanding") are
            # also reported in thousands and SHOULD be scaled.
            # Key distinction: if "shares" (plural) appears BEFORE
            # "per" it's a count ("shares used in ... per share");
            # if "per" comes first it's a rate ("earnings per share").
            _shares_pos = label_lower.find("shares")
            _per_pos = label_lower.find("per")
            is_share_count = _shares_pos >= 0 and (
                _per_pos < 0 or _shares_pos < _per_pos
            )
            skip_mult = not is_share_count and (
                bool(re.search(r"\bper\b.*\bshare\b", label_lower))
                or "eps" in label_lower
            )

            line_items.append(
                {
                    "label": full_label,
                    "section": section,
                    "values": values,
                    "skip_multiplier": skip_mult,
                }
            )
        elif label_zone and label_zone.rstrip().endswith(":"):
            combined = " ".join(label_buffer + [label_zone])
            section = combined.rstrip(":").strip()
            label_buffer = []
        elif label_zone:
            label_buffer.append(label_zone)

    return line_items, label_end_pos, format_line_idx


def _parse_sgml_statement(
    content: str, statement_type: str
) -> tuple["DataFrame", "DataFrame"]:
    """Parse financial statement from SGML <TABLE>/<S>/<C> formatted content.

    SGML filings (pre-2000) use <TABLE>/<S>/<C> tags for column layout.
    Handles multi-part statements (e.g. balance sheet split across two
    <TABLE> blocks for Assets and Liabilities) by parsing every matching
    table and combining the results.

    Parameters
    ----------
    content : str
        The raw SGML content of the filing document.
    statement_type : str
        Type of statement to extract: 'income', 'balance', 'cash', 'equity'

    Returns
    -------
    tuple[pd.DataFrame, pd.DataFrame]
        A tuple of (statement_df, meta_df).
    """
    from pandas import DataFrame

    tables = _find_best_sgml_table(content, statement_type)

    if not tables:
        return DataFrame(), DataFrame()

    keywords = _get_statement_keywords(statement_type)

    # Use the first table for title, multiplier, and period detection
    first_block, first_start = tables[0]
    preamble_start = max(0, first_start - 600)
    preamble = re.sub(r"<[^>]+>", "", content[preamble_start:first_start])

    # Detect column count from the first table's format line
    raw_lines_first = first_block.split("\n")
    num_cols = 2
    for raw_line in raw_lines_first:
        if "<S>" in raw_line and "<C>" in raw_line:
            num_cols = len(list(re.finditer(r"<C>", raw_line))) or 2
            break

    # Header area (before <S> line) for multiplier / periods / title
    header_end = 10
    for i, raw_line in enumerate(raw_lines_first):
        if "<S>" in raw_line and "<C>" in raw_line:
            header_end = i
            break
    header_text = re.sub(r"<[^>]+>", "", "\n".join(raw_lines_first[:header_end]))
    header_lines = header_text.split("\n")

    full_header = (preamble + "\n" + header_text).lower()
    if "in millions" in full_header or "(millions)" in full_header:
        multiplier = 1_000_000
    elif "in thousands" in full_header or "(thousands)" in full_header:
        multiplier = 1_000
    elif "in billions" in full_header:
        multiplier = 1_000_000_000
    else:
        multiplier = 1

    title = None
    for line in (preamble + "\n" + header_text).split("\n"):
        stripped = line.strip()
        if stripped and any(kw.lower() in stripped.lower() for kw in keywords):
            title = stripped
            break

    periods = _extract_sgml_periods(header_lines, num_cols)
    if not periods:
        # Try periods from subsequent tables (continuation tables may
        # repeat the period headers)
        for block_text, _ in tables[1:]:
            block_lines = block_text.split("\n")
            block_header_end = 10
            for i, raw_line in enumerate(block_lines):
                if "<S>" in raw_line and "<C>" in raw_line:
                    block_header_end = i
                    break
            block_header = re.sub(
                r"<[^>]+>", "", "\n".join(block_lines[:block_header_end])
            ).split("\n")
            periods = _extract_sgml_periods(block_header, num_cols)
            if periods:
                break
    if not periods:
        periods = [f"Period_{i + 1}" for i in range(num_cols)]

    # Parse line items from every matching table and combine
    all_line_items: list[dict] = []
    for block_text, block_start in tables:
        # Extract subtitle from this table's preamble + header
        blk_preamble_start = max(0, block_start - 600)
        blk_preamble = re.sub(r"<[^>]+>", "", content[blk_preamble_start:block_start])
        blk_lines = block_text.split("\n")
        blk_header_end = min(10, len(blk_lines))
        for i, rl in enumerate(blk_lines):
            if "<S>" in rl and "<C>" in rl:
                blk_header_end = i
                break
        blk_header = re.sub(r"<[^>]+>", "", "\n".join(blk_lines[:blk_header_end]))
        subtitle = _extract_table_subtitle(blk_preamble, blk_header)

        block_items, _, _ = _extract_block_line_items(
            block_text, num_cols, fallback_total_label=subtitle
        )
        all_line_items.extend(block_items)

    if not all_line_items:
        return DataFrame(), DataFrame()

    statement_df = _build_statement_dataframe(all_line_items, periods, multiplier)
    meta_df = _build_meta_dataframe(title, periods, multiplier)

    return statement_df, meta_df


def _get_negative_keywords(statement_type: str) -> list[str]:
    """Get keywords that should EXCLUDE a table from matching a statement type."""
    # Multi-year "Selected Financial Data" summaries and segment/unit tables mix
    # income, balance and per-share data; they must never be parsed as a real
    # statement (their uniform multiplier corrupts per-share and unit rows).
    common = [
        "selected financial data",
        "selected consolidated financial data",
        "unit sales",
        "unit shipment",
    ]
    negatives = {
        "income": [
            "cash flows",
            "cash flow",
            "balance sheet",
            "financial position",
            "financial condition",
            "stockholders equity",
            "shareholders equity",
        ],
        "balance": [
            "cash flows",
            "cash flow",
            "statements of operations",
            "statements of earnings",
            "statements of income",
        ],
        "cash": [
            "balance sheet",
            "financial position",
            "financial condition",
            "statements of operations",
            "statements of earnings",
            "statements of income",
            "stockholders equity",
        ],
        "equity": [
            "cash flows",
            "cash flow",
            "balance sheet",
            "statements of operations",
            "statements of earnings",
        ],
    }
    return negatives.get(statement_type, []) + common


def _extract_sgml_periods(lines: list[str], num_cols: int) -> list[str]:
    """Extract period labels from SGML table header lines.

    Handles multi-line dates (month/day on one line, years on the next),
    single-line full dates, and standalone years.

    Parameters
    ----------
    lines : list[str]
        Header lines from the SGML table (before the <S>/<C> format line).
    num_cols : int
        Expected number of period columns.

    Returns
    -------
    list[str]
        Period labels, e.g. ["December 31, 1993", "December 25, 1992"].
    """
    header_text = "\n".join(lines)

    # Strategy 1: Find month names and years on separate lines, then pair them
    month_re = re.compile(
        r"((?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s*\d{1,2})",
        re.IGNORECASE,
    )
    year_re = re.compile(r"\b((?:19|20)\d{2})\b")

    # Find the line(s) with month names
    date_fragments: list[str] = []
    year_fragments: list[str] = []
    date_line_idx = -1

    for i, line in enumerate(lines):
        months_on_line = month_re.findall(line)
        if months_on_line:
            date_fragments = months_on_line
            date_line_idx = i

    # If we found dates, look for years on the NEXT non-empty line
    if date_fragments and date_line_idx >= 0:
        for line in lines[date_line_idx + 1 : date_line_idx + 5]:
            stripped = line.strip()
            if not stripped:
                continue
            years = year_re.findall(stripped)
            if years:
                year_fragments = years
                break

        if year_fragments and len(date_fragments) == len(year_fragments):
            return [
                f"{d.strip().rstrip(',')}, {y}"
                for d, y in zip(date_fragments, year_fragments)
            ][:num_cols]
        elif year_fragments:
            # Mismatched count -- try pairing what we can
            periods = []
            for i, y in enumerate(year_fragments):
                if i < len(date_fragments):
                    periods.append(f"{date_fragments[i].strip().rstrip(',')}, {y}")
                else:
                    periods.append(y)
            return periods[:num_cols]

    # Strategy 2: Try full date on single line (Month Day, Year). The year may
    # follow the day with no space after the comma, e.g. "September 25,1999".
    date_full_re = re.compile(
        r"((?:January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s+\d{1,2},?\s*\d{4})",
        re.IGNORECASE,
    )
    dates = date_full_re.findall(header_text)
    if dates:
        cleaned = [re.sub(r",\s*", ", ", re.sub(r"\s+", " ", d.strip())) for d in dates]
        if len(cleaned) >= num_cols:
            return cleaned[:num_cols]
        # A single fiscal-year-end date with several year columns
        # ("Three fiscal years ended September 25, 1999   1999  1998  1997"):
        # pair the month/day with each column year.
        month_day = re.match(r"([A-Za-z]+\s+\d{1,2})", cleaned[0])
        years = year_re.findall(header_text)
        if month_day and len(years) >= num_cols:
            return [f"{month_day.group(1)}, {y}" for y in years[-num_cols:]]
        return cleaned[:num_cols]

    # Strategy 3: Standalone years on a single line
    for line in lines:
        stripped = line.strip()
        years = year_re.findall(stripped)
        if len(years) >= 2 and "$" not in stripped:
            return years[:num_cols]

    return []


def _parse_sgml_value(text: str) -> float | None:
    """Parse a numeric value from an SGML table cell."""
    text = text.strip()
    if not text or text in ("--", "---", "----", "-", "\u2014"):
        return None

    is_neg = "(" in text and ")" in text
    clean = re.sub(r"[\$\(\)\s]", "", text).replace(",", "")

    try:
        val = float(clean)
        return -val if is_neg else val
    except ValueError:
        return None


def _extract_text_blocks_sgml(content: str) -> dict[str, dict]:
    """Extract notes/text blocks from SGML-formatted filing content.

    SGML filings use numbered plain-text notes like:
        1. Interim information is unaudited...
        2. Effective September 25, 1993...
    """
    text = _sgml_to_text(content)
    text_blocks: dict = {}

    # Heading-based notes: "Note N - Title" (numbered with inline titles) or
    # name-titled headings ("Income Taxes"), scanned across the whole document.
    named = extract_plain_text_notes(text)

    # Find the "NOTES TO ... FINANCIAL STATEMENTS" section header. CONSOLIDATED,
    # CONDENSED, INTERIM and UNAUDITED may appear in any combination or order.
    notes_match = re.search(
        r"NOTES?\s+TO\s+(?:(?:CONSOLIDATED|CONDENSED|INTERIM|UNAUDITED)\s+)*"
        r"FINANCIAL\s+STATEMENTS?",
        text,
        re.IGNORECASE,
    )

    if not notes_match:
        return named

    notes_start = notes_match.end()

    # Find where notes end (typically at Item 2, Part II, or Signatures)
    end_patterns = [
        r"\bITEM\s+2\b",
        r"\bPART\s+II\b",
        r"\bSIGNATURES?\b",
        r"\bMANAGEMENT.S\s+DISCUSSION\b",
    ]
    notes_end = len(text)
    for pattern in end_patterns:
        m = re.search(pattern, text[notes_start:], re.IGNORECASE)
        if m:
            notes_end = min(notes_end, notes_start + m.start())

    notes_text = text[notes_start:notes_end]

    # Numbered notes ("1. Title", "2. Title") — typical of interim (10-Q) filings.
    # Restrict to one- or two-digit numbers so four-digit years ("1993.") are not
    # mistaken for note numbers.
    note_pattern = re.compile(r"^[ \t]*(\d{1,2})\.\s{1,4}(\S.+)", re.MULTILINE)
    matches = list(note_pattern.finditer(notes_text))

    # Prefer whichever split yields more notes; heading-based notes win ties
    # because they carry cleaner titles.
    if len(named) >= len(matches):
        return named

    for i, m in enumerate(matches):
        note_num = m.group(1)
        # Content is everything from this note to the next (or the section end).
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(notes_text)
        # Bare numbered notes have no titles, so name them "Note N" and drop the
        # number prefix from the body (the heading is carried by ``name``).
        body = re.sub(
            r"^[ \t]*\d{1,2}\.\s+", "", notes_text[start:end].strip(), count=1
        )

        key = f"note_{note_num}"
        text_blocks[key] = {
            "name": f"Note {note_num}",
            "disclosure": [key],
            "text": body,
        }

    return text_blocks


_TITLE_LOWERCASE_WORDS = frozenset(
    {"of", "and", "for", "to", "the", "in", "on", "a", "an", "or"}
)


def _extract_numbered_title_notes(text: str) -> dict[str, dict]:
    """Extract "Note N - Title" style notes (numbered with an inline title).

    Each note begins a line like ``Note 7 - Contingencies`` and runs until the
    next such heading, the MD&A, or the signature block. Common in interim
    (10-Q) filings whose notes are titled rather than a bare numbered list.
    """
    # The separator may be a doubled hyphen ("Note 9--Segment...") from an
    # em-dash, so consume the whole run.
    heads = list(
        re.finditer(r"(?im)^[ \t]*Note\s+(\d{1,2})\s*[-.:–—]+\s*(\S.*?)[ \t]*$", text)
    )
    if len(heads) < 2:
        return {}

    tail = re.search(
        r"(?im)^[ \t]*(?:ITEM\s+2\b|PART\s+II\b|SIGNATURES?\b|MANAGEMENT.S\s+DISCUSSION)",
        text[heads[-1].end() :],
    )
    end = heads[-1].end() + tail.start() if tail else len(text)

    # A note that spans pages repeats its "Note N--Title (Continued)" header on
    # each page. Keep only the first header per note number; the body then runs
    # to the next distinct note, spanning every continuation.
    firsts: list = []
    seen: set = set()
    for head in heads:
        if head.group(1) not in seen:
            seen.add(head.group(1))
            firsts.append(head)

    notes: dict = {}
    for index, head in enumerate(firsts):
        number = head.group(1)
        # Drop a trailing TOC page number and any "(continued)" marker.
        title = re.sub(r"\s{2,}\S.*$", "", head.group(2)).strip().rstrip(".")
        title = re.sub(r"\s*\(continued\)\s*$", "", title, flags=re.IGNORECASE).strip()
        stop = firsts[index + 1].start() if index + 1 < len(firsts) else end
        # Body only; strip repeated continuation page-headers inside it.
        body = text[head.end() : stop]
        body = re.sub(
            r"(?im)^[ \t]*(?:Note\s+\d+\s*[-.:–—]+|Notes?\s+to)[^\n]*"
            r"\(continued\)[^\n]*$\n?",
            "",
            body,
        )
        notes[f"note_{number}"] = {
            "name": title or f"Note {number}",
            "disclosure": [f"note_{number}"],
            "text": body.strip(),
        }
    return notes


def extract_plain_text_notes(text: str) -> dict[str, dict]:
    """Split a plain-text notes section into individually named notes.

    Old (pre-HTML) annual filings title each note with a short standalone
    heading line (e.g. "Income Taxes") followed by paragraph text, with no
    numbering or markup, so the numbered-note parser cannot find them.
    """
    # "Note N - Title" notes take priority when present.
    numbered_title = _extract_numbered_title_notes(text)
    if numbered_title:
        return numbered_title

    heads = list(
        re.finditer(
            r"(?im)^[ \t]*Notes?\s+to\s+.{0,45}Financial Statements\.?[ \t]*$", text
        )
    )
    if not heads:
        return {}

    section = text[heads[-1].end() :]
    end = re.search(
        r"(?im)^[ \t]*(SIGNATURES|SCHEDULE\s+[IVXivx]+|EXHIBIT\s+INDEX|INDEX TO EXHIBITS)\b",
        section,
    )
    if end:
        section = section[: end.start()]

    lines = [
        line.rstrip()
        for line in section.split("\n")
        if not re.fullmatch(r"\s*(<PAGE>|<[^>]+>|\d{1,4})\s*", line)
    ]

    def _is_heading(line: str, following: str) -> bool:
        """Return True for a short, title-cased line that heads a paragraph."""
        stripped = line.strip()
        if not (3 <= len(stripped) <= 48) or stripped[-1] in ".,:;-":
            return False
        if not stripped[0].isupper() or stripped.isupper():
            return False
        if re.search(r"\s{3,}", stripped) or any(c.isdigit() for c in stripped):
            return False
        cased = all(
            word[0].isupper() or word.lower() in _TITLE_LOWERCASE_WORDS
            for word in stripped.split()
        )
        return cased and len(following.strip()) > 55

    notes: dict = {}
    title: str | None = None
    body: list = []
    order = 0

    def _flush() -> None:
        nonlocal order, title, body
        if title and body:
            order += 1
            key = f"note_{order}"
            notes[key] = {
                "name": title,
                "disclosure": [key],
                "text": " ".join(body).strip(),
            }
        title, body = None, []

    for index, line in enumerate(lines):
        following = lines[index + 1] if index + 1 < len(lines) else ""
        if _is_heading(line, following):
            _flush()
            title = line.strip()
        elif title:
            body.append(line.strip())
    _flush()

    return notes


def extract_items(  # noqa: PLR0912
    html_content: str, filing_type: str | None = None
) -> dict[str, dict]:
    """
    Extract SEC filing items (MD&A, Risk Factors, etc.) from HTML content.

    Works for 10-K, 10-Q, and 8-K filings. Handles different company HTML formats.

    Args:
        html_content: HTML content of the filing
        filing_type: Optional filing type (10-K, 10-Q, 8-K) to help determine patterns

    Returns a dict mapping item identifiers to their content:
    {
        "item_1": {"name": "Financial Statements", "text": "...", "part": "I"},
        "item_2": {"name": "Management's Discussion and Analysis", "text": "...", "part": "I"},
        ...
    }

    For 8-K filings:
    {
        "item_1.01": {"name": "Entry into a Material Definitive Agreement", "text": "...", "section": "1"},
        "item_8.01": {"name": "Other Events", "text": "...", "section": "8"},
        ...
    }
    """
    from bs4 import BeautifulSoup

    items: dict = {}

    # Detect if this is an 8-K based on content or filing_type
    is_8k = filing_type and "8-K" in filing_type.upper()
    if not is_8k:
        # Check content for 8-K indicators (Item X.XX patterns)
        is_8k = bool(re.search(r"Item[\s\u2009]+\d+\.\d+", html_content, re.IGNORECASE))

    if is_8k:
        return _extract_8k_items(html_content)

    # Find all Item headers in the document
    # Pattern matches: <B>Item 2:</B>, <B>Item&nbsp;2:&nbsp;</B>, etc.
    # Use .+? to allow <BR> tags inside the title (some filings have <BR> before </B>)
    item_pattern_bold = re.compile(
        r"<[Bb]>Item\s*(?:&nbsp;)?(\d+[A-Za-z]?)\s*[:\s.]\s*(?:&nbsp;)?(.+?)</[Bb]>",
        re.IGNORECASE | re.DOTALL,
    )

    # Also match multi-cell format: <B>Item&nbsp;2:&nbsp;</B></TD><TD><B>Title</B>
    item_pattern_split = re.compile(
        r"<[Bb]>Item\s*(?:&nbsp;)?(\d+[A-Za-z]?)\s*[:\s.]\s*(?:&nbsp;)?</[Bb]>\s*</TD>\s*<TD[^>]*>\s*<[Bb]>([^<]+)</[Bb]>",
        re.IGNORECASE,
    )

    # Non-bold pattern: ITEM 7.&nbsp;&nbsp;&nbsp;&nbsp;TITLE (Microsoft style)
    # Some have title on same line, others have title after <A NAME=...> on next line
    item_pattern_nonbold = re.compile(
        r">ITEM\s*(\d+[A-Za-z]?)\s*[.\s](?:&nbsp;)*\s*(?:<[^>]*>)*\s*([A-Z][^<]{5,100}?)\s*</FONT>",
        re.IGNORECASE | re.DOTALL,
    )

    def clean_item_title(raw_title: str) -> str:
        """Clean up item title by removing BR tags, trailing colons, and extra whitespace."""
        title = re.sub(r"<[Bb][Rr]\s*/?>", " ", raw_title)  # Remove <BR> tags
        title = re.sub(r"<[^>]+>", "", title)  # Remove any HTML tags
        title = _clean_html_entities(title)
        title = re.sub(r":?\s*$", "", title)  # Remove trailing colon
        title = re.sub(r"\s+", " ", title).strip()  # Collapse whitespace
        return title

    # Find all matches
    matches = []

    # Try split pattern first (more specific)
    for m in item_pattern_split.finditer(html_content):
        item_num = m.group(1).upper()
        title = clean_item_title(m.group(2))
        matches.append((m.start(), item_num, title))

    # Then try bold pattern
    for m in item_pattern_bold.finditer(html_content):
        item_num = m.group(1).upper()
        title = clean_item_title(m.group(2))
        # Skip if we already got this position from split pattern
        if not any(abs(pos - m.start()) < 100 for pos, _, _ in matches):
            matches.append((m.start(), item_num, title))

    # Try non-bold pattern (Microsoft style)
    for m in item_pattern_nonbold.finditer(html_content):
        item_num = m.group(1).upper()
        title = clean_item_title(m.group(2))
        # Skip TOC entries (they're usually short or in TD cells)
        if len(title) < 10:
            continue
        # Skip if we already got this item number nearby
        if not any(
            abs(pos - m.start()) < 500 and num == item_num for pos, num, _ in matches
        ):
            matches.append((m.start(), item_num, title))

    # Sort by position
    matches.sort(key=lambda x: x[0])

    if not matches:
        # Fall back to SGML plain-text extraction for old filings
        if _is_sgml_content(html_content):
            return _extract_items_sgml(html_content)
        return items

    # Track which Part we're in (I or II) based on item sequence
    # Part I typically has Items 1-4, Part II has Items 1-6
    # Use position relative to other items to determine part
    seen_items = set()

    # Extract each item section
    for i, (pos, item_num, title) in enumerate(matches):
        # Determine part - if we see item 1 again after other items, we're in Part II
        if item_num == "1" and len(seen_items) > 0:
            part = "II"
        elif any(n in seen_items for n in ["1", "2", "3", "4"]) and item_num in [
            "1",
            "2",
            "3",
            "4",
            "5",
            "6",
        ]:
            # If we've seen items from Part I and now see them again
            part = "II" if item_num in seen_items else "I"
        else:
            part = "I"

        seen_items.add(item_num)

        # Get end position (start of next item or end of document)
        end_pos = matches[i + 1][0] if i + 1 < len(matches) else len(html_content)

        # Extract the HTML section
        section_html = html_content[pos:end_pos]

        # Parse this section
        soup = BeautifulSoup(section_html, "html.parser")

        # Process content in document order
        content_parts: list[tuple[str, str]] = []
        processed_texts: set[str] = set()

        # Process elements in document order
        for elem in soup.find_all(["p", "table"]):
            if elem.name == "table":
                # Skip nested tables (already processed by parent)
                if elem.find_parent("table"):
                    continue

                # Process table - check for bullet list first
                if _is_bullet_table(elem):
                    result = _extract_bullet_list(elem)
                elif not _is_financial_table(elem):
                    # Not a financial table - extract as simple text
                    text = elem.get_text(separator=" ", strip=True)
                    text = _clean_html_entities(text)
                    text = re.sub(r"\s+", " ", text).strip()
                    result = text if len(text) > 20 else None
                else:
                    # Parse as financial table
                    headers, data_rows = _parse_html_table_for_notes(elem)
                    result = (
                        _table_to_markdown_notes(headers, data_rows)
                        if data_rows
                        else None
                    )

                # Add content avoiding duplicates
                if result:
                    text_key = result[:200] if len(result) > 200 else result
                    if text_key not in processed_texts:
                        content_parts.append(("table", result))
                        processed_texts.add(text_key)

            elif elem.name == "p":
                # Skip if inside a table
                if elem.find_parent("table"):
                    continue

                # Check if this is a section header
                if _is_section_header(elem):
                    header_text = _get_direct_text(elem)
                    header_text = _clean_html_entities(header_text)
                    header_text = re.sub(r"\s+", " ", header_text).strip()
                    text_key = (
                        header_text[:200] if len(header_text) > 200 else header_text
                    )
                    if text_key not in processed_texts:
                        content_parts.append(("header", f"## {header_text}"))
                        processed_texts.add(text_key)
                    continue

                # Get only direct text (handles nested P tags in malformed HTML)
                text = _get_direct_text(elem)
                text = _clean_paragraph_text(text)
                # Add content avoiding duplicates
                if text:
                    text_key = text[:200] if len(text) > 200 else text
                    if text_key not in processed_texts:
                        content_parts.append(("text", text))
                        processed_texts.add(text_key)

        # Join with proper spacing
        full_text = "\n\n".join(item[1] for item in content_parts)

        # Create key
        key = f"item_II_{item_num}" if part == "II" else f"item_{item_num}"

        items[key] = {
            "name": title or _get_item_default_name(item_num, part),
            "part": part,
            "item_num": item_num,
            "text": full_text,
        }

    return items


def _clean_html_entities(text: str) -> str:
    """Clean HTML entities and normalize special characters."""
    # HTML entities
    text = text.replace("&nbsp;", " ")
    text = text.replace("&#146;", "'")
    text = text.replace("&#147;", '"')
    text = text.replace("&#148;", '"')
    text = text.replace("&#149;", "•")  # bullet
    text = text.replace("&#150;", "-")  # en-dash
    text = text.replace("&#151;", "—")  # em-dash
    text = text.replace("&#160;", " ")  # non-breaking space
    text = text.replace("&amp;", "&")
    text = text.replace("&mdash;", "—")
    text = text.replace("&ndash;", "-")
    text = text.replace("&bull;", "•")
    text = text.replace("&rsquo;", "'")
    text = text.replace("&lsquo;", "'")
    text = text.replace("&rdquo;", '"')
    text = text.replace("&ldquo;", '"')

    # SEC ASCII renderings of trademark symbols in old plain-text filings.
    text = text.replace("-Registered Trademark-", "®")
    text = text.replace("-Servicemark-", "℠")
    text = text.replace("-TM-", "™")

    # Unicode curly/smart quotes -> straight quotes
    text = text.replace('"', '"')  # left double quote
    text = text.replace('"', '"')  # right double quote
    text = text.replace(
        """, "'")  # left single quote
    text = text.replace(""",
        "'",
    )  # right single quote

    # Unicode dashes -> ASCII
    text = text.replace("–", "-")  # en-dash
    text = text.replace("—", "-")  # em-dash (to hyphen for consistency)

    # Clean remaining HTML entities
    text = re.sub(r"&\w+;", "", text)
    text = re.sub(r"&#\d+;", "", text)
    return text.strip()


def _extract_8k_items(html_content: str) -> dict[str, dict]:
    """
    Extract items from 8-K filings which use Item X.XX format.

    8-K items use a different numbering scheme:
    - Section 1: Registrant's Business and Operations
      - Item 1.01: Entry into a Material Definitive Agreement
      - Item 1.02: Termination of a Material Definitive Agreement
      - Item 1.03: Bankruptcy or Receivership
      - Item 1.04: Mine Safety - Reporting of Shutdowns and Patterns of Violations
    - Section 2: Financial Information
      - Item 2.01: Completion of Acquisition or Disposition of Assets
      - Item 2.02: Results of Operations and Financial Condition
      - Item 2.03: Creation of a Direct Financial Obligation
      - Item 2.04: Triggering Events That Accelerate or Increase a Direct Financial Obligation
      - Item 2.05: Costs Associated with Exit or Disposal Activities
      - Item 2.06: Material Impairments
    - Section 3: Securities and Trading Markets
    - Section 4: Matters Related to Accountants and Financial Statements
    - Section 5: Corporate Governance and Management
    - Section 6: [Reserved]
    - Section 7: Regulation FD
    - Section 8: Other Events
      - Item 8.01: Other Events
    - Section 9: Financial Statements and Exhibits
      - Item 9.01: Financial Statements and Exhibits
    """
    from bs4 import BeautifulSoup

    items: dict = {}

    # 8-K item pattern: Item X.XX - handles various spacing including thin space (U+2009)
    # Matches: Item 1.01, Item 8.01, Item 9.01, etc.
    item_pattern = re.compile(
        r"Item[\s\u2009]+(\d+\.\d+)[\s\u2009]*([^\n<]{0,100})", re.IGNORECASE
    )

    # Find all matches
    matches = []
    for m in item_pattern.finditer(html_content):
        item_num = m.group(1)
        title = m.group(2).strip()
        # Clean title
        title = re.sub(r"<[^>]+>", "", title)  # Remove HTML tags
        title = _clean_html_entities(title)
        title = re.sub(r"\s+", " ", title).strip()
        # Skip very short titles (likely TOC entries)
        if len(title) < 5:
            title = _get_8k_item_name(item_num)
        matches.append((m.start(), item_num, title))

    # Sort by position
    matches.sort(key=lambda x: x[0])

    if not matches:
        return items

    # Remove duplicate matches (keep first occurrence in body, skip TOC)
    # TOC entries are typically followed by page numbers or in tables
    seen_items = {}
    filtered_matches = []

    for pos, item_num, title in matches:
        if item_num in seen_items:
            # Keep the later occurrence (more likely to be the actual section, not TOC)
            # But only if there's significant content between them
            prev_pos = seen_items[item_num][0]
            if pos - prev_pos > 1000:  # Significant distance apart
                # Replace with the later occurrence
                filtered_matches = [m for m in filtered_matches if m[1] != item_num]
                filtered_matches.append((pos, item_num, title))
                seen_items[item_num] = (pos, title)
        else:
            filtered_matches.append((pos, item_num, title))
            seen_items[item_num] = (pos, title)

    matches = sorted(filtered_matches, key=lambda x: x[0])

    # Extract each item section
    for i, (pos, item_num, title) in enumerate(matches):
        # Get end position (start of next item or end of document)
        end_pos = matches[i + 1][0] if i + 1 < len(matches) else len(html_content)

        # Extract the HTML section
        section_html = html_content[pos:end_pos]

        # Parse this section
        soup = BeautifulSoup(section_html, "html.parser")

        # Process content in document order
        content_parts: list[tuple[str, str]] = []
        processed_texts: set[str] = set()

        # Process elements in document order
        for elem in soup.find_all(["p", "table", "div", "span"]):
            if elem.name == "table":
                # Skip nested tables (already processed by parent)
                if elem.find_parent("table"):
                    continue

                # Process table - check for bullet list first
                if _is_bullet_table(elem):
                    result = _extract_bullet_list(elem)
                elif not _is_financial_table(elem):
                    # Not a financial table - extract as simple text
                    text = elem.get_text(separator=" ", strip=True)
                    text = _clean_html_entities(text)
                    text = re.sub(r"\s+", " ", text).strip()
                    result = text if len(text) > 20 else None
                else:
                    # Parse as financial table
                    headers, data_rows = _parse_html_table_for_notes(elem)
                    result = (
                        _table_to_markdown_notes(headers, data_rows)
                        if data_rows
                        else None
                    )

                # Add content avoiding duplicates
                if result:
                    text_key = result[:200] if len(result) > 200 else result
                    if text_key not in processed_texts:
                        content_parts.append(("table", result))
                        processed_texts.add(text_key)

            elif elem.name in ("p", "div"):
                # Skip if inside a table
                if elem.find_parent("table"):
                    continue

                # Get text
                text = elem.get_text(separator=" ", strip=True)
                text = _clean_html_entities(text)
                text = re.sub(r"\s+", " ", text).strip()

                # Add content avoiding duplicates
                if text and len(text) > 10:
                    text_key = text[:200] if len(text) > 200 else text
                    if text_key not in processed_texts:
                        content_parts.append(("text", text))
                        processed_texts.add(text_key)

        # Join with proper spacing
        full_text = "\n\n".join(item[1] for item in content_parts)

        # Determine section number from item number
        section = item_num.split(".")[0]

        # Create key
        key = f"item_{item_num}"

        items[key] = {
            "name": title or _get_8k_item_name(item_num),
            "section": section,
            "item_num": item_num,
            "text": full_text,
        }

    return items


def _get_8k_item_name(item_num: str) -> str:
    """Get default name for an 8-K filing item."""
    names = {
        "1.01": "Entry into a Material Definitive Agreement",
        "1.02": "Termination of a Material Definitive Agreement",
        "1.03": "Bankruptcy or Receivership",
        "1.04": "Mine Safety - Reporting of Shutdowns and Patterns of Violations",
        "2.01": "Completion of Acquisition or Disposition of Assets",
        "2.02": "Results of Operations and Financial Condition",
        "2.03": "Creation of a Direct Financial Obligation",
        "2.04": "Triggering Events That Accelerate or Increase a Direct Financial Obligation",
        "2.05": "Costs Associated with Exit or Disposal Activities",
        "2.06": "Material Impairments",
        "3.01": "Notice of Delisting or Failure to Satisfy a Continued Listing Rule",
        "3.02": "Unregistered Sales of Equity Securities",
        "3.03": "Material Modification to Rights of Security Holders",
        "4.01": "Changes in Registrant's Certifying Accountant",
        "4.02": "Non-Reliance on Previously Issued Financial Statements",
        "5.01": "Changes in Control of Registrant",
        "5.02": "Departure of Directors or Certain Officers",
        "5.03": "Amendments to Articles of Incorporation or Bylaws",
        "5.04": "Temporary Suspension of Trading Under Registrant's Employee Benefit Plans",
        "5.05": "Amendment to Registrant's Code of Ethics",
        "5.06": "Change in Shell Company Status",
        "5.07": "Submission of Matters to a Vote of Security Holders",
        "5.08": "Shareholder Director Nominations",
        "6.01": "[Reserved]",
        "6.02": "[Reserved]",
        "6.03": "[Reserved]",
        "6.04": "[Reserved]",
        "6.05": "[Reserved]",
        "7.01": "Regulation FD Disclosure",
        "8.01": "Other Events",
        "9.01": "Financial Statements and Exhibits",
    }
    return names.get(item_num, f"Item {item_num}")


def _get_item_default_name(item_num: str, part: str) -> str:
    """Get default name for a filing item."""
    if part == "I":
        # 10-Q Part I items
        names = {
            "1": "Financial Statements",
            "2": "Management's Discussion and Analysis",
            "3": "Quantitative and Qualitative Disclosures About Market Risk",
            "4": "Controls and Procedures",
        }
    else:
        # Part II items (common to 10-K and 10-Q)
        names = {
            "1": "Legal Proceedings",
            "1A": "Risk Factors",
            "2": "Changes in Securities",
            "3": "Defaults Upon Senior Securities",
            "4": "Mine Safety Disclosures",
            "5": "Other Information",
            "6": "Exhibits",
        }
    return names.get(item_num, f"Item {item_num}")


def _extract_simple_table(table_elem) -> str | None:
    """
    Extract a simpler text representation of a table when structured parsing fails.
    Used for tables that don't follow financial statement format.
    """
    rows = table_elem.find_all("tr")
    if not rows:
        return None

    result_rows = []
    for tr in rows:
        cells = tr.find_all(["td", "th"], recursive=False)
        if not cells:
            continue

        # Get text from each cell
        cell_texts = []
        for c in cells:
            if c.find("table"):
                continue  # Skip nested tables
            text = c.get_text(strip=True)
            text = re.sub(r"\s+", " ", text)
            if text:
                cell_texts.append(text)

        if cell_texts:
            result_rows.append(" | ".join(cell_texts))

    if len(result_rows) > 1:
        return "\n".join(result_rows)
    return None


def _parse_html_table_for_notes(table_elem) -> tuple[list[str], list[list[str]]]:
    """
    Parse an HTML table for notes.
    Returns (headers, data_rows) where each row is a list of cell values.

    Uses the same extraction logic as financial statement parsing.
    """
    # Use _extract_table_data which already handles complex layouts
    result = _extract_table_data(table_elem)
    if result:
        line_items, periods, multiplier, _title = result
        headers = [""] + periods  # Empty for label column
        data_rows = []
        for item in line_items:
            label = item.get("label", "")
            values = item.get("values", [])
            # Format values
            row = [label]
            for v in values:
                if v is None:
                    row.append("")
                elif item.get("skip_multiplier"):
                    row.append(str(v))
                else:
                    row.append(str(v * multiplier) if multiplier != 1 else str(v))
            data_rows.append(row)
        return headers, data_rows

    # Fallback: simple cell extraction
    all_trs = table_elem.find_all("tr")
    if len(all_trs) < 2:
        return [], []

    headers = []
    data_rows = []
    for _i, tr in enumerate(all_trs):
        cells = tr.find_all(["td", "th"], recursive=False)
        row_data = [_clean_cell_text(c) for c in cells]
        # Skip empty rows
        if not any(row_data):
            continue
        if not headers:
            headers = row_data
        else:
            data_rows.append(row_data)

    return headers, data_rows


def _table_to_markdown_notes(headers: list[str], data_rows: list[list[str]]) -> str:
    """Convert parsed table data to markdown."""
    if not headers and not data_rows:
        return ""

    lines = []
    num_cols = len(headers) if headers else (len(data_rows[0]) if data_rows else 0)

    if num_cols == 0:
        return ""

    lines.append("| " + " | ".join(headers) + " |")
    lines.append("| " + " | ".join(["---"] * num_cols) + " |")

    for row in data_rows:
        # Ensure row has right number of cells
        row_data = list(row)
        while len(row_data) < num_cols:
            row_data.append("")
        lines.append("| " + " | ".join(row_data[:num_cols]) + " |")

    return "\n".join(lines)


def get_statement_names() -> dict[str, str]:
    """Get mapping of statement type codes to display names."""
    return {
        "income": "Consolidated Statements of Operations",
        "balance": "Consolidated Balance Sheet",
        "cash": "Consolidated Statements of Cash Flows",
        "equity": "Consolidated Statements of Stockholders' Equity",
    }
