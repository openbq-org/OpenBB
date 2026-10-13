"""Tests for openbb_core.api.exception_handlers."""

import json
from datetime import date
from unittest.mock import MagicMock

import pytest
from fastapi.exceptions import ResponseValidationError
from pydantic import BaseModel, ValidationError

from openbb_core.api.exception_handlers import ExceptionHandlers
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.utils.errors import EmptyDataError, UnauthorizedError


def _make_request(query_params: dict | None = None) -> MagicMock:
    req = MagicMock()
    req.query_params = query_params or {}
    return req


@pytest.mark.asyncio
async def test_handle_returns_json_response_when_not_debug(monkeypatch):
    monkeypatch.setattr(
        "openbb_core.api.exception_handlers.Env", type("E", (), {"DEBUG_MODE": False})
    )
    resp = await ExceptionHandlers._handle(ValueError("boom"), 500, "boom")
    assert resp.status_code == 500
    assert json.loads(resp.body) == {"detail": "boom"}


@pytest.mark.asyncio
async def test_handle_reraises_in_debug_mode(monkeypatch):
    monkeypatch.setattr(
        "openbb_core.api.exception_handlers.Env", type("E", (), {"DEBUG_MODE": True})
    )
    with pytest.raises(ValueError, match="boom"):
        await ExceptionHandlers._handle(ValueError("boom"), 500, "boom")


@pytest.mark.asyncio
async def test_exception_handler_value_error(monkeypatch):
    monkeypatch.setattr(
        "openbb_core.api.exception_handlers.Env", type("E", (), {"DEBUG_MODE": False})
    )

    err = ValueError("bad")
    err.errors = err  # type: ignore[attr-defined]
    resp = await ExceptionHandlers.exception(_make_request(), err)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_exception_handler_unknown_falls_back_to_500(monkeypatch):
    monkeypatch.setattr(
        "openbb_core.api.exception_handlers.Env", type("E", (), {"DEBUG_MODE": False})
    )

    class Boom(Exception):
        pass

    resp = await ExceptionHandlers.exception(_make_request(), Boom("oops"))
    assert resp.status_code == 500
    body = json.loads(resp.body)
    assert "Boom" in body["detail"]


@pytest.mark.asyncio
async def test_exception_handler_iterable_missing(monkeypatch):
    monkeypatch.setattr(
        "openbb_core.api.exception_handlers.Env", type("E", (), {"DEBUG_MODE": False})
    )

    class HasErrors(Exception):
        title = "EquityQuoteQueryParams"
        errors = [{"type": "missing", "loc": ("symbol",)}]

    resp = await ExceptionHandlers.exception(_make_request(), HasErrors())
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_exception_handler_missing_query_params_field_is_422(monkeypatch):
    """A required provider QueryParams field absent from the request is a 422."""
    monkeypatch.setattr(
        "openbb_core.api.exception_handlers.Env", type("E", (), {"DEBUG_MODE": False})
    )

    class ItemQueryParams(BaseModel):
        start_date: date
        code: str

    try:
        ItemQueryParams(start_date=date(2024, 1, 2))  # type: ignore[call-arg]
    except ValidationError as ve:
        err = ve

    # The input holds a date, so the detail must be JSON-encoded to serialize.
    resp = await ExceptionHandlers.exception(_make_request(), err)
    assert resp.status_code == 422
    detail = json.loads(resp.body)["detail"]
    assert (detail["type"], detail["loc"]) == ("missing", ["code"])
    assert detail["input"] == {"start_date": "2024-01-02"}


@pytest.mark.asyncio
async def test_exception_handler_missing_field_of_any_query_params_subclass_is_422(
    monkeypatch,
):
    """A QueryParams subclass whose name lacks "QueryParams" is still client input."""
    from openbb_core.provider.abstract.query_params import QueryParams

    monkeypatch.setattr(
        "openbb_core.api.exception_handlers.Env", type("E", (), {"DEBUG_MODE": False})
    )

    class BalanceQuery(QueryParams):
        symbol: str

    try:
        BalanceQuery()  # type: ignore[call-arg]
    except ValidationError as ve:
        err = ve

    resp = await ExceptionHandlers.exception(_make_request(), err)
    assert resp.status_code == 422
    assert json.loads(resp.body)["detail"]["type"] == "missing"


