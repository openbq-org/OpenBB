"""Fama-French utilities for handling US and International portfolios and factors."""

from functools import lru_cache

from openbb_famafrench.utils.constants import (
    BASE_URL,
    BREAKPOINT_FILES,
    COUNTRY_PORTFOLIO_FILES,
    COUNTRY_PORTFOLIOS_URLS,
    DATASET_CHOICES,
    FACTOR_REGION_MAP,
    INTERNATIONAL_INDEX_PORTFOLIO_FILES,
    INTERNATIONAL_INDEX_PORTFOLIOS_URLS,
    REGIONS_MAP,
)


async def get_factor_choices(
    region: str | None = None,
    factor: str | None = None,
    is_portfolio: bool = False,
    portfolio: str | None = None,
):
    """Get the list of choices for factors based on combinations of parameters.

    This function is for generating choices for Workspace dropdown menus.
    It is not intended to be used directly.

    Parameters
    ----------
    region : Optional[str]
        The region for which to get factor choices. If None, all regions are considered.
    factor : Optional[str]
        The specific factor for which to get choices. If None, all factors for the region are
        considered.
    is_portfolio : bool
        If True, the function will return portfolio choices instead of factor choices.
    portfolio : Optional[str]
        A specific portfolio.

    Returns
    -------
    list
        A list of dictionaries representing the choices for factors or portfolios.
        Each dictionary contains a 'label' and a 'value' key.
    """
    if region and not factor and not is_portfolio:
        factors = FACTOR_REGION_MAP.get(region, {}).get("factors", {})
        return [
            {
                "label": k.replace("_", " ")
                .title()
                .replace("Lt", "LT")
                .replace("St", "ST"),
                "value": k,
            }
            for k in list(factors)
        ]
    if region and factor and not is_portfolio:
        intervals = (
            FACTOR_REGION_MAP.get(region, {}).get("intervals", {}).get(factor, {})
        )
        intervals = [
            {"label": k.replace("_", " ").title(), "value": k} for k in list(intervals)
        ]
        return intervals

    if not is_portfolio:
        return [
            {"label": k.replace("_", " ").title(), "value": k}
            for k in list(FACTOR_REGION_MAP)
        ]
    region = region or ""
    mapped_region = REGIONS_MAP.get(region, "").replace("_", " ")
    if is_portfolio and region and not portfolio:
        portfolios = (
            [
                {
                    "label": (
                        d["label"].replace(mapped_region, "").strip()
                        if region != "america"
                        else d["label"]
                    ),
                    "value": d["value"],
                }
                for d in DATASET_CHOICES
                if "Portfolio" in d.get("value", "")
                and d["value"].startswith(REGIONS_MAP.get(region, region))
                and "daily" not in d.get("value", "").lower()
            ]
            if region != "america"
            else [
                d
                for d in DATASET_CHOICES
                if "Portfolio" in d.get("value", "")
                and all(
                    not d.get("value", "").startswith(reg)
                    for reg in REGIONS_MAP.values()
                    if reg
                )
                and "daily" not in d.get("value", "").lower()
            ]
        )

        if "ex_" not in region:
            portfolios = [d for d in portfolios if "ex_" not in d.get("value", "")]

        return portfolios

    if is_portfolio and region and portfolio:
        portfolios = (
            [
                d
                for d in DATASET_CHOICES
                if "Portfolio" in d.get("value", "")
                and d["value"].startswith(REGIONS_MAP.get(region, region))
                and portfolio in d.get("value", "")
            ]
            if region != "america"
            else [
                d
                for d in DATASET_CHOICES
                if "Portfolio" in d.get("value", "")
                and all(
                    not d.get("value", "").startswith(reg)
                    for reg in REGIONS_MAP.values()
                    if reg
                )
                and portfolio in d.get("value", "")
            ]
        )
        has_daily = False
        frequencies = ["monthly", "annual"]

        for d in portfolios:
            if "daily" in d.get("value", "").lower():
                has_daily = True
                break

        frequencies = ["daily"] + frequencies if has_daily else frequencies

        return [{"label": k.title(), "value": k} for k in frequencies]

    return [{"label": "No choices found. Try a new parameter.", "value": None}]


