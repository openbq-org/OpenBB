"""Shared query, pagination, and transform utilities for EIA APIv2 dataset models."""

import re
from datetime import (
    date as dateType,
    datetime,
)
from typing import Any, Literal, TypeVar

from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.utils.descriptions import QUERY_DESCRIPTIONS
from pydantic import Field

API_BASE = "https://api.eia.gov/v2"
PAGE_SIZE = 5000
MAX_AUTO_ROWS = 500_000

FACET_NAME_COLUMNS = {
    "duoarea": ("area-name",),
    "series": ("series-description",),
    "msn": ("seriesDescription",),
    "seriesId": ("seriesDescription", "seriesName"),
    "tableId": ("tableName",),
}

from openbb_us_eia.utils.catalog import snake_case as _snake


class EiaApiQueryParams(QueryParams):
    """Base query parameters shared by all EIA APIv2 dataset models."""

    __group__ = ""
    __dataset__ = ""

    start_date: dateType | None = Field(
        default=None,
        description=QUERY_DESCRIPTIONS.get("start_date", ""),
    )
    end_date: dateType | None = Field(
        default=None,
        description=QUERY_DESCRIPTIONS.get("end_date", ""),
    )
    sort: Literal["asc", "desc"] = Field(
        default="asc",
        description="Sort the results by date.",
    )
    limit: int | None = Field(
        default=None,
        gt=0,
        description="Maximum number of rows to return."
        " The default returns all rows, paginating requests as needed."
        f" A request matching more than {MAX_AUTO_ROWS:,} rows returns the"
        f" newest {PAGE_SIZE:,} unless a limit is set.",
    )

    @property
    def dataset_key(self) -> str:
        """Resolve the catalog dataset slug for this query."""
        if self.__dataset__:
            return self.__dataset__
        for field in ("dataset", "release"):
            value = getattr(self, field, None)
            if value is not None:
                return str(value)
        from openbb_us_eia.utils.catalog import dataset_choices

        return dataset_choices(self.__group__)[0]

    @property
    def facet_values(self) -> dict[str, str | None]:
        """Collect the facet filter fields declared by the concrete model."""
        from openbb_us_eia.utils.catalog import STANDARD_FIELDS

        return {
            name: getattr(self, name)
            for name in type(self).model_fields
            if name not in STANDARD_FIELDS
        }


class EiaApiData(Data):
    """Base data row for EIA APIv2 datasets."""

    date: dateType | datetime = Field(
        description="Start of the period the record covers."
        " Hourly frequencies return a timestamp."
    )


Q = TypeVar("Q", bound=EiaApiQueryParams)
D = TypeVar("D", bound=EiaApiData)


def transform_dataset_query(
    query_cls: type[Q],
    params: dict[str, Any],
) -> Q:
    """Validate raw parameters against the model and the dataset catalog.

    Parameters
    ----------
    query_cls : type[Q]
        The dataset's query parameter model.
    params : dict[str, Any]
        Raw parameters from the caller.

    Returns
    -------
    Q
        The validated query.
    """
    from openbb_core.app.model.abstract.error import OpenBBError

    from openbb_us_eia.utils import catalog

    known = set(query_cls.model_fields)
    unknown = sorted(set(params) - known)
    if unknown:
        filters = ", ".join(
            name
            for name in query_cls.model_fields
            if name not in catalog.STANDARD_FIELDS
        )
        raise OpenBBError(
            ValueError(
                f"Unknown parameter(s): {', '.join(unknown)}."
                f" Valid filters for this dataset: {filters or 'none'}"
            )
        )
    query = query_cls(**params)
    spec = catalog.get_dataset(query.__group__, query.dataset_key)
    frequency, _ = catalog.resolve_frequency(spec, getattr(query, "frequency", None))
    catalog.resolve_data_columns(spec, getattr(query, "data_type", None))
    catalog.resolve_facets(
        spec,
        frequency,
        query.facet_values,
        choices=catalog.get_group(query.__group__)["choices"],
    )
    return query


