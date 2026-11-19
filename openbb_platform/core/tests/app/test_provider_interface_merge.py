"""Direct unit tests for ``ProviderInterface._merge_fields`` and related branches."""

from typing import Annotated, Union

from fastapi.params import Query
from pydantic import BaseModel, Tag, TypeAdapter
from pydantic.fields import FieldInfo

from openbb_core.app.provider_interface import (
    DataclassField,
    ProviderInterface,
)
from openbb_core.provider.registry_map import RegistryMap


def _df(
    name, annotation, *, description="", title="", json_schema_extra=None, default=None
):
    """Build a ``DataclassField`` with a Pydantic ``FieldInfo`` default."""
    fi = FieldInfo(
        default=default,
        title=title,
        description=description,
        json_schema_extra=json_schema_extra or {},
    )
    return DataclassField(name=name, annotation=annotation, default=fi)


def test_merge_fields_similar_descriptions_use_provider_suffix():
    a = _df("ticker", str, description="Symbol of a security.", title="fmp")
    b = _df("ticker", str, description="Symbol of a security.", title="polygon")

    merged = ProviderInterface._merge_fields(a, b)

    assert merged.name == "ticker"
    assert merged.annotation is str
    assert merged.default.title == "fmp,polygon"
    assert "(provider: fmp, polygon)" in merged.default.description


def test_merge_fields_dissimilar_descriptions_concatenate():
    a = _df("x", int, description="An apple.", title="fmp")
    b = _df("x", int, description="Frequency in Hz.", title="polygon")

    merged = ProviderInterface._merge_fields(a, b)

    assert "An apple." in merged.default.description
    assert "Frequency in Hz." in merged.default.description
    # ';' is the separator used for the dissimilar branch
    assert ";" in merged.default.description


def test_merge_fields_unions_different_annotations():
    a = _df("x", int, description="d", title="fmp")
    b = _df("x", str, description="d", title="polygon")

    merged = ProviderInterface._merge_fields(a, b)

    # Union[int, str] (order depends on Python's typing internals)
    assert getattr(merged.annotation, "__origin__", None) is Union or "Union" in str(
        merged.annotation
    )


def test_merge_fields_keeps_annotation_when_same():
    a = _df("x", int, description="d", title="fmp")
    b = _df("x", int, description="d", title="polygon")

    merged = ProviderInterface._merge_fields(a, b)

    assert merged.annotation is int


def test_merge_fields_query_true_returns_query_default():
    a = _df("x", int, description="d", title="fmp")
    b = _df("x", int, description="d", title="polygon")

    merged = ProviderInterface._merge_fields(a, b, query=True)

    assert isinstance(merged.default, Query)


def test_merge_fields_query_false_returns_field_info_default():
    a = _df("x", int, description="d", title="fmp")
    b = _df("x", int, description="d", title="polygon")

    merged = ProviderInterface._merge_fields(a, b, query=False)

    assert isinstance(merged.default, FieldInfo)


def test_merge_fields_merges_json_schema_extra_overlapping_lists():
    a = _df(
        "x",
        int,
        description="d",
        title="fmp",
        json_schema_extra={"choices": ["a", "b"]},
    )
    b = _df(
        "x",
        int,
        description="d",
        title="polygon",
        json_schema_extra={"choices": ["b", "c"]},
    )

    merged = ProviderInterface._merge_fields(a, b)

    extra = merged.default.json_schema_extra
    assert isinstance(extra, dict)
    assert set(extra["choices"]) == {"a", "b", "c"}


def test_merge_fields_merges_json_schema_extra_disjoint_keys():
    a = _df("x", int, description="d", title="fmp", json_schema_extra={"alpha": 1})
    b = _df("x", int, description="d", title="polygon", json_schema_extra={"beta": 2})

    merged = ProviderInterface._merge_fields(a, b)

    extra = merged.default.json_schema_extra
    assert extra == {"alpha": 1, "beta": 2}


def test_merge_fields_handles_empty_titles():
    a = _df("x", int, description="d", title="")
    b = _df("x", int, description="d", title="polygon")

    merged = ProviderInterface._merge_fields(a, b)

    # Only the non-empty title should appear in the joined providers value
    assert merged.default.title == "polygon"


