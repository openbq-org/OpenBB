"""Shared handling for the release-table shaped datasets."""

import json
from datetime import UTC
from functools import lru_cache
from pathlib import Path
from typing import Any

INDENT = "\u00a0\u00a0\u00a0\u00a0"

FREQUENCY_NAMES = {
    "annual": "Annual",
    "quarterly": "Quarterly",
    "monthly": "Monthly",
    "weekly": "Weekly",
    "daily": "Daily",
}

TREND = 36

PAGE = 1000
MAX_SERIES = 10000
MAX_DEPTH = 2
MAX_NODES = 64
TRIES = 4

DISCONTINUED = "(DISCONTINUED)"
QUALIFIER = " in "
LEAD_WORDS = 2

JOINERS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "by",
        "for",
        "from",
        "in",
        "less",
        "of",
        "or",
        "the",
        "to",
        "with",
    }
)

STALE_DAYS = {
    "Annual": 1095,
    "Quarterly": 730,
    "Monthly": 548,
    "Weekly": 365,
    "Daily": 365,
}
DEFAULT_STALE_DAYS = 730

VISIBLE = ("date", "symbol", "name", "units", "value")
HIDDEN = ("element_type", "element_id", "parent_id", "children", "level", "line")


def shown(field: str) -> dict[str, Any]:
    """Return the schema extra placing one column in the reading order."""
    return {"x-widget_config": {"headerIndex": VISIBLE.index(field)}}


def tree() -> dict[str, Any]:
    """Return the schema extra for the parent and child identifier columns.

    Returns
    -------
    dict
        The ``json_schema_extra`` for a hidden identifier column.
    """
    return {
        "x-widget_config": {
            "hide": True,
            "cellDataType": "text",
            "formatterFn": "none",
        }
    }


async def release_series(release_id: str | int, credentials: dict | None) -> list[dict]:
    """Read every series a release publishes.

    Parameters
    ----------
    release_id : str or int
        The FRED release id.
    credentials : dict or None
        The provider credentials.

    Returns
    -------
    list[dict]
        One entry per series, as the search returns it.
    """
    import asyncio

    from openbb_fred.models.search import FredSearchData, FredSearchFetcher

    found: list[dict] = []
    offset = 0

    while offset < MAX_SERIES:
        page: list = []

        for attempt in range(TRIES):
            try:
                page = list(
                    await FredSearchFetcher.fetch_data(
                        {"release_id": int(release_id), "offset": offset}, credentials
                    )
                )
                break
            except Exception:  # noqa: BLE001
                if attempt == TRIES - 1:
                    return found

                await asyncio.sleep(2**attempt)

        rows = [d.model_dump() for d in page if isinstance(d, FredSearchData)]
        found.extend(rows)

        if len(rows) < PAGE:
            break

        offset += PAGE

    return found


def last_observed(series: dict) -> str | None:
    """Return the date a series was last published for.

    Parameters
    ----------
    series : dict
        One series, as the search or the observations endpoint returns it.

    Returns
    -------
    str or None
        The last date the series is published for.
    """
    end = series.get("observation_end")

    if end:
        return str(end)[:10]

    dated = [
        o["date"]
        for o in series.get("observations") or []
        if o.get("value") not in (".", "", None)
    ]

    return max(dated)[:10] if dated else None


def current(series: dict) -> bool:
    """Return whether a series is still being published.

    Parameters
    ----------
    series : dict
        One series, as the search or the observations endpoint returns it.

    Returns
    -------
    bool
        Whether the series is still current.
    """
    from datetime import datetime, timedelta

    if DISCONTINUED in (series.get("title") or "").upper():
        return False

    observed = last_observed(series)

    if observed is None:
        return True

    from dateutil import parser

    stale = STALE_DAYS.get(series.get("frequency") or "", DEFAULT_STALE_DAYS)

    return parser.parse(observed).replace(tzinfo=UTC) >= datetime.now(
        UTC
    ) - timedelta(days=stale)


async def get_units(release_id: str | int, credentials: dict | None) -> dict:
    """Read the unit of measure each series in a release is published in.

    Parameters
    ----------
    release_id : str or int
        The FRED release id.
    credentials : dict or None
        The provider credentials.

    Returns
    -------
    dict
        The unit of measure, keyed by series id.
    """
    return {
        row["series_id"]: row["units"]
        for row in await release_series(release_id, credentials)
        if row.get("series_id") and row.get("units")
    }


