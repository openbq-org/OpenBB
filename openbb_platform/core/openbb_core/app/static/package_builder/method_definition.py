"""Method definition emitter for the static package."""

import builtins
import inspect
import re
from collections import OrderedDict
from collections.abc import Callable
from inspect import Parameter, _empty, isclass, signature
from types import UnionType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    Literal,
    TypeVar,
    Union,
    get_args,
    get_origin,
)

from fastapi import Query, Request, Response, WebSocket
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse
from starlette.websockets import WebSocket as StarletteWebSocket
from typing_extensions import _AnnotatedAlias

from openbb_core.app.model.example import Example
from openbb_core.app.model.field import OpenBBField
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.provider_interface import ProviderInterface
from openbb_core.provider.abstract.query_params import QueryParams

if TYPE_CHECKING:
    from numpy import ndarray  # noqa
    from pandas import DataFrame, Series  # noqa
    from openbb_core.provider.abstract.data import Data  # noqa

from openbb_core.app.charting import ChartingManager

# Resolved through the charting manager so a drop-in engine override is honored
# instead of importing ``openbb_charting`` by name. ``Charting`` is the resolved
# engine accessor class (or ``None`` when no engine is installed).
Charting = ChartingManager.get_charting_class()
CHARTING_INSTALLED = Charting is not None

try:
    _HAS_FCNTL = True
except Exception:  # pragma: no cover  # noqa
    _HAS_FCNTL = False
    import msvcrt  # noqa

DataProcessingSupportedTypes = TypeVar(
    "DataProcessingSupportedTypes",
    list,
    dict,
    "DataFrame",
    list["DataFrame"],
    "Series",
    list["Series"],
    "ndarray",
    "Data",
)

from openbb_core.app.static.package_builder._indent import (  # noqa: F401
    TAB,
    create_indent,
)
from openbb_core.app.static.package_builder.docstring_generator import (
    DocstringGenerator,
)
from openbb_core.app.static.package_builder.path_handler import PathHandler


