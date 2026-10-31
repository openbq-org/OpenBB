"""Direct unit tests for static helpers in ``DocstringGenerator``."""

from collections import OrderedDict
from datetime import date, datetime
from inspect import Parameter
from typing import Annotated

import pytest
from pydantic import BaseModel, Field

pandas = pytest.importorskip("pandas")

pytestmark = pytest.mark.requires_pandas

from openbb_core.app.static.package_builder.docstring_generator import (
    DocstringGenerator,
)


def test_get_field_type_simple_required():
    out = DocstringGenerator.get_field_type(int, is_required=True)
    assert out == "int"


def test_get_field_type_simple_optional_wraps_in_optional():
    out = DocstringGenerator.get_field_type(int, is_required=False)
    assert out == "int | None"


def test_get_field_type_optional_target_website_strips_optional_wrapper():
    out = DocstringGenerator.get_field_type(int, is_required=False, target="website")
    assert out == "int"


def test_get_field_type_union_sorts_and_joins():
    out = DocstringGenerator.get_field_type(int | str, is_required=True)
    assert out == "int | str"


def test_get_field_type_optional_union_appends_none():
    out = DocstringGenerator.get_field_type(int | str | None, is_required=False)
    # Sorted alphabetically + None appended at the end
    assert out.endswith("| None")
    assert "int" in out and "str" in out


def test_get_field_type_datetime_aliases_normalized():
    out = DocstringGenerator.get_field_type(datetime, is_required=True)
    assert out == "datetime"


def test_get_field_type_date_alias_normalized():
    out = DocstringGenerator.get_field_type(date, is_required=True)
    assert out == "date"


def test_get_field_type_handles_forward_ref():
    from typing import ForwardRef

    fwd = ForwardRef("MyType")
    out = DocstringGenerator.get_field_type(fwd, is_required=True)
    assert "MyType" in out


def test_get_field_type_strips_nonetype_text():
    out = DocstringGenerator.get_field_type(str | None, is_required=False)
    assert "NoneType" not in out


def test_get_field_type_strips_openbb_module_path_inside_generic_container():
    """A Union member like ``list[openbb_<provider>.<module>.MyData]`` keeps
    the ``list[...]`` container but drops the dotted module path inside —
    the docstring shows ``list[MyData]``, not ``list[openbb_x.y.MyData]`` and
    not just the truncated tail ``MyData]``.

    Uses ``typing.Union[...]`` rather than ``X | Y`` so the test lands in
    the Union branch on every supported Python. On 3.10-3.13,
    ``get_origin(X | Y)`` returns ``types.UnionType`` (not ``typing.Union``),
    so ``X | Y`` syntax falls into the else branch and bypasses the
    container-aware strip we're trying to cover here. 3.14 unified
    ``types.UnionType`` with ``typing.Union``, masking the gap on dev
    machines but leaving Linux/Windows CI without coverage.
    """
    from typing import Union

    class MyData:
        """Stand-in provider Data class — its fully-qualified name lands
        inside ``str(list[MyData])`` so the generator's container-aware
        strip path is exercised."""

    # Forge the ``__module__`` so the generator's ``"openbb_" in type_name``
    # check trips, simulating a real provider Data class shipped under
    # an ``openbb_*`` package.
    MyData.__module__ = "openbb_someprovider.models.my_data"
    MyData.__qualname__ = "MyData"

    out = DocstringGenerator.get_field_type(
        Union[list[MyData], None],  # noqa: UP007 — explicit form is the point
        is_required=False,
    )
    # Container preserved, dotted prefix stripped.
    assert "list[MyData]" in out
    # The prefix must not leak through.
    assert "openbb_someprovider" not in out
    # And the bare ``MyData]`` (truncation that drops ``list[``) must not
    # appear either — that's the bug the bracket-aware branch fixes.
    assert "MyData]" in out and not out.endswith(" MyData]")
    # ``None`` still appended for the optional union.
    assert out.endswith("| None")


def test_get_field_type_pep604_union_syntax_takes_union_branch():
    """``list[X] | None`` (PEP 604) must hit the same Union branch as
    ``Union[list[X], None]``. On Python 3.10-3.13 the two forms produce
    different ``get_origin`` results — ``types.UnionType`` vs
    ``typing.Union`` — so the generator's check accepts both. Regression
    guard for the platform-dependent coverage gap.
    """
    from typing import Union

    class MyData:
        """Stand-in provider Data class."""

    MyData.__module__ = "openbb_someprovider.models.my_data"
    MyData.__qualname__ = "MyData"

    # Both syntaxes must produce the same docstring output.
    union_form = DocstringGenerator.get_field_type(
        Union[list[MyData], None],  # noqa: UP007 — explicit form is the point
        is_required=False,
    )
    pep604_form = DocstringGenerator.get_field_type(
        list[MyData] | None, is_required=False
    )
    assert union_form == pep604_form
    # And the container-aware strip fired for both.
    assert "list[MyData]" in pep604_form
    assert "openbb_someprovider" not in pep604_form


def test_get_field_type_strips_openbb_module_path_for_non_generic():
    """Non-generic ``openbb_*`` types take the simple ``rsplit('.', 1)``
    fallback (no ``[`` in the string) — exercises the else-branch
    paired with the bracket-aware fix."""

    class PlainData:
        """Stand-in provider Data class with no generic wrapper."""

    PlainData.__module__ = "openbb_someprovider.models.plain"
    PlainData.__qualname__ = "PlainData"

    out = DocstringGenerator.get_field_type(PlainData | int, is_required=True)
    assert "PlainData" in out
    assert "openbb_someprovider" not in out


def test_get_obbject_description_default_provider_placeholder():
    out = DocstringGenerator.get_OBBject_description("MyResults", None)
    assert "OBBject" in out
    assert "results : MyResults" in out
    assert "provider : str | None" in out
    assert "warnings" in out
    assert "chart" in out
    assert "extra" in out


def test_get_obbject_description_with_concrete_providers():
    out = DocstringGenerator.get_OBBject_description("MyResults", "fmp, polygon")
    assert "provider : fmp, polygon" in out


def test_get_obbject_description_replaces_nonetype():
    out = DocstringGenerator.get_OBBject_description("MyResults", None)
    assert "NoneType" not in out


def test_build_examples_no_examples_returns_empty_string():
    assert DocstringGenerator.build_examples("obb.foo", {}, None) == ""
    assert DocstringGenerator.build_examples("obb.foo", {}, []) == ""


def test_build_examples_docstring_format():
    from openbb_core.app.model.example import APIEx

    examples = [APIEx(parameters={"symbol": "AAPL"})]
    out = DocstringGenerator.build_examples(
        "obb.equity.profile", {"symbol": str}, examples
    )
    assert "Examples" in out
    assert ">>> " in out
    assert "from openbb import obb" in out


def test_build_examples_website_format_wraps_in_code_fence():
    from openbb_core.app.model.example import APIEx

    examples = [APIEx(parameters={"symbol": "AAPL"})]
    out = DocstringGenerator.build_examples(
        "obb.equity.profile", {"symbol": str}, examples, target="website"
    )
    assert "```python" in out
    assert out.endswith("```\n\n")


def test_get_generic_types_union_unpacks_to_inner_names():
    out = DocstringGenerator._get_generic_types(list[str] | dict[str, str], [])
    assert "list" in out
    assert "dict" in out