@lru_cache(maxsize=64)
def download_file(dataset) -> str:
    """Download the specified dataset file from the Ken French data library.

    Note: This function is not intended for direct use, it is called by `get_portfolio_data`.
    """
    import zipfile
    from io import BytesIO

    from openbb_core.provider.utils.helpers import get_requests_session

    url_map = {item["label"]: item["value"] for item in DATASET_CHOICES}

    if dataset.replace("_", " ") not in list(url_map) and dataset not in list(
        url_map.values()
    ):
        raise ValueError(
            f"Dataset {dataset} not found in available datasets: {list(url_map)}"
        )

    url = (
        BASE_URL + dataset
        if dataset.endswith(".zip")
        else BASE_URL + url_map[dataset.replace("_", " ")]
    )

    with get_requests_session() as session:
        response = session.get(url)
        response.raise_for_status()

    raw_data = b""

    with (
        zipfile.ZipFile(BytesIO(response.content)) as f,
        f.open(f.namelist()[0]) as file,
    ):
        raw_data = file.read()

    try:
        data = raw_data.decode("utf-8")
    except UnicodeDecodeError:
        data = raw_data.decode("latin-1")

    return data


@lru_cache(maxsize=64)
def download_international_portfolios(url):
    """Download the international index portfolios file.

    Note: This function is not intended for direct use,
    it is called by `get_international_portfolio`.
    """
    from openbb_core.provider.utils.helpers import get_requests_session

    with get_requests_session() as session:
        response = session.get(url)
        response.raise_for_status()

    return response


def apply_date(x):
    """Pandas Apply helper to convert various date formats to a standard YYYY-MM-DD format."""
    from pandas import to_datetime

    date = str(x).replace(" ", "")
    if len(date) == 6:
        date = date[:4] + "-" + date[4:]
        date = to_datetime(date, format="%Y-%m")
        date = date.date().strftime("%Y-%m-%d")
    elif len(date) == 8:
        date = date[:4] + "-" + date[4:6] + "-" + date[6:]
    elif len(date) == 4:
        date = date + "-12-31"
    return date


def read_csv_file(data: str):
    """Parse the raw data from a .csv file into a list of dictionaries representing tables.

    Note: This function is not intended for direct use, it is called by `get_portfolio_data`.
    """
    import re

    lines = data.splitlines()
    tables: list = []
    general_description: list = []

    # Extract general description from the top of the file
    description_end_idx = 0
    for idx, line in enumerate(lines):
        if line.strip().startswith(",") or re.match(r"^\s*\d{4,6}", line):
            description_end_idx = idx
            break
        if line.strip():
            general_description.append(line.strip())

    # Extract initial table metadata from the last line of general description
    table_metadata: str = ""
    if general_description and (
        "Monthly" in general_description[-1]
        or "Annual" in general_description[-1]
        or "Returns" in general_description[-1]
    ):
        table_metadata = general_description[-1]
        general_description = general_description[:-1]

    general_desc_text = "\n".join(general_description)

    # Process tables in the file
    i = description_end_idx

    while i < len(lines):
        # Skip empty lines
        while i < len(lines) and not lines[i].strip():
            i += 1

        if i >= len(lines):
            break

        # Check if this is a table header (starts with comma)
        if lines[i].strip().startswith(","):
            # Look for metadata line before this header
            metadata = table_metadata  # Default to initial metadata
            j = i - 1
            while j >= description_end_idx:
                if lines[j].strip():
                    metadata = lines[j].strip()
                    break
                j -= 1

            # Parse headers
            header_line = lines[i].strip()
            headers = ["Date"] + header_line.split(",")[1:]

            # Move past header row
            i += 1

            # Collect data rows
            data_rows = []

            # Look for data rows until we hit the next header or end of file
            while i < len(lines):
                line = lines[i].strip()
                if not line:
                    break
                values = line.split(",")
                if values:
                    data_rows.append([d.strip() for d in values])

                i += 1

            # Add table if it has data
            if data_rows:
                tables.append(
                    {
                        "meta": metadata,
                        "headers": headers,
                        "rows": data_rows,
                        "is_annual": "Annual" in metadata,
                    }
                )

        # Check for standalone metadata
        elif "--" in lines[i] and any(
            d in lines[i] for d in ["Daily", "Monthly", "Annual", "Weekly"]
        ):
            # Update metadata for next table
            table_metadata = lines[i].strip()
            i += 1
        else:
            # Skip other lines
            i += 1

    return tables, general_desc_text