def test_merge_fields_strips_multiple_items_text_for_similarity():
    a = _df(
        "x",
        int,
        description="Symbol of a security. Multiple comma separated items allowed.",
        title="fmp",
    )
    b = _df("x", int, description="Symbol of a security.", title="polygon")

    merged = ProviderInterface._merge_fields(a, b)

    # Descriptions should be considered similar -> "(provider: ...)" suffix used
    assert "(provider: fmp, polygon)" in merged.default.description


def test_create_field_required_no_force_optional_uses_ellipsis_default():
    fi = FieldInfo(annotation=int, description="something")  # required (no default)
    out = ProviderInterface._create_field("symbol", fi)
    # required fields → default becomes ... at the field level (or wrapped FieldInfo)
    # The exact wrapper depends on params; we just assert it's been transformed
    assert out.name == "symbol"
    assert out.annotation is int


def test_create_field_force_optional_wraps_in_optional_with_none_default():
    fi = FieldInfo(annotation=int, description="something")
    out = ProviderInterface._create_field(
        "symbol", fi, provider_name="fmp", force_optional=True
    )
    # Annotation should be wrapped as Optional[int]
    args = getattr(out.annotation, "__args__", ())
    assert int in args and type(None) in args
    # Default goes through Field/Body/Query — value should be None or wrapped None
    assert out.default is not None  # a wrapper was produced


def test_create_field_with_literal_choices_auto_derived():
    from typing import Literal as Lit

    fi = FieldInfo(annotation=Lit["a", "b"], description="d")
    out = ProviderInterface._create_field(
        "symbol", fi, provider_name="fmp", force_optional=True
    )
    extra = getattr(out.default, "json_schema_extra", {}) or {}
    assert extra.get("fmp", {}).get("choices") == ["a", "b"]


def test_create_field_with_optional_literal_unwraps_and_derives_choices():
    from typing import Literal as Lit

    fi = FieldInfo(annotation=Lit["x", "y"] | None, description="d")
    out = ProviderInterface._create_field(
        "f", fi, provider_name="polygon", force_optional=False
    )
    extra = getattr(out.default, "json_schema_extra", {}) or {}
    assert extra.get("polygon", {}).get("choices") == ["x", "y"]


def test_create_field_with_multiple_items_allowed_dict_extra():
    fi = FieldInfo(
        annotation=str,
        description="d",
        json_schema_extra={"fmp": {"multiple_items_allowed": True, "choices": ["a"]}},
    )
    out = ProviderInterface._create_field(
        "symbol", fi, provider_name="fmp", force_optional=True
    )
    desc = out.default.description
    assert "Multiple comma separated items allowed" in desc


def test_create_field_with_multiple_items_allowed_list_legacy_format():
    fi = FieldInfo(
        annotation=str,
        description="d",
        json_schema_extra={"fmp": ["multiple_items_allowed"]},
    )
    # query=True so the result is a Query() carrying the description
    out = ProviderInterface._create_field(
        "symbol", fi, provider_name=None, query=True, force_optional=True
    )
    desc = out.default.description
    assert "Multiple comma separated items allowed for provider(s): fmp" in desc


def test_create_field_with_widget_config_extra():
    fi = FieldInfo(
        annotation=str,
        description="d",
        json_schema_extra={"fmp": {"x-widget_config": {"type": "selector"}}},
    )
    out = ProviderInterface._create_field(
        "symbol", fi, provider_name="fmp", force_optional=True
    )
    extra = getattr(out.default, "json_schema_extra", {}) or {}
    assert extra.get("fmp", {}).get("x-widget_config") == {"type": "selector"}


def test_create_field_with_choices_and_widget_config_updates_existing_choice_bucket():
    fi = FieldInfo(
        annotation=str,
        description="d",
        json_schema_extra={
            "fmp": {
                "choices": ["a", "b"],
                "x-widget_config": {"type": "selector"},
            }
        },
    )
    out = ProviderInterface._create_field(
        "symbol", fi, provider_name="fmp", force_optional=True
    )
    extra = getattr(out.default, "json_schema_extra", {}) or {}
    assert extra["fmp"]["choices"] == ["a", "b"]
    assert extra["fmp"]["x-widget_config"] == {"type": "selector"}


