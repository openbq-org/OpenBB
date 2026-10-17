"""Commands: generates the command map."""

import inspect
import json
from collections.abc import Callable
from functools import partial, wraps
from inspect import Parameter, Signature, signature
from typing import Annotated, Any, TypeVar, get_args, get_origin

from fastapi import APIRouter, Depends, Header
from fastapi.encoders import jsonable_encoder
from fastapi.params import Depends as DependsParam
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel
from starlette.responses import (
    Response as StarletteResponse,
    StreamingResponse,
)
from typing_extensions import ParamSpec

from openbb_core.app.charting import ChartingManager
from openbb_core.app.command_runner import CommandRunner
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.app.model.command_context import CommandContext
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.model.stream import OBBStream
from openbb_core.app.model.user_settings import UserSettings
from openbb_core.app.route_iter import iter_api_routes
from openbb_core.app.router import RouterLoader
from openbb_core.app.service.auth_service import AuthService
from openbb_core.app.service.system_service import SystemService
from openbb_core.app.service.user_service import UserService
from openbb_core.env import Env
from openbb_core.provider.utils.helpers import to_snake_case

# Resolved through the charting manager so a drop-in engine override is honored
# instead of importing ``openbb_charting`` by name. ``Charting`` is the resolved
# engine accessor class (or ``None`` when no engine is installed).
Charting = ChartingManager.get_charting_class()
CHARTING_INSTALLED = Charting is not None

T = TypeVar("T")
P = ParamSpec("P")
router = APIRouter(prefix="")


def build_new_annotation_map(sig: Signature) -> dict[str, Any]:
    """Build new annotation map."""
    annotation_map = {}
    parameter_list = sig.parameters.values()

    for parameter in parameter_list:
        annotation_map[parameter.name] = parameter.annotation

    annotation_map["return"] = sig.return_annotation

    return annotation_map


def build_new_signature(path: str, func: Callable) -> Signature:
    """Build new function signature."""
    # build_api_wrapper stores the signature built here on the function, and one
    # function can back several routes; always start from the original.
    sig = func.__dict__.setdefault("_openbb_original_signature", signature(func))
    parameter_list = sig.parameters.values()
    return_annotation = sig.return_annotation
    new_parameter_list: list = []
    var_kw_pos = len(parameter_list)

    for pos, parameter in enumerate(parameter_list):
        if (
            parameter.name == "cc"
            and parameter.annotation == CommandContext
            or parameter.name in ["kwargs", "args", "*", "**", "**kwargs", "*args"]
        ):
            # We do not add kwargs into the finished API signature.
            # Kwargs will be passed to every function that accepts them,
            # but we won't force the endpoint to take them.
            # We read the original signature in the wrapper to
            # determine if kwargs can be passed to the locals.
            continue

        # These are path parameters or dependency injections.
        if parameter.kind == Parameter.VAR_KEYWORD:
            # We track VAR_KEYWORD parameter to insert the any additional
            # parameters we need to add before it and avoid a SyntaxError
            var_kw_pos = pos

        if get_origin(parameter.annotation) is Annotated:
            # Get the metadata from Annotated
            metadata = get_args(parameter.annotation)[1:]
            # Check if any metadata item is a Depends instance
            if any(isinstance(m, DependsParam) for m in metadata):
                # Insert at var_kw_pos with include_in_schema=False
                new_parameter_list.insert(
                    var_kw_pos,
                    Parameter(
                        parameter.name,
                        kind=Parameter.POSITIONAL_OR_KEYWORD,
                        default=parameter.default,
                        annotation=parameter.annotation,
                    ),
                )
                var_kw_pos += 1
                continue

        new_parameter_list.append(
            Parameter(
                parameter.name,
                kind=parameter.kind,
                default=parameter.default,
                annotation=parameter.annotation,
            )
        )

    if (
        CHARTING_INSTALLED
        and Charting is not None
        and path.replace("/", "_")[1:] in Charting.functions()
    ):
        new_parameter_list.insert(
            var_kw_pos,
            Parameter(
                "chart",
                kind=Parameter.POSITIONAL_OR_KEYWORD,
                default=False,
                annotation=bool,
            ),
        )
        var_kw_pos += 1

    if custom_headers := SystemService().system_settings.api_settings.custom_headers:
        for name, default in custom_headers.items():
            new_parameter_list.insert(
                var_kw_pos,
                Parameter(
                    name.replace("-", "_"),
                    kind=Parameter.POSITIONAL_OR_KEYWORD,
                    default=default,
                    annotation=Annotated[str | None, Header(include_in_schema=False)],
                ),
            )
            var_kw_pos += 1

    if Env().API_AUTH:
        new_parameter_list.insert(
            var_kw_pos,
            Parameter(
                "__authenticated_user_settings",
                # Keyword-only, so it may follow a command's own keyword-only parameters.
                kind=Parameter.KEYWORD_ONLY,
                default=UserSettings(),
                annotation=Annotated[
                    UserSettings, Depends(AuthService().user_settings_hook)
                ],
            ),
        )
        var_kw_pos += 1

    return Signature(
        parameters=new_parameter_list,
        return_annotation=return_annotation,
    )