def process_csv_tables(tables, general_description="") -> tuple:
    """Convert parsed table dictionaries from CSV files to pandas DataFrames.

    Note: This function is not intended for direct use, it is called by `get_portfolio_data`.
    """
    import warnings  # noqa
    from pandas import DataFrame

    dataframes: list = []
    metadata: list = []

    for table_idx, table in enumerate(tables):
        # Skip empty tables
        if not table["rows"]:
            continue

        # Create DataFrame from rows
        rows_data = table.get("rows", [])
        headers = table["headers"]

        # Check if we have enough headers
        max_cols = max(len(row) for row in rows_data)
        if len(headers) < max_cols:
            headers.extend([f"Column_{i}" for i in range(len(headers), max_cols)])

        # Create dataframe with proper dimensions and headers
        df = DataFrame(rows_data)

        if df.empty or df.shape[1] == 0:
            continue

        # Set column names
        df.columns = headers[: df.shape[1]]

        # Convert Date column to datetime
        try:
            # Convert YYYYMM format to datetime
            df["Date"] = df.Date.apply(apply_date)
        except Exception as e:
            warnings.warn(f"Error parsing dates: {e}")
            df["Date"] = df["Date"].astype(str)

        # Set Date as index
        df = df.set_index("Date")
        df = df.sort_index()
        dataframes.append(df)

        # Get metadata from the table
        table_meta_desc = table["meta"].strip()

        # Determine frequency from the table's metadata
        frequency = "monthly"
        if "Annual" in table_meta_desc:
            frequency = "annual"

        # Create metadata entry
        table_meta = {
            "description": f"### {table_meta_desc}\n\n"
            + general_description.replace("\n", " ")
            + "\n\n",
            "frequency": frequency,
            "formations": headers[1:],
        }
        metadata.append(table_meta)

    return dataframes, metadata


