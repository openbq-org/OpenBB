"""Docstring generator for the static package."""

import inspect
import re
from collections import OrderedDict
from collections.abc import Callable
from inspect import Parameter, isclass
from textwrap import indent
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

from pydantic.fields import FieldInfo
from typing_extensions import _AnnotatedAlias

from openbb_core.app.model.example import Example
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.provider_interface import ProviderInterface
from openbb_core.app.service.system_service import SystemService

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

_MERGED_PROVIDER_DESCRIPTION_RE = re.compile(r"(\(provider:\s*[^)]+\))\s*;\s*")
_QUOTED_TYPE_NAME_RE = re.compile(r"'([A-Za-z_][\w.]*)'")


def _strip_annotated(type_: Any) -> Any:
    """Remove ``Annotated`` metadata from a type, recursing into unions and containers.

    Parameters
    ----------
    type_ : Any
        The type to unwrap.

    Returns
    -------
    Any
        The type with every ``Annotated[X, ...]`` replaced by ``X``.
    """
    origin = get_origin(type_)
    if origin is Annotated:
        return _strip_annotated(get_args(type_)[0])
    if origin is Union or origin is UnionType:
        return Union[tuple(_strip_annotated(arg) for arg in get_args(type_))]  # noqa: UP007
    if origin in (list, dict, set, tuple) and get_args(type_):
        return origin[tuple(_strip_annotated(arg) for arg in get_args(type_))]
    return type_


def _literal_type_name(type_: Any) -> str:
    """Return the value type of a ``Literal``, e.g. ``str`` for ``Literal['a', 'b']``.

    Parameters
    ----------
    type_ : Any
        A ``Literal`` type.

    Returns
    -------
    str
        The sorted, ``|``-joined type names of the literal's values.
    """
    return " | ".join(sorted({type(arg).__name__ for arg in get_args(type_)}))


def _literal_choices(type_: Any) -> list:
    """Return the values of every ``Literal`` in a type, including inside unions.

    Parameters
    ----------
    type_ : Any
        The type to inspect.

    Returns
    -------
    list
        The literal values, in declaration order.
    """
    type_ = _strip_annotated(type_)
    if get_origin(type_) is Literal:
        return list(get_args(type_))
    if get_origin(type_) is Union or get_origin(type_) is UnionType:
        return [
            value
            for arg in get_args(type_)
            if get_origin(arg) is Literal
            for value in get_args(arg)
        ]
    return []


_MODULE_PREFIX_RE = re.compile(r"\b(?:[A-Za-z_]\w*\.)+(?=[A-Za-z_])")


def _strip_module_paths(type_name: str) -> str:
    """Drop the dotted module path from every class named in a type string.

    ``list[openbb_x.models.A | openbb_x.models.B]`` -> ``list[A | B]``. Literal
    values are left alone, since a quoted ``'a.b'`` is data, not a module path.
    """
    if "Literal[" in type_name:
        return type_name
    return _MODULE_PREFIX_RE.sub("", type_name)


def _split_top_level(text: str, separator: str) -> list[str]:
    """Split ``text`` on ``separator``, ignoring separators inside ``[...]``."""
    parts: list[str] = []
    depth = 0
    current = ""
    index = 0
    while index < len(text):
        char = text[index]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        if depth == 0 and text.startswith(separator, index):
            parts.append(current)
            current = ""
            index += len(separator)
            continue
        current += char
        index += 1
    parts.append(current)
    return parts


def _matching_bracket(text: str, open_index: int) -> int:
    """Index of the ``]`` closing the ``[`` at ``open_index`` (``-1`` if none)."""
    depth = 0
    for index in range(open_index, len(text)):
        if text[index] == "[":
            depth += 1
        elif text[index] == "]":
            depth -= 1
            if depth == 0:
                return index
    return -1


def _rewrite_optional_and_union(type_str: str) -> str:
    """Rewrite ``Optional[X]`` / ``Union[X, Y]`` as ``X | None`` / ``X | Y``.

    Brackets are matched, not guessed, so wrapped generics such as
    ``Optional[list[Union[A, B]]]`` become ``list[A | B] | None``. The rightmost
    wrapper is rewritten first, which is always an innermost one.
    """
    token = re.compile(r"\b(Optional|Union)\[")
    while True:
        matches = list(token.finditer(type_str))
        if not matches:
            return type_str
        found = matches[-1]
        open_index = found.end() - 1
        close_index = _matching_bracket(type_str, open_index)
        if close_index < 0:
            return type_str
        inner = type_str[open_index + 1 : close_index]
        if found.group(1) == "Optional":
            parts = [inner.strip()]
            has_none = True
        else:
            parts = [p.strip() for p in _split_top_level(inner, ",") if p.strip()]
            has_none = any(p in ("None", "NoneType") for p in parts)
            parts = [p for p in parts if p not in ("None", "NoneType")]
        rewritten = " | ".join(parts)
        if has_none:
            rewritten += " | None"
        type_str = type_str[: found.start()] + rewritten + type_str[close_index + 1 :]