class MethodDefinition:
    """Build the method definition for the Platform."""

    # These are types we want to expand.
    # For example, start_date is always a 'date', but we also accept 'str' as input.
    # Be careful, if the type is not coercible by pydantic to the original type, you
    # will need to add some conversion code in the input filter.
    TYPE_EXPANSION = {
        "data": DataProcessingSupportedTypes,
        "start_date": str,
        "end_date": str,
        "date": str,
        "provider": None,
    }

    REQUEST_BOUND_PARAM_TYPES = tuple(
        t
        for t in (
            Request,
            StarletteRequest,
            Response,
            StarletteResponse,
            WebSocket,
            StarletteWebSocket,
        )
        if t is not None
    )
    REQUEST_BOUND_ANNOTATION_NAMES = {
        "header",
        "request",
        "fastapi.request",
        "fastapi.requests.request",
        "starlette.request",
        "starlette.requests.request",
        "response",
        "fastapi.response",
        "fastapi.responses.response",
        "starlette.response",
        "starlette.responses.response",
        "websocket",
        "starlette.websockets.websocket",
        "fastapi.websockets.websocket",
    }

    @staticmethod
    def _is_charting_command(path: str) -> bool:
        """Return whether ``path`` maps to an installed charting function.

        Parameters
        ----------
        path : str
            The route path.

        Returns
        -------
        bool
            True if charting is installed and exposes a matching function.
        """
        if not CHARTING_INSTALLED or Charting is None:
            return False
        try:
            return path.replace("/", "_")[1:] in Charting.functions()
        except Exception:  # noqa: BLE001
            return False

    @staticmethod
    def _snake_case(name: str) -> str:
        if not name:
            return ""
        name = name.replace(".", "_")
        s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
        return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).lower()

    @staticmethod
    def _dependency_identifier(dependency_func: Callable) -> str:
        try:
            return_annotation = signature(dependency_func).return_annotation
        except (ValueError, TypeError):
            return_annotation = inspect._empty

        class_name = ""
        if return_annotation not in (inspect._empty, None):
            if isinstance(return_annotation, str):
                class_name = return_annotation.rsplit(".", maxsplit=1)[-1]
            elif isclass(return_annotation):
                class_name = return_annotation.__name__

        if not class_name and isclass(dependency_func):
            class_name = dependency_func.__name__

        if not class_name:
            func_name = dependency_func.__name__  # ty: ignore[unresolved-attribute]
            class_name = (
                func_name[4:]
                if func_name.startswith("get_") and len(func_name) > 4
                else func_name
            )

        identifier = MethodDefinition._snake_case(class_name)
        return identifier or MethodDefinition._snake_case(
            dependency_func.__name__  # ty: ignore[unresolved-attribute]
        )

    @staticmethod
    def _is_none_like_return(annotation: Any) -> bool:
        if annotation in (None, type(None)):
            return True
        if annotation is inspect._empty:
            return False
        if isinstance(annotation, str):
            normalized = annotation.lower().strip()
            normalized = normalized.replace("typing.", "")
            normalized = normalized.replace("builtins.", "")
            normalized = normalized.split("[", 1)[0]
            return normalized in {"none", "nonetype"}

        origin = get_origin(annotation)
        if origin is Union or (UnionType is not None and origin is UnionType):
            args = get_args(annotation) or getattr(annotation, "__args__", ())
            if not args:
                return True
            return all(MethodDefinition._is_none_like_return(arg) for arg in args)

        return False

    @staticmethod
    def _has_request_bound_annotation(annotation: Any) -> bool:
        if annotation is Parameter.empty:
            return False

        origin = get_origin(annotation)
        if origin is Annotated:
            args = get_args(annotation)
            if not args:
                return False
            return MethodDefinition._has_request_bound_annotation(args[0])

        origin = get_origin(annotation)
        if origin is Union or (UnionType is not None and origin is UnionType):
            args = get_args(annotation) or getattr(annotation, "__args__", ())
            return any(
                MethodDefinition._has_request_bound_annotation(arg) for arg in args
            )

        if isinstance(annotation, str):
            normalized = annotation.lower().strip()
            normalized = normalized.replace("typing.", "")
            normalized = normalized.replace("builtins.", "")
            normalized = normalized.split("[", 1)[0]
            return normalized in MethodDefinition.REQUEST_BOUND_ANNOTATION_NAMES

        if isinstance(annotation, type):
            return annotation in MethodDefinition.REQUEST_BOUND_PARAM_TYPES

        return annotation in MethodDefinition.REQUEST_BOUND_PARAM_TYPES

    @staticmethod
    def _is_safe_dependency(dependency_func: Callable) -> bool:
        try:
            sig = signature(dependency_func)
        except (TypeError, ValueError):
            return False

        if MethodDefinition._is_none_like_return(sig.return_annotation):
            return False

        for param in sig.parameters.values():
            annotation = param.annotation
            if MethodDefinition._has_request_bound_annotation(annotation):
                return False

            if (
                param.kind
                in (
                    Parameter.POSITIONAL_ONLY,
                    Parameter.POSITIONAL_OR_KEYWORD,
                    Parameter.KEYWORD_ONLY,
                )
                and param.default is Parameter.empty
            ):
                return False
        return True

    @staticmethod
    def _surfaced_param_spec(param: Parameter) -> tuple[Any, Any]:
        """Resolve the ``(annotation, default)`` to surface for a dependency param.

        Unwraps ``Annotated[...]`` to the inner type, ports any description from
        the FastAPI parameter object (``Header``/``Query``/``Cookie``/``Path``)
        or field metadata into an ``OpenBBField``, and reads the default from the
        FastAPI parameter object when present, so the surfaced parameter reads as
        a plain typed, documented argument.
        """
        annotation = param.annotation
        inner_type = annotation
        metadata: tuple = ()
        if isinstance(annotation, _AnnotatedAlias):
            args = get_args(annotation)
            inner_type = args[0] if args else Any
            metadata = annotation.__metadata__
        if inner_type is Parameter.empty:
            inner_type = Any

        default = param.default

        description = ""
        for meta in (*metadata, default):
            candidate = getattr(meta, "description", None)
            if candidate:
                description = candidate
                break

        if default is not Parameter.empty and hasattr(default, "default"):
            fastapi_default = default.default
            default = (
                Parameter.empty
                if fastapi_default in (Ellipsis, PydanticUndefined)
                else fastapi_default
            )

        annotated = Annotated[inner_type, OpenBBField(description=description)]
        return annotated, default

    @staticmethod
    def _surface_dependency(
        dependency_func: Callable,
    ) -> tuple["OrderedDict[str, Parameter]", str] | None:
        """Resolve a dependency in-process by surfacing its parameters.

        A dependency is surfaceable when every parameter can be supplied by the
        caller — i.e. none is a ``Request``/``Response``/``WebSocket`` object and
        none is itself a nested ``Depends(...)``. Header/Cookie/Query/plain-value
        parameters are surfaced as plain arguments on the generated command and
        forwarded to the dependency call, so the dependency runs without an HTTP
        request (e.g. an ``x-api-key`` header becomes an ``x_api_key`` argument).

        Returns ``(surfaced_params, call_args)`` or ``None`` when the dependency
        cannot be resolved in-process.
        """
        try:
            sig = signature(dependency_func)
        except (TypeError, ValueError):
            return None

        if MethodDefinition._is_none_like_return(sig.return_annotation):
            return None

        surfaced: OrderedDict[str, Parameter] = OrderedDict()
        arg_pairs: list[str] = []
        for pname, param in sig.parameters.items():
            annotation = param.annotation
            if MethodDefinition._has_request_bound_annotation(annotation):
                return None
            if isinstance(annotation, _AnnotatedAlias) and any(
                hasattr(meta, "dependency") for meta in annotation.__metadata__
            ):
                return None
            inner_type, default = MethodDefinition._surfaced_param_spec(param)
            surfaced[pname] = Parameter(
                name=pname,
                kind=Parameter.POSITIONAL_OR_KEYWORD,
                annotation=inner_type,
                default=default,
            )
            arg_pairs.append(f"{pname}={pname}")
        return surfaced, ", ".join(arg_pairs)

    @staticmethod
    def _collect_surfaced_params(
        parameter_map: dict[str, Parameter],
    ) -> "OrderedDict[str, Parameter]":
        """Collect parameters to surface for parameter-level dependencies.

        For each ``Depends(...)`` parameter that is not already safe (resolvable
        with no arguments) but is surfaceable, the dependency's own parameters are
        promoted onto the generated command.
        """
        surfaced: OrderedDict[str, Parameter] = OrderedDict()
        for _name, param in parameter_map.items():
            if not isinstance(param.annotation, _AnnotatedAlias):
                continue
            for meta in param.annotation.__metadata__:
                dependency_func = getattr(meta, "dependency", None)
                if dependency_func is None:
                    continue
                if MethodDefinition._is_safe_dependency(dependency_func):
                    continue
                result = MethodDefinition._surface_dependency(dependency_func)
                if result is not None:
                    params, _ = result
                    for pname, pparam in params.items():
                        surfaced.setdefault(pname, pparam)
        return surfaced

    @staticmethod
    def build_class_loader_method(path: str) -> str:
        """Build the class loader method."""
        module_name = PathHandler.build_module_name(path=path)
        class_name = PathHandler.build_module_class(path=path)
        function_name = path.rsplit("/", maxsplit=1)[-1].strip("/").replace("-", "_")
        description = PathHandler.get_router_description(path)

        code = "\n    @property\n"
        code += f"    def {function_name}(self):\n"
        if description:
            escaped = description.replace('"""', '\\"\\"\\"')
            code += f'        """{escaped}"""\n'
        code += f"        from . import {module_name}\n\n"
        code += f"        return {module_name}.{class_name}(command_runner=self._command_runner)\n"

        return code

    @staticmethod
    def get_type(field: FieldInfo) -> type:
        """Get the type of the field."""
        field_type = getattr(
            field, "annotation", getattr(field, "type", Parameter.empty)
        )
        if isclass(field_type):
            name = field_type.__name__
            if name.startswith("Constrained") and name.endswith("Value"):
                name = name[11:-5].lower()
                return getattr(builtins, name, field_type)
            return field_type
        return field_type

    @staticmethod
    def get_default(field: FieldInfo):
        """Get the default value of the field."""
        # First check if field has a default attribute at all
        if not hasattr(field, "default"):
            return Parameter.empty

        # Check for Ellipsis directly in field.default
        if field.default is Ellipsis:
            return None

        if hasattr(field, "default") and hasattr(field.default, "default"):
            default_val = field.default.default
            if default_val is PydanticUndefined:
                return Parameter.empty
            if default_val is Ellipsis:
                return None
            return default_val
        return field.default

    @staticmethod
    def get_extra(field: FieldInfo) -> dict:
        """Get json schema extra."""
        field_default = getattr(field, "default", None)
        if field_default:
            # Getting json_schema_extra without changing the original dict
            json_schema_extra = (
                getattr(field_default, "json_schema_extra", {}) or {}
            ).copy()
            json_schema_extra.pop("choices", None)
            return json_schema_extra
        return {}

    @staticmethod
    def is_annotated_dc(annotation) -> bool:
        """Check if the annotation is an annotated dataclass."""
        return isinstance(annotation, _AnnotatedAlias) and hasattr(
            annotation.__args__[0], "__dataclass_fields__"
        )

    @staticmethod
    def query_params_model(annotation) -> type[QueryParams] | None:
        """Return the ``QueryParams`` class if ``annotation`` is one (or wraps one).

        Endpoints can declare a single ``params: XxxQueryParams`` argument
        instead of listing every field; the builder flattens that model into
        individual kwargs so the generated SDK method, docstring, and CLI all
        expose the fields directly. ``Annotated[XxxQueryParams, ...]`` is
        unwrapped first.
        """
        candidate = annotation
        if isinstance(candidate, _AnnotatedAlias):
            candidate = candidate.__args__[0]
        if (
            isclass(candidate)
            and issubclass(candidate, QueryParams)
            and candidate is not QueryParams
        ):
            return candidate
        return None

    @staticmethod
    def is_data_processing_function(path: str) -> bool:
        """Check if the function is a data processing function."""
        route = PathHandler.build_route_map().get(path)
        if not route:
            return False
        methods: set = getattr(route, "methods", set())
        # Consider POST, PUT, PATCH as data processing, but not GET
        return bool(methods & {"POST", "PUT", "PATCH"})

    @staticmethod
    def is_deprecated_function(path: str) -> bool:
        """Check if the function is deprecated."""
        return getattr(PathHandler.build_route_map()[path], "deprecated", False)

    @staticmethod
    def get_deprecation_message(path: str) -> str:
        """Get the deprecation message."""
        return getattr(PathHandler.build_route_map()[path], "summary", "")

    @staticmethod
    def reorder_params(
        params: dict[str, Parameter],
        var_kw: list[str] | None = None,
        for_docstring: bool = False,
    ) -> "OrderedDict[str, Parameter]":
        """Reorder the params based on context.

        For function signatures: provider is placed last (before VAR_KEYWORD)
        For docstrings: provider is placed first
        """
        formatted_keys = list(params.keys())

        if for_docstring and "provider" in formatted_keys:
            # For docstrings: Place "provider" first
            formatted_keys.remove("provider")
            formatted_keys.insert(0, "provider")
        else:
            # For function signatures: Place "provider" and VAR_KEYWORD at the end
            for k in ["provider"] + (var_kw or []):
                if k in formatted_keys:
                    formatted_keys.remove(k)
                    formatted_keys.append(k)

        od: OrderedDict[str, Parameter] = OrderedDict()
        for k in formatted_keys:
            od[k] = params[k]

        return od

    @staticmethod
    def _parse_docstring_params(func: Callable | None) -> dict[str, str]:
        """Parse parameter descriptions from a NumPy-style docstring.

        Parameters
        ----------
        func : Optional[Callable]
            The function whose docstring to parse.

        Returns
        -------
        dict[str, str]
            Mapping of parameter name to its description text.
        """
        if func is None:
            return {}
        doc = inspect.getdoc(func) or ""
        if not doc:
            return {}

        # Find the Parameters section
        params_match = re.search(
            r"^\s*Parameters\s*\n\s*[-=~`]{3,}",
            doc,
            re.MULTILINE,
        )
        if not params_match:
            return {}

        # Extract text after the dashes line
        after_header = doc[params_match.end() :]
        # Find the next section header (e.g., Returns, Raises, Examples, Notes)
        next_section = re.search(
            r"^\s*[A-Z][a-z]+\s*\n\s*[-=~`]{3,}",
            after_header,
            re.MULTILINE,
        )
        params_text = (
            after_header[: next_section.start()] if next_section else after_header
        )

        result: dict[str, str] = {}
        current_name: str | None = None
        current_desc_lines: list[str] = []

        for line in params_text.splitlines():
            # Match a parameter line like "param_name : type" or "param_name: type"
            param_match = re.match(r"^\s{0,4}(\w+)\s*:\s*", line)
            if param_match:
                # Save previous parameter
                if current_name is not None:
                    result[current_name] = " ".join(current_desc_lines).strip()
                current_name = param_match.group(1)
                current_desc_lines = []
            elif current_name is not None and line.strip():
                current_desc_lines.append(line.strip())

        # Save last parameter
        if current_name is not None:
            result[current_name] = " ".join(current_desc_lines).strip()

        return result

    @staticmethod
    def _format_annotated_param(
        name: str,
        param: Parameter,
        path: str,
        formatted: dict[str, Parameter],
    ) -> bool:
        """Handle ``Annotated[...]`` parameters during ``format_params``.

        Returns True when the parameter has been fully consumed (caller should
        ``continue``), False when the caller should fall through to the
        remaining handling.
        """
        has_depends = any(
            hasattr(meta, "dependency") for meta in param.annotation.__metadata__
        )
        model = param.annotation.__args__[0]
        is_pydantic_model = hasattr(model, "model_fields") or hasattr(
            model, "__pydantic_fields__"
        )
        is_get_request = not MethodDefinition.is_data_processing_function(path)

        if is_pydantic_model and is_get_request and not has_depends:
            fields = getattr(
                model,
                "model_fields",
                getattr(model, "__pydantic_fields__", {}),
            )
            for field_name, field in fields.items():
                type_ = field.annotation
                default = (
                    field.default
                    if field.default is not PydanticUndefined
                    else Parameter.empty
                )
                description = getattr(field, "description", "")
                extra = getattr(field, "json_schema_extra", {}) or {}
                new_type = MethodDefinition.get_expanded_type(field_name, extra, type_)
                updated_type = (
                    type_ if new_type is ... else Union[type_, new_type]  # noqa
                )
                formatted[field_name] = Parameter(
                    name=field_name,
                    kind=Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=Annotated[
                        updated_type,
                        OpenBBField(description=description),
                    ],
                    default=default,
                )
            return True

        query_obj = next(
            (
                meta
                for meta in param.annotation.__metadata__
                if hasattr(meta, "__class__") and "Query" in meta.__class__.__name__
            ),
            None,
        )
        if query_obj is None:
            return False

        description = getattr(query_obj, "description", "") or ""
        default_value = getattr(query_obj, "default", Parameter.empty)
        if default_value is PydanticUndefined:
            default_value = Parameter.empty

        formatted[name] = Parameter(
            name=name,
            kind=param.kind,
            annotation=Annotated[
                param.annotation.__args__[0],
                OpenBBField(description=description),
            ],
            default=param.default,
        )
        return True

    @staticmethod
    def format_params(  # noqa: PLR0912
        path: str,
        parameter_map: dict[str, Parameter],
        func: Callable | None = None,
    ) -> OrderedDict[str, Parameter]:
        """Format the params."""
        # Parse docstring descriptions as fallback for unannotated params
        docstring_descs = MethodDefinition._parse_docstring_params(func)

        parameter_map.pop("cc", None)

        # Extract path parameters from the route path
        path_params = PathHandler.extract_path_parameters(path)

        # we need to add the chart parameter here bc of the docstring generation
        if (
            CHARTING_INSTALLED
            and Charting is not None
            and path.replace("/", "_")[1:] in Charting.functions()
        ):
            parameter_map["chart"] = Parameter(
                name="chart",
                kind=Parameter.POSITIONAL_OR_KEYWORD,
                annotation=Annotated[
                    bool,
                    Query(
                        description="Whether to create a chart or not, by default False.",
                    ),
                ],
                default=False,
            )

        formatted: dict[str, Parameter] = {}
        var_kw = []

        # First, handle path parameters - they must come first
        for name in path_params:
            if name in parameter_map:
                formatted[name] = Parameter(
                    name=name,
                    kind=Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=Annotated[
                        str,
                        OpenBBField(
                            description=f"Path parameter: {name}",
                        ),
                    ],
                    default=Parameter.empty,  # Path params are always required
                )

        # Then process all other parameters
        for name, param in parameter_map.items():
            # Skip path parameters - they should be required string parameters
            if name in path_params or name in ("kwargs", "**kwargs"):
                continue  # Already handled above

            # Unpack a V5 QueryParams-model parameter into its individual fields.
            model = param.annotation
            if isclass(model) and issubclass(model, QueryParams):
                model_fields = getattr(
                    model,
                    "model_fields",
                    getattr(model, "__pydantic_fields__", {}),
                )
                for field_name, field in model_fields.items():
                    type_ = field.annotation
                    default = (
                        field.default
                        if field.default is not PydanticUndefined
                        else Parameter.empty
                    )
                    description = getattr(field, "description", "") or ""
                    extra = getattr(field, "json_schema_extra", {}) or {}
                    new_type = MethodDefinition.get_expanded_type(
                        field_name, extra, type_
                    )
                    if hasattr(new_type, "__constraints__"):
                        # Inline the TypeVar constraints into the annotation.
                        types = new_type.__constraints__ + (type_,)  # type: ignore
                        updated_type = Union[types]  # noqa
                    elif new_type is ...:
                        updated_type = type_
                    else:
                        updated_type = Union[type_, new_type]  # noqa
                    formatted[field_name] = Parameter(
                        name=field_name,
                        kind=Parameter.POSITIONAL_OR_KEYWORD,
                        annotation=Annotated[
                            updated_type,
                            OpenBBField(description=description),
                        ],
                        default=default,
                    )
                continue

            # Case 1: Handle Query objects inside Annotated
            if isinstance(
                param.annotation, _AnnotatedAlias
            ) and MethodDefinition._format_annotated_param(
                name, param, path, formatted
            ):
                continue

            # Case 2: Handle Query objects as default values
            if (
                hasattr(param.default, "__class__")
                and "Query" in param.default.__class__.__name__
            ):
                query_obj = param.default
                description = getattr(query_obj, "description", "") or ""
                default_value = getattr(query_obj, "default", "")
                formatted[name] = Parameter(
                    name=name,
                    kind=param.kind,
                    annotation=Annotated[
                        param.annotation,
                        OpenBBField(
                            description=description,
                        ),
                    ],
                    default=(
                        Parameter.empty
                        if default_value is PydanticUndefined
                        or default_value is Ellipsis
                        else default_value
                    ),
                )
                continue

            # Case 3: a ``QueryParams`` model parameter — flatten its fields
            # into individual kwargs so the generated method exposes each
            # field directly (``method(field1=, field2=, ...)``) rather than a
            # single opaque ``params`` argument. The method body re-packages
            # them into the model the route expects.
            if (
                qp_model := MethodDefinition.query_params_model(param.annotation)
            ) is not None:
                for field_name, field in qp_model.model_fields.items():
                    field_anno: Any = field.annotation
                    new_type = MethodDefinition.get_expanded_type(
                        field_name, None, field_anno
                    )
                    if hasattr(new_type, "__constraints__"):
                        updated_type = Union[  # noqa
                            new_type.__constraints__ + (field_anno,)  # type: ignore
                        ]
                    elif new_type is ...:
                        updated_type = field_anno
                    else:
                        updated_type = Union[field_anno, new_type]  # noqa

                    if field.is_required():
                        field_default: Any = Parameter.empty
                    elif field.default_factory is not None:
                        field_default = field.get_default(call_default_factory=True)
                    else:
                        field_default = field.default
                    formatted[field_name] = Parameter(
                        name=field_name,
                        kind=Parameter.POSITIONAL_OR_KEYWORD,
                        annotation=Annotated[
                            updated_type,
                            OpenBBField(description=field.description or ""),
                        ],
                        default=field_default,
                    )
                continue

            if name == "extra_params":
                formatted[name] = Parameter(name="kwargs", kind=Parameter.VAR_KEYWORD)
                var_kw.append(name)
            elif name == "provider_choices":
                if param.annotation != Parameter.empty and hasattr(
                    param.annotation, "__args__"
                ):
                    fields = param.annotation.__args__[0].__dataclass_fields__
                    field = fields["provider"]
                else:
                    continue
                type_ = getattr(field, "type")
                default_priority = getattr(type_, "__args__")
                formatted["provider"] = Parameter(
                    name="provider",
                    kind=Parameter.POSITIONAL_OR_KEYWORD,
                    annotation=Annotated[
                        MethodDefinition.get_type(  # noqa  # ty: ignore[invalid-type-form]
                            field
                        )
                        | None,
                        OpenBBField(
                            description=(
                                "The provider to use, by default None. "
                                "If None, the priority list configured in the settings is used. "
                                f"Default priority: {', '.join(default_priority)}."
                            ),
                        ),
                    ],
                    default=None,
                )

            elif MethodDefinition.is_annotated_dc(param.annotation):
                fields = param.annotation.__args__[0].__dataclass_fields__
                for field_name, field in fields.items():
                    type_ = MethodDefinition.get_type(field)
                    default = MethodDefinition.get_default(field)
                    extra = MethodDefinition.get_extra(field)
                    new_type = MethodDefinition.get_expanded_type(
                        field_name, extra, type_
                    )
                    updated_type = (
                        type_
                        if new_type is ...
                        else Union[  # noqa: UP007
                            type_,  # ty: ignore[invalid-type-form]
                            new_type,
                        ]
                    )

                    formatted[field_name] = Parameter(
                        name=field_name,
                        kind=Parameter.POSITIONAL_OR_KEYWORD,
                        annotation=updated_type,
                        default=default,
                    )

            if isinstance(param.annotation, _AnnotatedAlias):
                # Specifically look for Depends dependency rather than any annotation
                has_depends = any(
                    hasattr(meta, "dependency")
                    for meta in param.annotation.__metadata__
                )
                if has_depends:
                    continue

                # If not a dependency, process it as a normal parameter.
                inner_type = param.annotation.__origin__
                new_type = MethodDefinition.get_expanded_type(name)
                if hasattr(new_type, "__constraints__"):
                    types = new_type.__constraints__ + (inner_type,)  # type: ignore
                    updated_type = Union[types]  # noqa
                else:
                    updated_type = (
                        inner_type if new_type is ... else Union[inner_type, new_type]  # noqa
                    )

                metadata = getattr(param.annotation, "__metadata__", [])
                description = (
                    getattr(metadata[0], "description", "") if metadata else ""
                )
                # Fall back to docstring description if annotation has none
                if not description:
                    description = docstring_descs.get(name, "")

                formatted[name] = Parameter(
                    name=name,
                    kind=param.kind,
                    annotation=Annotated[
                        updated_type,
                        OpenBBField(
                            description=description,
                        ),
                    ],
                    default=MethodDefinition.get_default(param),  # type: ignore
                )

            else:
                new_type = MethodDefinition.get_expanded_type(name)
                if hasattr(new_type, "__constraints__"):
                    types = new_type.__constraints__ + (param.annotation,)  # type: ignore
                    updated_type = Union[types]  # noqa
                else:
                    updated_type = (
                        param.annotation
                        if new_type is ...
                        else Union[param.annotation, new_type]  # noqa
                    )

                metadata = getattr(param.annotation, "__metadata__", [])
                description = (
                    getattr(metadata[0], "description", "") if metadata else ""
                )
                # Fall back to docstring description if annotation has none
                if not description:
                    description = docstring_descs.get(name, "")

                # Untyped positional arguments are typed as Any
                updated_type = Any if updated_type is inspect._empty else updated_type

                formatted[name] = Parameter(
                    name=name,
                    kind=param.kind,
                    annotation=Annotated[
                        updated_type,
                        OpenBBField(
                            description=description,
                        ),
                    ],
                    default=MethodDefinition.get_default(param),  # type: ignore
                )
                if param.kind == Parameter.VAR_KEYWORD:
                    var_kw.append(name)

        required_params = OrderedDict()
        optional_params = OrderedDict()

        for name, param in formatted.items():
            if param.default == Parameter.empty:
                required_params[name] = param
            else:
                optional_params[name] = param

        # Combine them in the correct order
        ordered_params = OrderedDict(
            list(required_params.items()) + list(optional_params.items())
        )

        return MethodDefinition.reorder_params(params=ordered_params, var_kw=var_kw)

    @staticmethod
    def add_field_custom_annotations(
        od: OrderedDict[str, Parameter], model_name: str | None = None
    ):
        """Add the field custom description and choices to the param signature as annotations."""
        if not model_name:
            return

        provider_interface = ProviderInterface()

        # Get fields from standard model
        try:
            available_fields = provider_interface.params[model_name][
                "standard"
            ].__dataclass_fields__
            extra_fields = provider_interface.params[model_name][
                "extra"
            ].__dataclass_fields__
        except (KeyError, AttributeError):
            return

        # Combined fields
        all_fields: dict = {}
        all_fields.update(available_fields)
        all_fields.update(extra_fields)

        for param, value in od.items():
            if param not in all_fields:
                continue

            field_default = all_fields[param].default
            extra = MethodDefinition.get_extra(all_fields[param])
            choices = getattr(all_fields[param], "json_schema_extra", {}).get(
                "choices", []
            ) or extra.get("choices", [])
            description = getattr(field_default, "description", "")

            # Handle provider-specific choices and add them to the description
            provider_specific: dict = {}
            for provider, provider_info in extra.items():
                if isinstance(provider_info, dict) and "choices" in provider_info:
                    provider_specific[provider] = provider_info["choices"]

            # Add provider-specific choices to description
            if provider_specific:
                # Add each provider's choices on a new line
                for provider, provider_choices in provider_specific.items():
                    if provider_choices:
                        choices_str = ", ".join(f"'{c}'" for c in provider_choices)
                        description += f"\nChoices for {provider}: {choices_str}"

            # Handle multiple_items_allowed
            multiple_items_providers: list = []
            for provider, provider_info in extra.items():
                if (
                    isinstance(provider_info, dict)
                    and provider_info.get("multiple_items_allowed")
                    or (
                        isinstance(provider_info, list)
                        and "multiple_items_allowed" in provider_info
                    )
                ):
                    multiple_items_providers.append(provider)

            if (
                multiple_items_providers
                and "Multiple comma separated items allowed for provider(s)"
                not in description
            ):
                description += f"\nMultiple items supported by: {', '.join(multiple_items_providers)}"

            # Process the field type - if it's a Union of many Literals, simplify to base type
            field_type = all_fields[param].type
            simplified_type = field_type

            # If there are provider-specific choices, try to simplify the type
            if (
                provider_specific
                and hasattr(field_type, "__origin__")
                and field_type.__origin__ is Union
            ):
                # Check if all union members are Literals
                all_literals = True
                for arg in field_type.__args__:
                    if not (hasattr(arg, "__origin__") and arg.__origin__ is Literal):
                        all_literals = False
                        break

                if all_literals:
                    # Find the base type of the literals (usually str or int)
                    literal_types = set()
                    for arg in field_type.__args__:
                        for lit_val in arg.__args__:
                            literal_types.add(type(lit_val))

                    # If all literals are of the same type, use that type
                    if len(literal_types) == 1:
                        simplified_type = next(iter(literal_types))

            # Create field with enhanced description and possibly simplified type
            field_kwargs = {
                "description": description,
            }

            if choices:
                field_kwargs["choices"] = choices

            new_value = value.replace(
                annotation=Annotated[
                    (
                        simplified_type  # ty: ignore[invalid-type-form]
                        if simplified_type != field_type
                        else value.annotation
                    ),
                    OpenBBField(description=description),
                ],
            )

            od[param] = new_value

    @staticmethod
    def _get_type_repr(type_hint: Any) -> str:
        """Get the string representation of a type hint."""
        if isinstance(type_hint, type):
            return type_hint.__name__

        # Unwrap ForwardRef to its inner string so we don't emit
        # ForwardRef('int') in generated signatures.
        if hasattr(type_hint, "__forward_arg__"):
            return type_hint.__forward_arg__

        s = str(type_hint)
        if s.startswith("typing."):
            s = s[7:]
        return s

    @staticmethod
    def _normalize_type_names(text: str) -> str:
        """Rewrite ``typing`` and fully-qualified names in a rendered type."""
        text = text.replace("NoneType", "None")
        text = text.replace("pandas.core.frame.DataFrame", "pandas.DataFrame")
        text = text.replace("openbb_core.provider.abstract.data.Data", "Data")
        text = text.replace("ForwardRef('Data')", "Data")
        text = text.replace("ForwardRef('DataFrame')", "DataFrame")
        text = text.replace("ForwardRef('Series')", "Series")
        text = text.replace("ForwardRef('ndarray')", "ndarray")
        text = re.sub(r"\bDict\b", "dict", text)
        text = re.sub(r"\bList\b", "list", text)
        return text.replace("typing.", "")

    @staticmethod
    def build_func_params(formatted_params: OrderedDict[str, Parameter]) -> str:
        """Convert function params to string representations."""

        def split_preserving_whitespace(text: str, width: int) -> list[str]:
            """Split text into chunks of about ``width`` characters that rejoin exactly."""
            chunks: list[str] = []
            current = ""
            for word in re.findall(r"\S+\s*|\s+", text):
                if current and len(current) + len(word.rstrip()) > width:
                    chunks.append(current)
                    current = ""
                current += word
            if current:
                chunks.append(current)
            return chunks

        def stringify_param(param: Parameter) -> str:
            """Format a parameter as a string."""
            if not (
                isinstance(param.annotation, _AnnotatedAlias)
                and any(
                    isinstance(m, OpenBBField) for m in param.annotation.__metadata__
                )
            ):
                return MethodDefinition._normalize_type_names(str(param))

            type_hint = param.annotation.__args__[0]
            type_repr = MethodDefinition._normalize_type_names(
                MethodDefinition._get_type_repr(type_hint)
            )
            meta = next(
                m for m in param.annotation.__metadata__ if isinstance(m, OpenBBField)
            )
            desc = meta.description
            desc_repr = repr(desc)

            if desc is None:
                desc = ""
            # For function signatures, use shorter max width to prevent line overflow
            max_width = 50

            if len(desc) <= max_width:
                desc_repr = repr(desc)
            else:
                parts = split_preserving_whitespace(desc, max_width)
                joined = "\n                    ".join(f"{repr(p)}" for p in parts)
                desc_repr = f"(\n                    {joined}" + "\n                )"

            default_part = ""

            if param.default is not Parameter.empty:
                default_repr = repr(param.default)
                if default_repr == "Ellipsis":
                    default_repr = "None"
                default_part = f" = {default_repr}"
            if (
                "None" in default_part
                and "| None" not in type_repr
                and "Optional" not in type_repr
            ):
                type_repr += " | None"
            final_param = f"""{param.name.strip()}: Annotated[
            {type_repr},
            OpenBBField(
                description={desc_repr}
            )
        ]{default_part}"""

            return final_param

        params_list = [stringify_param(p) for p in formatted_params.values()]
        return ",\n        ".join(params_list)

    @staticmethod
    def build_func_returns(return_type: type) -> str:
        """Build the function returns."""
        if return_type == _empty:
            func_returns = "Any"
        elif isinstance(return_type, str):
            func_returns = return_type
        elif isclass(return_type) and issubclass(return_type, OBBject):
            func_returns = "OBBject"
        elif return_type:
            func_returns = MethodDefinition._normalize_type_names(
                MethodDefinition._get_type_repr(return_type)
            )
        else:
            func_returns = Any

        return func_returns  # type: ignore

    @staticmethod
    def build_command_method_signature(
        func_name: str,
        formatted_params: OrderedDict[str, Parameter],
        return_type: type,
        path: str,
        model_name: str | None = None,
    ) -> str:
        """Build the command method signature."""

        MethodDefinition.add_field_custom_annotations(
            od=formatted_params, model_name=model_name
        )  # this modified `od` in place
        func_params = MethodDefinition.build_func_params(formatted_params)
        func_returns = MethodDefinition.build_func_returns(return_type)

        args = (
            '(config={"arbitrary_types_allowed": True})'
            if "DataFrame" in func_params
            or "Series" in func_params
            or "ndarray" in func_params
            else ""
        )

        code = ""
        deprecated = ""

        if MethodDefinition.is_deprecated_function(path):
            deprecation_message = MethodDefinition.get_deprecation_message(path)
            deprecation_type_class = type(deprecation_message.metadata).__name__  # type: ignore

            deprecated = "\n    @deprecated("
            deprecated += f'\n        "{deprecation_message}",'
            deprecated += f"\n        category={deprecation_type_class},"
            deprecated += "\n    )"

        code += "\n    @exception_handler"
        code += f"\n    @validate{args}"
        code += deprecated
        code += f"\n    def {func_name}("
        code += f"\n        self,\n        {func_params}\n    ) -> {func_returns}:\n"

        return code

    @staticmethod
    def build_command_method_doc(
        path: str,
        func: Callable,
        formatted_params: OrderedDict[str, Parameter],
        model_name: str | None = None,
        examples: list[Example] | None = None,
        return_type: Any = None,
    ):
        """Build the command method docstring."""
        doc = func.__doc__
        doc = DocstringGenerator.generate(
            path=path,
            func=func,
            formatted_params=formatted_params,
            model_name=model_name,
            examples=examples,
            return_type=return_type,
        )

        code = (
            f'{create_indent(2)}"""{doc.rstrip()}\n{create_indent(2)}"""  # noqa: E501\n\n'
            if doc
            else ""
        )

        return code

    @staticmethod
    def _collect_dependency_calls(
        path: str, parameter_map: dict[str, Parameter]
    ) -> tuple[list[str], set[str]]:
        """Collect router-level and parameter-level dependency injection calls.

        Returns the list of generated source-code lines and the set of parameter
        names that were satisfied by a parameter-level ``Depends(...)``.
        """
        dependency_calls: list[str] = []
        dependency_names: set[str] = set()

        seen_router_dependency_funcs: set = set()
        for dependency in PathHandler.get_router_dependencies(path):
            dependency_func = getattr(dependency, "dependency", None)
            if (
                callable(dependency_func)
                and dependency_func not in seen_router_dependency_funcs
                and MethodDefinition._is_safe_dependency(dependency_func)
            ):
                dependency_identifier = MethodDefinition._dependency_identifier(
                    dependency_func
                )
                dependency_calls.append(
                    f"        {dependency_identifier} = {dependency_func.__name__}()"
                )
                dependency_calls.append(
                    f"        kwargs['{dependency_identifier}'] = {dependency_identifier}"
                )
                seen_router_dependency_funcs.add(dependency_func)

        for name, param in parameter_map.items():
            if not isinstance(param.annotation, _AnnotatedAlias):
                continue
            for meta in param.annotation.__metadata__:
                if not (hasattr(meta, "dependency") and meta.dependency is not None):
                    continue
                dependency_func = meta.dependency
                func_name = dependency_func.__name__
                if MethodDefinition._is_safe_dependency(dependency_func):
                    dependency_calls.append(f"        {name} = {func_name}()")
                    dependency_names.add(name)
                elif (
                    surfaced := MethodDefinition._surface_dependency(dependency_func)
                ) is not None:
                    _, call_args = surfaced
                    dependency_calls.append(
                        f"        {name} = {func_name}({call_args})"
                    )
                    dependency_names.add(name)

        return dependency_calls, dependency_names

    @staticmethod
    def build_command_method_body(
        path: str,
        func: Callable,
        formatted_params: OrderedDict[str, Parameter] | None = None,
    ):
        """Build the command method implementation."""
        if formatted_params is None:
            formatted_params = OrderedDict()

        sig = signature(func)
        parameter_map = dict(sig.parameters)
        parameter_map.pop("cc", None)

        dependency_calls, dependency_names = MethodDefinition._collect_dependency_calls(
            path, parameter_map
        )

        code = ""

        if dependency_calls:
            code += "\n".join(dependency_calls) + "\n\n"

        if (
            CHARTING_INSTALLED
            and Charting is not None
            and path.replace("/", "_")[1:] in Charting.functions()
        ):
            parameter_map["chart"] = Parameter(
                name="chart",
                kind=Parameter.POSITIONAL_OR_KEYWORD,
                annotation=bool,
                default=False,
            )

        if MethodDefinition.is_deprecated_function(path):
            deprecation_message = MethodDefinition.get_deprecation_message(path)
            code += "        simplefilter('always', DeprecationWarning)\n"
            code += f"""        warn("{deprecation_message}", category=DeprecationWarning, stacklevel=2)\n\n"""

        info = {}

        code += "        return self._run(\n"
        code += f"""            "{path}",\n"""
        code += "            **filter_inputs(\n"

        # Check if we already have a kwargs parameter (VAR_KEYWORD) in formatted_params
        has_kwargs = any(
            param.kind == Parameter.VAR_KEYWORD for param in formatted_params.values()
        )
        has_extra_params = False

        for name, param in parameter_map.items():
            is_dependency = isinstance(param.annotation, _AnnotatedAlias) and any(
                getattr(meta, "dependency", None) is not None
                for meta in param.annotation.__metadata__
            )
            if is_dependency:
                if name in dependency_names:
                    code += f"                {name}={name},\n"
                continue
            if name == "extra_params":
                has_extra_params = True
                fields = (
                    param.annotation.__args__[0].__dataclass_fields__
                    if hasattr(param.annotation, "__args__")
                    else param.annotation
                )
                values = {k: k for k in fields}
                for k in values:
                    if extra := MethodDefinition.get_extra(fields[k]):
                        info[k] = extra
                code += f"                {name}=kwargs,\n"
            elif name == "provider_choices":
                field = param.annotation.__args__[0].__dataclass_fields__["provider"]
                available = field.type.__args__
                cmd = path.strip("/").replace("/", ".")
                code += "                provider_choices={\n"
                code += '                    "provider": self._get_provider(\n'
                code += "                        provider,\n"
                code += f'                        "{cmd}",\n'
                code += f"                        {available},\n"
                code += "                    )\n"
                code += "                },\n"
            elif MethodDefinition.is_annotated_dc(param.annotation):
                fields = param.annotation.__args__[0].__dataclass_fields__
                values = {k: k for k in fields}
                code += f"                {name}={{\n"
                for k, v in values.items():
                    code += f'                    "{k}": {v},\n'
                    if extra := MethodDefinition.get_extra(fields[k]):
                        info[k] = extra
                code += "                },\n"
            elif (
                qp_model := MethodDefinition.query_params_model(param.annotation)
            ) is not None:
                # Re-pack the flattened kwargs into the ``QueryParams`` model
                # the route declares — the inverse of the flattening done in
                # ``format_params``.
                code += f"                {name}={{\n"
                for field_name in qp_model.model_fields:
                    code += f'                    "{field_name}": {field_name},\n'
                code += "                },\n"
            elif (
                isinstance(param.annotation, _AnnotatedAlias)
                and (
                    hasattr(param.annotation.__args__[0], "model_fields")
                    or hasattr(param.annotation.__args__[0], "__pydantic_fields__")
                )
                and not MethodDefinition.is_data_processing_function(path)
            ):
                model = param.annotation.__args__[0]
                fields = getattr(
                    model,
                    "model_fields",
                    getattr(model, "__pydantic_fields__", {}),
                )
                values = {k: k for k in fields}
                code += f"                {name}={{\n"
                for k, v in values.items():
                    code += f'                    "{k}": {v},\n'
                code += "                },\n"
            elif isclass(param.annotation) and issubclass(
                param.annotation, QueryParams
            ):
                # Repack the unpacked QueryParams fields into a dict for the route.
                model = param.annotation
                fields = getattr(
                    model,
                    "model_fields",
                    getattr(model, "__pydantic_fields__", {}),
                )
                code += f"                {name}={{\n"
                for field_name in fields:
                    code += f'                    "{field_name}": {field_name},\n'
                code += "                },\n"
            elif name != "kwargs":
                code += f"                {name}={name},\n"

        if info:
            code += f"                info={info},\n"

        if MethodDefinition.is_data_processing_function(path):
            code += "                data_processing=True,\n"

        # Add kwargs parameter
        if has_kwargs and not has_extra_params:
            code += "                **kwargs,\n"

        code += "            )\n"
        code += "        )\n"

        return code

    @classmethod
    def get_expanded_type(
        cls,
        field_name: str,
        extra: dict | None = None,
        original_type: type | None = None,
    ) -> object:
        """Expand the original field type."""
        if extra and any(
            (
                v.get("multiple_items_allowed")
                if isinstance(v, dict)
                # For backwards compatibility, before this was a list
                else "multiple_items_allowed" in v
            )
            for v in extra.values()
        ):
            if original_type is None:
                raise ValueError(
                    "multiple_items_allowed requires the original type to be specified."
                )
            return list[original_type]  # type: ignore
        return cls.TYPE_EXPANSION.get(field_name, ...)

    @classmethod
    def build_command_method(
        cls,
        path: str,
        func: Callable,
        model_name: str | None = None,
        examples: list[Example] | None = None,
        response_model: Any = None,
    ) -> str:
        """Build the command method."""
        path_parts = [p for p in path.split("/") if p and not p.startswith("{")]
        func_name = (
            path_parts[-1].replace("-", "_") if path_parts else func.__name__  # ty: ignore[unresolved-attribute]
        )
        sig = signature(func)
        parameter_map = dict(sig.parameters)
        # Get the function source code and extract filter_inputs parameters
        additional_params = {}

        if hasattr(func, "__code__"):
            try:
                func_source = inspect.getsource(func)

                # First, find the filter_inputs block to extract parameter names
                filter_inputs_match = re.search(
                    r"filter_inputs\(\s*(.*?)\s*\)", func_source, re.DOTALL
                )
                if filter_inputs_match:
                    filter_inputs_text = filter_inputs_match.group(1)
                    filter_params = re.findall(r"(\w+)=(\w+)", filter_inputs_text)

                    # Then look for parameter definitions in function body
                    # Find parameters defined with types in comments or actual code
                    param_defs = re.findall(
                        r"(\w+)\s*:\s*(\w+)(?:\s*=\s*([^,\n]+))?", func_source
                    )
                    param_dict = {
                        name: (typ, default) for name, typ, default in param_defs
                    }

                    # Add missing parameters preserving types when available
                    for param_name, param_value in filter_params:
                        if (
                            param_name != param_value
                            and param_value not in parameter_map
                            and param_value not in ["True", "False", "None"]
                        ):
                            # Use type from param_dict if available, otherwise Any
                            if param_value in param_dict:
                                param_type = param_dict[param_value][0]
                                try:
                                    # Try to evaluate the type
                                    annotation = eval(param_type)  # noqa: S307
                                except (NameError, SyntaxError):
                                    annotation = Any

                                # Get default if available
                                default_str = param_dict[param_value][1]
                                try:
                                    default = (
                                        eval(default_str)  # noqa: S307
                                        if default_str
                                        else None
                                    )
                                except (NameError, SyntaxError):
                                    default = None
                            else:
                                annotation = Any
                                default = None

                            # Add parameter with preserved type/default
                            additional_params[param_value] = Parameter(
                                name=param_value,
                                kind=Parameter.POSITIONAL_OR_KEYWORD,
                                annotation=annotation,
                                default=default,
                            )
            except (OSError, TypeError):
                pass

        # Add missing parameters to parameter_map
        for name, param in additional_params.items():
            if name not in parameter_map:
                parameter_map[name] = param

        for name, param in cls._collect_surfaced_params(parameter_map).items():
            if name not in parameter_map:
                parameter_map[name] = param

        formatted_params = cls.format_params(
            path=path, parameter_map=parameter_map, func=func
        )

        has_var_kwargs = any(
            param.kind == Parameter.VAR_KEYWORD for param in formatted_params.values()
        )

        # If not, add **kwargs to formatted_params
        if not has_var_kwargs:
            formatted_params["kwargs"] = Parameter(
                name="kwargs",
                kind=Parameter.VAR_KEYWORD,
                annotation=Any,
                default=Parameter.empty,
            )

        return_type = sig.return_annotation
        if return_type is signature(func).empty and response_model is not None:
            return_type = response_model

        code = cls.build_command_method_signature(
            func_name=func_name,
            formatted_params=formatted_params,
            return_type=return_type,
            path=path,
            model_name=model_name,
        )
        code += cls.build_command_method_doc(
            path=path,
            func=func,
            formatted_params=formatted_params,
            model_name=model_name,
            examples=examples,
            return_type=return_type,
        )

        code += cls.build_command_method_body(
            path=path, func=func, formatted_params=formatted_params
        )

        return code