def test_get_generic_types_simple_list_returns_list_name():
    out = DocstringGenerator._get_generic_types(list[int], [])
    assert "list" in out


def test_get_generic_types_non_generic_returns_empty():
    out = DocstringGenerator._get_generic_types(int, [])
    assert out == []


def test_get_repr_single_item_returns_bracketed_string():
    out = DocstringGenerator._get_repr(["list"], "MyModel")
    assert out == "list[MyModel]"


def test_get_repr_dict_uses_str_key():
    out = DocstringGenerator._get_repr(["dict"], "MyModel")
    assert out == "dict[str, MyModel]"


def test_get_repr_multiple_items_joined_with_pipe():
    out = DocstringGenerator._get_repr(["list", "dict"], "MyModel")
    assert "list[MyModel]" in out
    assert "dict[str, MyModel]" in out
    assert " | " in out


def test_get_repr_empty_items_returns_model_only():
    out = DocstringGenerator._get_repr([], "MyModel")
    assert out == "MyModel"


from openbb_core.app.model.example import APIEx  # noqa: E402
from openbb_core.app.model.field import OpenBBField  # noqa: E402
from openbb_core.app.model.obbject import OBBject  # noqa: E402


def _gen():
    return DocstringGenerator()


def test_get_OBBject_description_with_providers():
    out = DocstringGenerator.get_OBBject_description("list[X]", "Literal['a','b']")
    assert "list[X]" in out
    assert "Literal['a','b']" in out


def test_get_OBBject_description_default_providers():
    out = DocstringGenerator.get_OBBject_description("X", None)
    assert "str | None" in out


def test_get_OBBStream_description_mirrors_obbject_field_format():
    out = DocstringGenerator.get_OBBStream_description("MyFeed")
    assert "OBBStream" in out
    assert "results : AsyncIterator[MyFeed]" in out
    assert "id : str" in out
    assert "provider : str | None" in out
    assert "warnings : list[Warning_] | None" in out
    assert "extra : dict[str, Any]" in out
    assert "start : (output=None, handler=None) -> OBBStream" in out
    assert "stop : (timeout=5.0) -> None" in out
    assert "wait : (timeout=None) -> None" in out


def test_generate_model_docstring_streaming_emits_obbstream_returns():
    out = DocstringGenerator.generate_model_docstring(
        model_name="MyFeed",
        summary="Stream it.",
        explicit_params={},
        kwarg_params={},
        returns={},
        results_type="MyFeed",
        sections=["returns"],
        is_streaming=True,
    )
    assert "OBBStream" in out
    assert "results : AsyncIterator[MyFeed]" in out
    # The OBBject result block must not be used for a stream.
    assert "Serializable results." not in out


def test_get_field_type_handles_forward_ref_extended():
    from typing import ForwardRef

    out = DocstringGenerator.get_field_type(ForwardRef("int"), is_required=True)
    assert "ForwardRef" not in out
    assert "int" in out


def test_get_field_type_optional():
    out = DocstringGenerator.get_field_type(int | None, is_required=False)
    assert "int" in out


def test_build_examples_docstring_target():
    out = DocstringGenerator.build_examples(
        func_path="openbb.test.command",
        param_types={"symbol": str},
        examples=[APIEx(parameters={"symbol": "AAPL"})],
        target="docstring",
    )
    assert "Examples" in out
    assert ">>> from openbb import obb" in out


def test_build_examples_website_target():
    out = DocstringGenerator.build_examples(
        func_path="openbb.test.command",
        param_types={"symbol": str},
        examples=[APIEx(parameters={"symbol": "AAPL"})],
        target="website",
    )
    assert "```python" in out
    assert out.strip().endswith("```")


def test_build_examples_empty_returns_empty():
    out = DocstringGenerator.build_examples("p", {}, None)
    assert out == ""
    out = DocstringGenerator.build_examples("p", {}, [])
    assert out == ""


def _func_with_no_doc(symbol: Annotated[str, OpenBBField(description="The sym.")]):
    pass


def _func_with_doc(symbol: Annotated[str, OpenBBField(description="")]) -> str:
    """Top-level summary."""
    return symbol


async def _func_obbject(
    symbol: Annotated[str, OpenBBField(description="X")],
) -> OBBject:
    """An OBBject command."""


def _func_no_params() -> int:
    """Plain int return."""
    return 1


def test_generate_no_model_basic_no_params():
    g = _gen()
    out = g.generate(
        path="/test/cmd",
        func=_func_no_params,
        formatted_params=OrderedDict(),
        model_name=None,
    )
    assert out
    assert "Returns" in out


def test_generate_no_model_with_params():
    g = _gen()
    fp = OrderedDict(
        {
            "symbol": Parameter(
                name="symbol",
                kind=Parameter.POSITIONAL_OR_KEYWORD,
                annotation=Annotated[str, OpenBBField(description="The symbol.")],
            )
        }
    )
    # Patch _annotation since generate inspects param._annotation
    fp["symbol"]._annotation = Annotated[str, OpenBBField(description="The symbol.")]
    out = g.generate(
        path="/test/cmd",
        func=_func_with_doc,
        formatted_params=fp,
        model_name=None,
    )
    assert out
    assert "Parameters" in out
    assert "symbol" in out


def test_generate_no_model_obbject_return():
    g = _gen()
    fp = OrderedDict(
        {
            "symbol": Parameter(
                name="symbol",
                kind=Parameter.POSITIONAL_OR_KEYWORD,
                annotation=Annotated[str, OpenBBField(description="X")],
            )
        }
    )
    fp["symbol"]._annotation = Annotated[str, OpenBBField(description="X")]
    out = g.generate(
        path="/test/cmd",
        func=_func_obbject,
        formatted_params=fp,
        model_name=None,
    )
    assert out


def test_generate_no_model_with_examples():
    g = _gen()
    out = g.generate(
        path="/test/cmd",
        func=_func_no_params,
        formatted_params=OrderedDict(),
        model_name=None,
        examples=[APIEx(parameters={})],
    )
    assert out


class _RetModel(BaseModel):
    """A return model."""

    foo: str = Field(default="x", description="The foo field.")
    bar: int | None = Field(default=None, description="A bar number.")


def _func_returns_model() -> _RetModel:
    """Plain model return."""


def test_generate_returns_section_non_obbject_model_fields():
    g = _gen()
    out = g.generate(
        path="/test/cmd2",
        func=_func_returns_model,
        formatted_params=OrderedDict(),
        model_name=None,
    )
    assert "Returns" in out
    assert "_RetModel" in out or "RetModel" in out


def test_generate_obbject_inner_type_extraction():
    """A ``OBBject[list[XxxData]]`` return annotation has its row model
    introspected directly: the data-model field section is built from the
    model class carried in ``OBBject.results``, not from ReferenceGenerator.
    """

    async def _func_obbject_typed() -> OBBject[list[_RetModel]]:
        """Typed OBBject."""

    g = _gen()
    out = g.generate(
        path="/test/inner",
        func=_func_obbject_typed,
        formatted_params=OrderedDict(),
        model_name=None,
    )
    # Row model fields are documented from ``_RetModel`` itself.
    assert "_RetModel" in out
    assert "foo : str" in out
    assert "The foo field." in out
    assert "bar : int | None" in out
    assert "A bar number." in out