def validate_output(c_out: OBBject) -> OBBject:
    """
    Validate OBBject object.

    Checks against the OBBject schema and removes fields that contain the
    `exclude_from_api` extra `pydantic.Field` kwarg.
    Note that the modification to the `OBBject` object is done in-place.

    Parameters
    ----------
    c_out : OBBject
        OBBject object to validate.

    Returns
    -------
    Dict
        Serialized OBBject.
    """

    def is_model(type_):
        return inspect.isclass(type_) and issubclass(type_, BaseModel)

    def exclude_fields_from_api(key: str, value: Any):
        type_ = type(value)
        field = getattr(type(c_out), "model_fields", {}).get(key, None)
        json_schema_extra = field.json_schema_extra if field else None

        # case where 1st layer field needs to be excluded
        if (
            json_schema_extra
            and isinstance(json_schema_extra, dict)
            and json_schema_extra.get("exclude_from_api", None)
        ):
            delattr(c_out, key)

        # if it's a model with nested fields
        elif is_model(type_):
            for field_name, field in type_.model_fields.items():
                extra = getattr(field, "json_schema_extra", None)
                if (
                    extra
                    and isinstance(extra, dict)
                    and extra.get("exclude_from_api", None)
                ):
                    delattr(value, field_name)

                # if it's a yet a nested model we need to go deeper in the recursion
                elif is_model(getattr(field, "annotation", None)):
                    exclude_fields_from_api(field_name, getattr(value, field_name))

    # Let a non-OBBject object pass through without validation
    if not isinstance(c_out, OBBject):
        return c_out

    for k, v in c_out.model_copy():
        exclude_fields_from_api(k, v)

    return c_out