def _format_type_string(type_str: str, char_limit: int | None = None) -> str:
    """Render a stringified annotation the way docstrings show it."""
    type_str = (
        type_str.replace("<class '", "")
        .replace("'>", "")
        .replace("typing.", "")
        .replace("pydantic.types.", "")
        .replace("datetime.date", "date")
        .replace("datetime.datetime", "datetime")
        .replace("NoneType", "None")
    )

    # Optional[X] -> X | None, Union[X, Y, ...] -> X | Y | ...
    type_str = _rewrite_optional_and_union(type_str)

    # Simplify Literal[...] to str (choices are shown in the description)
    if "Literal[" in type_str:
        has_none = type_str.endswith(" | None")
        type_str = re.sub(r"Literal\[[^\]]+\]", "str", type_str)
        if has_none and not type_str.endswith(" | None"):
            type_str += " | None"

    # Clean up ", None" that might be left over
    type_str = type_str.replace(", None", "")

    # Deduplicate top-level alternatives (str | str -> str), keeping order
    parts = [p.strip() for p in _split_top_level(type_str, " | ")]
    if len(parts) > 1:
        has_none = "None" in parts
        unique = list(OrderedDict.fromkeys(p for p in parts if p != "None"))
        type_str = " | ".join(unique)
        if has_none:
            type_str += " | None"

    # Apply char_limit if specified (simple truncation with bracket balancing)
    if char_limit and len(type_str) > char_limit:
        truncated = type_str[:char_limit]
        open_brackets = truncated.count("[") - truncated.count("]")
        if open_brackets > 0:
            truncated += "]" * open_brackets
        type_str = truncated

    return type_str