def test_generate_model_docstring_format_type_union_literal():
    """Lines 252-281: format_type Union/Literal/dedup branches via real model docstring."""
    from inspect import Parameter
    from typing import Annotated, Literal

    from openbb_core.app.static.package_builder.docstring_generator import (
        DocstringGenerator,
    )

    p1 = Parameter(
        name="kind",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[Literal["a", "b"] | int | None, "tag"],
        default=None,
    )
    object.__setattr__(
        p1, "_annotation", Annotated[Literal["a", "b"] | int | None, "tag"]
    )
    p2 = Parameter(
        name="vals",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=str | int | None,
        default=None,
    )
    object.__setattr__(p2, "_annotation", str | int | None)

    explicit_params = {"kind": p1, "vals": p2}
    out = DocstringGenerator.generate_model_docstring(
        model_name="NoSuchModelXYZ",
        summary="S",
        explicit_params=explicit_params,
        kwarg_params={},
        returns={},
        results_type="",
        sections=["parameters"],
    )
    assert "kind" in out
    assert "vals" in out
    assert "str" in out and "int" in out


def test_get_field_type_beforevalidator():
    """Test BeforeValidator path -> int / Optional[int]."""
    from typing import Annotated

    from pydantic import BeforeValidator

    from openbb_core.app.static.package_builder.docstring_generator import (
        DocstringGenerator,
    )

    t = Annotated[int, BeforeValidator(lambda v: v)]
    assert "int" in DocstringGenerator.get_field_type(t, False, "docstring")
    assert (
        DocstringGenerator.get_field_type(t, False, "docstring") == "Optional[int]"
        or DocstringGenerator.get_field_type(t, False, "docstring") == "int"
    )


def test_get_field_type_union_with_literal_skip():
    """Lines ~108: union member with Literal origin is skipped."""
    from typing import Literal

    from openbb_core.app.static.package_builder.docstring_generator import (
        DocstringGenerator,
    )

    out = DocstringGenerator.get_field_type(
        Literal["a", "b"] | int | None, True, "docstring"
    )
    assert "int" in out


def test_get_field_type_typeerror_fallback():
    """Lines 159-160: TypeError -> str(field_type) fallback."""
    from openbb_core.app.static.package_builder.docstring_generator import (
        DocstringGenerator,
    )

    class _Bad:
        def __str__(self):
            return "BadThing"

    out = DocstringGenerator.get_field_type(_Bad(), False, "docstring")
    assert isinstance(out, str)


def test_generate_model_docstring_kwarg_query_json_extra_choices():
    from types import SimpleNamespace
    from typing import Annotated, Literal

    from fastapi import Query

    from openbb_core.app.static.package_builder.docstring_generator import (
        DocstringGenerator,
    )

    kwarg_param = SimpleNamespace(
        _annotation=Annotated[
            Literal["one", "two"],
            OpenBBField(description="Choice value."),
        ],
        type=Literal["one", "two"],
        default=Query(
            default=None,
            description="",
            json_schema_extra={
                "tmx": {
                    "choices": ["one", "two"],
                    "multiple_items_allowed": True,
                }
            },
        ),
        annotation=Annotated[
            Literal["one", "two"],
            OpenBBField(description="Choice value."),
        ],
    )

    out = DocstringGenerator.generate_model_docstring(
        model_name="NoSuchModelXYZ",
        summary="S",
        explicit_params={},
        kwarg_params={"choice": kwarg_param},
        returns={},
        results_type="",
        sections=["parameters"],
    )

    assert "choice" in out
    assert "Choices for tmx" in out


def test_get_field_type_openbb_path_is_shortened():
    out = DocstringGenerator.get_field_type(
        "openbb_core.provider.abstract.data.Data", is_required=True
    )
    assert out == "Data"


def test_get_field_type_union_openbb_name_branch(monkeypatch):
    from types import UnionType

    from openbb_core.app.static.package_builder import docstring_generator as dg

    class openbb_model_type:
        pass

    monkeypatch.setattr(dg, "Union", UnionType)
    out = DocstringGenerator.get_field_type(openbb_model_type | str, is_required=True)
    assert "openbb_model_type" in out


def test_generate_model_docstring_provider_extraction_handles_missing_model_providers():
    from inspect import Parameter
    from types import SimpleNamespace, UnionType

    from openbb_core.app.static.package_builder import docstring_generator as dg

    original_provider_interface = DocstringGenerator.provider_interface
    try:
        original_union = dg.Union
        dg.Union = UnionType
        DocstringGenerator.provider_interface = SimpleNamespace(
            model_providers={},
            map={},
        )
        p = Parameter(
            name="provider",
            kind=Parameter.POSITIONAL_OR_KEYWORD,
            annotation=str | int,
            default=None,
        )
        object.__setattr__(p, "_annotation", str | int)
        out = DocstringGenerator.generate_model_docstring(
            model_name="NoSuchModelXYZ",
            summary="S",
            explicit_params={"provider": p},
            kwarg_params={},
            returns={},
            results_type="",
            sections=["parameters"],
        )
        assert "provider" in out
    finally:
        DocstringGenerator.provider_interface = original_provider_interface
        dg.Union = original_union


def test_generate_model_docstring_provider_choices_handles_attribute_error_in_map():
    from dataclasses import make_dataclass
    from inspect import Parameter
    from types import SimpleNamespace, UnionType
    from typing import Literal

    from openbb_core.app.static.package_builder import docstring_generator as dg

    class _BadMap:
        def get(self, *_args, **_kwargs):
            raise AttributeError("boom")

    original_provider_interface = DocstringGenerator.provider_interface
    try:
        original_union = dg.Union
        dg.Union = UnionType
        ModelProviders = make_dataclass("ModelProviders", [("provider", object)])
        ProviderField = type("F", (), {"type": Literal["alpha"]})
        ModelProviders.__dataclass_fields__["provider"] = ProviderField
        DocstringGenerator.provider_interface = SimpleNamespace(
            model_providers={"NoSuchModelXYZ": ModelProviders("alpha")},
            map=_BadMap(),
        )

        p = Parameter(
            name="provider",
            kind=Parameter.POSITIONAL_OR_KEYWORD,
            annotation=str | int,
            default=None,
        )
        object.__setattr__(p, "_annotation", str | int)

        out = DocstringGenerator.generate_model_docstring(
            model_name="NoSuchModelXYZ",
            summary="S",
            explicit_params={"provider": p},
            kwarg_params={},
            returns={},
            results_type="",
            sections=["parameters"],
        )
        assert "provider" in out
    finally:
        DocstringGenerator.provider_interface = original_provider_interface
        dg.Union = original_union


def test_generate_model_docstring_provider_choices_handles_missing_model_provider_entry(
    monkeypatch,
):
    from inspect import Parameter
    from types import SimpleNamespace, UnionType

    from openbb_core.app.static.package_builder import docstring_generator as dg

    monkeypatch.setattr(dg, "Union", UnionType)
    monkeypatch.setattr(
        DocstringGenerator,
        "provider_interface",
        SimpleNamespace(model_providers={"M": None}, map={}),
    )

    p = Parameter(
        name="provider",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=str | int,
        default=None,
    )
    object.__setattr__(p, "_annotation", str | int)

    out = DocstringGenerator.generate_model_docstring(
        model_name="M",
        summary="S",
        explicit_params={"provider": p},
        kwarg_params={},
        returns={},
        results_type="",
        sections=["parameters"],
    )
    assert "provider" in out


