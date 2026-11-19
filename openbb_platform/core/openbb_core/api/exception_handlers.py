"""Exception handlers module."""

import logging
from collections.abc import Iterable
from typing import Any

from fastapi import Request
from fastapi.exceptions import ResponseValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.env import Env
from openbb_core.provider.utils.errors import EmptyDataError, UnauthorizedError

logger = logging.getLogger("uvicorn.error")


class ExceptionHandlers:
    """Exception handlers."""

    @staticmethod
    async def _handle(exception: Exception, status_code: int, detail: Any):
        """Exception handler."""
        if Env().DEBUG_MODE:
            raise exception
        logger.error(exception)
        return JSONResponse(
            status_code=status_code,
            content={
                "detail": detail,
            },
        )

    @staticmethod
    async def exception(_: Request, error: Exception) -> JSONResponse:
        """Exception handler for Base Exception."""
        errors = error.errors if hasattr(error, "errors") else error

        if errors:
            if isinstance(errors, ValueError):
                return await ExceptionHandlers._handle(
                    exception=errors,
                    status_code=422,
                    detail=errors.args,
                )
            # Required parameters are missing and is not handled by ValidationError.
            if isinstance(errors, Iterable):
                for err in errors:
                    if err.get("type") == "missing":
                        return await ExceptionHandlers._handle(
                            exception=error,
                            status_code=422,
                            detail={**err},
                        )
        return await ExceptionHandlers._handle(
            exception=error,
            status_code=500,
            detail=f"Unexpected Error -> {error.__class__.__name__} -> {error}",
        )

    @staticmethod
    async def validation(
        request: Request, error: ValidationError | ResponseValidationError
    ):
        """Exception handler for ValidationError."""
        # Some validation is performed at Fetcher level.
        # So we check if the validation error comes from a QueryParams class.
        # And that it is in the request query params.
        # If yes, we update the error location with query.
        # If not, we handle it as a base Exception error.
        query_params = dict(request.query_params)
        if isinstance(error, ResponseValidationError):
            detail = [
                {
                    **{k: v for k, v in err.items() if k != "ctx"},
                    "loc": ("query",) + err.get("loc", ()),
                }
                for err in error.errors()
            ]
            return await ExceptionHandlers._handle(
                exception=error,
                status_code=422,
                detail=detail,
            )
        try:
            errors = (
                error.errors(include_url=False)
                if hasattr(error, "errors")
                else error.errors
            )
        except Exception:
            errors = error.errors if hasattr(error, "errors") else error
        if "QueryParams" in error.title:
            detail = [
                {
                    **{k: v for k, v in err.items() if k != "ctx"},
                    "loc": (
                        ("query",) + err.get("loc", ())
                        if (
                            # Fetcher QueryParams validation reports absent
                            # fields without a transport source. Preserve an
                            # explicit source such as "body".
                            (
                                err.get("type") == "missing"
                                and len(err.get("loc", ())) == 1
                            )
                            or all(
                                loc in query_params
                                for loc in err.get("loc", ())
                            )
                        )
                        else err.get("loc", ())
                    ),
                }
                for err in errors  # ty: ignore[not-iterable]
            ]
            return await ExceptionHandlers._handle(
                exception=error,
                status_code=422,
                detail=detail,
            )
        return await ExceptionHandlers.exception(request, error)

    @staticmethod
    async def openbb(_: Request, error: OpenBBError):
        """Exception handler for OpenBBError."""
        return await ExceptionHandlers._handle(
            exception=error,
            status_code=400,
            detail=str(error.original),
        )

    @staticmethod
    async def empty_data(_: Request, error: EmptyDataError):
        """Exception handler for EmptyDataError."""
        return Response(status_code=204)

    @staticmethod
    async def unauthorized(_: Request, error: UnauthorizedError):
        """Exception handler for OpenBBError."""
        return await ExceptionHandlers._handle(
            exception=error,
            status_code=502,
            detail=str(error.original),
        )
