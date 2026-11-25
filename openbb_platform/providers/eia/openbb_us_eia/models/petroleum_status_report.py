"""EIA Weekly Petroleum Status Report model."""

from typing import Any

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.petroleum_status_report import (
    PetroleumStatusReportData,
    PetroleumStatusReportQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_us_eia.utils.constants import (
    WpsrCategoryChoices,
    WpsrCategoryType,
    WpsrFileMap,
    WpsrTableChoices,
    WpsrTableMap,
)

WpsrTableChoicesString = "\n        ".join(WpsrTableChoices)


class EiaPetroleumStatusReportQueryParams(PetroleumStatusReportQueryParams):
    """EIA Petroleum Status Report Query Parameters.

    Source: https://www.eia.gov/petroleum/supply/weekly/
    """

    __json_schema_extra__ = {
        "category": {
            "multiple_items_allowed": False,
            "choices": WpsrCategoryChoices,
        },
        "table": {
            "multiple_items_allowed": True,
            "choices": WpsrTableChoices,
        },
    }

    category: WpsrCategoryType = Field(
        default="balance_sheet",
        description="The group of data to be returned. The default is the balance sheet.",
    )
    table: str | None = Field(
        default=None,
        description="The specific table element within the category to be returned,"
        + " default is 'stocks', if the category is 'weekly_estimates', else 'all'."
        + "\n    Note: Choices represent all available tables from the entire collection and are not all"
        + " available for every category."
        + "\n    Invalid choices will raise a ValidationError with a message"
        + " indicating the valid choices for the selected category."
        + "\n    Choices are:"
        + f"\n        {WpsrTableChoicesString}\n   ",
    )
    use_cache: bool = Field(
        default=True,
        description="Subsequent requests for the same source data are cached for the session using ALRU cache.",
    )


class EiaPetroleumStatusReportData(PetroleumStatusReportData):
    """EIA Petroleum Status Report Data Model."""


class EiaPetroleumStatusReportFetcher(
    Fetcher[EiaPetroleumStatusReportQueryParams, list[EiaPetroleumStatusReportData]]
):
    """EIA Petroleum Status Report Fetcher."""

    require_credentials = False

    @staticmethod
    def transform_query(params: dict[str, Any]) -> EiaPetroleumStatusReportQueryParams:
        """Transform the query parameters."""
        from warnings import warn

        category = params.get("category", "balance_sheet")
        tables = WpsrTableMap.get(category, {})
        _table = params.get("table", "")

        if not _table:
            _table = "stocks" if category == "weekly_estimates" else "all"

        _tables = _table.split(",")

        if len(_tables) == 1 and _tables[0] == "all" and category == "weekly_estimates":
            raise OpenBBError(
                ValueError(
                    f"'all' is not a supported choice for {category}. Please choose from: {list(tables)}"
                )
            )

        if "all" in _tables and len(_tables) > 1:
            _tables.remove("all")
            warn("'all' cannot be used with other table choices. Ignoring 'all'.")

        for table in _tables:
            if table != "all" and table not in tables:
                raise OpenBBError(
                    ValueError(
                        f"Invalid table choice: {table}. Valid choices for {category}: {list(tables)}"
                    )
                )

        params["table"] = ",".join(_tables)

        return EiaPetroleumStatusReportQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: EiaPetroleumStatusReportQueryParams,
        credentials: dict[str, Any] | None,
        **kwargs: Any,
    ) -> dict:
        """Extract the data from the EIA website."""
        from openbb_us_eia.utils.helpers import download_excel_file

        url = WpsrFileMap.get(query.category, "balance_sheet")

        try:
            results = await download_excel_file(url, query.use_cache)
        except OpenBBError as e:
            raise OpenBBError(f"Error extracting data -> {e}") from e

        return {"file": results}

    @staticmethod
    def transform_data(
        query: EiaPetroleumStatusReportQueryParams,
        data: dict,
        **kwargs: Any,
    ) -> list[EiaPetroleumStatusReportData]:
        """Transform the data."""
        import concurrent.futures
        import re
        from functools import lru_cache
        from threading import Lock
        from warnings import warn

        from numpy import nan
        from pandas import Categorical, ExcelFile, concat, read_excel

        category = query.category

        _tables = (
            query.table.split(",")
            if query.table
            else ["stocks"]
            if category == "weekly_estimates"
            else ["all"]
        )
        all_tables = list(WpsrTableMap[category])
        tables = all_tables if "all" in _tables else _tables

        file = data.get("file")

        if not isinstance(file, ExcelFile):
            raise OpenBBError(
                TypeError(f"Expected an ExcelFile object, got {type(file)} instead.")
            )

        dfs: list = []
        excel_lock = Lock()

        def replace_data_strings(text):
            """Replace the table strings with sortable numbers."""
            pattern = r"Data (\d):"

            def replacer(match):
                """Replace the matched string with a sortable number."""
                return f"Data 0{match.group(1)}:"

            return re.sub(pattern, replacer, text)

        @lru_cache(maxsize=128)
        def read_excel_file(file, category, table):
            """Read the ExcelFile for the sheet name and flatten the table."""
            sheet_name = WpsrTableMap[category][table]
            with excel_lock:
                banner = read_excel(file, sheet_name, header=None, nrows=1)
                header = read_excel(file, sheet_name, header=[1, 2], nrows=3)
                df = read_excel(file, sheet_name, header=None, skiprows=3)
            table_name = replace_data_strings(banner.iloc[0, 1])
            symbols = header.columns.get_level_values(0).tolist()
            titles = [
                d.replace(".1", "") for d in header.columns.get_level_values(1).tolist()
            ]
            title_map = dict(zip(symbols, titles))
            df.columns = [d.replace("Sourcekey", "date") for d in symbols]
            df = df.melt(
                id_vars="date",
                value_vars=[d for d in df.columns if d != "date"],
                var_name="symbol",
            ).dropna()
            df = df.reset_index(drop=True)
            df["title"] = df.symbol.map(title_map)
            df["unit"] = df.title.map(lambda x: x.split(" (")[-1].split(")")[0])
            units = [f"({d})" for d in df.unit.unique().tolist()]
            for unit in units:
                df["title"] = df.title.str.replace(unit, "", regex=False).str.strip()
            df["table"] = table_name
            df["order"] = df.groupby("date").cumcount() + 1
            df = df[["date", "table", "symbol", "order", "title", "value", "unit"]]
            df["symbol"] = Categorical(df.symbol, categories=symbols, ordered=True)
            df = df.sort_values(["date", "symbol"])
            df["date"] = df.date.dt.date

            if query.start_date:
                df = df[df.date >= query.start_date]

            if query.end_date:
                df = df[df.date <= query.end_date]

            df = df.reset_index(drop=True)

            if len(df) > 0:
                dfs.append(df)
            else:
                warn(f"No data for table: {table}")

        try:
            with concurrent.futures.ThreadPoolExecutor() as executor:
                executor.map(
                    lambda table: read_excel_file(file, category, table), tables
                )

            results = concat(dfs)

            if len(results) < 1:  # pragma: no cover
                raise EmptyDataError("The data is empty.")

            results = results.sort_values(by=["date", "table", "order"]).replace(
                {nan: None}
            )

            return [
                EiaPetroleumStatusReportData.model_validate(d)
                for d in results.to_dict(orient="records")
            ]
        except Exception as e:
            raise OpenBBError(f"Error transforming the data -> {e}") from e