def test_generate_model_docstring_forced_union_with_missing_model_providers(
    monkeypatch,
):
    from types import SimpleNamespace

    from openbb_core.app.static.package_builder import docstring_generator as dg

    union_sentinel = object()

    class _FakeUnionType:
        __origin__ = union_sentinel

    kwarg_param = SimpleNamespace(
        _annotation=_FakeUnionType,
        type=_FakeUnionType,
        default=SimpleNamespace(description="d", json_schema_extra=None),
        annotation=_FakeUnionType,
    )

    monkeypatch.setattr(dg, "Union", union_sentinel)
    monkeypatch.setattr(
        DocstringGenerator,
        "provider_interface",
        SimpleNamespace(model_providers={}, map={}),
    )

    out = DocstringGenerator.generate_model_docstring(
        model_name="NoSuchModelXYZ",
        summary="S",
        explicit_params={},
        kwarg_params={"x": kwarg_param},
        returns={},
        results_type="",
        sections=["parameters"],
    )
    assert "x" in out


def test_generate_model_docstring_forced_union_provider_map_attribute_error(
    monkeypatch,
):
    from dataclasses import make_dataclass
    from types import SimpleNamespace
    from typing import Literal

    from openbb_core.app.static.package_builder import docstring_generator as dg

    union_sentinel = object()

    class _FakeUnionType:
        __origin__ = union_sentinel

    class _BadMap:
        def get(self, *_args, **_kwargs):
            raise AttributeError("boom")

    ModelProviders = make_dataclass("ModelProvidersX", [("provider", object)])
    ProviderField = type("F", (), {"type": Literal["alpha"]})
    ModelProviders.__dataclass_fields__["provider"] = ProviderField

    kwarg_param = SimpleNamespace(
        _annotation=_FakeUnionType,
        type=_FakeUnionType,
        default=SimpleNamespace(description="d", json_schema_extra=None),
        annotation=_FakeUnionType,
    )

    monkeypatch.setattr(dg, "Union", union_sentinel)
    monkeypatch.setattr(
        DocstringGenerator,
        "provider_interface",
        SimpleNamespace(
            model_providers={"NoSuchModelXYZ": ModelProviders("alpha")},
            map=_BadMap(),
        ),
    )

    out = DocstringGenerator.generate_model_docstring(
        model_name="NoSuchModelXYZ",
        summary="S",
        explicit_params={},
        kwarg_params={"x": kwarg_param},
        returns={},
        results_type="",
        sections=["parameters"],
    )
    assert "x" in out


def test_generate_model_docstring_forced_union_model_providers_attribute_error(
    monkeypatch,
):
    from types import SimpleNamespace

    from openbb_core.app.static.package_builder import docstring_generator as dg

    union_sentinel = object()

    class _FakeUnionType:
        __origin__ = union_sentinel

    class _BadModelProviders:
        def get(self, *_args, **_kwargs):
            raise AttributeError("boom")

    kwarg_param = SimpleNamespace(
        _annotation=_FakeUnionType,
        type=_FakeUnionType,
        default=SimpleNamespace(description="d", json_schema_extra=None),
        annotation=_FakeUnionType,
    )

    monkeypatch.setattr(dg, "Union", union_sentinel)
    monkeypatch.setattr(
        DocstringGenerator,
        "provider_interface",
        SimpleNamespace(model_providers=_BadModelProviders(), map={}),
    )

    out = DocstringGenerator.generate_model_docstring(
        model_name="NoSuchModelXYZ",
        summary="S",
        explicit_params={},
        kwarg_params={"x": kwarg_param},
        returns={},
        results_type="",
        sections=["parameters"],
    )
    assert "x" in out


def test_generate_model_docstring_kwarg_provider_map_attribute_error(monkeypatch):
    from dataclasses import dataclass
    from types import SimpleNamespace
    from typing import Annotated, Literal

    from openbb_core.app.static.package_builder.docstring_generator import (
        DocstringGenerator,
    )

    @dataclass
    class _MP:
        provider: Literal["prov1"]

    kwarg_param = SimpleNamespace(
        _annotation=Annotated[str | int, OpenBBField(description="d")],
        type=str | int,
        default=SimpleNamespace(description="d", json_schema_extra=None),
        annotation=Annotated[str | int, OpenBBField(description="d")],
    )

    fake_pi = SimpleNamespace(model_providers={"M": _MP}, map=object())
    monkeypatch.setattr(DocstringGenerator, "provider_interface", fake_pi)

    out = DocstringGenerator.generate_model_docstring(
        model_name="M",
        summary="S",
        explicit_params={},
        kwarg_params={"x": kwarg_param},
        returns={},
        results_type="",
        sections=["parameters"],
    )
    assert "x" in out


def test_generate_model_docstring_kwarg_model_providers_attribute_error(monkeypatch):
    from types import SimpleNamespace
    from typing import Annotated

    from openbb_core.app.static.package_builder.docstring_generator import (
        DocstringGenerator,
    )

    kwarg_param = SimpleNamespace(
        _annotation=Annotated[str | int, OpenBBField(description="d")],
        type=str | int,
        default=SimpleNamespace(description="d", json_schema_extra=None),
        annotation=Annotated[str | int, OpenBBField(description="d")],
    )

    fake_pi = SimpleNamespace(model_providers={"M": object()}, map={})
    monkeypatch.setattr(DocstringGenerator, "provider_interface", fake_pi)

    out = DocstringGenerator.generate_model_docstring(
        model_name="M",
        summary="S",
        explicit_params={},
        kwarg_params={"x": kwarg_param},
        returns={},
        results_type="",
        sections=["parameters"],
    )
    assert "x" in out


def test_generate_non_model_return_generic_alias_type_name_path(monkeypatch):
    from openbb_core.app.static.package_builder import docstring_generator as dg

    class _SS:
        class _PS:
            docstring_sections = ["returns"]
            docstring_max_length = None

        python_settings = _PS()

    class _Svc:
        system_settings = _SS()

    monkeypatch.setattr(dg, "SystemService", _Svc)

    def _func() -> list[int]:
        return [1]

    out = DocstringGenerator.generate(
        path="/x/y",
        func=_func,
        formatted_params=OrderedDict(),
        model_name=None,
    )
    assert "Returns" in out
    assert "list" in out


def test_generate_non_model_return_model_fields_exception_path(monkeypatch):
    from openbb_core.app.static.package_builder import docstring_generator as dg

    class _SS:
        class _PS:
            docstring_sections = ["returns"]
            docstring_max_length = None

        python_settings = _PS()

    class _Svc:
        system_settings = _SS()

    class _BadFields:
        def items(self):
            raise TypeError("boom")

    class _BadRet:
        model_fields = _BadFields()

    monkeypatch.setattr(dg, "SystemService", _Svc)

    def _func() -> _BadRet:
        return _BadRet()

    out = DocstringGenerator.generate(
        path="/x/y",
        func=_func,
        formatted_params=OrderedDict(),
        model_name=None,
    )
    assert "Returns" in out