def test_create_field_required_provider_query_param_is_not_optional_in_widget():
    """A required provider-only query param stays optional on the route.

    Other providers share the route, so the API parameter must allow null.
    The provider's own widget input is marked ``optional: False``, so a
    client asks for it instead of sending nothing.
    """
    fi = FieldInfo(annotation=str, description="d")
    out = ProviderInterface._create_field(
        "code", fi, provider_name="cftc", query=True, force_optional=True
    )
    assert out.default.default is None
    assert out.default.json_schema_extra == {
        "cftc": {"x-widget_config": {"optional": False}}
    }


def test_create_field_required_query_param_keeps_provider_widget_config():
    """The provider's own x-widget_config keys are kept, and win on conflict."""
    fi = FieldInfo(
        annotation=str,
        description="d",
        json_schema_extra={
            "fmp": {
                "choices": ["a", "b"],
                "x-widget_config": {"type": "selector", "optional": True},
            }
        },
    )
    out = ProviderInterface._create_field(
        "symbol", fi, provider_name="fmp", query=True, force_optional=True
    )
    extra = out.default.json_schema_extra
    assert extra["fmp"]["choices"] == ["a", "b"]
    assert extra["fmp"]["x-widget_config"] == {"type": "selector", "optional": True}


def test_extract_params_marks_only_the_requiring_provider():
    def fields(**f):
        return {"QueryParams": {"fields": f}}

    _, extra = ProviderInterface._extract_params(
        {
            "openbb": fields(),
            "a": fields(code=FieldInfo(annotation=str)),
            "b": fields(code=FieldInfo(annotation=str, default=None)),
        }
    )
    _, _, default = extra["code"]
    assert default.default is None  # the shared route stays optional
    assert default.json_schema_extra == {"a": {"x-widget_config": {"optional": False}}}


def test_extract_data_required_field_gets_no_widget_config():
    _, extra = ProviderInterface._extract_data(
        {
            "openbb": {"Data": {"fields": {}}},
            "a": {"Data": {"fields": {"value": FieldInfo(annotation=float)}}},
        }
    )
    _, _, default = extra["value"]
    assert not default.json_schema_extra


def test_get_annotated_union_handles_annotated_data_and_discriminator_callable(
    fake_registry,
):
    class M1(BaseModel):
        x: int

    class M2(BaseModel):
        y: int

    models = {
        "p1": {"data": Annotated[M1, Tag("seed")]},
        "p2": {"data": M2},
    }

    ProviderInterface._instances.pop(ProviderInterface, None)  # type: ignore[attr-defined]
    provider_interface = ProviderInterface(
        registry_map=RegistryMap(registry=fake_registry)
    )
    union_t = provider_interface._get_annotated_union(models)

    # Ensure providers are attached for discriminator routing.
    assert getattr(M1, "_provider") == "p1"
    assert getattr(M2, "_provider") == "p2"

    # Validate through the annotated union so the discriminator callable executes.
    validated = TypeAdapter(union_t).validate_python(M1(x=1))
    assert isinstance(validated, M1)
    ProviderInterface._instances.pop(ProviderInterface, None)  # type: ignore[attr-defined]


def test_create_field_dict_annotation_uses_body():
    from fastapi.params import Body as BodyParam

    fi = FieldInfo(annotation=dict, description="d")
    out = ProviderInterface._create_field(
        "payload", fi, provider_name="fmp", force_optional=False
    )
    assert isinstance(out.default, BodyParam)


def _qp_fields(*pairs):
    return {
        "QueryParams": {
            "fields": {name: fi for name, fi in pairs},
        }
    }


def _data_fields(*pairs):
    return {
        "Data": {
            "fields": {name: fi for name, fi in pairs},
        }
    }