RELEASE_MAP = Path(__file__).resolve().parent.parent / "assets" / "release_map.json"


@lru_cache(maxsize=1)
def release_map() -> dict:
    """Return the packaged map of releases and the tables under each.

    Returns
    -------
    dict
        Each release id mapped to its name and its element tree.
    """
    try:
        return json.loads(RELEASE_MAP.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def list_releases() -> list[dict]:
    """Return every release the map carries, as label and value pairs.

    Returns
    -------
    list[dict]
        The release name and id pairs, ordered by name.
    """
    published = {rid: entry["name"] for rid, entry in release_map().items()}

    return [
        {"label": f"{name} ({rid})", "value": rid}
        for rid, name in sorted(published.items(), key=lambda pair: pair[1])
    ]


def shared_prefix(names: "list[str]") -> str:
    """Return the lead every name in a release repeats, at a clean boundary.

    Parameters
    ----------
    names : list[str]
        The table names published by one release.

    Returns
    -------
    str
        The repeated lead, ending at a separator, or an empty string.
    """
    if len(names) < 2:
        return ""

    first, last = min(names), max(names)
    shared = ""

    for index, character in enumerate(first):
        if index >= len(last) or last[index] != character:
            break

        shared += character

    cut = max(shared.rfind(", "), shared.rfind(": "), shared.rfind(" - "))

    return shared[: cut + 2] if cut > 0 else ""


def common_lead(names: "list[str]") -> str:
    """Return the lead every name repeats, cut at a word boundary.

    Parameters
    ----------
    names : list[str]
        The series titles being listed together.

    Returns
    -------
    str
        The repeated lead, ending at a space, or an empty string.
    """
    if len(names) < 2:
        return ""

    first, last = min(names), max(names)
    shared = ""

    for index, character in enumerate(first):
        if index >= len(last) or last[index] != character:
            break

        shared += character

    cut = shared.rfind(" ")

    return shared[: cut + 1] if cut > 0 else ""


def period_of(date: str, interval: str | None) -> str:
    """Return the period one observation date falls in.

    Parameters
    ----------
    date : str
        The observation date.
    interval : str or None
        The interval the table is presented at.

    Returns
    -------
    str
        The period the date falls in.
    """
    year, month, _ = date.split("-")

    if interval == "Annual":
        return year

    if interval == "Quarterly":
        return f"{year}Q{(int(month) - 1) // 3 + 1}"

    if interval == "Monthly":
        return f"{year}-{month}"

    return date


def align(values: dict, interval: str | None) -> tuple[list[str], dict]:
    """Read every series onto one set of period columns.

    Parameters
    ----------
    values : dict
        The observed values of each series, keyed by date.
    interval : str or None
        The interval the table is presented at.

    The column is dated rather than named for its period, because the grid is
    given no definition for a column it did not know about and reads a bare
    year as a number to be ordered by.

    Returns
    -------
    tuple[list[str], dict]
        The columns, newest first, and each series read onto them.
    """
    held: dict[str, dict[str, float]] = {}
    dated: dict[str, dict[str, int]] = {}

    for series_id, observed in values.items():
        onto: dict[str, float] = {}

        for date in sorted(observed):
            period = period_of(date, interval)
            onto[period] = observed[date]
            dated.setdefault(period, {})
            dated[period][date] = dated[period].get(date, 0) + 1

        held[series_id] = onto

    labels = {
        period: max(dates, key=lambda date: (dates[date], date))
        for period, dates in dated.items()
    }
    axis = sorted(labels, key=lambda period: labels[period], reverse=True)

    return [labels[period] for period in axis], {
        series_id: {labels[period]: value for period, value in onto.items()}
        for series_id, onto in held.items()
    }


def _nest(lines: list[dict]) -> list[dict]:
    """Read the flat lines back into the tree their levels describe."""
    root: list[dict] = []
    stack: list[tuple[int, list[dict]]] = [(0, root)]

    for line in lines:
        while len(stack) > 1 and stack[-1][0] >= int(line["level"]):
            stack.pop()

        node = {"line": line, "under": []}
        stack[-1][1].append(node)
        stack.append((int(line["level"]), node["under"]))

    return root


def _flatten(nodes: list[dict], level: int, out: list[dict]) -> None:
    """Write the tree back out as lines, levelled by their depth."""
    for node in nodes:
        node["line"]["level"] = level
        out.append(node["line"])
        _flatten(node["under"], level + 1, out)


def _split(nodes: list[dict]) -> list[dict]:
    """Group the lines naming the same thing in different places."""
    keyed: dict[str, list[dict]] = {}

    for node in nodes:
        name = str(node["line"]["name"])

        if QUALIFIER not in name or node["under"]:
            return nodes

        keyed.setdefault(name.rsplit(QUALIFIER, 1)[0], []).append(node)

    if len(keyed) < 2 or all(len(shared) < 2 for shared in keyed.values()):
        return nodes

    grouped: list[dict] = []

    for measure, shared in keyed.items():
        if len(shared) < 2:
            grouped.extend(shared)
            continue

        for node in shared:
            name = str(node["line"]["name"])
            node["line"]["name"] = name.rsplit(QUALIFIER, 1)[1]

        grouped.append(
            {
                "line": {
                    "series_id": None,
                    "name": measure,
                    "level": 0,
                    "table": shared[0]["line"].get("table", ""),
                },
                "under": shared,
            }
        )

    return grouped


def concept(titles: "list[str]") -> str:
    """Return what a set of series are all a measure of.

    Parameters
    ----------
    titles : list[str]
        The titles of the series being read together.

    Returns
    -------
    str
        The measure they share, or an empty string.
    """
    if not titles:
        return ""

    if len(titles) == 1:
        cut = min(
            (
                found
                for found in (titles[0].find(mark) for mark in (" - ", ": ", ", "))
                if found > 0
            ),
            default=-1,
        )

        return titles[0][:cut] if cut > 0 else ""

    first, last = min(titles), max(titles)
    shared = ""

    for index, character in enumerate(first):
        if index >= len(last) or last[index] != character:
            break

        shared += character

    if shared in titles:
        return shared

    cut = max(shared.rfind(" - "), shared.rfind(": "), shared.rfind(", "))

    if cut > 0:
        return shared[:cut]

    cut = shared.rfind(" ")

    return shared[:cut] if cut > 0 else ""


def _titles(node: dict, titles: dict) -> list[str]:
    """Read every series title under one line."""
    found = []
    series_id = node["line"].get("series_id")

    if series_id and series_id in titles:
        found.append(titles[series_id])

    for child in node["under"]:
        found.extend(_titles(child, titles))

    return found


def _name(nodes: list[dict], titles: dict, inherited: str) -> list[dict]:
    """Head each run of lines with what it is a measure of."""
    measured = [concept(_titles(node, titles)) for node in nodes]

    for index, measure in enumerate(measured):
        if measure:
            continue

        held = _titles(nodes[index], titles)
        near = [m for m in measured[index - 1 :: -1] if m] if index else []
        near += [m for m in measured[index + 1 :] if m]
        measured[index] = next(
            (m for m in near if any(title.startswith(m) for title in held)), ""
        )

    marked = [
        (node, measure or inherited)
        for node, measure in zip(nodes, measured, strict=True)
    ]
    named = {name for _, name in marked}

    if len(named) < 2 or named <= {"", inherited}:
        return nodes

    grouped: list[dict] = []
    run: list[dict] = []
    running = ""

    def close() -> None:
        if not run:
            return

        if running in ("", inherited) or len(run) < 2:
            grouped.extend(run)
            return

        grouped.append(
            {
                "line": {
                    "series_id": None,
                    "name": running,
                    "level": 0,
                    "table": run[0]["line"].get("table", ""),
                },
                "under": list(run),
            }
        )

    for node, name in marked:
        if name != running:
            close()
            run, running = [], name

        run.append(node)

    close()

    return grouped


def _regroup(nodes: list[dict], titles: dict, inherited: str) -> list[dict]:
    """Name each group of lines by what tells its members apart."""
    lead = common_lead([str(node["line"]["name"]) for node in nodes])

    if lead.strip().count(" ") >= LEAD_WORDS:
        for node in nodes:
            node["line"]["name"] = str(node["line"]["name"])[len(lead) :]

    nodes = _name(_split(nodes), titles, inherited)

    for node in nodes:
        if node["under"]:
            node["under"] = _regroup(
                node["under"],
                titles,
                concept(_titles(node, titles)) or inherited,
            )

    return nodes


def regroup(lines: list[dict], titles: dict | None = None) -> list[dict]:
    """Say what each group of lines is, and drop what they all repeat.

    Parameters
    ----------
    lines : list[dict]
        The published lines, in order, each carrying its level.
    titles : dict or None
        The title of each series, keyed by id.

    Returns
    -------
    list[dict]
        The lines, each named by what tells it apart from its siblings.
    """
    out: list[dict] = []
    _flatten(_regroup(_nest(lines), titles or {}, ""), 1, out)

    return out


def hierarchy(labelled: "list[tuple[str, str]]") -> list[dict]:
    """Arrange series into the tree their names describe.

    Parameters
    ----------
    labelled : list[tuple[str, str]]
        Each series id with the name it is listed under.

    Returns
    -------
    list[dict]
        One entry per line, headings included, as a table publishes them.
    """

    def branch(items: "list[tuple[str, list[str]]]", level: int) -> list[dict]:
        lines: list[dict] = []
        groups: dict[str, list[tuple[str, list[str]]]] = {}

        for series_id, words in items:
            groups.setdefault(words[0], []).append((series_id, words[1:]))

        for head in sorted(groups):
            members = groups[head]

            if head.lower() in JOINERS:
                for only, rest in members:
                    lines.append(
                        {
                            "series_id": only,
                            "name": " ".join([head, *rest]),
                            "level": level,
                        }
                    )

                continue

            if len(members) == 1:
                only, rest = members[0]
                lines.append(
                    {
                        "series_id": only,
                        "name": " ".join([head, *rest]),
                        "level": level,
                    }
                )
                continue

            shared = [head]

            while (
                all(rest for _, rest in members)
                and len({rest[0] for _, rest in members}) == 1
            ):
                shared.append(members[0][1][0])
                members = [(series_id, rest[1:]) for series_id, rest in members]

            named = [member for member in members if not member[1]]
            deeper = [member for member in members if member[1]]
            lines.append(
                {
                    "series_id": named[0][0] if named else None,
                    "name": " ".join(shared),
                    "level": level,
                }
            )

            for extra in named[1:]:
                lines.append(
                    {
                        "series_id": extra[0],
                        "name": " ".join(shared),
                        "level": level,
                    }
                )

            if deeper:
                lines.extend(branch(deeper, level + 1))

        return lines

    return branch(
        [
            (series_id, words)
            for series_id, label in labelled
            if (words := [word.rstrip(":;") for word in label.split()])
        ],
        1,
    )


def list_elements(release_id: str) -> list[dict]:
    """Return the tables published under one release, as label and value pairs.

    Parameters
    ----------
    release_id : str
        The FRED release id.

    Returns
    -------
    list[dict]
        The element name and id pairs, indented by depth.
    """
    release = release_map().get(str(release_id))

    if release is None:
        return []

    tables = [
        element
        for element in release.get("elements") or []
        if element.get("type", "table") == "table"
    ]

    if not tables:
        return [{"label": "All Series", "value": ""}]

    lead = shared_prefix([element["name"] for element in tables])

    return [
        {
            "label": "— " * element["depth"]
            + (element["name"][len(lead) :] if lead else element["name"]),
            "value": element["element_id"],
        }
        for element in tables
    ]


def resolve_element(release_id: str, element_id: str | None) -> str | None:
    """Return the table to present, when the one asked for is not on offer.

    Parameters
    ----------
    release_id : str
        The FRED release id.
    element_id : str or None
        The table the picker is holding.

    Returns
    -------
    str or None
        The table to present, or None when the release publishes none.
    """
    offered = [element["value"] for element in list_elements(release_id)]

    if element_id and element_id in offered:
        return element_id

    return offered[0] if offered else None


async def list_frequencies(
    release_id: str,
    element_id: str | None,
    credentials: dict | None,
) -> list[dict]:
    """Return the publication frequencies present in one table.

    Parameters
    ----------
    release_id : str
        The FRED release id.
    element_id : str or None
        The table within the release, or None for the release whole.
    credentials : dict or None
        The provider credentials.

    Returns
    -------
    list[dict]
        The frequency label and value pairs the table actually carries.
    """
    import asyncio

    from openbb_fred.utils.v2 import release_observations

    api_key = (credentials or {}).get("fred_api_key") or ""

    try:
        observations, lines = await asyncio.gather(
            release_observations(release_id, api_key),
            table_lines(release_id, element_id, api_key),
        )
    except Exception:  # noqa: BLE001
        return []

    _, series = observations
    listed = (
        [line["series_id"] for line in lines if line["series_id"]]
        if lines
        else list(series)
    )

    return [
        {"label": FREQUENCY_NAMES[value], "value": value}
        for value in frequencies(series, listed)
    ]


def frequencies(series: dict, listed: "list[str]") -> list[str]:
    """Return the frequencies a set of series is published at.

    Parameters
    ----------
    series : dict
        Every series on the release, keyed by id.
    listed : list[str]
        The series the table is built from.

    Returns
    -------
    list[str]
        The frequencies present, the dominant one first.
    """
    counted: dict[str, int] = {}

    for series_id in listed:
        entry = series.get(series_id)

        if not entry or not current(entry):
            continue

        for value, name in FREQUENCY_NAMES.items():
            if entry.get("frequency") == name:
                counted[value] = counted.get(value, 0) + 1

    order = list(FREQUENCY_NAMES)

    return sorted(counted, key=lambda value: (-counted[value], -order.index(value)))


async def table_lines(
    release_id: str,
    element_id: str | None,
    api_key: str | None,
    use_cache: bool = True,
) -> list[dict]:
    """Read the published order and indentation of one table.

    Parameters
    ----------
    release_id : str
        The FRED release id.
    element_id : str or None
        The table within the release. Nothing is read without one.
    api_key : str or None
        The FRED API key.
    use_cache : bool
        Whether to read and write the on-disk cache.

    Returns
    -------
    list[dict]
        One entry per line, in publication order. A line without a series id
        is a heading the lines below it are read under.
    """
    if not element_id:
        return []

    from openbb_fred.utils.api import release_tables_url
    from openbb_fred.utils.rate_limiter import fred_get

    lines: list[dict] = []
    read: set[str] = set()

    async def node(eid: str, base: int) -> None:
        if eid in read or len(read) >= MAX_NODES:
            return

        read.add(eid)
        url = release_tables_url(release_id, eid, api_key)

        try:
            payload = await fred_get(url, use_cache=use_cache) or {}
        except Exception:  # noqa: BLE001
            return

        table = payload.get("name") or ""

        for element in (payload.get("elements") or {}).values():
            if not element:
                continue

            level = base + int(element.get("level") or 1)
            line = {
                "series_id": element.get("series_id"),
                "name": element.get("name") or element.get("series_id") or "",
                "level": level,
                "table": table,
            }

            if element.get("series_id") or element.get("children"):
                lines.append(line)
                continue

            lines.append(line)
            await node(str(element["element_id"]), level)

    await node(str(element_id), 0)

    return lines


def indent_of(label: str) -> int:
    """Return how many levels of indentation a rendered label carries."""
    depth = 0

    while label.startswith(INDENT):
        label = label[len(INDENT) :]
        depth += 1

    return depth


def drop_empty_headings(rows: list[dict]) -> list[dict]:
    """Drop the headings left with nothing under them.

    Parameters
    ----------
    rows : list[dict]
        The rendered rows, headings included.

    Returns
    -------
    list[dict]
        The rows with every empty heading removed.
    """
    kept: list[dict] = []

    for index, row in enumerate(rows):
        if row["symbol"]:
            kept.append(row)
            continue

        depth = indent_of(row["series"])
        under = False

        for following in rows[index + 1 :]:
            if indent_of(following["series"]) <= depth:
                break

            if following["symbol"]:
                under = True
                break

        if under:
            kept.append(row)

    return kept


def distinguish(rows: list[dict], apart: dict | None = None) -> list[dict]:
    """Name apart the lines the hierarchy cannot tell apart.

    Parameters
    ----------
    rows : list[dict]
        The rendered rows, headings included.
    apart : dict or None
        What each series is published as, in the order it should be tried.

    Returns
    -------
    list[dict]
        The rows, each series named distinctly from every other.
    """
    published = apart or {}
    above: dict[int, str] = {}
    placed: dict[tuple, list[dict]] = {}

    for row in rows:
        depth = indent_of(row["series"])
        label = row["series"][len(INDENT) * depth :]
        path = tuple(above[level] for level in sorted(above) if level < depth)
        above = {level: name for level, name in above.items() if level < depth}
        above[depth] = label

        if row["symbol"]:
            placed.setdefault((*path, label), []).append(row)

    for shared in placed.values():
        if len(shared) < 2:
            continue

        told = [published.get(row["symbol"]) or [] for row in shared]
        which = next(
            (
                index
                for index in range(max((len(one) for one in told), default=0))
                if len({str(one[index]) for one in told if index < len(one)})
                == len(shared)
            ),
            None,
        )

        for row, carried in zip(shared, told, strict=True):
            depth = indent_of(row["series"])
            label = row["series"][len(INDENT) * depth :]
            name = carried[which] if which is not None else row["symbol"]
            row["series"] = INDENT * depth + f"{label} ({name})"

    return rows


async def build_release_table(
    release_id: str,
    element_id: str | None,
    frequency: str,
    limit: int,
    api_key: str | None,
    *,
    use_cache: bool = True,
) -> list[dict]:
    """Build one release table as the rows a grid renders directly.

    Parameters
    ----------
    release_id : str
        The FRED release id.
    element_id : str or None
        The table within the release.
    frequency : str
        The publication frequency to keep, or 'all'.
    limit : int
        How many periods to present.
    api_key : str or None
        The FRED API key.
    use_cache : bool
        Whether to read and write the on-disk cache.

    Returns
    -------
    list[dict]
        One row per line, each keyed in the order the columns read.
    """
    import asyncio

    from openbb_fred.utils.v2 import published, release_observations

    observations, lines = await asyncio.gather(
        release_observations(release_id, api_key, use_cache=use_cache),
        table_lines(release_id, element_id, api_key, use_cache=use_cache),
    )
    _, series = observations
    live = {series_id for series_id, entry in series.items() if current(entry)}
    present = frequencies(
        series,
        [line["series_id"] for line in lines if line["series_id"]]
        if lines
        else list(series),
    )
    wanted = FREQUENCY_NAMES.get(
        frequency if frequency in present else (present[0] if present else "")
    )
    if lines:
        order = regroup(
            lines,
            {
                series_id: entry.get("title") or ""
                for series_id, entry in series.items()
            },
        )
    else:
        listed = sorted(
            (s for s in series if s in live), key=lambda s: series[s].get("title") or s
        )
        lead = common_lead([series[s].get("title") or s for s in listed])
        order = hierarchy(
            [
                (
                    series_id,
                    (series[series_id].get("title") or series_id)[len(lead) :]
                    or series_id,
                )
                for series_id in listed
            ]
        )
    values = {
        line["series_id"]: published(
            series[line["series_id"]].get("observations") or []
        )
        for line in order
        if line["series_id"] in live
        and (not wanted or series[line["series_id"]].get("frequency") == wanted)
    }
    axis, aligned = align(values, wanted)
    periods = axis[:limit]
    rows: list[dict] = []

    for line in order:
        series_id = str(line["series_id"] or "")
        depth = max(int(line["level"]) - 1, 0)

        if not series_id:
            heading: dict = {
                "series": INDENT * depth + str(line["name"]),
                "symbol": None,
                "units": None,
                "trend": None,
            }
            heading.update({date: None for date in periods})
            rows.append(heading)
            continue

        observed = aligned.get(series_id)

        if not observed or not any(date in observed for date in periods):
            continue

        entry = series[series_id]
        history = [values[series_id][date] for date in sorted(values[series_id])][
            -TREND:
        ]
        row: dict = {
            "series": INDENT * depth
            + str(line["name"] or entry.get("title") or series_id),
            "symbol": series_id,
            "units": entry.get("units"),
            "trend": history,
        }

        for date in periods:
            row[date] = observed.get(date)

        rows.append(row)

    return distinguish(
        drop_empty_headings(rows),
        {
            series_id: [entry.get("units"), entry.get("seasonal_adjustment")]
            for series_id, entry in series.items()
        },
    )
