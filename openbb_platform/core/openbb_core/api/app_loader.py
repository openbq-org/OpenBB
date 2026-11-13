"""App loader module."""

import json
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.exceptions import ResponseValidationError
from pydantic import ValidationError

from openbb_core.api.exception_handlers import ExceptionHandlers
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.app.route_iter import iter_included_routers
from openbb_core.app.router import RouterLoader
from openbb_core.provider.utils.errors import EmptyDataError, UnauthorizedError


class AppLoader:
    """App loader."""

    @staticmethod
    def add_routers(app: FastAPI, routers: list[APIRouter | None], prefix: str):
        """Add routers."""
        for router in routers:
            if router:
                app.include_router(router=router, prefix=prefix)
        AppLoader.deduplicate_router_event_handlers(app)

    @staticmethod
    def add_openapi_tags(app: FastAPI):
        """Declare extension tags and collapse per-level route tags into one."""
        main_router = RouterLoader.from_extensions()
        # Add tag data for each router in the main router
        app.openapi_tags = [
            {
                "name": r,
                "description": main_router.get_attr(r, "description"),
            }
            for r in main_router.routers
        ]

        base_openapi = app.openapi
        extension_names = set(main_router.routers)

        def _order(group: str, name: str) -> tuple[int, str]:
            """Sort data extensions first; the core's own groups last."""
            return (0 if group in extension_names else 1, name.lower())

        def _describe(levels: list[str]) -> str:
            """Return the router description registered for a tag's full path."""
            return main_router.get_attr("/" + "/".join(levels), "description") or ""

        def openapi() -> dict[str, Any]:
            """Build the schema, then rewrite its tags into the nested shape."""
            if app.openapi_schema:
                return app.openapi_schema

            schema = base_openapi()
            composites: dict[str, list[str]] = {}

            for path_item in schema.get("paths", {}).values():
                for operation in path_item.values():
                    if not isinstance(operation, dict):
                        continue
                    levels = operation.get("tags") or []
                    if not levels:
                        continue
                    composite = "/".join(levels)
                    composites[composite] = levels
                    operation["tags"] = [composite]

            if composites:
                schema["tags"] = [
                    {"name": name, "description": _describe(levels)}
                    for name, levels in sorted(
                        composites.items(), key=lambda kv: _order(kv[1][0], kv[0])
                    )
                ]
                groups: dict[str, list[str]] = {}
                for name, levels in composites.items():
                    groups.setdefault(levels[0], []).append(name)
                schema["x-tagGroups"] = [
                    {"name": group, "tags": sorted(names, key=str.lower)}
                    for group, names in sorted(
                        groups.items(), key=lambda kv: _order(kv[0], kv[0])
                    )
                ]

            app.openapi_schema = schema
            return schema

        # Shadowing the bound method with a plain function on the instance is
        # the documented FastAPI hook for customising the schema.
        app.openapi = openapi  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]

    @staticmethod
    def add_exception_handlers(app: FastAPI):
        """Add exception handlers."""
        app.add_exception_handler(Exception, ExceptionHandlers.exception)
        # Handled inside the CORS middleware, unlike the Exception catch-all.
        app.add_exception_handler(TimeoutError, ExceptionHandlers.exception)
        app.add_exception_handler(json.JSONDecodeError, ExceptionHandlers.exception)
        app.add_exception_handler(ValidationError, ExceptionHandlers.validation)  # ty: ignore[invalid-argument-type]
        app.add_exception_handler(ResponseValidationError, ExceptionHandlers.validation)  # ty: ignore[invalid-argument-type]
        app.add_exception_handler(OpenBBError, ExceptionHandlers.openbb)  # ty: ignore[invalid-argument-type]
        app.add_exception_handler(EmptyDataError, ExceptionHandlers.empty_data)  # ty: ignore[invalid-argument-type]
        app.add_exception_handler(UnauthorizedError, ExceptionHandlers.unauthorized)  # ty: ignore[invalid-argument-type]

    @staticmethod
    def deduplicate_router_event_handlers(app: FastAPI) -> None:
        """Clear startup/shutdown handlers on included routers after assembly."""
        for included in iter_included_routers(app.router):
            on_startup = getattr(included, "on_startup", None)
            on_shutdown = getattr(included, "on_shutdown", None)
            if isinstance(on_startup, list):
                on_startup.clear()
            if isinstance(on_shutdown, list):
                on_shutdown.clear()