def read_dat_file(data: str) -> list:
    """Parse the raw data from a .dat file into a list of dictionaries representing tables.

    Note: This function is not intended for direct use,
    it is called by `get_international_portfolio`.
    """
    import re

    lines = data.splitlines()
    tables: list = []

    i = 0

    current_table: dict = {}
    while i < len(lines):
        # Check for table separator or new table metadata indicator
        if re.match(r"\s*,", lines[i]) or (
            i > 1
            and "Data" in lines[i]
            and "current_table" in locals()
            and current_table["rows"]
        ):
            # Add current table if it exists and has rows
            if "current_table" in locals() and current_table["rows"]:
                tables.append(current_table)

            # If this is a separator line, skip it
            if re.match(r"\s*,", lines[i]):
                i += 1
                continue

        # Start a new table
        current_table = {"meta": "", "spanners": "", "headers": [], "rows": []}
        meta_lines = []

        # Process metadata (which may span multiple lines)
        while i < len(lines):
            line = lines[i].strip()
            # Check if this line looks like the start of data or spanner rows
            if (
                "--" in line
                or "Firms" in line.split()
                and any(c.isdigit() for c in lines[i + 1])  # Spanner line
                if i + 1 < len(lines)
                else False  # Firms header
                or line in ["", " "]  # Empty separator
                or (line and line[0].isdigit() and len(line.split()) > 2)  # Data row
            ):
                break

            if line:  # Only add non-empty lines
                meta_lines.append(line)
            i += 1

        # Join all metadata lines
        current_table["meta"] = "\n".join(meta_lines)

        # Process spanners if we have a line with dashes
        if i < len(lines) and "--" in lines[i]:
            current_table["spanners"] = lines[i]
            i += 1
        else:
            # No spanners line found
            current_table["spanners"] = ""  # Empty spanners for tables like "Firms"

        # Process headers - handle special case for "Firms" tables
        if i < len(lines):
            header_line = lines[i].strip()
            # Check if this is a "Firms" table with its specific format
            if (
                "Firms" in header_line.split()
                or header_line
                and not header_line[0].isdigit()
            ):
                current_table["headers"] = ["Date"] + header_line.split()
                i += 1
            elif "Firms" in current_table["meta"]:
                # Default headers for Firms tables if header row is missing
                current_table["headers"] = [
                    "Date",
                    "Firms",
                    "B/M",
                    "E/P",
                    "CE/P",
                    "Yld",
                ]
            else:
                # Skip this table - malformed
                while i < len(lines) and not (
                    re.match(r"\s*,", lines[i]) or "Data" in lines[i]
                ):
                    i += 1
                continue

        # Process rows until next separator or next table start
        row_count = 0
        while i < len(lines) and not (
            re.match(r"\s*,", lines[i]) or "Data" in lines[i]
        ):
            # Skip copyright lines, empty lines, and other non-data lines
            if (
                lines[i].strip()
                and not lines[i].strip().startswith("Copyright")
                and "©" not in lines[i]
                and any(c.isdigit() for c in lines[i])
            ):  # Ensure line has at least one digit (likely a date)
                current_table["rows"].append(lines[i].split())
                row_count += 1
            i += 1

    # Add the last table if it has rows
    if "current_table" in locals() and current_table["rows"]:
        tables.append(current_table)

    return tables


def get_international_portfolio_data(
    index: str | None = None,
    country: str | None = None,
    dividends: bool = True,
) -> str:
    """Download and extract the international index or country portfolio data.

    Note: Not intended for direct use, this function is called by `get_international_portfolio`.
    """
    import zipfile
    from io import BytesIO

    url: str = ""
    data: str = ""
    if not index and not country:
        raise ValueError("Please provide either an index or a country.")
    if index and country:
        raise ValueError(
            "Please provide either an index or a country, not both at the same time."
        )
    if index:
        index = INTERNATIONAL_INDEX_PORTFOLIO_FILES.get(index)

        if not index:
            raise ValueError(
                f"Index {index} not found in available indexes: "
                + f"{INTERNATIONAL_INDEX_PORTFOLIO_FILES}"
            )
        url = (
            BASE_URL
            + INTERNATIONAL_INDEX_PORTFOLIOS_URLS["dividends" if dividends else "ex"]
        )
    if country:
        country = country.title().replace("_", " ")
        if country not in list(COUNTRY_PORTFOLIO_FILES):
            raise ValueError(
                f"Country {country} not found in available countries: "
                + f"{COUNTRY_PORTFOLIO_FILES}"
            )
        url = BASE_URL + COUNTRY_PORTFOLIOS_URLS["dividends" if dividends else "ex"]
        index = COUNTRY_PORTFOLIO_FILES[country]

    response = download_international_portfolios(url)

    with zipfile.ZipFile(BytesIO(response.content)) as f:
        filenames = f.namelist()
        if index is None:
            raise ValueError("Could not resolve portfolio index from input parameters.")

        if index in filenames:
            try:
                with f.open(index) as file:
                    data = file.read().decode("utf-8")
            except UnicodeDecodeError:
                # Fallback to latin-1 encoding if utf-8 fails
                with f.open(index) as file:
                    data = file.read().decode("latin-1")
        else:
            raise ValueError(
                f"Index {index} not found in available indexes: {filenames}"
            )

    return data