@pytest.mark.asyncio
async def test_exception_handler_missing_data_field_stays_500(monkeypatch):
    """A Data model missing a field is the upstream response's fault, not the client's."""
    monkeypatch.setattr(
        "openbb_core.api.exception_handlers.Env", type("E", (), {"DEBUG_MODE": False})
    )

    class ItemData(BaseModel):
        value: float

    try:
        ItemData()  # type: ignore[call-arg]
    except ValidationError as ve:
        err = ve

    resp = await ExceptionHandlers.exception(_make_request(), err)
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_exception_handler_timeout_is_504(monkeypatch):
    monkeypatch.setattr(
        "openbb_core.api.exception_handlers.Env", type("E", (), {"DEBUG_MODE": False})
    )
    resp = await ExceptionHandlers.exception(_make_request(), TimeoutError("slow"))
    assert (resp.status_code, json.loads(resp.body)["detail"]) == (504, "slow")

    resp = await ExceptionHandlers.exception(_make_request(), TimeoutError())
    assert resp.status_code == 504
    assert "did not respond in time" in json.loads(resp.body)["detail"]


@pytest.mark.asyncio
async def test_exception_handler_invalid_json_is_502(monkeypatch):
    monkeypatch.setattr(
        "openbb_core.api.exception_handlers.Env", type("E", (), {"DEBUG_MODE": False})
    )
    err = json.JSONDecodeError("Expecting value", "<html>blocked</html>", 0)
    resp = await ExceptionHandlers.exception(_make_request(), err)
    assert resp.status_code == 502
    assert json.loads(resp.body)["detail"] == (
        "The data source returned a response that is not valid JSON."
    )


@pytest.mark.asyncio
async def test_validation_handler_query_params_routed_to_query_loc(monkeypatch):
    monkeypatch.setattr(
        "openbb_core.api.exception_handlers.Env", type("E", (), {"DEBUG_MODE": False})
    )

    class MyQueryParams(BaseModel):
        symbol: str

    try:
        MyQueryParams()  # type: ignore[call-arg]
    except ValidationError as ve:
        err = ve

    req = _make_request({"symbol": ""})  # ensure all_in_query short-circuit works
    # Force `error.title` to contain "QueryParams"; pydantic provides title via model name.
    resp = await ExceptionHandlers.validation(req, err)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_validation_handler_response_validation_error(monkeypatch):
    monkeypatch.setattr(
        "openbb_core.api.exception_handlers.Env", type("E", (), {"DEBUG_MODE": False})
    )

    err = ResponseValidationError(
        [
            {
                "type": "value_error",
                "loc": ("body", "field"),
                "msg": "bad",
                "ctx": {"x": 1},
            }
        ],
        body={},
    )

    resp = await ExceptionHandlers.validation(_make_request(), err)
    assert resp.status_code == 422
    detail = json.loads(resp.body)["detail"]
    assert detail[0]["loc"] == ["query", "body", "field"]
    assert "ctx" not in detail[0]


@pytest.mark.asyncio
async def test_validation_handler_errors_fallback_when_include_url_raises(monkeypatch):
    monkeypatch.setattr(
        "openbb_core.api.exception_handlers.Env", type("E", (), {"DEBUG_MODE": False})
    )

    class BrokenValidationError(Exception):
        title = "NotQueryParams"

        def errors(self, include_url=False):
            raise RuntimeError("boom")

    err = BrokenValidationError("bad")
    err.errors = [{"type": "other", "loc": ("field",), "msg": "bad"}]  # type: ignore[assignment]

    resp = await ExceptionHandlers.validation(_make_request(), err)  # type: ignore[arg-type]
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_validation_handler_non_queryparams_falls_back_to_exception(monkeypatch):
    monkeypatch.setattr(
        "openbb_core.api.exception_handlers.Env", type("E", (), {"DEBUG_MODE": False})
    )

    class NonQueryValidationError(Exception):
        title = "SomeOtherModel"

        def errors(self, include_url=False):
            return [{"type": "value_error", "loc": ("field",), "msg": "bad"}]

    resp = await ExceptionHandlers.validation(
        _make_request({"other": "x"}),
        NonQueryValidationError("bad"),  # type: ignore[arg-type]
    )
    assert resp.status_code == 500


@pytest.mark.asyncio
async def test_openbb_handler(monkeypatch):
    monkeypatch.setattr(
        "openbb_core.api.exception_handlers.Env", type("E", (), {"DEBUG_MODE": False})
    )
    err = OpenBBError("bad input")
    resp = await ExceptionHandlers.openbb(_make_request(), err)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_empty_data_handler():
    resp = await ExceptionHandlers.empty_data(_make_request(), EmptyDataError("empty"))
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_unauthorized_handler(monkeypatch):
    monkeypatch.setattr(
        "openbb_core.api.exception_handlers.Env", type("E", (), {"DEBUG_MODE": False})
    )
    err = UnauthorizedError("nope")
    resp = await ExceptionHandlers.unauthorized(_make_request(), err)
    assert resp.status_code == 502
