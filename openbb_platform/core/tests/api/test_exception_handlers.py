"""Tests for openbb_core.api.exception_handlers."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.exceptions import ResponseValidationError
from pydantic import BaseModel, ValidationError

from openbb_core.api.exception_handlers import ExceptionHandlers
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.utils.errors import EmptyDataError, UnauthorizedError


def _make_request(query_params: dict | None = None, body: bytes = b"") -> MagicMock:
    req = MagicMock()
    req.query_params = query_params or {}
    req.body = AsyncMock(return_value=body)
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
        errors = [{"type": "missing", "loc": ("symbol",)}]

    resp = await ExceptionHandlers.exception(_make_request(), HasErrors())
    assert resp.status_code == 422


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

    req = _make_request({"symbol": ""})
    # Force `error.title` to contain "QueryParams"; pydantic provides title via model name.
    resp = await ExceptionHandlers.validation(req, err)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_validation_handler_missing_query_param_returns_422(monkeypatch):
    monkeypatch.setattr(
        "openbb_core.api.exception_handlers.Env", type("E", (), {"DEBUG_MODE": False})
    )

    class SearchQueryParams(BaseModel):
        category: str

    with pytest.raises(ValidationError) as exc_info:
        SearchQueryParams()  # type: ignore[call-arg]

    response = await ExceptionHandlers.validation(_make_request(), exc_info.value)

    assert response.status_code == 422
    detail = json.loads(response.body)["detail"]
    assert detail[0]["loc"] == ["query", "category"]


@pytest.mark.asyncio
async def test_validation_query_params_model_bound_to_body_is_not_query_scoped(
    monkeypatch,
):
    monkeypatch.setattr(
        "openbb_core.api.exception_handlers.Env", type("E", (), {"DEBUG_MODE": False})
    )

    class SearchQueryParams(BaseModel):
        category: str

    with pytest.raises(ValidationError) as exc_info:
        SearchQueryParams()  # type: ignore[call-arg]

    response = await ExceptionHandlers.validation(
        _make_request(body=b"{}"), exc_info.value
    )

    assert response.status_code == 500


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