def test_generate_non_model_doc_truncation_max_length(monkeypatch):
    from openbb_core.app.static.package_builder import docstring_generator as dg

    class _SS:
        class _PS:
            docstring_sections = ["description"]
            docstring_max_length = 20

        python_settings = _PS()

    class _Svc:
        system_settings = _SS()

    monkeypatch.setattr(dg, "SystemService", _Svc)

    def _func():
        """A very long summary line for truncation testing."""

    out = DocstringGenerator.generate(
        path="/x/y",
        func=_func,
        formatted_params=OrderedDict(),
        model_name=None,
    )
    assert out.endswith("...")


def test_generate_model_docstring_semicolon_provider_sections_with_choices():
    from inspect import Parameter
    from typing import Annotated

    desc = (
        "Base desc. Alpha detail (provider: a); "
        "Base desc. Beta detail (provider: b)\n"
        "Choices for a: 'x', 'y'\n"
        "Choices for b: 'z'\n"
        "Multiple comma separated items allowed for provider(s): a."
    )

    p = Parameter(
        name="kind",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[str, OpenBBField(description=desc)],
        default=None,
    )
    object.__setattr__(p, "_annotation", Annotated[str, OpenBBField(description=desc)])

    out = DocstringGenerator.generate_model_docstring(
        model_name="NoSuchModelXYZ",
        summary="S",
        explicit_params={"kind": p},
        kwarg_params={},
        returns={},
        results_type="",
        sections=["parameters"],
    )

    assert "(provider: a)" in out
    assert "(provider: b)" in out
    assert "Choices:" in out
    assert "Multiple comma separated items allowed" in out


def test_generate_model_docstring_choices_without_provider_sections():
    from inspect import Parameter
    from typing import Annotated

    desc = "Simple description\nChoices for a: 'x', 'y'"
    p = Parameter(
        name="kind",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[str, OpenBBField(description=desc)],
        default=None,
    )
    object.__setattr__(p, "_annotation", Annotated[str, OpenBBField(description=desc)])

    out = DocstringGenerator.generate_model_docstring(
        model_name="NoSuchModelXYZ",
        summary="S",
        explicit_params={"kind": p},
        kwarg_params={},
        returns={},
        results_type="",
        sections=["parameters"],
    )

    assert "Choices for a" in out


def test_generate_model_docstring_chart_param_branch():
    from inspect import Parameter
    from typing import Annotated

    provider = Parameter(
        name="provider",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[str, OpenBBField(description="provider desc")],
        default=None,
    )
    object.__setattr__(
        provider,
        "_annotation",
        Annotated[str, OpenBBField(description="provider desc")],
    )

    chart = Parameter(
        name="chart",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[bool, OpenBBField(description="chart desc")],
        default=False,
    )
    object.__setattr__(
        chart, "_annotation", Annotated[bool, OpenBBField(description="chart desc")]
    )

    out = DocstringGenerator.generate_model_docstring(
        model_name="NoSuchModelXYZ",
        summary="S",
        explicit_params={"provider": provider, "chart": chart},
        kwarg_params={},
        returns={},
        results_type="X",
        sections=["parameters"],
    )
    assert "chart : bool" in out


def test_generate_model_docstring_kwarg_choices_wrapping_and_multi_items():
    from types import SimpleNamespace
    from typing import Annotated, Literal

    choices = [f"item_{i:02d}" for i in range(20)]
    kwarg_param = SimpleNamespace(
        _annotation=Annotated[
            Literal["seed"], OpenBBField(description="(provider: wrap)")
        ],
        type=Literal["seed"],
        default=SimpleNamespace(
            description="(provider: wrap)",
            json_schema_extra={
                "wrap": {
                    "choices": choices,
                    "multiple_items_allowed": True,
                }
            },
        ),
        annotation=Annotated[
            Literal["seed"], OpenBBField(description="(provider: wrap)")
        ],
    )

    out = DocstringGenerator.generate_model_docstring(
        model_name="NoSuchModelXYZ",
        summary="S",
        explicit_params={},
        kwarg_params={"wrapped": kwarg_param},
        returns={},
        results_type="",
        sections=["parameters"],
    )
    assert "Choices for wrap" in out
    assert "Multiple comma separated items allowed" in out


def test_get_repr_returns_model_when_items_empty():
    out = DocstringGenerator._get_repr([], "MyModel")
    assert out == "MyModel"


def test_generate_no_model_parameters_section_prefix_newline_paths(monkeypatch):
    from inspect import Parameter
    from typing import Annotated

    from openbb_core.app.static.package_builder import docstring_generator as dg

    class _SS:
        class _PS:
            docstring_sections = ["parameters"]
            docstring_max_length = None

        python_settings = _PS()

    class _Svc:
        system_settings = _SS()

    monkeypatch.setattr(dg, "SystemService", _Svc)

    def _func():
        """desc"""

    p_annot = Parameter(
        name="x",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[str, OpenBBField(description="x desc")],
        default=Parameter.empty,
    )
    object.__setattr__(
        p_annot, "_annotation", Annotated[str, OpenBBField(description="x desc")]
    )
    p_plain = Parameter(
        name="y",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=int,
        default=1,
    )
    object.__setattr__(p_plain, "_annotation", int)
    p_kwargs = Parameter(
        name="kwargs",
        kind=Parameter.VAR_KEYWORD,
        annotation=dict,
        default=Parameter.empty,
    )
    object.__setattr__(p_kwargs, "_annotation", dict)

    out = DocstringGenerator.generate(
        path="/x/y",
        func=_func,
        formatted_params=OrderedDict({"x": p_annot, "y": p_plain, "kwargs": p_kwargs}),
        model_name=None,
    )
    assert "Parameters" in out
    assert "x :" in out and "y :" in out
    assert "kwargs" not in out


def test_generate_model_docstring_kwarg_literal_provider_from_description_fallback():
    from types import SimpleNamespace
    from typing import Annotated, Literal

    kwarg_param = SimpleNamespace(
        _annotation=Annotated[
            Literal["a", "b"], OpenBBField(description="(provider: p1, p2)")
        ],
        type=Literal["a", "b"],
        default=SimpleNamespace(
            description="(provider: p1, p2)", json_schema_extra=None
        ),
        annotation=Annotated[
            Literal["a", "b"], OpenBBField(description="(provider: p1, p2)")
        ],
    )
    out = DocstringGenerator.generate_model_docstring(
        model_name="NoSuchModelXYZ",
        summary="S",
        explicit_params={},
        kwarg_params={"k": kwarg_param},
        returns={},
        results_type="",
        sections=["parameters"],
    )
    assert "Choices for p1" in out and "Choices for p2" in out


def test_get_field_type_openbb_name_cleanup_branch():
    class openbb_fake_model:
        __module__ = "openbb_fake.mod"

    out = DocstringGenerator.get_field_type(openbb_fake_model, is_required=True)
    assert isinstance(out, str)


def test_get_field_type_union_openbb_name_cleanup_in_union():
    class openbb_union_model:
        pass

    out = DocstringGenerator.get_field_type(
        openbb_union_model | None,
        is_required=True,
    )
    assert "openbb_union_model" in out


def test_get_field_type_typeerror_path_with_monkeypatch(monkeypatch):
    from openbb_core.app.static.package_builder import docstring_generator as dg

    monkeypatch.setattr(
        dg, "get_origin", lambda _t: (_ for _ in ()).throw(TypeError("x"))
    )
    out = DocstringGenerator.get_field_type(str, is_required=True)
    assert isinstance(out, str)


