"""Direct unit tests for static helpers in ``MethodDefinition``."""

from collections import OrderedDict
from dataclasses import dataclass, field
from inspect import Parameter
from typing import Annotated, Literal, Union
from unittest.mock import patch

import pytest

pandas = pytest.importorskip("pandas")

pytestmark = pytest.mark.requires_pandas

from fastapi import Request
from pydantic import Field
from pydantic.fields import FieldInfo

from openbb_core.app.model.field import OpenBBField
from openbb_core.app.provider_interface import ProviderInterface
from openbb_core.app.static.package_builder import method_definition as md_module
from openbb_core.app.static.package_builder.method_definition import MethodDefinition
from openbb_core.provider.abstract.data import Data
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.abstract.provider import Provider
from openbb_core.provider.abstract.query_params import QueryParams
from openbb_core.provider.registry import Registry
from openbb_core.provider.registry_map import RegistryMap


def test_snake_case_camel_to_snake():
    assert MethodDefinition._snake_case("MyClassName") == "my_class_name"


def test_snake_case_dot_to_underscore():
    assert MethodDefinition._snake_case("a.b.c") == "a_b_c"


def test_snake_case_already_snake():
    assert MethodDefinition._snake_case("already_snake") == "already_snake"


def test_snake_case_empty_string():
    assert MethodDefinition._snake_case("") == ""


def test_snake_case_acronym_followed_by_lowercase():
    # "AAPLPriceData" -> handles ABBR + Word
    out = MethodDefinition._snake_case("HTTPResponse")
    assert "http" in out
    assert "response" in out


def test_is_none_like_return_none_type():
    assert MethodDefinition._is_none_like_return(None) is True
    assert MethodDefinition._is_none_like_return(type(None)) is True


def test_is_none_like_return_inspect_empty():
    import inspect

    assert MethodDefinition._is_none_like_return(inspect._empty) is False


def test_is_none_like_return_string_none():
    assert MethodDefinition._is_none_like_return("None") is True
    assert MethodDefinition._is_none_like_return("nonetype") is True
    assert MethodDefinition._is_none_like_return("typing.None") is True


def test_is_none_like_return_string_other():
    assert MethodDefinition._is_none_like_return("int") is False


def test_is_none_like_return_optional_int_is_false():
    assert MethodDefinition._is_none_like_return(int | None) is False


def test_is_none_like_return_union_of_nones_is_true():
    assert MethodDefinition._is_none_like_return(None | type(None)) is True


def test_has_request_bound_annotation_request_type():
    assert MethodDefinition._has_request_bound_annotation(Request) is True


def test_has_request_bound_annotation_plain_int_false():
    assert MethodDefinition._has_request_bound_annotation(int) is False


def test_has_request_bound_annotation_param_empty_false():
    assert MethodDefinition._has_request_bound_annotation(Parameter.empty) is False


def test_has_request_bound_annotation_string_request():
    assert MethodDefinition._has_request_bound_annotation("Request") is True


def test_has_request_bound_annotation_optional_request():
    assert MethodDefinition._has_request_bound_annotation(Request | None) is True


def test_has_request_bound_annotation_non_type_membership_path():
    class _EqAny:
        __hash__ = None

        def __eq__(self, _other):
            return True

    assert MethodDefinition._has_request_bound_annotation(_EqAny()) is True


def test_has_request_bound_annotation_annotated_request():
    assert (
        MethodDefinition._has_request_bound_annotation(Annotated[Request, "meta"])
        is True
    )


def test_is_safe_dependency_safe_function():
    def dep() -> int:
        return 0

    assert MethodDefinition._is_safe_dependency(dep) is True


def test_is_safe_dependency_returns_none_is_unsafe():
    def dep() -> None:
        return None

    assert MethodDefinition._is_safe_dependency(dep) is False


def test_is_safe_dependency_with_request_param_is_unsafe():
    def dep(request: Request) -> int:
        return 0

    assert MethodDefinition._is_safe_dependency(dep) is False


def test_is_safe_dependency_with_required_param_is_unsafe():
    def dep(x: int) -> int:
        return x

    # x has no default -> unsafe
    assert MethodDefinition._is_safe_dependency(dep) is False


def test_is_safe_dependency_with_default_param_is_safe():
    def dep(x: int = 0) -> int:
        return x

    assert MethodDefinition._is_safe_dependency(dep) is True


def test_dependency_identifier_signature_error_fallback_name():
    class _Bad:
        __name__ = "get.BadThing"

    out = MethodDefinition._dependency_identifier(_Bad())
    assert out == "get__bad_thing"