def build_api_wrapper(
    command_runner: CommandRunner,
    route: APIRoute,
) -> Callable:
    """Build API wrapper for a command."""
    func: Callable = route.endpoint
    path: str = route.path
    original_signature = signature(func)
    has_var_kwargs = any(
        param.kind == Parameter.VAR_KEYWORD
        for param in original_signature.parameters.values()
    )
    no_validate = (
        openapi_extra.get("no_validate")
        if (openapi_extra := getattr(route, "openapi_extra", None))
        else None
    )
    new_signature = build_new_signature(path=path, func=func)
    new_annotations_map = build_new_annotation_map(sig=new_signature)
    func.__signature__ = new_signature  # type: ignore
    func.__annotations__ = new_annotations_map

    if no_validate is True:
        route.response_model = None

    @wraps(wrapped=func)
    async def wrapper(  # noqa: PLR0912
        *args: tuple[Any], **kwargs: dict[str, Any]
    ) -> OBBject | JSONResponse | StarletteResponse:
        user_settings: UserSettings = UserSettings.model_validate(
            kwargs.pop(
                "__authenticated_user_settings",
                UserService.read_from_file(),
            )
        )
        p = path.strip("/").replace("/", ".")
        defaults = (
            getattr(user_settings.defaults, "__dict__", {})
            .get("commands", {})
            .get(p, {})
        )
        standard_params = getattr(kwargs.pop("standard_params", None), "__dict__", {})
        extra_params = getattr(kwargs.pop("extra_params", None), "__dict__", {})

        if defaults:
            _ = defaults.pop("provider", None)

            if "chart" in defaults:
                kwargs["chart"] = defaults.pop("chart", False)

            if "chart_params" in defaults:
                extra_params["chart_params"] = defaults.pop("chart_params", {})

            for k, v in defaults.items():
                if k in standard_params and standard_params[k] is None:
                    standard_params[k] = v
                elif (k in standard_params and standard_params[k] is not None) or (
                    k in extra_params and extra_params[k] is not None
                ):
                    continue
                elif k not in extra_params or (
                    k in extra_params and extra_params[k] is None
                ):
                    extra_params[k] = v

        kwargs["standard_params"] = standard_params
        kwargs["extra_params"] = extra_params

        # We need to insert dependency objects that are
        # Added at the Router level and may not be part
        # of the function signature.
        dependencies = route.dependencies or []
        dep_names: list = []
        # Only inject the dependency if the endpoint
        # accepts undefined arguments.
        if has_var_kwargs and "kwargs" not in kwargs:
            kwargs["kwargs"] = {}

        for dep in dependencies:
            dep_callable = dep.dependency

            if not dep_callable:
                continue

            dep_name = getattr(dep_callable, "__name__", "") or ""
            dep_name = to_snake_case(dep_name).replace("get_", "")

            if has_var_kwargs and dep_name not in kwargs:
                kwargs["kwargs"][dep_name] = dep_callable()

            dep_names.append(dep_name)

        execute = partial(command_runner.run, path, user_settings)

        output = await execute(*args, **kwargs)

        if isinstance(output, StarletteResponse):
            return output
        if isinstance(output, OBBStream):
            # The body is reserved for SSE chunks, so the response-level fields
            # (id, provider, warnings) are broadcast out-of-band as headers.
            stream_headers: dict[str, str] = {"X-OpenBB-Stream-Id": output.id}
            if output.provider:
                stream_headers["X-OpenBB-Provider"] = output.provider
            if output.warnings:
                stream_headers["X-OpenBB-Warning"] = json.dumps(
                    jsonable_encoder(output.warnings)
                )
            return StreamingResponse(
                output.aiter_bytes(),
                media_type=output.media_type or "text/event-stream",
                headers=stream_headers,
            )

        if isinstance(output, OBBject):
            # This is where we check for `on_command_output` extensions
            mutated_output = getattr(output, "_extension_modified", False)
            results_only = getattr(output, "_results_only", False)
            try:
                if results_only is True:
                    content = output.model_dump(
                        exclude_unset=True, exclude_none=True
                    ).get("results", [])

                    return JSONResponse(
                        content=jsonable_encoder(content), status_code=200
                    )

                if (mutated_output and isinstance(output, OBBject)) or (
                    isinstance(output, OBBject) and no_validate
                ):
                    output.results = output.model_dump(
                        exclude_unset=True, exclude_none=True
                    ).get("results")

                    return JSONResponse(
                        content=jsonable_encoder(output), status_code=200
                    )
            except Exception as exc:
                raise OpenBBError(
                    f"Error serializing output for an extension-modified endpoint {path}: {exc}",
                ) from exc

            if not no_validate:
                return validate_output(output)

        return output

    return wrapper


def add_command_map(command_runner: CommandRunner, api_router: APIRouter) -> None:
    """Add command map to the API router."""
    plugins_router = RouterLoader.from_extensions()
    for effective in iter_api_routes(plugins_router.api_router):
        leaf = getattr(effective, "original_route", effective)
        if not isinstance(leaf, APIRoute):
            continue
        original_leaf_path = leaf.path
        leaf.path = effective.path
        try:
            leaf.endpoint = build_api_wrapper(command_runner=command_runner, route=leaf)
        finally:
            leaf.path = original_leaf_path
    api_router.include_router(router=plugins_router.api_router)


system_settings = SystemService(logging_sub_app="api").system_settings
command_runner_instance = CommandRunner(system_settings=system_settings)
add_command_map(command_runner=command_runner_instance, api_router=router)