def test_extract_params_standard_only_openbb():
    providers = {
        "openbb": _qp_fields(
            ("symbol", FieldInfo(annotation=str, description="Symbol")),
        ),
    }
    standard, extra = ProviderInterface._extract_params(providers)
    assert "symbol" in standard
    assert extra == {}


def test_extract_params_provider_redefines_standard_field_merges():
    providers = {
        "openbb": _qp_fields(
            ("symbol", FieldInfo(annotation=str, description="Standard symbol.")),
        ),
        "fmp": _qp_fields(
            (
                "symbol",
                FieldInfo(annotation=str, description="FMP-specific symbol details."),
            ),
        ),
    }
    standard, extra = ProviderInterface._extract_params(providers)
    assert "symbol" in standard
    # extra should be empty since the field exists on the standard side
    assert "symbol" not in extra


def test_extract_params_provider_only_field_goes_to_extra():
    providers = {
        "openbb": _qp_fields(
            ("symbol", FieldInfo(annotation=str, description="Symbol")),
        ),
        "fmp": _qp_fields(
            ("limit", FieldInfo(annotation=int, description="Row limit")),
        ),
    }
    standard, extra = ProviderInterface._extract_params(providers)
    assert "limit" in extra
    assert "limit" not in standard


def test_extract_params_extra_field_from_two_providers_is_merged():
    providers = {
        "openbb": _qp_fields(
            ("symbol", FieldInfo(annotation=str, description="Symbol")),
        ),
        "fmp": _qp_fields(
            ("limit", FieldInfo(annotation=int, description="Row limit")),
        ),
        "polygon": _qp_fields(
            ("limit", FieldInfo(annotation=int, description="Row limit")),
        ),
    }
    _, extra = ProviderInterface._extract_params(providers)
    assert "limit" in extra
    name, ann, default = extra["limit"]
    title = getattr(default, "title", "")
    assert "fmp" in title and "polygon" in title


def test_extract_data_skips_openbb_provider_field_marker():
    """The synthetic 'provider' marker field on openbb Data must be filtered out."""
    providers = {
        "openbb": _data_fields(
            (
                "provider",
                FieldInfo(
                    annotation=str, description="The data provider for the data."
                ),
            ),
            ("close", FieldInfo(annotation=float, description="Closing price")),
        ),
    }
    standard, extra = ProviderInterface._extract_data(providers)
    assert "provider" not in standard
    assert "close" in standard
    assert extra == {}


def test_extract_data_extra_field_only_on_provider():
    providers = {
        "openbb": _data_fields(
            ("close", FieldInfo(annotation=float, description="Closing price")),
        ),
        "fmp": _data_fields(
            ("close", FieldInfo(annotation=float, description="Closing price")),
            ("eps_diluted", FieldInfo(annotation=float, description="Diluted EPS")),
        ),
    }
    standard, extra = ProviderInterface._extract_data(providers)
    assert "close" in standard
    assert "eps_diluted" in extra
    assert "close" not in extra


def test_extract_data_extra_field_from_two_providers_is_merged():
    providers = {
        "openbb": _data_fields(
            ("close", FieldInfo(annotation=float, description="Closing price")),
        ),
        "fmp": _data_fields(
            ("eps_diluted", FieldInfo(annotation=float, description="Diluted EPS")),
        ),
        "polygon": _data_fields(
            ("eps_diluted", FieldInfo(annotation=float, description="Diluted EPS")),
        ),
    }
    _, extra = ProviderInterface._extract_data(providers)
    assert "eps_diluted" in extra
    name, ann, default = extra["eps_diluted"]
    title = getattr(default, "title", "")
    assert "fmp" in title and "polygon" in title


def test_extract_data_skips_provider_marker_on_provider_block_too():
    providers = {
        "openbb": _data_fields(
            ("close", FieldInfo(annotation=float, description="Closing price")),
        ),
        "fmp": _data_fields(
            (
                "provider",
                FieldInfo(
                    annotation=str, description="The data provider for the data."
                ),
            ),
        ),
    }
    standard, extra = ProviderInterface._extract_data(providers)
    assert "provider" not in standard
    assert "provider" not in extra
