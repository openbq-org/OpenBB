"""USDA ERS Tableau Public visualization catalog."""

import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

CATALOG_FILE = Path(__file__).parent.parent / "assets" / "ers_viz_catalog.json"
PROFILE_API = (
    "https://public.tableau.com/public/apis/workbooks"
    "?profileName=economic.research.service&start={start}&count=50"
    "&visibility=NON_HIDDEN"
)


@lru_cache(maxsize=1)
def load_catalog() -> tuple[dict, ...]:
    """Load the packaged ERS visualization catalog.

    Returns
    -------
    tuple[dict, ...]
        Catalog entries with title, workbook, default_view, description,
        and last_updated keys, sorted by title.
    """
    with CATALOG_FILE.open(encoding="utf-8") as file:
        return tuple(json.load(file))


@lru_cache(maxsize=1)
def viz_paths() -> dict[str, dict]:
    """Map each catalog entry's 'workbook/default_view' path to its entry."""
    return {
        f"{entry['workbook']}/{entry['default_view']}": entry
        for entry in load_catalog()
    }


async def fetch_catalog() -> list[dict]:
    """Fetch the current workbook catalog from the Tableau Public profile API.

    Returns
    -------
    list[dict]
        Catalog entries in the packaged asset's schema, sorted by title.
    """
    from openbb_core.provider.utils.helpers import amake_request

    entries: list[dict] = []
    start = 0
    while True:
        response = await amake_request(PROFILE_API.format(start=start))
        workbooks = (
            response.get("contents", response.get("workbooks", []))
            if isinstance(response, dict)
            else response
        )
        for workbook in workbooks or []:
            repo_url = workbook.get("workbookRepoUrl", "")
            default_view = workbook.get("defaultViewRepoUrl", "").rpartition(
                "/sheets/"
            )[2]
            if not repo_url or not default_view:
                continue
            updated_ms = workbook.get("lastUpdateDate") or workbook.get(
                "lastPublishDate"
            )
            entries.append(
                {
                    "title": workbook.get("title", repo_url),
                    "workbook": repo_url,
                    "default_view": default_view,
                    "description": workbook.get("description")
                    or workbook.get("title", repo_url),
                    "last_updated": datetime.fromtimestamp(
                        updated_ms / 1000, tz=UTC
                    ).strftime("%Y-%m-%d")
                    if updated_ms
                    else None,
                }
            )
        next_index = response.get("nextIndex", -1) if isinstance(response, dict) else -1
        if next_index is None or int(next_index) < 0:
            break
        start = int(next_index)
    return sorted(entries, key=lambda entry: entry["title"])


def main() -> None:
    """Regenerate the packaged catalog asset from the live profile."""
    import asyncio

    entries = asyncio.run(fetch_catalog())
    CATALOG_FILE.write_text(json.dumps(entries, indent=1) + "\n", encoding="utf-8")
    print(f"Wrote {len(entries)} entries to {CATALOG_FILE}")  # noqa: T201


if __name__ == "__main__":
    main()