def process_international_portfolio_data(tables: list, dividends: bool = True) -> tuple:
    """Convert parsed table dictionaries to pandas DataFrames with proper multi-index columns.

    Note: Not intended for direct use, this function is called by `get_international_portfolio`.
    """
    import re  # noqa
    import warnings
    from pandas import DataFrame, MultiIndex

    dataframes: list = []
    metadata: list = []

    for table_idx, table in enumerate(tables):
        # Extract spanner groups
        spanner_groups = table["spanners"].replace("-", "").split()

        # Create DataFrame from rows
        rows_data = table.get("rows", [])
        df = DataFrame(rows_data)

        if df.empty:
            continue

        # Set column names based on headers
        headers = table["headers"]
        if len(headers) == len(df.columns):
            df.columns = headers

        # Check if this is a special case table with "Firms" column
        has_firms_column = "Firms" in df.columns

        # Parse and set Date column
        try:
            df["Date"] = df["Date"].apply(apply_date)
        except Exception as e:
            warnings.warn(f"Error parsing dates. Using string conversion. -> {e}")
            df["Date"] = df["Date"].astype(str)

        # Set Date as index (or Date and Mkt if applicable)
        df = (
            df.set_index(["Date", "Mkt"])
            if "Mkt" in df.columns and not has_firms_column
            else df.set_index("Date")
        )

        # Create multi-index columns only for regular tables (not those with Firms)
        if not has_firms_column and spanner_groups and len(df.columns) > 0:
            # Create multi-index columns
            remaining_headers = list(df.columns)
            bottom_level = remaining_headers

            # Calculate columns per group
            cols_per_group = len(remaining_headers) // len(spanner_groups)

            # Create top level for multi-index
            top_level = []
            for group in spanner_groups:
                top_level.extend([group] * cols_per_group)

            # Handle Zero column specially
            if "Zero" in remaining_headers:
                zero_idx = remaining_headers.index("Zero")
                # Find Yld group
                for group in spanner_groups:
                    if group.lower() == "yld":
                        # Ensure top_level has enough elements
                        while len(top_level) <= zero_idx:
                            top_level.append("")
                        top_level[zero_idx] = group
                        break

            # Create the multi-index columns
            if len(top_level) == len(bottom_level):
                df.columns = MultiIndex.from_arrays([top_level, bottom_level])

        dataframes.append(df)

        # Format metadata for description
        meta_text = table["meta"].strip().replace("\n", " - ")
        if dividends is False:
            meta_text += " - Ex-Dividends"

        # Format metadata nicely, replacing multiple spaces with a single space
        meta_text = re.sub(r"\s{2,}", " ", meta_text)

        is_annual = (
            df.index[0][0][-2:] in ["31", 31]
            if isinstance(df.index, MultiIndex)
            else df.index[0][-2:] in ["31", 31]
        )

        table_meta = {
            "description": meta_text,
            "frequency": "annual" if is_annual else "monthly",
            "formations": (
                [d for d in df.columns.tolist() if d != "Firms"]
                if has_firms_column
                else spanner_groups
            ),
        }
        metadata.append(table_meta)

    return dataframes, metadata