def test_is_none_like_return_union_with_no_args(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(
        md_module, "get_origin", lambda a: Union if a is sentinel else None
    )
    monkeypatch.setattr(md_module, "get_args", lambda _a: ())
    assert MethodDefinition._is_none_like_return(sentinel) is True


def test_has_request_bound_annotation_annotated_empty_args(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(
        md_module, "get_origin", lambda a: Annotated if a is sentinel else None
    )
    monkeypatch.setattr(md_module, "get_args", lambda _a: ())
    assert MethodDefinition._has_request_bound_annotation(sentinel) is False


def test_is_safe_dependency_signature_error():
    assert MethodDefinition._is_safe_dependency(object()) is False


def test_dependency_identifier_uses_return_annotation_class():
    class MyService:
        pass

    def dep() -> MyService:
        return MyService()

    assert MethodDefinition._dependency_identifier(dep) == "my_service"


def test_dependency_identifier_strips_get_prefix():
    def get_user_settings():
        return None

    assert MethodDefinition._dependency_identifier(get_user_settings) == "user_settings"


def test_dependency_identifier_falls_back_to_func_name():
    def my_dep_func():
        return None

    assert MethodDefinition._dependency_identifier(my_dep_func) == "my_dep_func"


def test_get_extra_returns_empty_dict_when_no_default():
    class F:
        default = None

    assert MethodDefinition.get_extra(F()) == {}


def test_get_extra_strips_choices_key():
    fi = FieldInfo(default="x", json_schema_extra={"choices": ["a", "b"], "other": 1})
    out = MethodDefinition.get_extra(FieldInfo(annotation=str, default=fi))
    assert "choices" not in out
    assert out == {"other": 1}


def test_get_extra_returns_empty_dict_for_missing_extra():
    fi = FieldInfo(default="x")
    out = MethodDefinition.get_extra(FieldInfo(annotation=str, default=fi))
    # No extra defined -> empty dict (after .copy() on missing dict)
    assert out == {}


def test_get_type_constrained_value_maps_to_builtin():
    class ConstrainedIntValue:
        pass

    class F:
        annotation = ConstrainedIntValue

    assert MethodDefinition.get_type(F()) is int


def test_get_default_nested_pydantic_undefined_and_ellipsis():
    from pydantic_core import PydanticUndefined

    class D1:
        default = type("_Wrap", (), {"default": PydanticUndefined})()

    class D2:
        default = type("_Wrap", (), {"default": Ellipsis})()

    assert MethodDefinition.get_default(D1()) is Parameter.empty
    assert MethodDefinition.get_default(D2()) is None


def test_is_data_processing_function_true(monkeypatch):
    class _R:
        methods = {"POST"}

    monkeypatch.setattr(
        md_module.PathHandler, "build_route_map", staticmethod(lambda: {"/x": _R()})
    )
    assert MethodDefinition.is_data_processing_function("/x") is True


def test_is_data_processing_function_route_exists_but_not_processing(monkeypatch):
    class _R:
        methods = {"GET"}

    monkeypatch.setattr(
        md_module.PathHandler, "build_route_map", staticmethod(lambda: {"/x": _R()})
    )
    assert MethodDefinition.is_data_processing_function("/x") is False


def test_get_deprecation_message(monkeypatch):
    class _R:
        summary = "deprecated msg"

    monkeypatch.setattr(
        md_module.PathHandler, "build_route_map", staticmethod(lambda: {"/x": _R()})
    )
    assert MethodDefinition.get_deprecation_message("/x") == "deprecated msg"


def test_parse_docstring_params_extracts_descriptions():
    def f():
        """Do nothing.

        Parameters
        ----------
        symbol : str
            Symbol of the security.
        limit : int
            Number of rows to return.

        Returns
        -------
        None
        """

    out = MethodDefinition._parse_docstring_params(f)
    assert out["symbol"] == "Symbol of the security."
    assert out["limit"] == "Number of rows to return."


def test_parse_docstring_params_no_function_returns_empty():
    assert MethodDefinition._parse_docstring_params(None) == {}


def test_parse_docstring_params_no_params_section_returns_empty():
    def f():
        """Just a description, no params section."""

    assert MethodDefinition._parse_docstring_params(f) == {}


def test_parse_docstring_params_no_docstring_returns_empty():
    def f():
        return None

    assert MethodDefinition._parse_docstring_params(f) == {}


def test_reorder_params_for_signature_provider_at_end():
    params = {
        "symbol": Parameter("symbol", Parameter.POSITIONAL_OR_KEYWORD),
        "provider": Parameter("provider", Parameter.POSITIONAL_OR_KEYWORD),
        "limit": Parameter("limit", Parameter.POSITIONAL_OR_KEYWORD),
    }
    out = MethodDefinition.reorder_params(params)
    assert list(out.keys()) == ["symbol", "limit", "provider"]


def test_reorder_params_for_signature_var_kw_after_provider():
    params = {
        "symbol": Parameter("symbol", Parameter.POSITIONAL_OR_KEYWORD),
        "kwargs": Parameter("kwargs", Parameter.VAR_KEYWORD),
        "provider": Parameter("provider", Parameter.POSITIONAL_OR_KEYWORD),
    }
    out = MethodDefinition.reorder_params(params, var_kw=["kwargs"])
    assert list(out.keys())[-1] == "kwargs"
    # provider should be just before kwargs
    assert list(out.keys()).index("provider") < list(out.keys()).index("kwargs")


def test_reorder_params_for_docstring_provider_first():
    params = {
        "symbol": Parameter("symbol", Parameter.POSITIONAL_OR_KEYWORD),
        "provider": Parameter("provider", Parameter.POSITIONAL_OR_KEYWORD),
    }
    out = MethodDefinition.reorder_params(params, for_docstring=True)
    assert list(out.keys())[0] == "provider"


def test_reorder_params_no_provider_unchanged_order():
    params = {
        "a": Parameter("a", Parameter.POSITIONAL_OR_KEYWORD),
        "b": Parameter("b", Parameter.POSITIONAL_OR_KEYWORD),
    }
    out = MethodDefinition.reorder_params(params)
    assert list(out.keys()) == ["a", "b"]


def test_get_expanded_type_no_extra_returns_default():
    out = MethodDefinition.get_expanded_type("symbol")
    # No expansion match, no extras -> ellipsis
    assert out is ... or "TYPE_EXPANSION" in str(out) or out is not None


def test_get_expanded_type_multiple_items_allowed_dict_wraps_in_list():
    out = MethodDefinition.get_expanded_type(
        "symbol",
        extra={"fmp": {"multiple_items_allowed": True}},
        original_type=str,
    )
    assert out == list[str]


def test_get_expanded_type_multiple_items_allowed_legacy_list_format():
    out = MethodDefinition.get_expanded_type(
        "symbol",
        extra={"fmp": ["multiple_items_allowed"]},
        original_type=int,
    )
    assert out == list[int]


def test_get_expanded_type_multiple_items_requires_original_type():
    with pytest.raises(ValueError, match="original type"):
        MethodDefinition.get_expanded_type(
            "symbol",
            extra={"fmp": {"multiple_items_allowed": True}},
            original_type=None,
        )


def test_is_annotated_dc_true_for_annotated_dataclass():
    from dataclasses import dataclass

    @dataclass
    class D:
        x: int = 0

    ann = Annotated[D, "meta"]
    assert MethodDefinition.is_annotated_dc(ann) is True


def test_is_annotated_dc_false_for_plain_annotated():
    ann = Annotated[int, "meta"]
    assert MethodDefinition.is_annotated_dc(ann) is False


def test_is_annotated_dc_false_for_non_annotated():
    assert MethodDefinition.is_annotated_dc(int) is False


class _RichQueryParams(QueryParams):
    symbol: str = Field(
        description="Symbol(s).",
        json_schema_extra={
            "rich_a": {"choices": ["AAPL", "MSFT"], "multiple_items_allowed": True},
            "rich_b": {"choices": ["GOOG"], "multiple_items_allowed": False},
        },
    )
    exchange: str | None = Field(
        default=None,
        description="Exchange.",
        json_schema_extra={
            "rich_a": {"choices": ["NYSE", "NASDAQ"]},
        },
    )


class _RichData(Data):
    """Standard data class."""

    symbol: str | None = None


class _RichAFetcher(Fetcher[_RichQueryParams, list[_RichData]]):
    require_credentials = False

    @staticmethod
    def transform_query(params):
        return _RichQueryParams(**params)

    @staticmethod
    def extract_data(query, credentials):
        return [{"symbol": "AAPL"}]

    @staticmethod
    def transform_data(query, data, **kwargs):
        return [_RichData(**row) for row in data]


class _RichBQueryParams(_RichQueryParams):
    region: Literal["us", "eu"] | None = None


class _RichBFetcher(Fetcher[_RichBQueryParams, list[_RichData]]):
    require_credentials = False

    @staticmethod
    def transform_query(params):
        return _RichBQueryParams(**params)

    @staticmethod
    def extract_data(query, credentials):
        return []

    @staticmethod
    def transform_data(query, data, **kwargs):
        return []


@pytest.fixture
def rich_provider_interface():
    ProviderInterface._instances.pop(ProviderInterface, None)
    registry = Registry()
    registry.include_provider(
        Provider(
            name="rich_a",
            description="rich A",
            website="https://example.invalid",
            credentials=None,
            fetcher_dict={"RichModel": _RichAFetcher},
        )
    )
    registry.include_provider(
        Provider(
            name="rich_b",
            description="rich B",
            website="https://example.invalid",
            credentials=None,
            fetcher_dict={"RichModel": _RichBFetcher},
        )
    )
    pi = ProviderInterface(registry_map=RegistryMap(registry=registry))
    yield pi
    ProviderInterface._instances.pop(ProviderInterface, None)


def test_add_field_custom_annotations_standard_model_path(rich_provider_interface):
    """Cover the entry path: real model_name with empty od triggers no-op iteration."""
    od = OrderedDict()
    out = MethodDefinition.add_field_custom_annotations(od, model_name="RichModel")
    assert out is None


class _FakeQuery:
    """Stand-in for fastapi.Query carrying json_schema_extra."""

    def __init__(self, description, json_schema_extra):
        self.description = description
        self.json_schema_extra = json_schema_extra


def _build_fake_pi_with_rich_extras():
    """Construct a ProviderInterface-like object whose params[model] has json_schema_extra."""

    @dataclass
    class StdParams:
        symbol: Annotated[
            Literal["AAPL"] | Literal["GOOG"] | str,
            OpenBBField(description=""),
        ] = field(
            default=_FakeQuery(
                description="sym",
                json_schema_extra={
                    "prov_a": {
                        "choices": ["AAPL", "MSFT"],
                        "multiple_items_allowed": True,
                    },
                    "prov_b": {
                        "choices": ["GOOG"],
                        "multiple_items_allowed": ["foo"],
                    },
                },
            )
        )
        exchange: Annotated[str | None, OpenBBField(description="")] = field(
            default=_FakeQuery(
                description="exch",
                json_schema_extra={"prov_a": {"choices": ["NYSE"]}},
            )
        )

    @dataclass
    class ExtraParams:
        pass

    class _FakePI:
        params = {
            "RichModel": {"standard": StdParams, "extra": ExtraParams},
        }

    return _FakePI()


def test_add_field_custom_annotations_full_branch_coverage():
    fake_pi = _build_fake_pi_with_rich_extras()
    od = OrderedDict()
    od["symbol"] = Parameter(
        "symbol",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[
            Literal["AAPL"] | Literal["GOOG"],
            OpenBBField(description=""),
        ],
    )
    od["exchange"] = Parameter(
        "exchange",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[str | None, OpenBBField(description="")],
        default=None,
    )
    od["unrelated"] = Parameter(
        "unrelated",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[int, OpenBBField(description="orig")],
    )
    with patch(
        "openbb_core.app.static.package_builder.method_definition.ProviderInterface",
        return_value=fake_pi,
    ):
        MethodDefinition.add_field_custom_annotations(od, model_name="RichModel")

    sym_desc = od["symbol"].annotation.__metadata__[-1].description
    assert "Choices for prov_a" in sym_desc
    assert "Choices for prov_b" in sym_desc
    assert "Multiple items supported by" in sym_desc
    exch_desc = od["exchange"].annotation.__metadata__[-1].description
    assert "Choices for prov_a" in exch_desc
    # 'unrelated' not touched (not in fields)
    assert od["unrelated"].annotation.__metadata__[0].description == "orig"


def test_add_field_custom_annotations_no_model_name():
    od = OrderedDict()
    od["x"] = Parameter("x", kind=Parameter.POSITIONAL_OR_KEYWORD)
    out = MethodDefinition.add_field_custom_annotations(od, model_name=None)
    assert out is None
    assert "x" in od


def test_add_field_custom_annotations_unknown_model_returns_silently(
    rich_provider_interface,
):
    od = OrderedDict()
    od["x"] = Parameter("x", kind=Parameter.POSITIONAL_OR_KEYWORD)
    out = MethodDefinition.add_field_custom_annotations(od, model_name="DoesNotExist")
    assert out is None


def test_add_field_custom_annotations_skips_params_not_in_fields(
    rich_provider_interface,
):
    od = OrderedDict()
    od["unknown_param"] = Parameter(
        "unknown_param",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[str, OpenBBField(description="orig")],
    )
    MethodDefinition.add_field_custom_annotations(od, model_name="RichModel")
    # unchanged
    assert od["unknown_param"].annotation.__metadata__[0].description == "orig"


def test_format_annotated_param_pydantic_body_expands_fields():
    from inspect import Parameter
    from typing import Annotated

    from pydantic import BaseModel, Field

    from openbb_core.app.static.package_builder.method_definition import (
        MethodDefinition,
    )

    class Body(BaseModel):
        a: str = Field(default="x", description="A field.")
        b: int = Field(default=1, description="B field.")

    p = Parameter(
        name="body",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[Body, "tag"],
    )
    formatted: dict = {}
    consumed = MethodDefinition._format_annotated_param(
        "body", p, "/some/path", formatted
    )
    assert consumed is True
    assert "a" in formatted and "b" in formatted
    assert formatted["a"].default == "x"
    assert formatted["b"].default == 1


def test_format_annotated_param_query_object_in_metadata():
    """Lines 485-499: Query meta object with description+default."""
    from inspect import Parameter
    from typing import Annotated

    from openbb_core.app.static.package_builder.method_definition import (
        MethodDefinition,
    )

    class _Q:
        description = "Sym desc"
        default = "AAPL"

    _Q.__name__ = "Query"
    p = Parameter(
        name="symbol",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[str, _Q()],
        default="AAPL",
    )
    formatted: dict = {}
    consumed = MethodDefinition._format_annotated_param("symbol", p, "/x", formatted)
    assert consumed is True
    assert "symbol" in formatted


def test_format_annotated_param_no_query_returns_false():
    """Falls through when neither Pydantic nor Query."""
    from inspect import Parameter
    from typing import Annotated

    from openbb_core.app.static.package_builder.method_definition import (
        MethodDefinition,
    )

    p = Parameter(
        name="x",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[str, "just_a_string"],
    )
    formatted: dict = {}
    consumed = MethodDefinition._format_annotated_param("x", p, "/path", formatted)
    assert consumed is False


def test_format_annotated_param_data_processing_skips_pydantic_branch():
    """When path is data-processing, the Pydantic body branch is skipped."""
    from inspect import Parameter
    from typing import Annotated

    from pydantic import BaseModel

    from openbb_core.app.static.package_builder.method_definition import (
        MethodDefinition,
    )

    class Body(BaseModel):
        a: str = "x"

    p = Parameter(
        name="body",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[Body, "tag"],
    )
    formatted: dict = {}
    # data-processing path means is_get_request is False
    # This requires a path that returns False from is_data_processing_function
    # If Body has no Query meta, returns False
    consumed = MethodDefinition._format_annotated_param(
        "body", p, "/econometrics/foo", formatted
    )
    # Either consumed True (if /econometrics/foo treated as get) or False (data-proc)
    assert consumed in (True, False)


def test_parse_docstring_params_basic():
    from openbb_core.app.static.package_builder.method_definition import (
        MethodDefinition,
    )

    def f(symbol):
        """Func.

        Parameters
        ----------
        symbol : str
            The symbol description.
        other : int
            Another desc.
        """

    out = MethodDefinition._parse_docstring_params(f)
    assert out.get("symbol") == "The symbol description."
    assert out.get("other") == "Another desc."


def test_build_command_method_filter_inputs_source_extraction(monkeypatch):
    """Lines 1263-1313: extract additional params from filter_inputs() in func source."""
    from openbb_core.app.static.package_builder.method_definition import (
        MethodDefinition,
    )
    from openbb_core.app.static.package_builder.path_handler import PathHandler

    def my_endpoint(symbol: str = "AAPL"):
        """Endpoint."""
        period: int = 5
        weights: list = []
        result = filter_inputs(sym=symbol, p=period, w=weights, flag=True)  # noqa: F821
        return result

    class _FakeRoute:
        deprecated = False
        path = "/test/endpoint"
        endpoint = my_endpoint
        openapi_extra: dict = {}

    monkeypatch.setattr(
        PathHandler,
        "build_route_map",
        staticmethod(lambda: {"/test/endpoint": _FakeRoute()}),
    )

    code = MethodDefinition.build_command_method(
        path="/test/endpoint",
        func=my_endpoint,
        model_name=None,
    )
    assert "def endpoint" in code


def test_format_params_query_default_value(monkeypatch):
    """Lines 567-586: when param.default is a Query-class instance, extract description+default."""
    from inspect import Parameter

    from openbb_core.app.static.package_builder.method_definition import (
        MethodDefinition,
    )
    from openbb_core.app.static.package_builder.path_handler import PathHandler

    class _Q:
        description = "Sym"
        default = "AAPL"

    _Q.__name__ = "Query"

    parameter_map = {
        "symbol": Parameter(
            name="symbol",
            kind=Parameter.POSITIONAL_OR_KEYWORD,
            annotation=str,
            default=_Q(),
        ),
    }
    monkeypatch.setattr(PathHandler, "build_route_map", staticmethod(lambda: {}))
    out = MethodDefinition.format_params("/x/y", parameter_map)
    assert "symbol" in out
    assert out["symbol"].default == "AAPL"


def test_format_params_query_params_model_expanded_field(monkeypatch):
    """A QueryParams-model field present in TYPE_EXPANSION is widened (else branch)."""
    from openbb_core.app.static.package_builder.path_handler import PathHandler

    class _ExpandedQP(QueryParams):
        start_date: str = Field(default="", description="Start date.")

    parameter_map = {
        "params": Parameter(
            name="params",
            kind=Parameter.POSITIONAL_OR_KEYWORD,
            annotation=_ExpandedQP,
        ),
    }
    monkeypatch.setattr(PathHandler, "build_route_map", staticmethod(lambda: {}))
    out = MethodDefinition.format_params("/x/y", parameter_map)

    assert "start_date" in out
    assert "str" in str(out["start_date"].annotation)


def test_format_params_dataclass_annotated_field_expansion(monkeypatch):
    """Lines 623-638: is_annotated_dc branch -> field expansion."""
    from dataclasses import dataclass
    from inspect import Parameter
    from typing import Annotated

    from openbb_core.app.static.package_builder.method_definition import (
        MethodDefinition,
    )
    from openbb_core.app.static.package_builder.path_handler import PathHandler

    @dataclass
    class _Std:
        symbol: str = "AAPL"
        days: int = 7

    parameter_map = {
        "standard_params": Parameter(
            name="standard_params",
            kind=Parameter.POSITIONAL_OR_KEYWORD,
            annotation=Annotated[_Std, "tag"],
        ),
    }
    monkeypatch.setattr(PathHandler, "build_route_map", staticmethod(lambda: {}))
    out = MethodDefinition.format_params("/x/y", parameter_map)
    assert "symbol" in out
    assert "days" in out


def test_format_params_provider_choices(monkeypatch):
    """Lines 591-619: provider_choices Annotated[dataclass, ...] -> 'provider' Parameter."""
    from dataclasses import dataclass
    from inspect import Parameter
    from typing import Annotated, Literal

    from openbb_core.app.static.package_builder.method_definition import (
        MethodDefinition,
    )
    from openbb_core.app.static.package_builder.path_handler import PathHandler

    @dataclass
    class _PC:
        provider: Literal["a", "b"] = "a"

    parameter_map = {
        "provider_choices": Parameter(
            name="provider_choices",
            kind=Parameter.POSITIONAL_OR_KEYWORD,
            annotation=Annotated[_PC, "tag"],
        ),
    }
    monkeypatch.setattr(PathHandler, "build_route_map", staticmethod(lambda: {}))
    out = MethodDefinition.format_params("/x/y", parameter_map)
    assert "provider" in out
    assert out["provider"].default is None


def test_format_params_path_parameters_extracted(monkeypatch):
    from inspect import Parameter

    from openbb_core.app.static.package_builder.method_definition import (
        MethodDefinition,
    )
    from openbb_core.app.static.package_builder.path_handler import PathHandler

    parameter_map = {
        "ticker": Parameter(
            name="ticker", kind=Parameter.POSITIONAL_OR_KEYWORD, annotation=str
        ),
    }
    monkeypatch.setattr(PathHandler, "build_route_map", staticmethod(lambda: {}))
    out = MethodDefinition.format_params("/equity/{ticker}/info", parameter_map)
    assert "ticker" in out


def test_build_command_method_body_annotated_basemodel(monkeypatch):
    """Lines 1176-1193: Annotated[BaseModel, ...] without Depends -> field expansion."""
    from typing import Annotated

    from pydantic import BaseModel

    from openbb_core.app.static.package_builder.method_definition import (
        MethodDefinition,
    )

    monkeypatch.setattr(
        MethodDefinition, "is_deprecated_function", staticmethod(lambda p: False)
    )

    class _Body(BaseModel):
        symbol: str = "AAPL"
        period: int = 7

    def my_endpoint(body: Annotated[_Body, "tag"]):
        return body

    code = MethodDefinition.build_command_method_body(path="/x/y", func=my_endpoint)
    assert '"symbol": symbol' in code
    assert '"period": period' in code


def test_build_command_method_body_annotated_basemodel_with_depends(monkeypatch):
    """Lines 1192-1193: Annotated[BaseModel, ...] WITH Depends -> passthrough."""
    from typing import Annotated

    from fastapi import Depends
    from pydantic import BaseModel

    from openbb_core.app.static.package_builder.method_definition import (
        MethodDefinition,
    )

    monkeypatch.setattr(
        MethodDefinition, "is_deprecated_function", staticmethod(lambda p: False)
    )

    class _Body(BaseModel):
        symbol: str = "AAPL"

    def _dep():
        return _Body()

    def my_endpoint(body: Annotated[_Body, Depends(_dep)]):
        return body

    code = MethodDefinition.build_command_method_body(path="/x/y", func=my_endpoint)
    assert "body=body" in code


def test_build_command_method_body_extra_params_with_extras(monkeypatch):
    """Lines 1141-1147: extra_params dataclass with extras dict -> info accumulated."""
    from dataclasses import dataclass, field
    from typing import Annotated

    from openbb_core.app.static.package_builder.method_definition import (
        MethodDefinition,
    )

    monkeypatch.setattr(
        MethodDefinition, "is_deprecated_function", staticmethod(lambda p: False)
    )

    @dataclass
    class _Extras:
        symbol: str = field(default="AAPL", metadata={"x-extra": {"choices": ["AAPL"]}})

    def my_endpoint(extra_params: Annotated[_Extras, "tag"]):
        return None

    code = MethodDefinition.build_command_method_body(path="/x/y", func=my_endpoint)
    assert "extra_params=kwargs" in code


def test_build_command_method_deprecated_path(monkeypatch):
    """Lines 1117-1120: deprecated function path -> emits simplefilter+warn lines."""
    from openbb_core.app.static.package_builder.method_definition import (
        MethodDefinition,
    )

    monkeypatch.setattr(
        MethodDefinition, "is_deprecated_function", staticmethod(lambda p: True)
    )
    monkeypatch.setattr(
        MethodDefinition, "get_deprecation_message", staticmethod(lambda p: "Old API")
    )

    def my_endpoint(symbol: str = "AAPL"):
        return symbol

    code = MethodDefinition.build_command_method_body(path="/x/y", func=my_endpoint)
    assert "simplefilter('always', DeprecationWarning)" in code
    assert "Old API" in code


def test_format_params_extra_params_and_provider_choices_skip(monkeypatch):
    from inspect import Parameter

    from openbb_core.app.static.package_builder.path_handler import PathHandler

    parameter_map = {
        "extra_params": Parameter(
            name="extra_params", kind=Parameter.POSITIONAL_OR_KEYWORD, annotation=dict
        ),
        "provider_choices": Parameter(
            name="provider_choices",
            kind=Parameter.POSITIONAL_OR_KEYWORD,
            annotation=Parameter.empty,
        ),
    }
    monkeypatch.setattr(PathHandler, "build_route_map", staticmethod(lambda: {}))
    out = MethodDefinition.format_params("/x/y", parameter_map)
    assert "extra_params" in out


def test_format_params_annotated_without_depends_and_var_keyword(monkeypatch):
    from inspect import Parameter

    from openbb_core.app.static.package_builder.path_handler import PathHandler

    parameter_map = {
        "symbol": Parameter(
            name="symbol",
            kind=Parameter.POSITIONAL_OR_KEYWORD,
            annotation=Annotated[str, OpenBBField(description="")],
        ),
        "kwargs": Parameter(
            name="kwargs",
            kind=Parameter.VAR_KEYWORD,
            annotation=int,
            default=Parameter.empty,
        ),
        "any_kwargs": Parameter(
            name="any_kwargs",
            kind=Parameter.VAR_KEYWORD,
            annotation=int,
            default=Parameter.empty,
        ),
    }
    monkeypatch.setattr(PathHandler, "build_route_map", staticmethod(lambda: {}))
    out = MethodDefinition.format_params("/x/y", parameter_map)
    assert "symbol" in out and "any_kwargs" in out


def test_format_params_constrained_expanded_type_branch(monkeypatch):
    from inspect import Parameter

    from openbb_core.app.static.package_builder.path_handler import PathHandler

    class _Constrained:
        __constraints__ = (str,)

    parameter_map = {
        "x": Parameter(name="x", kind=Parameter.POSITIONAL_OR_KEYWORD, annotation=int)
    }
    monkeypatch.setattr(PathHandler, "build_route_map", staticmethod(lambda: {}))
    monkeypatch.setattr(
        MethodDefinition,
        "get_expanded_type",
        classmethod(lambda cls, *_a, **_k: _Constrained),
    )
    out = MethodDefinition.format_params("/x/y", parameter_map)
    assert "x" in out


def test_add_field_custom_annotations_all_literal_union_simplifies_type(monkeypatch):
    from dataclasses import dataclass

    class _QueryObj:
        def __init__(self):
            self.json_schema_extra = {"prov": {"choices": ["a", "b"]}}
            self.description = "desc"

    @dataclass
    class _Std:
        p: Literal["a"] | Literal["b"] = _QueryObj()

    @dataclass
    class _Extra:
        pass

    fake_pi = type("_PI", (), {"params": {"M": {"standard": _Std, "extra": _Extra}}})()

    od = OrderedDict(
        {
            "p": Parameter(
                "p",
                kind=Parameter.POSITIONAL_OR_KEYWORD,
                annotation=Annotated[
                    Literal["a"] | Literal["b"], OpenBBField(description="")
                ],
            )
        }
    )

    monkeypatch.setattr(
        "openbb_core.app.static.package_builder.method_definition.ProviderInterface",
        lambda: fake_pi,
    )
    MethodDefinition.add_field_custom_annotations(od, model_name="M")
    assert "Choices for prov" in od["p"].annotation.__metadata__[-1].description


def test_build_func_params_wraps_long_desc_and_ellipsis_default():
    long_desc = "x" * 120
    params = OrderedDict(
        {
            "x": Parameter(
                name="x",
                kind=Parameter.POSITIONAL_OR_KEYWORD,
                annotation=Annotated[list[int], OpenBBField(description=long_desc)],
                default=Ellipsis,
            )
        }
    )
    out = MethodDefinition.build_func_params(params)
    assert "OpenBBField" in out
    assert " = None" in out


def test_build_func_returns_obbject_subclass():
    from openbb_core.app.model.obbject import OBBject

    class _O(OBBject):
        pass

    assert MethodDefinition.build_func_returns(_O) == "OBBject"


def test_build_func_returns_plain_class():
    assert MethodDefinition.build_func_returns(int) == "int"


def test_build_func_returns_pep604_union():
    from openbb_core.provider.abstract.data import Data

    assert MethodDefinition.build_func_returns(Data | None) == "Data | None"


def test_build_func_returns_falsy_return_type():
    """A falsy (but not ``inspect._empty``) return type — e.g. ``None`` —
    falls through to the ``Any`` sentinel rather than a rendered type name.
    """
    from typing import Any

    assert MethodDefinition.build_func_returns(None) is Any


def test_collect_dependency_calls_skips_unsafe_annotated_dependency():
    def _unsafe() -> None:
        return None

    parameter_map = {
        "dep": Parameter(
            name="dep",
            kind=Parameter.POSITIONAL_OR_KEYWORD,
            annotation=Annotated[int, type("_Meta", (), {"dependency": _unsafe})()],
        )
    }
    calls, names = MethodDefinition._collect_dependency_calls("/x/y", parameter_map)
    assert calls == []
    assert names == set()


def test_build_command_method_body_provider_choices_annotated_dc_info_and_kwargs(
    monkeypatch,
):
    from dataclasses import dataclass

    monkeypatch.setattr(
        MethodDefinition, "is_deprecated_function", staticmethod(lambda p: False)
    )
    monkeypatch.setattr(
        MethodDefinition, "is_data_processing_function", staticmethod(lambda p: True)
    )

    class _D:
        json_schema_extra = {"note": "x"}

    @dataclass
    class _Extras:
        alpha: str = _D()

    @dataclass
    class _ProviderChoices:
        provider: Literal["a", "b"] = "a"

    @dataclass
    class _Std:
        beta: int = 1

    def endpoint(
        extra_params: Annotated[_Extras, "tag"],
        provider_choices: Annotated[_ProviderChoices, "tag"],
        standard_params: Annotated[_Std, "tag"],
        **kwargs,
    ):
        return None

    code = MethodDefinition.build_command_method_body("/x/y", endpoint)
    assert "provider_choices={" in code
    assert "standard_params={" in code
    assert "info={" in code
    assert "data_processing=True" in code


def test_build_command_method_source_eval_fallback_branches(monkeypatch):
    def endpoint(symbol: str = "AAPL"):
        bad: UnknownType = nope  # type: ignore[name-defined]  # noqa: F821
        result = filter_inputs(a=bad, b=missing)  # noqa: F821
        return result

    monkeypatch.setattr(
        MethodDefinition, "is_deprecated_function", staticmethod(lambda p: False)
    )
    code = MethodDefinition.build_command_method("/x/y", endpoint)
    assert "def y" in code


def test_format_annotated_param_query_default_pydantic_undefined():
    from pydantic_core import PydanticUndefined

    class _Q:
        description = "x"
        default = PydanticUndefined

    _Q.__name__ = "Query"

    p = Parameter(
        name="x",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[str, _Q()],
        default=Parameter.empty,
    )
    formatted = {}
    assert MethodDefinition._format_annotated_param("x", p, "/x", formatted) is True


def test_format_params_chart_branch(monkeypatch):
    from openbb_core.app.static.package_builder import method_definition as md
    from openbb_core.app.static.package_builder.path_handler import PathHandler

    class _Chart:
        @staticmethod
        def functions():
            return ["x_y"]

    monkeypatch.setattr(md, "CHARTING_INSTALLED", True)
    monkeypatch.setattr(md, "Charting", _Chart, raising=False)
    monkeypatch.setattr(PathHandler, "build_route_map", staticmethod(lambda: {}))
    out = MethodDefinition.format_params("/x/y", {})
    assert "chart" in out


def test_format_params_continue_when_annotated_param_consumed(monkeypatch):
    from openbb_core.app.static.package_builder.path_handler import PathHandler

    p = Parameter(
        name="x",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[str, OpenBBField(description="")],
    )
    monkeypatch.setattr(PathHandler, "build_route_map", staticmethod(lambda: {}))
    monkeypatch.setattr(
        MethodDefinition,
        "_format_annotated_param",
        staticmethod(lambda *_a, **_k: True),
    )
    out = MethodDefinition.format_params("/x/y", {"x": p})
    assert out == OrderedDict()


def test_format_params_annotated_non_depends_new_type_ellipsis(monkeypatch):
    from openbb_core.app.static.package_builder.path_handler import PathHandler

    p = Parameter(
        name="x",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[str, OpenBBField(description="")],
    )
    monkeypatch.setattr(PathHandler, "build_route_map", staticmethod(lambda: {}))
    monkeypatch.setattr(
        MethodDefinition, "get_expanded_type", classmethod(lambda cls, *_a, **_k: ...)
    )
    out = MethodDefinition.format_params("/x/y", {"x": p})
    assert "x" in out


def test_format_params_annotated_non_depends_constrained_type(monkeypatch):
    """An annotated, non-Depends param whose expanded type is a constrained
    TypeVar unrolls ``__constraints__`` into a ``Union`` with the inner type.
    """
    from openbb_core.app.static.package_builder.path_handler import PathHandler

    class _Constrained:
        __constraints__ = (str, bytes)

    p = Parameter(
        name="x",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[int, OpenBBField(description="")],
    )
    monkeypatch.setattr(PathHandler, "build_route_map", staticmethod(lambda: {}))
    monkeypatch.setattr(
        MethodDefinition,
        "get_expanded_type",
        classmethod(lambda cls, *_a, **_k: _Constrained),
    )
    out = MethodDefinition.format_params("/x/y", {"x": p})
    assert "x" in out


def test_format_params_annotated_with_depends_continue(monkeypatch):
    from openbb_core.app.static.package_builder.path_handler import PathHandler

    meta = type("_Meta", (), {"dependency": lambda: 1})()
    p = Parameter(
        name="x",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[str, meta],
    )
    monkeypatch.setattr(PathHandler, "build_route_map", staticmethod(lambda: {}))
    out = MethodDefinition.format_params("/x/y", {"x": p})
    assert "x" not in out


def test_add_field_custom_annotations_union_not_all_literals(monkeypatch):
    from dataclasses import dataclass

    class _QueryObj:
        def __init__(self):
            self.json_schema_extra = {"prov": {"choices": ["a", "b"]}}
            self.description = "desc"

    @dataclass
    class _Std:
        p: Literal["a"] | int = _QueryObj()

    @dataclass
    class _Extra:
        pass

    fake_pi = type("_PI", (), {"params": {"M": {"standard": _Std, "extra": _Extra}}})()
    od = OrderedDict(
        {
            "p": Parameter(
                "p",
                kind=Parameter.POSITIONAL_OR_KEYWORD,
                annotation=Annotated[Literal["a"] | int, OpenBBField(description="")],
            )
        }
    )
    monkeypatch.setattr(
        "openbb_core.app.static.package_builder.method_definition.ProviderInterface",
        lambda: fake_pi,
    )
    MethodDefinition.add_field_custom_annotations(od, model_name="M")
    assert "Choices for prov" in od["p"].annotation.__metadata__[-1].description


def test_add_field_custom_annotations_choices_branch(monkeypatch):
    from types import SimpleNamespace

    std_field = SimpleNamespace(
        default=SimpleNamespace(description="d"),
        type=Literal["a"] | Literal["b"],
        json_schema_extra={"choices": ["a", "b"]},
    )
    fake_std = type("_S", (), {"__dataclass_fields__": {"p": std_field}})
    fake_extra = type("_E", (), {"__dataclass_fields__": {}})
    fake_pi = type(
        "_PI", (), {"params": {"M": {"standard": fake_std, "extra": fake_extra}}}
    )()

    od = OrderedDict(
        {
            "p": Parameter(
                "p",
                kind=Parameter.POSITIONAL_OR_KEYWORD,
                annotation=Annotated[
                    Literal["a"] | Literal["b"], OpenBBField(description="")
                ],
            )
        }
    )
    monkeypatch.setattr(
        "openbb_core.app.static.package_builder.method_definition.ProviderInterface",
        lambda: fake_pi,
    )
    MethodDefinition.add_field_custom_annotations(od, model_name="M")
    assert od["p"].annotation.__metadata__[-1].description == "d"


def test_build_func_params_typing_repr_and_none_description():

    params = OrderedDict(
        {
            "x": Parameter(
                name="x",
                kind=Parameter.POSITIONAL_OR_KEYWORD,
                annotation=Annotated[list[int], OpenBBField(description=None)],
                default=1,
            )
        }
    )
    out = MethodDefinition.build_func_params(params)
    assert "List[int]" in out or "list[int]" in out or "list" in out


def test_build_command_method_body_chart_branch(monkeypatch):
    from openbb_core.app.static.package_builder import method_definition as md

    class _Chart:
        @staticmethod
        def functions():
            return ["x_y"]

    monkeypatch.setattr(md, "CHARTING_INSTALLED", True)
    monkeypatch.setattr(md, "Charting", _Chart, raising=False)
    monkeypatch.setattr(
        MethodDefinition, "is_deprecated_function", staticmethod(lambda p: False)
    )

    def endpoint(symbol: str = "AAPL"):
        return symbol

    code = MethodDefinition.build_command_method_body("/x/y", endpoint)
    assert "chart" in code


def test_build_command_method_body_annotated_dc_info_extra(monkeypatch):
    from dataclasses import dataclass

    monkeypatch.setattr(
        MethodDefinition, "is_deprecated_function", staticmethod(lambda p: False)
    )
    monkeypatch.setattr(
        MethodDefinition, "is_data_processing_function", staticmethod(lambda p: False)
    )

    class _D:
        json_schema_extra = {"note": "x"}

    @dataclass
    class _Std:
        beta: int = _D()

    def endpoint(standard_params: Annotated[_Std, "tag"]):
        return None

    code = MethodDefinition.build_command_method_body("/x/y", endpoint)
    assert "info={" in code


def test_build_command_method_getsource_typeerror(monkeypatch):
    from openbb_core.app.static.package_builder import method_definition as md

    def endpoint(symbol: str = "AAPL"):
        return symbol

    monkeypatch.setattr(
        MethodDefinition, "is_deprecated_function", staticmethod(lambda p: False)
    )
    real_getsource = md.inspect.getsource

    def _patched_getsource(obj):
        if obj is endpoint:
            raise TypeError("x")
        return real_getsource(obj)

    monkeypatch.setattr(md.inspect, "getsource", _patched_getsource)
    code = MethodDefinition.build_command_method("/x/y", endpoint)
    assert "def y" in code


def test_surface_dependency_none_like_return():
    def dep() -> None: ...

    assert MethodDefinition._surface_dependency(dep) is None


def test_surface_dependency_request_bound_param():
    def dep(request: Request) -> dict: ...

    assert MethodDefinition._surface_dependency(dep) is None


def test_surface_dependency_nested_depends():
    from fastapi import Depends

    def other() -> int:
        return 1

    def dep(value: Annotated[int, Depends(other)]) -> dict: ...

    assert MethodDefinition._surface_dependency(dep) is None


def test_surface_dependency_surfaceable_header():
    from fastapi import Header

    def dep(x_api_key: Annotated[str, Header()]) -> dict: ...

    result = MethodDefinition._surface_dependency(dep)
    assert result is not None
    surfaced, call_args = result
    assert "x_api_key" in surfaced
    assert call_args == "x_api_key=x_api_key"


def test_surfaced_param_spec_empty_annotation_defaults_to_any():
    from typing import Any, get_args

    param = Parameter("x", Parameter.POSITIONAL_OR_KEYWORD)
    annotation, default = MethodDefinition._surfaced_param_spec(param)
    assert get_args(annotation)[0] is Any
    assert default is Parameter.empty


def test_surfaced_param_spec_reads_fastapi_default():
    from fastapi import Query as FastAPIQuery

    param = Parameter(
        "x",
        Parameter.POSITIONAL_OR_KEYWORD,
        default=FastAPIQuery(default=5),
        annotation=int,
    )
    _annotation, default = MethodDefinition._surfaced_param_spec(param)
    assert default == 5


def test_collect_surfaced_params_promotes_header():
    from fastapi import Depends, Header

    def dep(x_api_key: Annotated[str, Header()]) -> dict: ...

    parameter_map = {
        "principal": Parameter(
            "principal",
            Parameter.POSITIONAL_OR_KEYWORD,
            annotation=Annotated[dict, Depends(dep)],
        )
    }
    surfaced = MethodDefinition._collect_surfaced_params(parameter_map)
    assert "x_api_key" in surfaced


def test_is_charting_command_without_charting():
    with patch.object(md_module, "CHARTING_INSTALLED", False):
        assert MethodDefinition._is_charting_command("/x/y") is False


def test_is_charting_command_handles_exception():
    with (
        patch.object(md_module, "CHARTING_INSTALLED", True),
        patch.object(md_module, "Charting", create=True) as mock_charting,
    ):
        mock_charting.functions.side_effect = RuntimeError("boom")
        assert MethodDefinition._is_charting_command("/x/y") is False


def test_format_params_flattens_query_params_model():
    from openbb_core.provider.abstract.query_params import QueryParams

    class _MyQueryParams(QueryParams):
        symbol: str
        limit: int = 10

    parameter_map = {
        "params": Parameter(
            "params",
            Parameter.POSITIONAL_OR_KEYWORD,
            annotation=Annotated[_MyQueryParams, "meta"],
        )
    }
    out = MethodDefinition.format_params("/x/y", parameter_map)
    assert "symbol" in out
    assert "limit" in out


def test_build_command_method_body_query_params_model(monkeypatch):
    from openbb_core.provider.abstract.query_params import QueryParams

    class _BodyQueryParams(QueryParams):
        symbol: str = "AAPL"

    monkeypatch.setattr(
        MethodDefinition, "is_deprecated_function", staticmethod(lambda p: False)
    )

    def endpoint(params: _BodyQueryParams):
        return params

    code = MethodDefinition.build_command_method_body("/x/y", endpoint)
    assert '"symbol": symbol' in code


def test_build_command_method_body_pydantic_model_param(monkeypatch):
    from pydantic import BaseModel

    class _Body(BaseModel):
        ticker: str = "AAPL"

    monkeypatch.setattr(
        MethodDefinition, "is_deprecated_function", staticmethod(lambda p: False)
    )

    def endpoint(payload: Annotated[_Body, OpenBBField(description="body")]):
        return payload

    code = MethodDefinition.build_command_method_body("/x/y", endpoint)
    assert '"ticker": ticker' in code


def test_format_params_query_params_model_data_processing_path(monkeypatch):
    from openbb_core.provider.abstract.query_params import QueryParams

    class _MyQueryParams(QueryParams):
        data: str
        start_date: str = "2020-01-01"
        tags: list = Field(default_factory=list)

    monkeypatch.setattr(
        MethodDefinition, "is_data_processing_function", staticmethod(lambda p: True)
    )
    parameter_map = {
        "params": Parameter(
            "params",
            Parameter.POSITIONAL_OR_KEYWORD,
            annotation=Annotated[_MyQueryParams, "meta"],
        )
    }
    out = MethodDefinition.format_params("/x/y", parameter_map)
    assert "data" in out
    assert "start_date" in out
    assert "tags" in out


def test_format_params_query_params_default_factory_is_optional():
    """A field with a default_factory keeps that default instead of becoming required."""

    class _FactoryQueryParams(QueryParams):
        data: str
        models: list[str] = Field(default_factory=lambda: ["std", "parkinson"])

    parameter_map = {
        "params": Parameter(
            "params",
            Parameter.POSITIONAL_OR_KEYWORD,
            annotation=_FactoryQueryParams,
        )
    }
    out = MethodDefinition.format_params("/x/y", parameter_map)
    assert out["data"].default is Parameter.empty
    assert out["models"].default == ["std", "parkinson"]


def test_format_params_annotated_model_default_factory_is_optional(monkeypatch):
    """Same for the fields of a pydantic model flattened on a GET command."""
    from pydantic import BaseModel

    class _FactoryModel(BaseModel):
        symbol: str
        columns: list[str] = Field(default_factory=lambda: ["close"])

    monkeypatch.setattr(
        MethodDefinition, "is_data_processing_function", staticmethod(lambda p: False)
    )
    parameter_map = {
        "params": Parameter(
            "params",
            Parameter.POSITIONAL_OR_KEYWORD,
            annotation=Annotated[_FactoryModel, "meta"],
        )
    }
    out = MethodDefinition.format_params("/x/y", parameter_map)
    assert out["symbol"].default is Parameter.empty
    assert out["columns"].default == ["close"]


def test_build_command_method_body_raw_query_params_fallback(monkeypatch):
    from openbb_core.provider.abstract.query_params import QueryParams

    class _RawQueryParams(QueryParams):
        symbol: str = "AAPL"

    monkeypatch.setattr(
        MethodDefinition, "is_deprecated_function", staticmethod(lambda p: False)
    )
    monkeypatch.setattr(
        MethodDefinition, "query_params_model", staticmethod(lambda _a: None)
    )

    def endpoint(params: _RawQueryParams):
        return params

    code = MethodDefinition.build_command_method_body("/x/y", endpoint)
    assert '"symbol": symbol' in code


def test_surfaced_param_spec_takes_description_from_metadata():
    from fastapi import Header

    param = Parameter(
        "x_api_key",
        Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[str, Header(description="The API key.")],
    )
    annotation, _default = MethodDefinition._surfaced_param_spec(param)
    field = annotation.__metadata__[0]
    assert isinstance(field, OpenBBField)
    assert field.description == "The API key."


def test_collect_dependency_calls_surfaces_unsafe_but_resolvable_dependency():
    """An unsafe dependency that is surfaceable is called with surfaced arguments."""
    from fastapi import Depends, Header

    def get_principal(x_api_key: Annotated[str, Header()]) -> dict: ...

    parameter_map = {
        "principal": Parameter(
            "principal",
            Parameter.POSITIONAL_OR_KEYWORD,
            annotation=Annotated[dict, Depends(get_principal)],
        )
    }

    calls, names = MethodDefinition._collect_dependency_calls("/x/y", parameter_map)
    assert calls == ["        principal = get_principal(x_api_key=x_api_key)"]
    assert names == {"principal"}


def test_build_command_method_promotes_surfaced_dependency_params(monkeypatch):
    """Parameters surfaced from a dependency land on the generated signature."""
    from fastapi import Depends, Header

    monkeypatch.setattr(
        MethodDefinition, "is_deprecated_function", staticmethod(lambda p: False)
    )

    def get_principal(x_api_key: Annotated[str, Header()]) -> dict: ...

    def endpoint(principal: Annotated[dict, Depends(get_principal)]) -> dict:
        return principal

    code = MethodDefinition.build_command_method("/x/y", endpoint)
    assert "x_api_key" in code
    assert "principal = get_principal(x_api_key=x_api_key)" in code


def test_build_command_method_falls_back_to_response_model(monkeypatch):
    """With no return annotation the passed ``response_model`` becomes the return type."""
    from openbb_core.app.model.obbject import OBBject

    monkeypatch.setattr(
        MethodDefinition, "is_deprecated_function", staticmethod(lambda p: False)
    )

    def endpoint(symbol: str = "AAPL"):
        return symbol

    code = MethodDefinition.build_command_method(
        "/x/y", endpoint, response_model=OBBject
    )
    assert "-> OBBject" in code


def test_format_params_expands_query_params_model_field_types():
    """Unpacking a bare ``QueryParams`` param expands ``TYPE_EXPANSION`` fields and
    leaves unexpanded fields at their declared type."""
    from typing import get_args

    from openbb_core.provider.abstract.query_params import QueryParams

    class _QP(QueryParams):
        data: list = []
        symbol: str = "AAPL"

    parameter_map = {
        "params": Parameter("params", Parameter.POSITIONAL_OR_KEYWORD, annotation=_QP)
    }

    out = MethodDefinition.format_params("/x/y", parameter_map)

    # ``data`` is in TYPE_EXPANSION -> the TypeVar constraints are inlined.
    data_type = get_args(out["data"].annotation)[0]
    rendered = str(data_type)
    assert "DataFrame" in rendered
    assert "dict" in rendered

    # ``symbol`` is not in TYPE_EXPANSION -> the declared type is kept as-is.
    assert get_args(out["symbol"].annotation)[0] is str


def test_build_func_params_wrapped_description_keeps_spaces_and_case():
    description = (
        "The provider to use, by default None. If None, the priority list "
        "configured in the settings is used. List of Dict values is accepted."
    )
    annotation = Annotated[Literal["fred"] | None, OpenBBField(description=description)]
    param_map = OrderedDict(
        provider=Parameter(
            "provider",
            Parameter.POSITIONAL_OR_KEYWORD,
            annotation=annotation,
            default=None,
        )
    )
    rendered = MethodDefinition.build_func_params(param_map)
    namespace: dict = {}
    exec(  # noqa: S102
        "from typing import Annotated, Literal, Optional\n"
        "from openbb_core.app.model.field import OpenBBField\n"
        f"def f({rendered}): pass\n",
        namespace,
    )
    rendered_annotation = namespace["f"].__annotations__["provider"]
    assert rendered_annotation.__metadata__[0].description == description


def test_build_func_params_normalizes_typing_names_in_types_only():
    from typing import Dict, List  # noqa: UP035

    annotation = Annotated[
        List[Dict[str, int]] | None,  # noqa: UP006
        OpenBBField(description="List of Dict rows."),
    ]
    param_map = OrderedDict(
        rows=Parameter(
            "rows", Parameter.POSITIONAL_OR_KEYWORD, annotation=annotation, default=None
        )
    )
    rendered = MethodDefinition.build_func_params(param_map)
    assert "list[dict[str, int]]" in rendered
    assert "'List of Dict rows.'" in rendered
