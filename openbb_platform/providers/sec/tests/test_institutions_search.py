"""Unit tests for the SEC institutions search fetcher."""

import asyncio
from unittest.mock import patch

import pytest
from openbb_core.app.model.abstract.error import OpenBBError
from pandas import DataFrame

from openbb_sec.models.institutions_search import (
    SecInstitutionsSearchFetcher,
    SecInstitutionsSearchQueryParams,
)


async def _all_ciks(use_cache=True):
    return DataFrame(
        {"Institution": ["Alpha Bank", "Beta Trust"], "CIK Number": [1, 2]}
    )


def _extract(query):
    with patch("openbb_sec.utils.helpers.get_all_ciks", _all_ciks):
        return asyncio.run(
            SecInstitutionsSearchFetcher.aextract_data(
                SecInstitutionsSearchQueryParams(query=query), None
            )
        )


@pytest.mark.parametrize("blank", [None, ""])
def test_blank_query_asks_for_a_name(blank):
    """A blank search would return every filer, so it asks for a name."""
    with pytest.raises(OpenBBError, match="institution name"):
        _extract(blank)


def test_query_filters_by_name():
    """A name matches case-insensitively."""
    assert [r["Institution"] for r in _extract("beta")] == ["Beta Trust"]


def test_widget_marks_query_required():
    """The widget asks for a query instead of sending an empty one."""
    from openbb_core.api.rest_api import app

    path = app.openapi()["paths"]["/api/v1/sec/institutions_search"]
    query = next(p for p in path["get"]["parameters"] if p["name"] == "query")
    assert query["schema"]["sec"]["x-widget_config"] == {"optional": False}