class DocstringGenerator:
    """Dynamically generate docstrings for the commands."""

    provider_interface = ProviderInterface()

    @staticmethod
    def get_field_type(
        field_type: Any,
        is_required: bool,
        target: Literal["docstring", "website"] = "docstring",
    ) -> str:
        """Get the implicit data type of a defined Pydantic field.
        Parameters
        ----------
        field_type : Any
            Typing object containing the field type.
        is_required : bool
            Flag to indicate if the field is required.
        target : Literal["docstring", "website"]
            Target to return type for. Defaults to "docstring".
        Returns
        -------
        str
            String representation of the field type.
        """
        is_optional = not is_required

        try:
            _type = field_type

            # Unwrap ForwardRef to its inner string
            if hasattr(_type, "__forward_arg__"):
                _type = _type.__forward_arg__

            if "BeforeValidator" in str(_type):
                _type = "Optional[int]" if is_optional else "int"

            _type = _strip_annotated(_type)

            if isinstance(_type, TypeVar):
                _type = "Any"
            elif get_origin(_type) is Literal:
                _type = _literal_type_name(_type)

            origin = get_origin(_type)
            # On Python 3.10-3.13, ``X | Y`` produces ``types.UnionType``
            # whose ``get_origin()`` is ``types.UnionType`` — distinct from
            # ``typing.Union``. 3.14 unified them, but until 3.13 is gone
            # we have to accept both so the container-aware ``openbb_*``
            # strip below covers ``list[X] | None`` as well as
            # ``Union[list[X], None]``.
            if origin is Union or origin is UnionType:
                args = get_args(_type)
                type_names = []
                has_none = False
                for arg in args:
                    if arg is type(None):
                        has_none = True
                        continue
                    if get_origin(arg) is Literal:
                        type_names.append(_literal_type_name(arg))
                        continue
                    if isinstance(arg, TypeVar):
                        type_names.append("Any")
                        continue
                    type_name = str(arg)
                    if hasattr(arg, "__forward_arg__"):
                        # Render a ForwardRef as its target name.
                        type_name = arg.__forward_arg__
                    elif hasattr(arg, "__name__") and not get_args(arg):
                        type_name = arg.__name__
                    type_name = (
                        type_name.replace("typing.", "")
                        .replace("pydantic.types.", "")
                        .replace("datetime.datetime", "datetime")
                        .replace("datetime.date", "date")
                    )
                    # Unwrap any ForwardRef('X') left inside a container repr,
                    # e.g. ``list[ForwardRef('DataFrame')]`` -> ``list[DataFrame]``.
                    type_name = re.sub(r"ForwardRef\('([^']+)'\)", r"\1", type_name)
                    type_name = _QUOTED_TYPE_NAME_RE.sub(r"\1", type_name)
                    if "openbb_" in type_name:
                        # Strip the dotted module path of every class in the
                        # type, so ``list[openbb_x.y.A | openbb_x.y.B]`` becomes
                        # ``list[A | B]`` (not just the last name).
                        type_name = _strip_module_paths(type_name)
                    if type_name != "NoneType":
                        type_names.append(type_name)

                unique_types = sorted(list(set(type_names)))
                if has_none:
                    unique_types.append("None")
                _type = " | ".join(unique_types)
            else:
                _type = (
                    str(_type)
                    .replace("<class '", "")
                    .replace("'>", "")
                    .replace("typing.", "")
                    .replace("pydantic.types.", "")
                    .replace("datetime.datetime", "datetime")
                    .replace("datetime.date", "date")
                    .replace("NoneType", "None")
                    .replace(", None", "")
                )
                if "Literal[" not in _type:
                    _type = _QUOTED_TYPE_NAME_RE.sub(r"\1", _type)

            if "openbb_" in str(_type):
                _type = _strip_module_paths(str(_type))

            # Render optionality as ``X | None`` (PEP 604), not ``Optional[X]``.
            _type = (
                f"{_type} | None"
                if is_optional
                and "Optional" not in str(_type)
                and " | None" not in str(_type)
                else _type
            )

            if target == "website":
                _type = re.sub(r"Optional\[(.*)\]", r"\1", _type)
                _type = re.sub(r"\s*\|\s*None$", "", _type)

            return _type

        except TypeError:
            return str(field_type)

    @staticmethod
    def get_OBBject_description(
        results_type: str,
        providers: str | None,
    ) -> str:
        """Get the command output description."""
        available_providers = providers or "str | None"
        indent = 2

        obbject_description = (
            f"{create_indent(indent)}OBBject\n"
            f"{create_indent(indent + 1)}results : {results_type}\n"
            f"{create_indent(indent + 2)}Serializable results.\n"
            f"{create_indent(indent + 1)}provider : {available_providers}\n"
            f"{create_indent(indent + 2)}Provider name.\n"
            f"{create_indent(indent + 1)}warnings : list[Warning_] | None\n"
            f"{create_indent(indent + 2)}List of warnings.\n"
            f"{create_indent(indent + 1)}chart : Chart | None\n"
            f"{create_indent(indent + 2)}Chart object.\n"
            f"{create_indent(indent + 1)}extra : dict[str, Any]\n"
            f"{create_indent(indent + 2)}Extra info.\n"
        )

        obbject_description = obbject_description.replace("NoneType", "None")

        return obbject_description

    @staticmethod
    def get_OBBStream_description(model_name: str) -> str:
        """Get the streaming command output description."""
        indent = 2
        stream_description = (
            f"{create_indent(indent)}OBBStream\n"
            f"{create_indent(indent + 1)}results : AsyncIterator[{model_name}]\n"
            f"{create_indent(indent + 2)}Async iterator of streamed results;"
            " use ``async for row in stream``.\n"
            f"{create_indent(indent + 1)}id : str\n"
            f"{create_indent(indent + 2)}Unique identifier of the stream.\n"
            f"{create_indent(indent + 1)}provider : str | None\n"
            f"{create_indent(indent + 2)}Provider name.\n"
            f"{create_indent(indent + 1)}warnings : list[Warning_] | None\n"
            f"{create_indent(indent + 2)}List of warnings.\n"
            f"{create_indent(indent + 1)}extra : dict[str, Any]\n"
            f"{create_indent(indent + 2)}Extra info.\n"
            f"{create_indent(indent + 1)}start : (output=None, handler=None) -> OBBStream\n"
            f"{create_indent(indent + 2)}Begin streaming on a background thread; output"
            " defaults to STDOUT and may be a file path, file object, or socket;"
            " handler transforms or filters each item.\n"
            f"{create_indent(indent + 1)}stop : (timeout=5.0) -> None\n"
            f"{create_indent(indent + 2)}Stop the stream and wait for it to wind down.\n"
            f"{create_indent(indent + 1)}wait : (timeout=None) -> None\n"
            f"{create_indent(indent + 2)}Block until the stream finishes.\n"
        )
        return stream_description.replace("NoneType", "None")

    @staticmethod
    def build_examples(
        func_path: str,
        param_types: dict[str, type],
        examples: list[Example] | None,
        target: Literal["docstring", "website"] = "docstring",
    ) -> str:
        """Get the example section from the examples."""
        if examples:
            if target == "docstring":
                prompt = ">>> "
                indent = create_indent(2)
            else:
                prompt = "\n```python\n"
                indent = create_indent(0)

            doc = f"{indent}Examples\n"
            doc += f"{indent}--------\n"
            doc += f"{indent}{prompt}from openbb import obb\n"

            for e in examples:
                doc += e.to_python(
                    func_path=func_path,
                    param_types=param_types,
                    indentation=indent,
                    prompt=">>> " if target == "docstring" else "",
                )
            return doc if target == "docstring" else doc + "```\n\n"
        return ""

    @classmethod
    def generate_model_docstring(  # noqa: PLR0912, PLR0917
        cls,
        model_name: str,
        summary: str,
        explicit_params: dict[str, Parameter],
        kwarg_params: dict,
        returns: dict[str, FieldInfo],
        results_type: str,
        sections: list[str],
        is_streaming: bool = False,
    ) -> str:
        """Create the docstring for model."""
        docstring: str = "\n"

        def format_type(type_: str, char_limit: int | None = None) -> str:
            """Format type in docstrings."""
            return _format_type_string(str(_strip_annotated(type_)), char_limit)

        def format_schema_description(description: str) -> str:
            """Format description in docstrings."""
            description = (
                description.replace("\n", f"\n{create_indent(2)}")
                if "\n        " not in description
                else description
            )

            return description

        def format_description(description: str) -> str:
            """Format description in docstrings with proper indentation for provider choices."""
            # Base indent for description content (called with create_indent(3) prefix)
            base_indent = create_indent(3)  # 12 spaces

            # Extract "Choices for provider: ..." into a dict keyed by provider
            provider_choices: dict[str, str] = {}
            main_description = description
            multi_items_text = ""

            if "\nChoices for " in description:
                choices_idx = description.index("\nChoices for ")
                main_description = description[:choices_idx]
                choices_text = description[choices_idx:]

                # Parse each "Choices for provider: values" line
                # Handle multi-line choices where continuation lines don't have "Choices for" prefix
                current_provider = None
                current_choices = []

                for ln in choices_text.strip().split("\n"):
                    line = ln.strip()

                    # Check if this is the "Multiple comma separated" line
                    if line.startswith("Multiple comma separated items allowed"):
                        # Save current provider's choices first
                        if current_provider and current_choices:
                            provider_choices[current_provider] = "\n".join(
                                current_choices
                            )
                            current_provider = None
                            current_choices = []
                        multi_items_text = line
                        continue

                    if line.startswith("Choices for "):
                        # Save previous provider's choices if any
                        if current_provider and current_choices:
                            provider_choices[current_provider] = "\n".join(
                                current_choices
                            )

                        # Extract provider name and choices
                        rest = line[len("Choices for ") :]
                        if ": " in rest:
                            prov, choices = rest.split(": ", 1)
                            current_provider = prov.strip()
                            current_choices = [choices.strip()]
                    elif current_provider and line:
                        # This is a continuation line for the current provider's choices
                        current_choices.append(line)

                # Save the last provider's choices
                if current_provider and current_choices:
                    provider_choices[current_provider] = "\n".join(current_choices)

            # Extract multiple items text from main_description if not already found
            if not multi_items_text:
                multi_pattern = (
                    r"\nMultiple comma separated items allowed for provider\(s\): [^.]+"
                )
                multi_match = re.search(multi_pattern, main_description)
                if multi_match:
                    multi_items_text = multi_match.group().strip()
                    main_description = re.sub(multi_pattern, "", main_description)

            if _MERGED_PROVIDER_DESCRIPTION_RE.search(main_description):
                pieces = _MERGED_PROVIDER_DESCRIPTION_RE.split(main_description)
                parts = [
                    pieces[i] + pieces[i + 1] for i in range(0, len(pieces) - 1, 2)
                ] + [pieces[-1]]
                provider_sections = []

                # Extract provider tag pattern
                provider_pattern = re.compile(r"\s*\(provider:\s*([^)]+)\)")

                for part in parts:
                    p = part.strip()
                    match = provider_pattern.search(p)
                    if match:
                        provider_name = match.group(1).strip()
                        content = provider_pattern.sub("", p).strip()
                        provider_sections.append((provider_name, content))
                    elif p:
                        provider_sections.append((None, p))

                if provider_sections:
                    # Find common base description
                    provider_contents = [
                        (name, content)
                        for name, content in provider_sections
                        if name is not None
                    ]
                    base_description = ""

                    if len(provider_contents) >= 2:
                        first_sentences = []
                        for _, content in provider_contents:
                            if "." in content:
                                first_sent = content.split(".", 1)[0].strip()
                                first_sentences.append(first_sent)
                            else:
                                first_sentences.append(content)

                        if first_sentences and all(
                            s == first_sentences[0] for s in first_sentences
                        ):
                            base_description = first_sentences[0] + "."

                    # Check for base description without provider tag
                    base_parts = [
                        content
                        for name, content in provider_sections
                        if name is None and "Choices" not in content
                    ]
                    if base_parts and not base_description:
                        base_description = base_parts[0]

                    # Build formatted output
                    formatted_lines = []

                    if base_description:
                        formatted_lines.append(base_description)
                        formatted_lines.append("")

                    for provider_name, content in provider_sections:
                        if provider_name and content:
                            if base_description:
                                base_clean = base_description.rstrip(".")
                                if content.startswith(base_clean):
                                    content = content[len(base_clean) :].strip()  # noqa
                                    if content.startswith("."):
                                        content = content[1:].strip()  # noqa

                            if not content:
                                continue

                            formatted_lines.append(f"(provider: {provider_name})")
                            for line in content.split("\n"):
                                new_line = line.strip()
                                if new_line:
                                    formatted_lines.append(f"    {new_line}")

                            # Add choices for this provider inside its section
                            if provider_name in provider_choices:
                                formatted_lines.append(
                                    f"    Choices: {provider_choices[provider_name]}"
                                )

                            formatted_lines.append("")

                    while formatted_lines and formatted_lines[-1] == "":
                        formatted_lines.pop()

                    # Join lines
                    if formatted_lines:
                        result = formatted_lines[0]
                        for line in formatted_lines[1:]:
                            if line:
                                result += f"\n{base_indent}{line}"
                            else:
                                result += "\n"
                        main_description = result

            # If no provider sections but we have choices, add them at the end
            # Skip if the description already enumerates choices to avoid duplication.
            elif provider_choices:
                already_listed = re.search(
                    r"(?im)^\s*(choices(\s+for\s+\w+)?\s+are|choices(\s+for\s+\w+)?)\s*:",
                    main_description,
                )
                if not already_listed:
                    for prov, choices in provider_choices.items():
                        main_description += (
                            f"\n{base_indent}Choices for {prov}: {choices}"
                        )

            # Add multiple items text at the end
            if multi_items_text:
                main_description += f"\n{base_indent}{multi_items_text}"

            # Re-indent continuation lines of the main description to align with
            # the parameter description column (base_indent = 12 spaces). The raw
            # field descriptions can carry their own embedded indentation that
            # would otherwise leave continuation lines unaligned in the rendered
            # docstring.
            lines = main_description.splitlines()
            if len(lines) > 1:
                normalized = [lines[0]]
                for ln in lines[1:]:
                    stripped = ln.lstrip()
                    normalized.append(f"{base_indent}{stripped}" if stripped else "")
                main_description = "\n".join(normalized)

            return main_description

        def get_param_info(parameter: Parameter | None) -> tuple[str, str]:
            """Get the parameter info."""
            if not parameter:
                return "", ""
            annotation = getattr(parameter, "_annotation", None)
            if isinstance(annotation, _AnnotatedAlias):
                args = getattr(annotation, "__args__", []) if annotation else []
                p_type = args[0] if args else None
            else:
                p_type = annotation
            type_ = (
                getattr(p_type, "__name__", "") if inspect.isclass(p_type) else p_type
            )
            metadata = getattr(annotation, "__metadata__", [])
            description = getattr(metadata[0], "description", "") if metadata else ""

            return type_, description  # type: ignore

        provider_param: Parameter | dict = {}
        chart_param: Parameter | dict = {}

        # Description summary
        if "description" in sections:
            docstring = summary.strip("\n").replace("\n    ", f"\n{create_indent(2)}")
            docstring += "\n\n"
        else:
            docstring += "\n\n"

        if "parameters" in sections:
            provider_param = explicit_params.pop("provider", {})
            chart_param = explicit_params.pop("chart", {})
            docstring += f"{create_indent(2)}Parameters\n"
            docstring += f"{create_indent(2)}----------\n"

            if provider_param:
                _, description = get_param_info(provider_param)  # type: ignore
                provider_param._annotation = str  # type: ignore
                docstring += f"{create_indent(2)}provider : str | None\n"
                docstring += f"{create_indent(3)}{format_description(description)}\n"

            # Explicit parameters
            for param_name, param in explicit_params.items():
                type_, description = get_param_info(param)
                type_str = format_type(type_, char_limit=86)
                docstring += f"{create_indent(2)}{param_name} : {type_str}\n"
                docstring += f"{create_indent(3)}{format_description(description)}\n"

            # Kwargs
            for param_name, param in kwarg_params.items():
                type_, description = get_param_info(param)
                p_type = getattr(param, "type", "")
                type_ = (
                    getattr(p_type, "__name__", "")
                    if inspect.isclass(p_type)
                    else p_type
                )

                # Extract Literal values before formatting the type
                literal_choices: list = []
                type_str = str(type_)
                if "Literal[" in type_str:
                    # Extract values from Literal[...]
                    literal_match = re.search(r"Literal\[([^\]]+)\]", type_str)
                    if literal_match:
                        literal_content = literal_match.group(1)
                        # Parse the literal values (they're quoted strings)
                        literal_choices = re.findall(r"'([^']+)'", literal_content)

                type_ = format_type(type_)
                if "NoneType" in str(type_):  # pragma: no cover
                    type_ = type_.replace(", NoneType", "")

                default = getattr(param, "default", "")
                description = getattr(default, "description", "")

                # If empty description, check for OpenBBField annotations in parameter's annotation
                if not description and hasattr(param, "annotation"):
                    param_annotation = getattr(param, "annotation", None)
                    # Check if annotation is an Annotated type
                    if (
                        hasattr(param_annotation, "__origin__")
                        and param_annotation.__origin__ is Annotated
                    ):
                        # Extract metadata from annotation
                        metadata = getattr(param_annotation, "__metadata__", [])
                        for meta in metadata:
                            # Look for OpenBBField with description
                            if hasattr(meta, "description") and meta.description:
                                description = meta.description
                                break

                # If still no description but param default is a Query object, extract from there
                if not description and hasattr(param, "default"):
                    param_default = getattr(param, "default")
                    if (
                        hasattr(param_default, "__class__")
                        and "Query" in param_default.__class__.__name__
                    ):
                        description = getattr(param_default, "description", "") or ""

                # Initialize provider_choices and multi_item_providers for this parameter
                provider_choices: dict = {}
                multi_item_providers: list = []

                # Extract choices and multiple_items_allowed from json_schema_extra
                # For kwarg_params (dataclass fields), json_schema_extra is on param.default (Query object)
                # For other params (Pydantic FieldInfo), it may be on param itself
                param_default = getattr(param, "default", None)
                json_extra = getattr(param_default, "json_schema_extra", None)
                if not json_extra:
                    json_extra = getattr(param, "json_schema_extra", None)
                if json_extra and isinstance(json_extra, dict):
                    for prov, prov_info in json_extra.items():
                        if isinstance(prov_info, dict):
                            if "choices" in prov_info:
                                provider_choices[prov] = prov_info["choices"]
                            if prov_info.get("multiple_items_allowed"):
                                multi_item_providers.append(prov)

                # If we have Literal choices from the type and no choices from json_schema_extra,
                # extract providers from the description and add choices for them
                if literal_choices and not provider_choices:
                    # Look for (provider: xxx) or (provider: xxx, yyy) in description
                    provider_match = re.search(r"\(provider:\s*([^)]+)\)", description)
                    if provider_match:
                        providers_text = provider_match.group(1)
                        providers_from_desc = [
                            p.strip() for p in providers_text.split(",")
                        ]
                        for prov in providers_from_desc:
                            if prov and prov not in provider_choices:
                                provider_choices[prov] = literal_choices

                # Extract provider-specific choices directly from the provider interface
                if (
                    not isinstance(p_type, str)
                    and hasattr(p_type, "__origin__")
                    and p_type.__origin__ is Union
                ):
                    # Get the list of providers for this model directly from provider_interface.model_providers
                    try:
                        model_providers = cls.provider_interface.model_providers.get(
                            model_name
                        )
                        if model_providers:
                            provider_field = model_providers.__dataclass_fields__.get(
                                "provider"
                            )
                            providers = (
                                list(provider_field.type.__args__)  # type: ignore[union-attr]
                                if provider_field
                                else []
                            )
                        else:
                            providers = []

                        # For each provider, extract their specific choices for this parameter from the map
                        for provider in providers:
                            if provider == "openbb":
                                continue
                            try:
                                # Directly get provider field info from the map structure
                                provider_field_info = (
                                    cls.provider_interface.map.get(model_name, {})
                                    .get(provider, {})
                                    .get("QueryParams", {})
                                    .get("fields", {})
                                    .get(param_name)
                                )

                                # If the field exists and has a Literal annotation
                                if (
                                    provider_field_info
                                    and hasattr(provider_field_info, "annotation")
                                    and hasattr(
                                        provider_field_info.annotation, "__origin__"
                                    )
                                    and provider_field_info.annotation.__origin__
                                    is Literal
                                ):
                                    # Extract literal values as provider choices
                                    provider_choices[provider] = list(
                                        provider_field_info.annotation.__args__
                                    )
                            except (KeyError, AttributeError):
                                continue
                    except (AttributeError, KeyError):
                        pass

                # Add provider-specific choices to description
                for provider, choices in provider_choices.items():
                    if choices:
                        # Format choices with word wrapping for readability
                        formatted_choices = []
                        line_length = 0
                        line_limit = 80  # Max line length

                        for i, choice in enumerate(choices):
                            choice_str = f"'{choice}'"

                            # If adding this choice would exceed line limit, start a new line
                            if (
                                line_length > 0
                                and line_length + len(choice_str) + 2 > line_limit
                            ):
                                formatted_choices.append(",\n")
                                line_length = 0

                            # Add comma and space if not the first choice in the line
                            if i > 0 and line_length > 0:
                                formatted_choices.append(", ")
                                line_length += 2

                            formatted_choices.append(choice_str)
                            line_length += len(choice_str)

                        choices_str = "".join(formatted_choices)
                        description += f"\nChoices for {provider}: {choices_str}"

                # Add multiple items allowed text at the end if applicable
                # But only if it's not already in the description
                if (
                    multi_item_providers
                    and "Multiple comma separated items allowed" not in description
                ):
                    providers_str = ", ".join(sorted(multi_item_providers))
                    description += f"\nMultiple comma separated items allowed for provider(s): {providers_str}."

                docstring += f"{create_indent(2)}{param_name} : {type_}\n"
                docstring += f"{create_indent(3)}{format_description(description)}\n"

            if chart_param:
                _, description = get_param_info(chart_param)  # type: ignore
                docstring += f"{create_indent(2)}chart : bool\n"
                docstring += f"{create_indent(3)}{format_description(description)}\n"

        if "returns" in sections:
            # Returns
            docstring += "\n"
            docstring += f"{create_indent(2)}Returns\n"
            docstring += f"{create_indent(2)}-------\n"
            if is_streaming:
                docstring += cls.get_OBBStream_description(model_name)
            else:
                _providers, _ = get_param_info(explicit_params.get("provider"))
                docstring += cls.get_OBBject_description(results_type, _providers)
            # Schema
            underline = "-" * len(model_name)
            docstring += f"\n{create_indent(2)}{model_name}\n"
            docstring += f"{create_indent(2)}{underline}\n"

            for name, field in returns.items():
                field_type = cls.get_field_type(field.annotation, field.is_required())
                description = getattr(field, "description", "")
                docstring += f"{create_indent(2)}{field.alias or name} : {field_type}\n"
                docstring += f"{create_indent(3)}{format_schema_description(description.strip())}\n"

        return docstring

    # flake8: noqa:PLR0912
    @classmethod
    def generate(  # noqa: PLR0912
        cls,
        path: str,
        func: Callable,
        formatted_params: OrderedDict[str, Parameter],
        model_name: str | None = None,
        examples: list[Example] | None = None,
        return_type: Any = None,
    ) -> str | None:
        """Generate the docstring for the function."""
        doc = inspect.getdoc(func) or ""
        param_types = {}
        sections = SystemService().system_settings.python_settings.docstring_sections
        max_length = (
            SystemService().system_settings.python_settings.docstring_max_length
        )
        # Parameters explicit in the function signature
        explicit_params = dict(formatted_params)
        explicit_params.pop("extra_params", None)
        # Map of parameter names to types
        param_types = {k: v.annotation for k, v in explicit_params.items()}

        dependency_param_names: set = set()
        try:
            _sig_params = inspect.signature(func).parameters
            for _pname, _p in _sig_params.items():
                _ann = _p.annotation
                if isinstance(_ann, _AnnotatedAlias) and any(
                    hasattr(_m, "dependency") for _m in _ann.__metadata__
                ):
                    dependency_param_names.add(_pname)
        except (AttributeError, TypeError, ValueError):
            pass

        if model_name:
            params = cls.provider_interface.params.get(model_name, {})
            return_schema = cls.provider_interface.return_schema.get(model_name, None)
            if params and return_schema:
                # Parameters passed as **kwargs
                kwarg_params = params["extra"].__dataclass_fields__
                param_types.update({k: v.type for k, v in kwarg_params.items()})
                # Format the annotation to hide the metadata, tags, etc.
                annotation = func.__annotations__.get("return")
                model_fields = getattr(annotation, "model_fields", {})
                results_type = (
                    cls._get_repr(
                        cls._get_generic_types(
                            model_fields["results"].annotation,  # type: ignore[union-attr,arg-type]
                            [],
                        ),
                        model_name,
                    )
                    if isclass(annotation)
                    and issubclass(annotation, OBBject)  # type: ignore[arg-type]
                    and "results" in model_fields
                    else model_name
                )
                is_streaming = (
                    isclass(annotation) and annotation.__name__ == "OBBStream"
                ) or (isclass(return_type) and return_type.__name__ == "OBBStream")
                doc = cls.generate_model_docstring(
                    model_name=model_name,
                    summary=func.__doc__ or "",
                    explicit_params=explicit_params,
                    kwarg_params=kwarg_params,
                    returns=getattr(return_schema, "model_fields", {}),
                    results_type=results_type,
                    sections=sections,
                    is_streaming=is_streaming,
                )
                doc += "\n"

                if "examples" in sections:
                    doc += cls.build_examples(
                        path.replace("/", "."),
                        param_types,
                        examples,
                    )
                    doc += "\n"
        else:
            primitive_types = {
                "int",
                "float",
                "str",
                "bool",
                "list",
                "dict",
                "tuple",
                "set",
            }
            type_name: str = ""
            sections = (
                SystemService().system_settings.python_settings.docstring_sections
            )
            doc_has_parameters = bool(
                re.search(r"^\s*Parameters\s*\n[-=~`]{3,}", doc, re.MULTILINE)
            )
            doc_has_returns = bool(
                re.search(r"^\s*Returns\s*\n[-=~`]{3,}", doc, re.MULTILINE)
            )
            doc_has_examples = bool(
                re.search(r"^\s*Examples\s*\n[-=~`]{3,}", doc, re.MULTILINE)
            )

            if dependency_param_names and doc_has_parameters:
                doc = re.sub(
                    r"\n[ \t]*Parameters[ \t]*\n[-=~`]{3,}[ \t]*\n.*?"
                    r"(?=\n[ \t]*[A-Z][A-Za-z ]*[ \t]*\n[-=~`]{3,}|\Z)",
                    "\n",
                    doc,
                    flags=re.DOTALL,
                )
                doc_has_parameters = False

            if doc_has_returns:
                doc = re.sub(
                    r"\n[ \t]*Returns[ \t]*\n[-=~`]{3,}[ \t]*\n.*?"
                    r"(?=\n[ \t]*[A-Z][A-Za-z ]*[ \t]*\n[-=~`]{3,}|\Z)",
                    "\n",
                    doc,
                    flags=re.DOTALL,
                )
                doc_has_returns = False
            result_doc = doc.strip("\n")

            if result_doc:
                result_doc += "\n\n"

            if (
                formatted_params
                and "parameters" in sections
                and not doc_has_parameters
                and [p for p_name, p in formatted_params.items() if p_name != "kwargs"]
            ):
                if result_doc and not result_doc.endswith("\n\n"):  # pragma: no cover
                    result_doc = result_doc.rstrip("\n") + "\n\n"
                elif not result_doc:
                    result_doc = "\n\n"

                param_section = "Parameters\n----------\n"

                for param_name, param in formatted_params.items():
                    if param_name == "kwargs":
                        continue

                    annotation = getattr(param, "_annotation", None)

                    if isinstance(annotation, _AnnotatedAlias):
                        p_type = annotation.__args__[0]
                        metadata = getattr(annotation, "__metadata__", [])
                        description = (
                            getattr(metadata[0], "description", "") if metadata else ""
                        )
                    else:
                        p_type = annotation
                        description = ""

                    type_str = cls.get_field_type(
                        p_type, param.default is Parameter.empty
                    )
                    param_section += f"{param_name} : {type_str}\n"

                    if description and description.strip() != '""':
                        param_section += f"{create_indent(1)}{description}\n"

                    if choices := _literal_choices(p_type):
                        formatted = ", ".join(repr(choice) for choice in choices)
                        param_section += f"{create_indent(1)}Choices: {formatted}\n"

                result_doc += param_section + "\n"

            if "returns" in sections and not doc_has_returns:
                if result_doc and not result_doc.endswith("\n\n"):  # pragma: no cover
                    result_doc = result_doc.rstrip("\n") + "\n\n"

                returns_section = "Returns\n-------\n"
                if return_type is not None and return_type is not inspect._empty:
                    return_annotation = return_type
                else:
                    return_annotation = inspect.signature(func).return_annotation

                if return_annotation and return_annotation != inspect._empty:
                    if hasattr(return_annotation, "__name__"):
                        type_name = return_annotation.__name__
                    else:
                        type_name = str(return_annotation)

                    type_name = (
                        type_name.replace("typing.", "")
                        .replace("typing_extensions.", "")
                        .replace("<class '", "")
                        .replace("'>", "")
                        .replace("OBBject[T]", "OBBject")
                    )
                    # Collapse ``OBBject[list[XxxData]]`` to ``OBBject`` — the
                    # envelope fields below already name the ``results`` type,
                    # and the data-model section names the row type in full.
                    type_name = re.sub(r"OBBject\[.*\]", "OBBject", type_name)

                    returns_section += f"{type_name}\n"
                    is_primitive = type_name.lower() in primitive_types

                    if not is_primitive:
                        try:
                            if hasattr(return_annotation, "model_fields"):
                                fields = getattr(return_annotation, "model_fields", {})

                                for field_name, field in fields.items():
                                    if type_name.startswith("OBBject") and (
                                        field_name == "id"
                                    ):
                                        continue
                                    field_type = cls.get_field_type(
                                        field.annotation, field.is_required
                                    )
                                    description = (
                                        field.description.replace('"', "'")
                                        if field.description
                                        else ""
                                    )
                                    returns_section += f"{create_indent(1)}{field_name.strip()} : {field_type}\n"
                                    if description:
                                        returns_section += (
                                            f"{create_indent(2)}{description}\n"
                                        )

                        except (AttributeError, TypeError):
                            pass
                else:
                    returns_section += "Any\n"

                result_doc += returns_section + "\n"

            doc = result_doc.rstrip()

            # Append a data-model section documenting every field of the row
            # type carried in ``OBBject.results``. The model class is taken
            # straight from the return annotation (``OBBject[list[XxxData]]``
            # or ``OBBject[XxxData]``) so it works for non-provider,
            # data-processing extensions that have no standard-model registry.
            if type_name and "OBBject" in type_name:
                result_model: type | None = None
                results_field = getattr(return_annotation, "model_fields", {}).get(
                    "results"
                )
                if results_field is not None:
                    _pending = [results_field.annotation]
                    while _pending:
                        node = _pending.pop()
                        if isclass(node) and hasattr(node, "model_fields"):
                            result_model = node
                            break
                        _pending.extend(get_args(node))

                if result_model is not None:
                    model_label = result_model.__name__
                    if doc and not doc.endswith("\n\n"):
                        doc += "\n\n"
                    doc += f"{model_label}\n"
                    doc += f"{'-' * len(model_label)}\n"

                    for field_name, field in result_model.model_fields.items():
                        field_type = cls.get_field_type(
                            field.annotation, field.is_required
                        )
                        field_description = field.description or ""
                        doc += f"{field_name} : {field_type}\n"
                        if field_description:
                            doc += f"{create_indent(1)}{field_description}\n"

                    doc += "\n"

            doc_lines = doc.split("\n")
            if len(doc_lines) > 1:
                indented_body = indent("\n".join(doc_lines[1:]), create_indent(2))
                doc = doc_lines[0] + "\n" + indented_body

            if "examples" in sections and not doc_has_examples:
                if doc and not doc.endswith("\n\n"):
                    doc += "\n\n"
                doc += cls.build_examples(
                    path.replace("/", "."),
                    param_types,
                    examples,
                )
                doc += "\n"

        if max_length and len(doc) > max_length and max_length > 3:
            doc = doc[: max_length - 3] + "..."
        return doc

    @classmethod
    def _get_generic_types(cls, type_: type, items: list) -> list[str]:
        """Unpack generic types recursively.

        Parameters
        ----------
        type_ : type
            Type to unpack.
        items : list
            List to store the unpacked types.

        Returns
        -------
        List[str]
            List of unpacked type names.

        Examples
        --------
        Union[List[str], Dict[str, str], Tuple[str]] -> ["List", "Dict", "Tuple"]
        """
        if hasattr(type_, "__args__"):
            origin = get_origin(type_)
            if origin is Union or origin is UnionType:
                for arg in type_.__args__:  # ty: ignore[not-iterable]
                    cls._get_generic_types(arg, items)
            elif (
                isinstance(origin, type)
                and origin is not Annotated
                and (name := getattr(type_, "_name", getattr(origin, "__name__", None)))
            ):
                items.append(name)
                for arg in type_.__args__:  # ty: ignore[not-iterable]
                    cls._get_generic_types(arg, items)

        return items

    @staticmethod
    def _get_repr(items: list[str], model: str) -> str:
        """Get the string representation of the types list with the model name.

        Parameters
        ----------
        items : List[str]
            List of type names.
        model : str
            Model name to access the model providers.

        Returns
        -------
        str
            String representation of the unpacked types list.

        Examples
        --------
        [List, Dict, Tuple[str]] -> "Union[List[str], Dict[str, str], Tuple[str]]"
        """
        if s := [
            f"{i}[str, {model}]" if i.lower() == "dict" else f"{i}[{model}]"
            for i in items
        ]:
            return f"{' | '.join(s)}" if len(s) > 1 else s[0]
        return model