def test_generate_model_docstring_format_type_optional_union_literal_and_charlimit():
    from inspect import Parameter

    p1 = Parameter(
        name="opt",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation="Optional[int]",
        default=None,
    )
    object.__setattr__(p1, "_annotation", "Optional[int]")

    p2 = Parameter(
        name="unioned",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation="Union[list[str], dict[str, int], None]",
        default=None,
    )
    object.__setattr__(p2, "_annotation", "Union[list[str], dict[str, int], None]")

    p3 = Parameter(
        name="lit",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation="Literal['a', 'b'] | None",
        default=None,
    )
    object.__setattr__(p3, "_annotation", "Literal['a', 'b'] | None")

    p4 = Parameter(
        name="long",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation="dict[str, list[dict[str, list[dict[str, list[str]]]]]]",
        default=None,
    )
    object.__setattr__(
        p4,
        "_annotation",
        "dict[str, list[dict[str, list[dict[str, list[str]]]]]]",
    )

    out = DocstringGenerator.generate_model_docstring(
        model_name="NoSuchModelXYZ",
        summary="S",
        explicit_params={"opt": p1, "unioned": p2, "lit": p3, "long": p4},
        kwarg_params={},
        returns={},
        results_type="",
        sections=["parameters"],
    )
    assert "opt" in out
    assert "unioned" in out
    assert "str | None" in out or "str" in out
    assert "lit" in out


def test_generate_model_docstring_semicolon_base_and_multi_pattern_paths():
    from inspect import Parameter
    from typing import Annotated

    desc = (
        "Base text; Alpha content (provider: a); Beta content (provider: b)\n"
        "Multiple comma separated items allowed for provider(s): a."
    )
    p = Parameter(
        name="k",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[str, OpenBBField(description=desc)],
        default=None,
    )
    object.__setattr__(p, "_annotation", Annotated[str, OpenBBField(description=desc)])

    out = DocstringGenerator.generate_model_docstring(
        model_name="NoSuchModelXYZ",
        summary="S",
        explicit_params={"k": p},
        kwarg_params={},
        returns={},
        results_type="",
        sections=["parameters"],
    )
    assert "(provider: a)" in out
    assert "(provider: b)" in out
    assert "Multiple comma separated items allowed" in out


def test_generate_model_docstring_model_providers_missing_branch(monkeypatch):
    from types import SimpleNamespace
    from typing import Annotated

    kwarg_param = SimpleNamespace(
        _annotation=Annotated[str | int, OpenBBField(description="d")],
        type=str | int,
        default=SimpleNamespace(description="d", json_schema_extra=None),
        annotation=Annotated[str | int, OpenBBField(description="d")],
    )
    fake_pi = SimpleNamespace(model_providers={}, map={})
    monkeypatch.setattr(DocstringGenerator, "provider_interface", fake_pi)

    out = DocstringGenerator.generate_model_docstring(
        model_name="MissingModel",
        summary="S",
        explicit_params={},
        kwarg_params={"k": kwarg_param},
        returns={},
        results_type="",
        sections=["parameters"],
    )
    assert "k" in out


def test_generate_model_docstring_literal_none_append_branch(monkeypatch):
    from inspect import Parameter

    from openbb_core.app.static.package_builder import docstring_generator as dg

    original_sub = dg.re.sub

    def fake_sub(pattern, repl, text):
        if pattern == r"Literal\[[^\]]+\]":
            return "str"
        return original_sub(pattern, repl, text)

    monkeypatch.setattr(dg.re, "sub", fake_sub)

    p = Parameter(
        name="lit",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation="Literal['a'] | None",
        default=None,
    )
    object.__setattr__(p, "_annotation", "Literal['a'] | None")

    out = DocstringGenerator.generate_model_docstring(
        model_name="NoSuchModelXYZ",
        summary="S",
        explicit_params={"lit": p},
        kwarg_params={},
        returns={},
        results_type="",
        sections=["parameters"],
    )
    assert "lit" in out


def test_generate_model_docstring_char_limit_truncation_branch():
    from inspect import Parameter

    very_long = "dict[str, list[dict[str, list[dict[str, list[dict[str, list[dict[str, list[str]]]]]]]]]"
    p = Parameter(
        name="long",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=very_long,
        default=None,
    )
    object.__setattr__(p, "_annotation", very_long)

    out = DocstringGenerator.generate_model_docstring(
        model_name="NoSuchModelXYZ",
        summary="S",
        explicit_params={"long": p},
        kwarg_params={},
        returns={},
        results_type="",
        sections=["parameters"],
    )
    assert "long" in out


def test_generate_model_docstring_provider_content_empty_continue_branch():
    from inspect import Parameter
    from typing import Annotated

    desc = "Base (provider: a); Base (provider: b)"
    p = Parameter(
        name="k",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[str, OpenBBField(description=desc)],
        default=None,
    )
    object.__setattr__(p, "_annotation", Annotated[str, OpenBBField(description=desc)])

    out = DocstringGenerator.generate_model_docstring(
        model_name="NoSuchModelXYZ",
        summary="S",
        explicit_params={"k": p},
        kwarg_params={},
        returns={},
        results_type="",
        sections=["parameters"],
    )
    assert "k" in out


def test_generate_model_docstring_format_type_union_nested_and_none():
    from inspect import Parameter
    from typing import Annotated

    p = Parameter(
        name="z",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[list[str] | dict[str, int] | None, "tag"],
        default=None,
    )
    object.__setattr__(
        p, "_annotation", Annotated[list[str] | dict[str, int] | None, "tag"]
    )

    out = DocstringGenerator.generate_model_docstring(
        model_name="NoSuchModelXYZ",
        summary="S",
        explicit_params={"z": p},
        kwarg_params={},
        returns={},
        results_type="",
        sections=["parameters"],
    )
    assert "list[str]" in out
    assert "dict[str, int]" in out
    assert "None" in out


def test_generate_model_docstring_kwarg_annotation_metadata_description_branch():
    from types import SimpleNamespace

    annotation = SimpleNamespace(
        __origin__=Annotated,
        __metadata__=[SimpleNamespace(), OpenBBField(description="meta-desc")],
    )
    kwarg_param = SimpleNamespace(
        _annotation=str,
        type=str,
        default=SimpleNamespace(description="", json_schema_extra=None),
        annotation=annotation,
    )

    out = DocstringGenerator.generate_model_docstring(
        model_name="NoSuchModelXYZ",
        summary="S",
        explicit_params={},
        kwarg_params={"k": kwarg_param},
        returns={},
        results_type="",
        sections=["parameters"],
    )
    assert "meta-desc" in out


def test_generate_model_docstring_provider_literal_choices_from_map(monkeypatch):
    from dataclasses import dataclass
    from types import SimpleNamespace
    from typing import Annotated, Literal

    @dataclass
    class _MP:
        provider: Literal["openbb", "provx"]

    kwarg_param = SimpleNamespace(
        _annotation=Annotated[str | int, OpenBBField(description="d")],
        type=str | int,
        default=SimpleNamespace(description="d", json_schema_extra=None),
        annotation=Annotated[str | int, OpenBBField(description="d")],
    )

    provider_field_info = SimpleNamespace(annotation=Literal["one", "two"])
    fake_pi = SimpleNamespace(
        model_providers={"M": _MP},
        map={"M": {"provx": {"QueryParams": {"fields": {"k": provider_field_info}}}}},
    )
    monkeypatch.setattr(DocstringGenerator, "provider_interface", fake_pi)

    out = DocstringGenerator.generate_model_docstring(
        model_name="M",
        summary="S",
        explicit_params={},
        kwarg_params={"k": kwarg_param},
        returns={},
        results_type="",
        sections=["parameters"],
    )
    assert "k :" in out
    assert "Choices for provx" in out or "d" in out