@lru_cache(maxsize=64)
def get_international_portfolio(
    index: str | None = None,
    country: str | None = None,
    dividends: bool = True,
    frequency: str | None = None,
    measure: str | None = None,
    all_data_items_required: bool | None = None,
) -> tuple:
    """Get the international portfolio data for a given index or country.

    Parameters
    ----------
    index : Optional[str]
        The index for which to get the portfolio data. If None, country must be provided.
    country : Optional[str]
        The country for which to get the portfolio data. If None, index must be provided.
    dividends : bool
        When False, returns data with dividends excluded. Defaults to True.
    frequency : Optional[str]
        The frequency of the data to return. Can be 'monthly', or 'annual'.
        If None, defaults to 'monthly'.
    measure : Optional[str]
        The measure of the data to return. Can be 'usd', 'local', or 'ratios'.
        If None, defaults to 'usd'.
    all_data_items_required : Optional[bool]
        Default is True.
        If True, returns only data for firms with all 4 ratios of B/M, E/P, CE/P, and Yld.
        When False, returns data for firms with B/M data only.

    Returns
    -------
    tuple
        A tuple containing a list of pandas DataFrames and a list of metadata dictionaries.
        In most scenarios, there will only be 1 DataFrame and 1 metadata dictionary.

    Raises
    ------
    ValueError
        When an invalid combination of parameters or unsupported values are supplied.
    """
    measure = measure.lower() if measure is not None else "usd"
    data = get_international_portfolio_data(index, country, dividends)
    tables = read_dat_file(data)
    dataframes, metadata = process_international_portfolio_data(tables, dividends)

    if measure and measure not in ["usd", "local", "ratios"]:
        raise ValueError(
            f"Measure {measure} not supported. Choose from 'usd', 'local', or 'ratios'."
        )

    if frequency == "monthly" and measure == "ratios":
        raise ValueError("Only annual frequency is available for 'ratios' measure.")

    if frequency:
        dfs = [
            df
            for df, meta in zip(dataframes, metadata)
            if meta["frequency"] == frequency
        ]
        dfs_meta = [meta for meta in metadata if meta["frequency"] == frequency]
    else:
        dfs = dataframes
        dfs_meta = metadata

    if measure == "local":
        dfs = [df for df, meta in zip(dfs, dfs_meta) if "Local" in meta["description"]]
        dfs_meta = [meta for meta in dfs_meta if "Local" in meta["description"]]
    elif measure == "usd":
        dfs = [df for df, meta in zip(dfs, dfs_meta) if "Dollar" in meta["description"]]
        dfs_meta = [meta for meta in dfs_meta if "Dollar" in meta["description"]]
    elif measure == "ratios":
        dfs = [df for df, meta in zip(dfs, dfs_meta) if "Ratios" in meta["description"]]
        dfs_meta = [meta for meta in dfs_meta if "Ratios" in meta["description"]]

    if all_data_items_required is False and measure != "ratios":
        dfs = [
            df for df, meta in zip(dfs, dfs_meta) if "Not Reqd" in meta["description"]
        ]
        dfs_meta = [meta for meta in dfs_meta if "Not Reqd" in meta["description"]]
    elif all_data_items_required is True:
        dfs = [
            df for df, meta in zip(dfs, dfs_meta) if "Required" in meta["description"]
        ]
        dfs_meta = [meta for meta in dfs_meta if "Required" in meta["description"]]

    return dfs, dfs_meta


