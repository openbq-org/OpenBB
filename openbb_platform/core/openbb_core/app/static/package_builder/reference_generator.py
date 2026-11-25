"""Reference (reference.json) generator for the static package."""

import inspect
import re
import sys
from collections.abc import Callable
from inspect import Parameter, signature
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    TypeVar,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

from pydantic_core import PydanticUndefined
from starlette.routing import BaseRoute
from typing_extensions import _AnnotatedAlias

from openbb_core.app.model.example import Example
from openbb_core.app.router import RouterLoader

if TYPE_CHECKING:
    from numpy import ndarray  # noqa
    from pandas import DataFrame, Series  # noqa
    from openbb_core.provider.abstract.data import Data  # noqa

try:
    _HAS_FCNTL = True
except Exception:  # noqa  # pragma: no cover
    _HAS_FCNTL = False
    import msvcrt  # noqa  # pragma: no cover

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
from openbb_core.app.static.package_builder.method_definition import MethodDefinition
from openbb_core.app.static.package_builder.path_handler import PathHandler


class ReferenceGenerator:
    """Generate the reference for the Platform."""

    REFERENCE_FIELDS = [
        "deprecated",
        "description",
        "examples",
        "parameters",
        "returns",
        "data",
    ]

    pi = DocstringGenerator.provider_interface
    route_map = PathHandler.build_route_map()

    @classmethod
    def _get_endpoint_examples(
        cls,
        path: str,
        func: Callable,
        examples: list[Example] | None,
    ) -> str:
        """Get the examples for the given standard model or function.

        For a given standard model or function, the examples are fetched from the
        list of Example objects and formatted into a string.

        Parameters
        ----------
        path : str
            Path of the router.
        func : Callable
            Router endpoint function.
        examples : Optional[List[Example]]
            List of Examples (APIEx or PythonEx type) for the endpoint.

        Returns
        -------
        str:
            Formatted string containing the examples for the endpoint.
        """
        sig = signature(func)
        parameter_map = dict(sig.parameters)
        formatted_params = MethodDefinition.format_params(
            path=path, parameter_map=parameter_map, func=func
        )
        explicit_params = dict(formatted_params)
        explicit_params.pop("extra_params", None)
        param_types = {k: v.annotation for k, v in explicit_params.items()}

        return DocstringGenerator.build_examples(
            path.replace("/", "."),
            param_types,
            examples,
            "website",
        )

    @classmethod
    def _get_provider_parameter_info(cls, model: str) -> dict[str, Any]:
        """Get the name, type, description, default value and optionality information for the provider parameter.

        Parameters
        ----------
        model : str
            Standard model to access the model providers.

        Returns
        -------
        Dict[str, Any]
            Dictionary of the provider parameter information
        """
        pi_model_provider = cls.pi.model_providers[model]
        provider_params_field = pi_model_provider.__dataclass_fields__["provider"]

        name = provider_params_field.name
        field_type = DocstringGenerator.get_field_type(
            provider_params_field.type, False
        )
        default_priority = (
            provider_params_field.type.__args__
            if provider_params_field.type
            and hasattr(provider_params_field.type, "__args__")
            else []
        )
        description = (
            "The provider to use, by default None. "
            "If None, the priority list configured in the settings is used. "
            f"Default priority: {', '.join(default_priority)}."
        )

        provider_parameter_info = {
            "name": name,
            "type": field_type,
            "description": description,
            "default": None,
            "optional": True,
        }

        return provider_parameter_info

    @classmethod
    def _get_provider_field_params(
        cls, model: str, params_type: str, provider: str = "openbb"
    ) -> list[dict[str, Any]]:
        """Get the fields of the given parameter type for the given provider of the standard_model."""
        provider_field_params = []
        expanded_types = MethodDefinition.TYPE_EXPANSION
        model_map = cls.pi.map[model]

        # First, check if the provider class itself has __json_schema_extra__
        # This contains class-level schema information that applies to fields
        class_schema_extra = {}
        try:
            # Get the actual provider class
            provider_class = model_map[provider][params_type]["class"]
            # Check for class-level __json_schema_extra__ attribute
            if hasattr(provider_class, "__json_schema_extra__"):
                class_schema_extra = provider_class.__json_schema_extra__
        except (KeyError, AttributeError):
            pass

        for field, field_info in model_map[provider][params_type]["fields"].items():
            # Start with class-level schema information for this field if it exists
            extra = {}
            choices = None
            if field in class_schema_extra:
                extra = class_schema_extra[field].copy()
                choices = extra.get("choices")

            # Then apply field-level schema extra (which takes precedence)
            field_extra = field_info.json_schema_extra or {}
            extra.update(field_extra)
            if "choices" in field_extra:
                choices = field_extra.pop("choices", [])

            if provider != "openbb" and provider in extra:
                extra = extra[provider]

            field_type_str, is_required = cls._resolve_field_type_str(field_info)

            cleaned_description = str(field_info.description).strip().replace('"', "'")

            # Add information for the providers supporting multiple symbols
            if params_type == "QueryParams" and extra:
                cleaned_description, field_type_str, choices = (
                    cls._apply_query_param_extras(
                        cleaned_description, field_type_str, choices, extra
                    )
                )
            elif field in expanded_types:
                expanded_type = DocstringGenerator.get_field_type(
                    expanded_types[field], is_required, "website"
                )
                field_type_str = f"{field_type_str} | {expanded_type}"

            default_value = (
                None if field_info.default is PydanticUndefined else field_info.default
            )
            if default_value == "":
                default_value = None

            to_append = {
                "name": field,
                "type": field_type_str,
                "description": cleaned_description,
                "default": default_value,
                "optional": not is_required,
            }
            if params_type != "Data":
                to_append.update(
                    {
                        "choices": choices or extra.pop("choices", []),
                        "multiple_items_allowed": extra.pop(
                            "multiple_items_allowed", False
                        ),
                        "json_schema_extra": extra or {},
                    }
                )
            else:
                to_append.update({"json_schema_extra": extra or {}})
            provider_field_params.append(to_append)

        return provider_field_params

    @staticmethod
    def _resolve_field_type_str(field_info: Any) -> tuple[str, bool]:
        """Resolve a Pydantic ``FieldInfo`` to a display type string and required flag.

        Strips ``Optional[...]`` / ``Union[..., None]`` wrappers and any
        ``Annotated[...]`` layers, returning the cleaned type string and the
        adjusted ``is_required`` flag.
        """
        field_type = field_info.annotation
        is_required = field_info.is_required()

        origin = get_origin(field_type)
        if origin is Union:
            args = get_args(field_type)
            non_none_types = [arg for arg in args if arg is not type(None)]
            if non_none_types:
                field_type = non_none_types[0]
            if type(None) in args:
                is_required = False

        # Then unwrap Annotated
        while get_origin(field_type) is Annotated:
            args = get_args(field_type)
            if not args:
                break
            field_type = args[0]

        field_type_str = DocstringGenerator.get_field_type(
            field_type, is_required, "website"
        )

        if field_type_str == "Annotated | None" or field_type_str.startswith(
            "Annotated"
        ):
            if hasattr(field_type, "__name__") or isinstance(field_type, type):
                field_type_str = field_type.__name__
            else:
                type_repr = str(field_type).replace("typing.", "")
                if "Annotated[" in type_repr:
                    match = re.search(r"Annotated\[([^,\]]+)", type_repr)
                    if match:
                        field_type_str = match.group(1)
                else:
                    field_type_str = type_repr

        if is_required is False and "| None" not in field_type_str:
            field_type_str = f"{field_type_str} | None"

        if ", optional" in field_type_str:
            field_type_str = field_type_str.replace(", optional", "")
            is_required = False

        return field_type_str, is_required

    @staticmethod
    def _apply_query_param_extras(
        cleaned_description: str,
        field_type_str: str,
        choices: Any,
        extra: dict,
    ) -> tuple[str, str, Any]:
        """Augment a query-param description / type for ``multiple_items_allowed`` providers."""
        providers: list = []
        for p, v in extra.items():
            if isinstance(v, dict) and v.get("multiple_items_allowed"):
                providers.append(p)
                if "choices" in v:
                    choices = v.get("choices")
            elif isinstance(v, list) and "multiple_items_allowed" in v:
                providers.append(p)
            elif isinstance(v, dict) and "choices" in v:
                choices = v.get("choices")

        if providers or extra.get("multiple_items_allowed"):
            cleaned_description += " Multiple items allowed"
            if providers:
                multiple_items = ", ".join(providers)
                cleaned_description += f" for provider(s): {multiple_items}"
            cleaned_description += "."
            field_type_str = f"{field_type_str} | list[{field_type_str}]"

        return cleaned_description, field_type_str, choices

    @staticmethod
    def _get_obbject_returns_fields(
        model: str,
        providers: str,
    ) -> list[dict[str, str]]:
        """Get the fields of the OBBject returns object for the given standard_model.

        Parameters
        ----------
        model : str
            Standard model of the returned object.
        providers : str
            Available providers for the model.

        Returns
        -------
        List[Dict[str, str]]
            List of dictionaries containing the field name, type, description, default
            and optionality of each field.
        """
        obbject_list = [
            {
                "name": "results",
                "type": model,
                "description": "Serializable results.",
            },
            {
                "name": "provider",
                "type": providers if providers else "str",
                "description": "Provider name.",
            },
            {
                "name": "warnings",
                "type": "Optional[list[Warning_]]",
                "description": "List of warnings.",
            },
            {
                "name": "chart",
                "type": "Optional[Chart]",
                "description": "Chart object.",
            },
            {
                "name": "extra",
                "type": "dict[str, Any]",
                "description": "Extra info.",
            },
        ]

        return obbject_list

    @staticmethod
    def _get_post_method_parameters_info(
        docstring: str,
    ) -> list[dict[str, bool | str]]:
        """Get the parameters for the POST method endpoints.

        Parameters
        ----------
        docstring : str
            Router endpoint function's docstring

        Returns
        -------
        List[Dict[str, str]]
            List of dictionaries containing the name, type, description, default
            and optionality of each parameter.
        """
        parameters_list: list = []

        # Extract only the Parameters section (between "Parameters" and "Returns")
        params_section = ""
        if "Parameters" in docstring and "Returns" in docstring:
            params_section = docstring.split("Parameters")[1].split(
                "Returns", maxsplit=1
            )[0]
        elif "Parameters" in docstring:
            params_section = docstring.split("Parameters")[1]
        else:
            return parameters_list  # No parameters section found

        # Define a regex pattern to match parameter blocks
        # This pattern looks for a parameter name followed by " : ", then captures the type and description
        pattern = re.compile(
            r"\n\s*(?P<name>\w+)\s*:\s*(?P<type>[^\n]+?)(?:\s*=\s*(?P<default>[^\n]+))?\n\s*(?P<description>[^\n]+)"
        )

        # Find all matches in the parameters section only
        matches = list(pattern.finditer(params_section))

        if matches:
            # Iterate over the matches to extract details
            for match in matches:
                # Extract named groups as a dictionary
                param_info = match.groupdict()

                # Clean up and process the type string
                param_type = param_info["type"].strip()

                # Check for ", optional" in type and handle appropriately
                is_optional = "Optional" in param_type or ", optional" in param_type
                if ", optional" in param_type:
                    param_type = param_type.replace(", optional", "")

                # If no default value is captured, set it to an empty string
                default_value = (
                    param_info["default"] if param_info["default"] is not None else ""
                )
                param_type = (
                    str(param_type)
                    .replace("openbb_core.provider.abstract.data.Data", "Data")
                    .replace("List", "list")
                    .replace("Dict", "dict")
                    .replace("NoneType", "None")
                )
                # Create a new dictionary with fields in the desired order
                param_dict = {
                    "name": param_info["name"],
                    "type": ReferenceGenerator._clean_string_values(param_type),
                    "description": ReferenceGenerator._clean_string_values(
                        param_info["description"]
                    ),
                    "default": default_value,
                    "optional": is_optional,
                }

                # Append the dictionary to the list
                parameters_list.append(param_dict)

        return parameters_list

    @staticmethod
    def _clean_string_values(value: Any) -> Any:
        """Convert double quotes in string values to single quotes and fix type references.

        Parameters
        ----------
        value : Any
            The value to clean

        Returns
        -------
        Any
            The cleaned value
        """
        if isinstance(value, str):
            # Fix fully qualified Data type references
            value = re.sub(
                r"list\[openbb_core\.provider\.abstract\.data\.Data\]",
                "list[Data]",
                value,
            )
            value = re.sub(
                r"openbb_core\.provider\.abstract\.data\.Data", "Data", value
            )

            # Clean up Union types
            if "Union[" in value:
                try:
                    # Extract types from Union
                    types_str = value[value.find("[") + 1 : value.rfind("]")]
                    # Split types and clean them up
                    types = [t.strip() for t in types_str.split(",")]
                    # Use a set to handle unique types and maintain order for display
                    unique_types = sorted(list(set(types)))
                    # Rebuild the string with " | " separator
                    value = " | ".join(unique_types)
                except Exception:  # noqa
                    pass

            # Handle Literal types specifically
            if (
                "Literal[" in value
                and "]" in value
                and "'" not in value
                and '"' not in value
            ):
                # Extract the content between Literal[ and ]
                start_idx = value.find("Literal[") + len("Literal[")
                end_idx = value.rfind("]")
                if start_idx < end_idx:
                    content = value[start_idx:end_idx]
                    # Add single quotes around each value
                    values = [f"'{v.strip()}'" for v in content.split(",")]
                    # Reconstruct the Literal type
                    return f"Literal[{', '.join(values)}]"

            value = re.sub(r"\bDict\b", "dict", value)
            value = re.sub(r"\bList\b", "list", value)

            return value.replace('"', "'")

        if isinstance(value, dict):
            return {
                k: ReferenceGenerator._clean_string_values(v) for k, v in value.items()
            }

        if isinstance(value, list):
            return [ReferenceGenerator._clean_string_values(item) for item in value]

        return value

    @staticmethod
    def _get_function_signature_info(func: Callable) -> list[dict[str, Any]]:
        """Extract parameter information directly from function signature."""
        params_info = []
        sig = signature(func)

        for name, param in sig.parameters.items():
            # Skip 'self' and context parameters
            if name in ["self", "cc"]:
                continue

            # Skip parameters with dependency injections through annotations
            if isinstance(param.annotation, _AnnotatedAlias) and any(
                hasattr(meta, "dependency") for meta in param.annotation.__metadata__
            ):
                continue

            # Skip parameters with Depends in default values
            if param.default is not Parameter.empty:
                default_str = str(param.default)
                if "Depends" in default_str:
                    continue

            param_type = param.annotation
            is_optional = (
                param.default is not Parameter.empty
            )  # Parameter is optional if it has a default value
            description = ""
            choices = None
            default = param.default if param.default is not Parameter.empty else None

            if default is PydanticUndefined:
                default = None
            json_extra: dict = {}

            # Check if type is optional
            if (
                hasattr(param_type, "__origin__")
                and param_type.__origin__ is Union
                and (type(None) in param_type.__args__ or None in param_type.__args__)
            ):
                # Check if None or NoneType is in the union
                is_optional = True
                # Extract the actual type (excluding None)
                non_none_args = [
                    arg
                    for arg in param_type.__args__
                    if arg is not type(None) and arg is not None
                ]
                if len(non_none_args) == 1:
                    param_type = non_none_args[0]

            if isinstance(param_type, _AnnotatedAlias):
                base_type = param_type.__args__[0]
                for meta in param_type.__metadata__:
                    if hasattr(meta, "description"):
                        description = meta.description
                    if hasattr(meta, "choices"):
                        choices = meta.choices
                    if hasattr(meta, "default"):
                        default = meta.default
                    if hasattr(meta, "json_schema_extra"):
                        json_extra = meta.json_schema_extra or {}

                # Set the actual type to the base type
                param_type = base_type

            # Handle Query objects passed as parameters or default values.
            if str(default.__class__).endswith("Query'>") or "Query" in str(
                default.__class__
            ):
                param_type = (
                    param_type.annotation
                    if hasattr(param_type, "annotation")
                    else str(param_type)
                )
                description = default.description  # type: ignore
                json_extra = default.json_schema_extra or {}  # type: ignore
                has_default = hasattr(default, "default") and default.default not in [
                    Parameter.empty,
                    PydanticUndefined,
                    Ellipsis,
                ]
                is_optional = has_default or (
                    hasattr(default, "is_required") and default.is_required is False
                )
                default = (
                    default.default  # ty: ignore[unresolved-attribute]
                    if default.default  # ty: ignore[unresolved-attribute]
                    not in [Parameter.empty, PydanticUndefined, Ellipsis]
                    else None
                )

            # Convert type to string representation
            type_str = str(param_type)
            # Clean up type string
            type_str = (
                type_str.replace("<class '", "")
                .replace("'>", "")
                .replace("typing.", "")
                .replace("NoneType", "None")
                .replace("inspect._empty", "Any")
            )
            params_info.append(
                {
                    "name": name,
                    "type": type_str,
                    "description": ReferenceGenerator._clean_string_values(description),
                    "default": (
                        None
                        if default in (PydanticUndefined, Parameter.empty, Ellipsis)
                        else ReferenceGenerator._clean_string_values(default)
                    ),
                    "optional": is_optional,
                    "choices": choices or json_extra.pop("choices", []),
                    "multiple_items_allowed": json_extra.pop(
                        "multiple_items_allowed", False
                    ),
                    "json_schema_extra": json_extra or {},
                }
            )

        return params_info

    @staticmethod
    def _get_post_method_returns_info(docstring: str) -> dict:
        """Get the returns information for the POST method endpoints.

        Parameters
        ----------
        docstring: str
            Router endpoint function's docstring

        Returns
        -------
        List[Dict[str, str]]
            Single element list having a dictionary containing the name, type,
            description of the return value
        """
        returns_dict: dict = {}
        # This pattern captures the model name inside "OBBject[]" and its description
        match = re.search(r"Returns\n\s*-------\n\s*([^\n]+)\n\s*([^\n]+)", docstring)

        if match:
            return_type = match.group(1).strip()
            # Remove newlines and indentation from the description
            description = match.group(2).strip().replace("\n", "").replace("    ", "")
            # Adjust regex to correctly capture content inside brackets, including nested brackets
            content_inside_brackets = re.search(
                r"OBBject\[\s*((?:[^\[\]]|\[[^\[\]]*\])*)\s*\]", return_type
            ) or re.search(r"list\[\s*((?:[^\[\]]|\[[^\[\]]*\])*)\s*\]", return_type)
            return_type = (
                content_inside_brackets.group(1)
                if content_inside_brackets is not None
                else return_type
            )

            returns_dict = {
                "name": "results",
                "type": return_type,
                "description": description,
            }

        return returns_dict

    @classmethod
    def get_paths(  # noqa: PLR0912
        cls, route_map: dict[str, BaseRoute]
    ) -> dict[str, dict[str, Any]]:
        """Get path reference data.

        The reference data is a dictionary containing the description, parameters,
        returns and examples for each endpoint. This is currently useful for
        automating the creation of the website documentation files.

        Returns
        -------
        Dict[str, Dict[str, Any]]
            Dictionary containing the description, parameters, returns and
            examples for each endpoint.
        """
        reference: dict[str, dict] = {}

        for path, route in route_map.items():
            # Initialize the provider parameter fields as an empty dictionary
            provider_parameter_fields = {"type": ""}
            # Initialize the reference fields as empty dictionaries
            reference[path] = {field: {} for field in cls.REFERENCE_FIELDS}
            # Route method is used to distinguish between GET and POST methods
            route_method = getattr(route, "methods", None)
            # Route endpoint is the callable function
            route_func = getattr(route, "endpoint", lambda: None)
            # Attribute contains the model and examples info for the endpoint
            openapi_extra = getattr(route, "openapi_extra", {}) or {}
            # Standard model is used as the key for the ProviderInterface Map dictionary
            standard_model = openapi_extra.get("model", "")
            # Add endpoint model for GET methods
            reference[path]["model"] = standard_model
            # Add endpoint deprecation details
            reference[path]["deprecated"] = {
                "flag": MethodDefinition.is_deprecated_function(path),
                "message": MethodDefinition.get_deprecation_message(path),
            }
            # Add endpoint examples
            examples = openapi_extra.get("examples", [])
            reference[path]["examples"] = cls._get_endpoint_examples(
                path,
                route_func,
                examples,
            )
            validate_output = not openapi_extra.get("no_validate", None)
            model_map = cls.pi.map.get(standard_model, {})
            # Exclude transient keys that were only needed above
            reference[path]["openapi_extra"] = {
                k: v
                for k, v in openapi_extra.items()
                if k not in ("examples", "no_validate")
            }

            # Extract return type information for all endpoints
            return_info = cls._extract_return_type(route_func)

            # Add data for the endpoints having a standard model
            if route_method and model_map:
                reference[path]["description"] = getattr(
                    route, "description", "No description available."
                )
                for provider in model_map:
                    if provider == "openbb":
                        # openbb provider is always present hence its the standard field
                        reference[path]["parameters"]["standard"] = (
                            cls._get_provider_field_params(
                                standard_model, "QueryParams"
                            )
                        )
                        # Add `provider` parameter fields to the openbb provider
                        provider_parameter_fields = cls._get_provider_parameter_info(
                            standard_model
                        )

                        # Add endpoint data fields for standard provider
                        reference[path]["data"]["standard"] = (
                            cls._get_provider_field_params(standard_model, "Data")
                        )
                        continue

                    # Adds provider specific parameter fields to the reference
                    reference[path]["parameters"][provider] = (
                        cls._get_provider_field_params(
                            standard_model, "QueryParams", provider
                        )
                    )

                    # Adds provider specific data fields to the reference
                    reference[path]["data"][provider] = cls._get_provider_field_params(
                        standard_model, "Data", provider
                    )

                    # Remove choices from standard parameters if they exist in provider-specific parameters
                    provider_param_names = {
                        p["name"] for p in reference[path]["parameters"][provider]
                    }

                    for i, param in enumerate(
                        reference[path]["parameters"]["standard"]
                    ):
                        param_name = param.get("name")
                        if (
                            param_name in provider_param_names
                            and param.get("choices") is not None
                        ):
                            # This parameter has a provider-specific version, so remove choices from standard
                            reference[path]["parameters"]["standard"][i]["choices"] = (
                                None
                            )

                # Add endpoint returns data
                if validate_output is False:
                    reference[path]["returns"]["Any"] = {
                        "description": "Unvalidated results object.",
                    }
                else:
                    providers = provider_parameter_fields["type"]
                    if isinstance(return_info, dict) and "OBBject" in return_info:
                        results_field = next(
                            (
                                f
                                for f in return_info["OBBject"]
                                if f["name"] == "results"
                            ),
                            None,
                        )
                        if results_field:
                            results_type = results_field["type"]
                            if results_type == "Any":
                                results_type = f"list[{standard_model}]"
                            reference[path]["returns"]["OBBject"] = (
                                cls._get_obbject_returns_fields(results_type, providers)
                            )
            # Add data for the endpoints without a standard model (data processing endpoints)
            else:
                results_type = "Any"
                openapi_extra = (
                    getattr(
                        route_func, "openapi_extra", getattr(route, "openapi_extra", {})
                    )
                    or {}
                )

                model_name = openapi_extra.get("model", "") or ""
                if isinstance(return_info, dict) and "OBBject" in return_info:
                    results_field = next(
                        (f for f in return_info["OBBject"] if f["name"] == "results"),
                        None,
                    )
                    if results_field:
                        results_type = results_field["type"]
                        # Extract model name from types like list[Model] or Model
                        if "[" in results_type and "]" in results_type:
                            inner_type = results_type.split("[")[1].split("]")[0]
                            extracted_model = (
                                inner_type.split(".")[-1]
                                if "." in inner_type
                                else inner_type
                            )
                            model_name = model_name or extracted_model
                        else:
                            extracted_model = (
                                results_type.split(".")[-1]
                                if "." in results_type
                                else results_type
                            )
                            model_name = model_name or extracted_model

                formatted_params = MethodDefinition.format_params(
                    path=path,
                    parameter_map=dict(signature(route_func).parameters),
                    func=route_func,
                )

                docstring = DocstringGenerator.generate(
                    path=path,
                    func=route_func,
                    formatted_params=formatted_params,
                    model_name=model_name,
                    examples=examples,
                )
                if not docstring:
                    continue

                description = docstring.split("Parameters")[0].strip()
                reference[path]["description"] = re.sub(" +", " ", description)

                # Extract parameters directly from formatted_params
                reference[path]["parameters"]["standard"] = []
                for param in formatted_params.values():
                    if param.name == "kwargs":
                        continue
                    annotation = param.annotation
                    if isinstance(annotation, _AnnotatedAlias):
                        type_str = DocstringGenerator.get_field_type(
                            annotation.__args__[0], False, "website"
                        )
                        # Search all metadata items for a description
                        description = ""
                        for meta in annotation.__metadata__:
                            desc = getattr(meta, "description", "")
                            if desc:
                                description = desc
                                break
                    else:
                        type_str = DocstringGenerator.get_field_type(
                            annotation, False, "website"
                        )
                        description = ""
                    reference[path]["parameters"]["standard"].append(
                        {
                            "name": param.name,
                            "type": type_str,
                            "description": description,
                            "default": (
                                param.default
                                if param.default != Parameter.empty
                                else None
                            ),
                            "optional": param.default != Parameter.empty,
                        }
                    )
                # Set returns based on return_info
                if isinstance(return_info, dict) and "OBBject" in return_info:
                    results_field = next(
                        (f for f in return_info["OBBject"] if f["name"] == "results"),
                        None,
                    )
                    if results_field:
                        results_type = results_field["type"]
                        reference[path]["returns"]["OBBject"] = (
                            cls._get_obbject_returns_fields(results_type, "str")
                        )

                # Extract data fields from the model class if results_type is not "Any"
                if results_type != "Any":
                    # Try to extract model name
                    if "[" in results_type:
                        if results_type.startswith("list["):
                            extracted_model_name = results_type[5:-1]
                        else:
                            extracted_model_name = results_type.split("[")[1].split(
                                "]"
                            )[0]
                    else:
                        extracted_model_name = results_type

                    # Try to get the model class from the function's module
                    try:
                        module = sys.modules[route_func.__module__]
                        model_class = getattr(module, extracted_model_name, None)
                        if model_class and hasattr(model_class, "model_fields"):
                            # Set data to the fields
                            reference[path]["data"]["standard"] = []
                            for field_name, field in getattr(
                                model_class, "model_fields", {}
                            ).items():
                                field_type = DocstringGenerator.get_field_type(
                                    field.annotation, field.is_required(), "website"
                                )
                                json_extra = getattr(field, "json_schema_extra", {})
                                reference[path]["data"]["standard"].append(
                                    {
                                        "name": field_name,
                                        "type": field_type,
                                        "description": getattr(
                                            field, "description", ""
                                        ),
                                        "default": (
                                            None
                                            if field.default is PydanticUndefined
                                            else field.default
                                        ),
                                        "optional": not field.is_required(),
                                        "json_schema_extra": json_extra or {},
                                    }
                                )
                    except (KeyError, AttributeError):
                        pass

        return reference

    @staticmethod
    def _extract_return_type(func: Callable) -> str | dict:
        """Extract return type information from function."""
        return_annotation = inspect.signature(func).return_annotation

        # If no return annotation, or return annotation is inspect.Signature.empty
        if return_annotation is inspect.Signature.empty:
            return {"type": "Any"}

        # Use get_type_hints to resolve TypeVars
        hints = get_type_hints(func)
        return_annotation = hints.get("return", return_annotation)

        # Check if the return type is an OBBject
        type_str = str(return_annotation)
        if "OBBject" in type_str or (
            hasattr(return_annotation, "__name__")
            and "OBBject" in return_annotation.__name__
        ):
            # Extract the model name from docstring or type annotation
            result_type = "Any"  # Default fallback

            # Try to extract from type annotation first (more reliable)
            args = get_args(return_annotation)
            # Pydantic generic aliases are concrete classes - read their metadata.
            if not args:
                pgm = getattr(return_annotation, "__pydantic_generic_metadata__", {})
                args = tuple(pgm.get("args") or ())
            if args:
                if len(args) > 1:
                    # For OBBject[T, SomeType], results type is SomeType
                    result_type = args[1].__name__
                else:
                    # For OBBject[SomeType]
                    inner_type = args[0]
                    if inner_type is not None:
                        # Handle container types like list[Model]
                        inner_origin = get_origin(inner_type)
                        if inner_origin is not None:
                            inner_args = get_args(inner_type)
                            if inner_args:
                                container_type = inner_origin
                                model_type = inner_args[0]
                                result_type = (
                                    f"{container_type.__name__}[{model_type.__name__}]"
                                )
                        elif hasattr(inner_type, "__name__"):
                            result_type = inner_type.__name__
                            # Resolve TypeVar bound if available
                            if (
                                hasattr(inner_type, "__bound__")
                                and inner_type.__bound__
                            ):
                                result_type = inner_type.__bound__.__name__
                        elif hasattr(inner_type, "_name") and inner_type._name:
                            result_type = inner_type._name
            else:
                # Fallback: parse from type_str if get_origin fails
                match = re.search(r"OBBject\[.*?\]\[(.*?)\]", type_str)
                if match:
                    result_type = match.group(1)
                # Check for OBBject_ModelName pattern
                elif "OBBject_" in type_str:
                    result_type = type_str.split("OBBject_")[1].split("'", maxsplit=1)[
                        0
                    ]

            # If not found, try to extract from docstring
            if result_type == "list[Data]":
                docstring = inspect.getdoc(func) or ""
                if "Returns" in docstring:
                    returns_section = docstring.split("Returns")[1].split("\n\n")[0]
                    # Look for model name in docstring
                    patterns = [
                        r"OBBject\[(.*?)\]",  # OBBject[Model]
                        r"results : ([\w\d_]+)",  # results : Model
                        r"Returns\s+-------\s+(\w+)",  # Direct return type
                    ]

                    for pattern in patterns:
                        model_match = re.search(pattern, returns_section)
                        if model_match:
                            result_type = model_match.group(1)
                            break

            # Ensure result_type doesn't already have a container type
            if "[" in result_type and "]" not in result_type:
                result_type += "]"  # Add missing closing bracket
            result_type = ReferenceGenerator._clean_string_values(result_type)
            # Return the standard OBBject structure with correct result type
            return {
                "OBBject": [
                    {
                        "name": "results",
                        "type": result_type,
                        "description": "Serializable results.",
                    },
                    {
                        "name": "provider",
                        "type": "Optional[str]",
                        "description": "Provider name.",
                    },
                    {
                        "name": "warnings",
                        "type": "Optional[list[Warning_]]",
                        "description": "List of warnings.",
                    },
                    {
                        "name": "chart",
                        "type": "Optional[Chart]",
                        "description": "Chart object.",
                    },
                    {
                        "name": "extra",
                        "type": "dict[str, Any]",
                        "description": "Extra info.",
                    },
                ]
            }

        # Clean up return type string
        type_str = (
            type_str.replace("<class '", "")
            .replace("'>", "")
            .replace("typing.", "")
            .replace("NoneType", "None")
            .replace("inspect._empty", "Any")
        )

        # Basic types handling
        basic_types = ["int", "str", "dict", "bool", "float", "None", "Any"]
        if type_str.lower() in [t.lower() for t in basic_types]:
            return type_str.lower()

        # Check for container types with square brackets
        container_match = re.search(r"(\w+)\[(.*?)\]", type_str)
        if container_match:
            container_type = container_match.group(1)
            inner_type = container_match.group(2)

            inner_type_name = (
                inner_type.split(".")[-1] if "." in inner_type else inner_type
            )

            return f"{container_type}[{inner_type_name}]"

        model_name = (
            type_str.rsplit(".", maxsplit=1)[-1] if "." in type_str else type_str
        )

        return model_name

    @classmethod
    def get_routers(cls, route_map: dict[str, BaseRoute]) -> dict:
        """Get router reference data.

        Parameters
        ----------
        route_map : Dict[str, BaseRoute]
            Dictionary containing the path and route object for the router.

        Returns
        -------
        Dict[str, Dict[str, Any]]
            Dictionary containing the description for each router.
        """
        main_router = RouterLoader().from_extensions()
        routers: dict = {}
        for path in route_map:
            path_parts = path.split("/")
            # We start at 2: ["/", "some_router"] "/some_router"
            i = 2
            p = "/".join(path_parts[:i])
            while p != path:
                if p not in routers:
                    description = main_router.get_attr(p, "description")
                    if description is not None:
                        routers[p] = {"description": description}
                # We go down the path to include sub-routers
                i += 1
                p = "/".join(path_parts[:i])
        return routers