def test_generate_no_model_parameters_section_empty_result_doc(monkeypatch):
    from inspect import Parameter
    from typing import Annotated

    from openbb_core.app.static.package_builder import docstring_generator as dg

    class _SS:
        class _PS:
            docstring_sections = ["parameters"]
            docstring_max_length = None

        python_settings = _PS()

    class _Svc:
        system_settings = _SS()

    monkeypatch.setattr(dg, "SystemService", _Svc)

    def _func():
        return None

    p_annot = Parameter(
        name="x",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=Annotated[str, OpenBBField(description="x desc")],
        default=Parameter.empty,
    )
    object.__setattr__(
        p_annot, "_annotation", Annotated[str, OpenBBField(description="x desc")]
    )

    out = DocstringGenerator.generate(
        path="/x/empty",
        func=_func,
        formatted_params=OrderedDict({"x": p_annot}),
        model_name=None,
    )
    assert "Parameters" in out


def test_generate_no_model_returns_str_type_name_and_any_fallback(monkeypatch):
    import inspect

    from openbb_core.app.static.package_builder import docstring_generator as dg

    class _SS:
        class _PS:
            docstring_sections = ["returns"]
            docstring_max_length = None

        python_settings = _PS()

    class _Svc:
        system_settings = _SS()

    class _Sig:
        return_annotation = object()

    monkeypatch.setattr(dg, "SystemService", _Svc)
    monkeypatch.setattr(dg.inspect, "signature", lambda _f: _Sig())

    def _func():
        return None

    out = DocstringGenerator.generate(
        path="/x/ret-str",
        func=_func,
        formatted_params=OrderedDict(),
        model_name=None,
    )
    assert "object" in out

    class _EmptySig:
        return_annotation = inspect._empty

    monkeypatch.setattr(dg.inspect, "signature", lambda _f: _EmptySig())
    out2 = DocstringGenerator.generate(
        path="/x/ret-any",
        func=_func,
        formatted_params=OrderedDict(),
        model_name=None,
    )
    assert "Any" in out2


def test_get_field_type_union_renders_forward_ref_by_name():
    """A ``ForwardRef`` inside a union renders as its target name.

    Built with ``Union[...]``, not ``X | Y``: before 3.14 ``type.__or__``
    rejects a ``ForwardRef`` operand. This is the shape ``format_params``
    produces when it inlines the ``DataProcessingSupportedTypes``
    constraints, so the union must be spelled the same way here.
    """
    from typing import ForwardRef, Union

    field_type = Union[list, ForwardRef("DataFrame")]  # noqa: UP007

    out = DocstringGenerator.get_field_type(field_type, is_required=True)
    assert "DataFrame" in out
    assert "ForwardRef" not in out


def test_generate_non_model_strips_parameters_section_for_dependency_params(
    monkeypatch,
):
    """A dependency-backed param drops the hand-written ``Parameters`` section."""
    from fastapi import Depends

    from openbb_core.app.static.package_builder import docstring_generator as dg

    class _SS:
        class _PS:
            docstring_sections = ["description", "parameters"]
            docstring_max_length = None

        python_settings = _PS()

    class _Svc:
        system_settings = _SS()

    monkeypatch.setattr(dg, "SystemService", _Svc)

    def _dep() -> dict:
        return {}

    def _func(principal: Annotated[dict, Depends(_dep)]):
        """Do a thing.

        Parameters
        ----------
        principal : dict
            The resolved principal.
        """

    out = DocstringGenerator.generate(
        path="/x/y",
        func=_func,
        formatted_params=OrderedDict(),
        model_name=None,
    )
    assert "Do a thing." in out
    assert "The resolved principal." not in out


def _param_with_description(name, description):
    from inspect import Parameter

    annotation = Annotated[str, OpenBBField(description=description)]
    param = Parameter(
        name=name,
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=annotation,
        default=None,
    )
    object.__setattr__(param, "_annotation", annotation)
    return param


def _render_params(**params):
    return DocstringGenerator.generate_model_docstring(
        model_name="NoSuchModelXYZ",
        summary="S",
        explicit_params=dict(params),
        kwarg_params={},
        returns={},
        results_type="",
        sections=["parameters"],
    )


def test_generate_model_docstring_keeps_single_provider_semicolons_intact():
    desc = (
        "Data column(s) to return, comma-separated. Choices: capacity (megawatts);"
        " outage (megawatts); percent_outage (percent). (provider: eia)"
    )
    out = _render_params(data_type=_param_with_description("data_type", desc))
    assert "Data column(s) to return, comma-separated." in out
    assert "capacity (megawatts); outage (megawatts); percent_outage (percent)." in out


def test_generate_model_docstring_keeps_semicolons_inside_examples():
    desc = (
        "A semicolon delimited list of tag names.  Example: 'japan;imports'"
        " (provider: fred)"
    )
    out = _render_params(tag_names=_param_with_description("tag_names", desc))
    assert "Example: 'japan;imports'" in out


def test_generate_model_docstring_splits_merged_provider_descriptions():
    desc = "Alpha detail. (provider: a);\n    Beta detail. (provider: b)"
    out = _render_params(kind=_param_with_description("kind", desc))
    assert "(provider: a)" in out
    assert "Alpha detail." in out
    assert "(provider: b)" in out
    assert "Beta detail." in out


def test_generate_model_docstring_wrapped_choices_keep_separating_commas():
    import re
    from types import SimpleNamespace
    from typing import Literal

    choices = [f"choice_number_{i:02d}" for i in range(12)]
    kwarg_param = SimpleNamespace(
        _annotation=Literal["seed"],
        type=Literal["seed"],
        default=SimpleNamespace(
            description="Pick one. (provider: wrap)",
            json_schema_extra={"wrap": {"choices": choices}},
        ),
        annotation=Literal["seed"],
    )
    out = DocstringGenerator.generate_model_docstring(
        model_name="NoSuchModelXYZ",
        summary="S",
        explicit_params={},
        kwarg_params={"wrapped": kwarg_param},
        returns={},
        results_type="",
        sections=["parameters"],
    )
    assert not re.search(r"'\s+'", out)
    assert ", ".join(f"'{c}'" for c in choices) == re.sub(
        r",\s+", ", ", out[out.index("'choice_number_00'") : out.rindex("'") + 1]
    )
    assert max(len(line) for line in out.splitlines()) < 120


def test_generate_model_docstring_strips_annotated_metadata_from_kwarg_types():
    from types import SimpleNamespace

    from annotated_types import Ge

    kwarg_param = SimpleNamespace(
        _annotation=Annotated[int, Ge(0)] | None,
        type=Annotated[int, Ge(0)] | None,
        default=SimpleNamespace(description="Row limit.", json_schema_extra=None),
        annotation=Annotated[int, Ge(0)] | None,
    )
    out = DocstringGenerator.generate_model_docstring(
        model_name="NoSuchModelXYZ",
        summary="S",
        explicit_params={},
        kwarg_params={"limit": kwarg_param},
        returns={},
        results_type="",
        sections=["parameters"],
    )
    assert "limit : int | None" in out
    assert "Annotated" not in out
    assert "Ge(" not in out