async def extract_dataset_data(
    query: EiaApiQueryParams,
    credentials: dict[str, str] | None,
) -> dict:
    """Request every page of a dataset query from the EIA API.

    Parameters
    ----------
    query : EiaApiQueryParams
        The validated query.
    credentials : dict[str, str] | None
        Credentials holding 'eia_api_key'.

    Returns
    -------
    dict
        Mapping with 'rows', 'total', and 'date_format' keys.
    """
    from openbb_core.provider.utils.helpers import amake_request, amake_requests

    from openbb_us_eia.utils import catalog
    from openbb_us_eia.utils.helpers import build_data_url, response_callback

    api_key = credentials.get("eia_api_key", "") if credentials else ""
    spec = catalog.get_dataset(query.__group__, query.dataset_key)
    frequency, freq_spec = catalog.resolve_frequency(
        spec, getattr(query, "frequency", None)
    )
    request = {
        "path": freq_spec["path"],
        "api_key": api_key,
        "frequency": frequency,
        "data_columns": catalog.resolve_data_columns(
            spec, getattr(query, "data_type", None)
        ),
        "facets": catalog.resolve_facets(
            spec,
            frequency,
            query.facet_values,
            choices=catalog.get_group(query.__group__)["choices"],
        ),
        "facet_params": {
            detail["id"]: canonical for canonical, detail in spec["facets"].items()
        },
        "coverage": (spec.get("start_period"), spec.get("end_period")),
        "start": (
            catalog.format_period(query.start_date, freq_spec["format"])
            if query.start_date
            else None
        ),
        "end": (
            catalog.format_period(query.end_date, freq_spec["format"])
            if query.end_date
            else None
        ),
        "sort": query.sort,
    }
    return await paginate(
        build_data_url,
        request,
        limit=query.limit,
        amake_request=amake_request,
        amake_requests=amake_requests,
        response_callback=response_callback,
    )


def transform_dataset_data(
    data_cls: type[D],
    query: EiaApiQueryParams,
    data: dict,
) -> list[D]:
    """Normalize column names, parse periods, sort, and validate the rows.

    Parameters
    ----------
    data_cls : type[D]
        The dataset's data model.
    query : EiaApiQueryParams
        The validated query.
    data : dict
        Extraction result with 'rows' and 'date_format' keys.

    Returns
    -------
    list[D]
        The validated data rows.
    """
    from openbb_us_eia.utils import catalog

    spec = catalog.get_dataset(query.__group__, query.dataset_key)
    _, freq_spec = catalog.resolve_frequency(spec, getattr(query, "frequency", None))
    date_format = data.get("date_format") or freq_spec["format"]
    rows = transform_rows(spec, data["rows"], date_format)
    rows.sort(key=lambda row: row["date"], reverse=query.sort == "desc")
    if query.limit is not None:
        rows = rows[: query.limit]
    return [data_cls(**row) for row in rows]


async def paginate(
    build_url,
    request: dict,
    limit: int | None,
    amake_request,
    amake_requests,
    response_callback,
) -> dict:
    """Fetch every page of an EIA data request.

    Parameters
    ----------
    build_url : Callable
        Renders a request dict plus offset/length into a URL.
    request : dict
        The prepared request description.
    limit : int | None
        Maximum number of rows to fetch; None fetches all rows.
    amake_request, amake_requests : Callable
        Async HTTP helpers, injected for testability.
    response_callback : Callable
        Response callback converting an aiohttp response to JSON.

    Returns
    -------
    dict
        Mapping with 'rows', 'total', and 'date_format' keys.
    """
    from warnings import warn

    from openbb_core.provider.utils.errors import EmptyDataError

    first_length = PAGE_SIZE if limit is None else min(limit, PAGE_SIZE)
    url = build_url(request, offset=0, length=first_length)
    response = await amake_request(url, response_callback=response_callback)
    payload = response.get("response", {})  # type: ignore[union-attr]
    rows = list(payload.get("data", []))
    total = int(payload.get("total") or 0)
    date_format = payload.get("dateFormat")

    if total == 0 or not rows:
        raise EmptyDataError(
            await empty_result_message(request, amake_request, response_callback)
        )

    target = total if limit is None else min(limit, total)
    if limit is None and total > MAX_AUTO_ROWS:
        # Too many rows to page through: serve the newest page instead of failing.
        if request.get("sort", "desc") != "desc":
            url = build_url({**request, "sort": "desc"}, offset=0, length=PAGE_SIZE)
            response = await amake_request(url, response_callback=response_callback)
            rows = list(response.get("response", {}).get("data", []))  # type: ignore[union-attr]
        target = len(rows)
        warn(
            f"The unfiltered request matches {total} rows, above the automatic"
            f" pagination ceiling of {MAX_AUTO_ROWS}. Returning the newest {target}"
            " rows. Narrow the request with facet filters or dates, or set an"
            " explicit limit, to get more."
        )

    if len(rows) < target:
        urls = [
            build_url(request, offset=offset, length=min(PAGE_SIZE, target - offset))
            for offset in range(len(rows), target, PAGE_SIZE)
        ]
        pages = await amake_requests(urls, response_callback=response_callback)
        for page in pages:
            rows.extend(page.get("response", {}).get("data", []))

    return {"rows": rows[:target], "total": total, "date_format": date_format}