@lru_cache(maxsize=64)
def get_portfolio_data(
    dataset: str, frequency: str | None = None, measure: str | None = None
) -> tuple:
    """Get US portfolio data for a given dataset.

    Parameters
    ----------
    dataset : str
        The dataset to retrieve. Must be one of the available datasets in DATASET_CHOICES.
    frequency : Optional[str]
        The frequency of the data to return. Can be 'monthly', 'annual', or 'daily'.
        If None, defaults to 'monthly'.
    measure : Optional[str]
        The measure of the data to return.
        Can be 'value', 'equal', 'number_of_firms', or 'firm_size'.
        If None, defaults to 'value'.

    Returns
    -------
    tuple
        A tuple containing a list of pandas DataFrames and a list of metadata dictionaries.
        In most scenarios, there will only be 1 DataFrame and 1 metadata dictionary.

    Raises
    ------
    ValueError
        When an invalid combination of parameters or unsupported values are supplied.
    """
    if frequency and frequency.lower() not in ["monthly", "annual", "daily"]:
        raise ValueError(
            f"Frequency {frequency} not supported. Choose from 'monthly', 'annual', or 'daily'."
        )
    if measure and measure not in ["value", "equal", "number_of_firms", "firm_size"]:
        raise ValueError(
            f"Measure {measure} not supported. "
            + "Choose from 'value', 'equal', 'number_of_firms', or 'firm_size'."
        )
    if measure in ["number_of_firms", "firm_size"] and frequency == "annual":
        raise ValueError(
            f"Measure '{measure}' is only available for monthly frequency."
        )
    if "Factor" in dataset:
        measure = None

    file = download_file(dataset)
    table, desc = read_csv_file(file)
    dfs, metadata = process_csv_tables(table, desc)

    if frequency:
        out_dfs = [
            df
            for df, meta in zip(dfs, metadata)
            if meta["frequency"].lower() == frequency.lower()
        ]
        out_metadata = [
            meta for meta in metadata if meta["frequency"].lower() == frequency.lower()
        ]
    else:
        out_dfs = dfs
        out_metadata = metadata

    if measure is not None:
        if measure in ["value", "equal"]:
            out_dfs = [
                df
                for df, meta in zip(out_dfs, out_metadata)
                if "--" in meta["description"]
                and measure.lower() in meta["description"].split(" -- ")[0].lower()
            ]
            out_metadata = [
                meta
                for meta in out_metadata
                if "--" in meta["description"]
                and measure.lower() in meta["description"].split(" -- ")[0].lower()
            ]
        elif measure == "number_of_firms":
            out_dfs = [
                df
                for df, meta in zip(out_dfs, out_metadata)
                if "Number of Firms" in meta["description"]
            ]
            out_metadata = [
                meta
                for meta in out_metadata
                if "Number of Firms" in meta["description"]
            ]
        elif measure == "firm_size":
            out_dfs = [
                df
                for df, meta in zip(out_dfs, out_metadata)
                if "Average Firm Size" in meta["description"]
            ]
            out_metadata = [
                meta
                for meta in out_metadata
                if "Average Firm Size" in meta["description"]
            ]

    return out_dfs, out_metadata


@lru_cache(maxsize=8)
def get_breakpoint_data(
    breakpoint_type: str,
) -> tuple:
    """Get US breakpoint data for a given dataset.

    Parameters
    ----------
    breakpoint_type : str
        The breakpoint to retrieve. Must be one of the available breakpoints in BREAKPOINT_FILES.

    Returns
    -------
    tuple
        A tuple containing a pandas DataFrames a metadata dictionary.
    """
    from io import StringIO  # noqa
    from pandas import offsets, read_csv, to_datetime

    col_names = [
        "num_firms",
        "percentile_5",
        "percentile_10",
        "percentile_15",
        "percentile_20",
        "percentile_25",
        "percentile_30",
        "percentile_35",
        "percentile_40",
        "percentile_45",
        "percentile_50",
        "percentile_55",
        "percentile_60",
        "percentile_65",
        "percentile_70",
        "percentile_75",
        "percentile_80",
        "percentile_85",
        "percentile_90",
        "percentile_95",
        "percentile_100",
    ]
    breakpoint_file = BREAKPOINT_FILES.get(breakpoint_type)
    file = download_file(breakpoint_file)
    metadata = ""

    for line in file.splitlines()[:3]:
        if not line.strip() or line.strip().startswith("19"):
            break
        metadata += line.strip() + " "

    metadata = metadata.strip()

    ratio_breakpoints = [
        "be-me",
        "e-p",
        "cf-p",
        "d-p",
    ]

    if breakpoint_type in ratio_breakpoints:
        col_names = ["num_firms_less_than_0", "num_firms_greater_than_0"] + col_names[
            1:
        ]

    breakpoint_data = StringIO(file)
    df = read_csv(
        breakpoint_data,
        skiprows=1 if breakpoint_type == "me" else 3,
        index_col=None,
        header=0,
        names=col_names,
        skipfooter=1,
        engine="python",
    ).reset_index()
    df = df.rename(columns={"index": "date"})
    df.date = df.date.apply(
        lambda x: (
            (to_datetime(x, format="%Y%m") + offsets.MonthEnd(0)).strftime("%Y-%m-%d")
            if len(str(x)) == 6
            else str(x) + "-12-31"
        )
    )

    return [df], [metadata]