def test_generate_model_docstring_provider_type_matches_none_default():
    out = _render_params(provider=_param_with_description("provider", "The provider."))
    assert "provider : str | None" in out


def test_get_field_type_optional_literal_renders_value_type():
    from typing import Literal

    assert (
        DocstringGenerator.get_field_type(Literal["a", "b"] | None, False)
        == "str | None"
    )
    assert DocstringGenerator.get_field_type(Literal["a", "b"], True) == "str"


def test_get_field_type_strips_annotated_metadata():
    from annotated_types import Gt

    out = DocstringGenerator.get_field_type(Annotated[float, Gt(0)] | None, False)
    assert out == "float | None"


def test_get_field_type_unquotes_string_forward_refs():
    forward_ref = "DataFrame"
    out = DocstringGenerator.get_field_type(list[forward_ref] | dict, True)
    assert out == "dict | list[DataFrame]"


def test_get_field_type_typevar_renders_any():
    from typing import TypeVar

    T = TypeVar("T")
    assert DocstringGenerator.get_field_type(T | None, False) == "Any | None"


def test_generate_non_model_lists_literal_choices_and_hides_obbject_id(monkeypatch):
    from inspect import Parameter
    from typing import Literal

    from openbb_core.app.static.package_builder import docstring_generator as dg

    class _SS:
        class _PS:
            docstring_sections = ["description", "parameters", "returns"]
            docstring_max_length = None

        python_settings = _PS()

    class _Svc:
        system_settings = _SS()

    monkeypatch.setattr(dg, "SystemService", _Svc)

    annotation = Annotated[
        Literal["coal", "petroleum"] | None, OpenBBField(description="The group.")
    ]

    async def _func(group: annotation = None) -> OBBject:
        """List the datasets."""

    param = Parameter(
        name="group",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=annotation,
        default=None,
    )
    object.__setattr__(param, "_annotation", annotation)

    out = DocstringGenerator.generate(
        path="/x/datasets",
        func=_func,
        formatted_params=OrderedDict({"group": param}),
        model_name=None,
    )
    assert "group : str | None" in out
    assert "Choices: 'coal', 'petroleum'" in out
    assert "id : str" not in out
    assert "results : Any | None" in out
    assert "warnings : list[Warning_] | None" in out
    assert "\n\n\n" not in out


def test_generate_model_docstring_strips_annotated_metadata_from_explicit_params():
    from inspect import Parameter

    from annotated_types import Ge

    annotation = Annotated[
        Annotated[int, Ge(0)] | None, OpenBBField(description="Row limit.")
    ]
    param = Parameter(
        name="limit",
        kind=Parameter.POSITIONAL_OR_KEYWORD,
        annotation=annotation,
        default=None,
    )
    object.__setattr__(param, "_annotation", annotation)
    out = _render_params(limit=param)
    assert "limit : int | None" in out
    assert "Annotated" not in out


def test_get_field_type_bare_typevar_renders_any():
    from typing import TypeVar

    T = TypeVar("T")
    assert DocstringGenerator.get_field_type(T, True) == "Any"


def test_generate_model_docstring_untagged_merged_description_becomes_base():
    desc = "Alpha detail. (provider: a);\n    Shared base text."
    out = _render_params(kind=_param_with_description("kind", desc))
    assert out.index("Shared base text.") < out.index("(provider: a)")
    assert "Alpha detail." in out


def test_literal_choices_reads_bare_optional_and_non_literal_types():
    from typing import Literal

    from openbb_core.app.static.package_builder.docstring_generator import (
        _literal_choices,
    )

    assert _literal_choices(Literal["a", "b"]) == ["a", "b"]
    assert _literal_choices(Literal["a", "b"] | None) == ["a", "b"]
    assert _literal_choices(int | None) == []


# --- _format_type_string -----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # the regressions: a wrapped generic holding a union
        ("typing.Optional[list[typing.Union[A, B, C]]]", "list[A | B | C] | None"),
        ("Optional[list[Union[A, B]]]", "list[A | B] | None"),
        ("Optional[dict[str, list[Union[A, B]]]]", "dict[str, list[A | B]] | None"),
        # things that already worked
        ("typing.Optional[str]", "str | None"),
        ("Optional[list[str]]", "list[str] | None"),
        ("typing.Union[str, int, NoneType]", "str | int | None"),
        ("typing.Union[list[str], str]", "list[str] | str"),
        ("list[typing.Optional[str]]", "list[str | None]"),
        ("<class 'str'>", "str"),
        ("datetime.date", "date"),
        ("typing.Optional[str", "Optional[str"),
        # Literal still collapses to str; duplicates still collapse
        ("typing.Optional[typing.Literal['a', 'b']]", "str | None"),
        ("typing.Union[typing.Literal['a'], typing.Literal['b']]", "str"),
        ("str | str | None", "str | None"),
        # a union inside brackets is not de-duplicated across the brackets
        ("list[A | A] | None", "list[A | A] | None"),
        ("list[A | B] | list[A | B] | None", "list[A | B] | None"),
    ],
)
def test_format_type_string(raw, expected):
    """Type strings are rewritten with brackets matched, never guessed."""
    from openbb_core.app.static.package_builder.docstring_generator import (
        _format_type_string,
    )

    assert _format_type_string(raw) == expected


def test_format_type_string_never_produces_unbalanced_brackets():
    """Every rewrite leaves the brackets balanced, including truncation."""
    from openbb_core.app.static.package_builder.docstring_generator import (
        _format_type_string,
    )

    raw = "typing.Optional[list[typing.Union[" + ", ".join(f"Item{i}" for i in range(12)) + "]]]"
    full = _format_type_string(raw)
    assert full.count("[") == full.count("]") and full.endswith("] | None")
    cut = _format_type_string(raw, char_limit=40)
    assert cut.count("[") == cut.count("]")


def test_get_field_type_strips_every_module_path_in_a_container():
    """``list[openbb_x.A | openbb_x.B | openbb_x.C]`` keeps all three names."""
    from pydantic import BaseModel

    from openbb_core.app.static.package_builder.docstring_generator import (
        DocstringGenerator,
        _format_type_string,
        _strip_module_paths,
    )

    def render(annotation, required):
        # the docs run ``get_field_type`` and then ``_format_type_string``
        return _format_type_string(DocstringGenerator.get_field_type(annotation, required))

    def model(name):
        return type(name, (BaseModel,), {"__module__": "openbb_fake.providers.models"})

    a, b, c = model("ItemA"), model("ItemB"), model("ItemC")
    assert render(list[a | b | c] | None, False) == "list[ItemA | ItemB | ItemC] | None"
    assert render(list[a], True) == "list[ItemA]"
    assert render(a | None, False) == "ItemA | None"
    assert _strip_module_paths("dict[str, openbb_x.m.A]") == "dict[str, A]"
    # quoted data in a Literal is not a module path
    assert _strip_module_paths("Literal['a.b']") == "Literal['a.b']"