async def empty_result_message(
    request: dict,
    amake_request,
    response_callback,
) -> str:
    """Explain an empty result by checking each filter against the live vocabulary.

    Parameters
    ----------
    request : dict
        The prepared request description, including 'facets', 'facet_params',
        and 'coverage'.
    amake_request : Callable
        Async HTTP helper, injected for testability.
    response_callback : Callable
        Response callback converting an aiohttp response to JSON.

    Returns
    -------
    str
        A human-readable explanation of the empty result.
    """
    from openbb_us_eia.utils.catalog import format_choice_list

    facet_params = request.get("facet_params") or {}
    facets = request.get("facets") or {}
    date_hint = ""
    if request.get("start") or request.get("end"):
        coverage = request.get("coverage") or (None, None)
        requested = f"{request.get('start') or '...'} to {request.get('end') or '...'}"
        date_hint = f"\nRequested period: {requested}."
        if coverage[0] or coverage[1]:
            date_hint += f" The dataset covers {coverage[0]} to {coverage[1]}."

    if not facets:
        return f"The request returned no data.{date_hint}"

    invalid_lines: list[str] = []
    valid_lines: list[str] = []
    for facet_id, values in facets.items():
        name = facet_params.get(facet_id, facet_id)
        try:
            response = await amake_request(
                f"{API_BASE}/{request['path']}/facet/{facet_id}"
                f"?api_key={request['api_key']}",
                response_callback=response_callback,
            )
            entries = response.get("response", {}).get("facets", [])
        except Exception:  # noqa: BLE001
            valid_lines.append(f"  {name}: {', '.join(values)}")
            continue
        vocabulary = {
            str(entry.get("id")): str(entry.get("name") or entry.get("id"))
            for entry in entries
        }
        invalid = [value for value in values if value not in vocabulary]
        if invalid:
            invalid_lines.append(
                f"  {name}: {', '.join(invalid)} is not valid for this dataset."
                f" Valid {name} choices:\n" + format_choice_list(vocabulary, name)
            )
        else:
            labeled = ", ".join(f"{value} ({vocabulary[value]})" for value in values)
            valid_lines.append(f"  {name}: {labeled}")

    if invalid_lines:
        return "\n".join(
            [
                "The request returned no data because of invalid filter value(s):",
                *invalid_lines,
            ]
        )
    return "\n".join(
        [
            "The request returned no data. Each filter value is valid for this"
            " dataset, but the combination does not match any series:",
            *valid_lines,
            "Remove or change one of the filters." + date_hint,
        ]
    )


def transform_rows(
    spec: dict[str, Any],
    rows: list[dict],
    date_format: str,
) -> list[dict]:
    """Normalize raw API rows for one dataset.

    Parameters
    ----------
    spec : dict[str, Any]
        Dataset specification from the catalog.
    rows : list[dict]
        Raw rows from the API response.
    date_format : str
        The EIA period format of the rows.

    Returns
    -------
    list[dict]
        Normalized rows.
    """
    from openbb_us_eia.utils.catalog import parse_period

    facet_renames: dict[str, str] = {}
    for canonical, facet in spec["facets"].items():
        facet_id = facet["id"]
        facet_renames[facet_id] = canonical
        base = re.sub(r"(?i)id$", "", facet_id)
        for companion in (
            *FACET_NAME_COLUMNS.get(facet_id, ()),
            f"{facet_id}Description",
            f"{facet_id}-name",
            f"{facet_id}-description",
            f"{base}Description",
            f"{base}Name",
            f"{base}-name",
        ):
            facet_renames[companion] = f"{canonical}_name"

    column_renames: dict[str, str] = {}
    numeric_columns: set[str] = set()
    dropped_columns: set[str] = set()
    for snake_name, detail in spec["data_columns"].items():
        column_renames[detail["id"]] = snake_name
        dropped_columns.add(f"{detail['id']}-units")
        if detail.get("numeric", True):
            numeric_columns.add(snake_name)

    out: list[dict] = []
    for row in rows:
        record: dict[str, Any] = {"date": parse_period(str(row["period"]), date_format)}
        for key, value in row.items():
            if key == "period" or key in dropped_columns:
                continue
            name = facet_renames.get(key) or column_renames.get(key) or _snake(key)
            record[name] = to_float(value) if name in numeric_columns else value
        out.append(record)
    return out


def to_float(value: Any) -> float | None:
    """Cast a measurement to float; withheld or flag values become null."""
    if value is None or isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def maybe_float(value: Any) -> Any:
    """Cast a string to float when possible, passing other values through."""
    if not isinstance(value, str):
        return value
    try:
        return float(value)
    except ValueError:
        return value
