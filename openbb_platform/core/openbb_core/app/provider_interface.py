"""Provider Interface."""

from collections.abc import Callable
from dataclasses import dataclass, make_dataclass
from difflib import SequenceMatcher
from typing import (
    Annotated,
    Any,
    Literal,
    Optional,
    Union,
    get_args,
    get_origin,
)

from fastapi import Body, Query
from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    SerializeAsAny,
    Tag,
    create_model,
)
from pydantic.fields import FieldInfo

from openbb_core.app.model.abstract.singleton import SingletonMeta
from openbb_core.app.model.obbject import OBBject
from openbb_core.provider.query_executor import QueryExecutor
from openbb_core.provider.registry_map import MapType, RegistryMap
from openbb_core.provider.utils.helpers import to_snake_case

TupleFieldType = tuple[str, type | None, Any | None]


@dataclass
class DataclassField:
    """Dataclass field."""

    name: str
    annotation: type | None
    default: Any | None


@dataclass
class StandardParams:
    """Standard params dataclass."""


@dataclass
class ExtraParams:
    """Extra params dataclass."""


class StandardData(BaseModel):
    """Standard data model."""


class ExtraData(BaseModel):
    """Extra data model."""


@dataclass
class ProviderChoices:
    """Provider choices dataclass."""

    provider: Literal  # type: ignore


class ProviderInterface(metaclass=SingletonMeta):
    """Provider interface class.

    Properties
    ----------
    map : MapType
        Dictionary of provider information.
    credentials: List[str]
        List of credentials.
    model_providers : Dict[str, ProviderChoices]
        Dictionary of provider choices by model.
    params : Dict[str, Dict[str, Union[StandardParams, ExtraParams]]]
        Dictionary of params by model.
    return_schema : Dict[str, Type[BaseModel]]
        Dictionary of return data schema by model.
    available_providers : List[str]
        List of available providers.
    provider_choices : ProviderChoices
        Dataclass with literal of provider names.
    models : List[str]
        List of model names.

    Methods
    -------
    create_executor : QueryExecutor
        Create a query executor
    """

    def __init__(
        self,
        registry_map: RegistryMap | None = None,
        query_executor: QueryExecutor | None = None,
    ) -> None:
        """Initialize provider interface."""
        self._registry_map = registry_map or RegistryMap()
        self._query_executor = query_executor or QueryExecutor

        self._map = self._registry_map.standard_extra
        # TODO: Try these 4 methods in a single iteration
        self._model_providers_map = self._generate_model_providers_dc(self._map)
        self._params = self._generate_params_dc(self._map)
        self._data = self._generate_data_dc(self._map)
        self._return_schema = self._generate_return_schema(self._data)
        self._return_annotations = self._generate_return_annotations(
            self._registry_map.original_models
        )

        self._available_providers = self._registry_map.available_providers
        self._provider_choices = self._get_provider_choices(self._available_providers)

    @property
    def map(self) -> MapType:
        """Dictionary of provider information."""
        return self._map

    @property
    def credentials(self) -> dict[str, list[str]]:
        """Map providers to credentials."""
        return self._registry_map.credentials

    @property
    def model_providers(self) -> dict[str, ProviderChoices]:
        """Dictionary of provider choices by model."""
        return self._model_providers_map

    @property
    def params(self) -> dict[str, dict[str, StandardParams | ExtraParams]]:
        """Dictionary of params by model."""
        return self._params

    @property
    def data(self) -> dict[str, dict[str, StandardData | ExtraData]]:
        """Dictionary of data by model."""
        return self._data

    @property
    def return_schema(self) -> dict[str, type[BaseModel]]:
        """Dictionary of data by model merged."""
        return self._return_schema

    @property
    def available_providers(self) -> list[str]:
        """List of available providers."""
        return self._available_providers

    @property
    def provider_choices(self) -> type:
        """Dataclass with literal of provider names."""
        return self._provider_choices

    @property
    def models(self) -> list[str]:
        """List of model names."""
        return self._registry_map.models

    @property
    def return_annotations(self) -> dict[str, type[OBBject]]:
        """Return map."""
        return self._return_annotations

    def create_executor(self) -> QueryExecutor:
        """Get query executor."""
        return self._query_executor(self._registry_map.registry)  # type: ignore[operator]  # ty: ignore[call-non-callable]

    @staticmethod
    def _merge_fields(
        current: DataclassField, incoming: DataclassField, query: bool = False
    ) -> DataclassField:
        """Merge 2 dataclass fields."""
        curr_name = current.name
        curr_type: type | None = current.annotation
        curr_desc = getattr(current.default, "description", "")
        curr_json_schema_extra = getattr(current.default, "json_schema_extra", {})

        inc_type: type | None = incoming.annotation
        inc_desc = getattr(incoming.default, "description", "")
        inc_json_schema_extra = getattr(incoming.default, "json_schema_extra", {})

        def split_desc(desc: str) -> str:
            """Split field description, removing provider tags and multiple items text."""
            item = desc.split(" (provider: ")
            detail = item[0] if item else ""
            # Also remove "Multiple comma separated items allowed." for comparison
            detail = detail.replace(" Multiple comma separated items allowed.", "")
            detail = detail.replace("Multiple comma separated items allowed.", "")
            return detail.strip()

        def merge_json_schema_extra(curr: dict, inc: dict) -> dict:
            """Merge json schema extra."""
            for key in curr.keys() & inc.keys():
                # Merge keys that are in both dictionaries if both are lists
                curr_value = curr[key]
                inc_value = inc[key]
                if isinstance(curr_value, list) and isinstance(inc_value, list):
                    curr[key] = list(set(curr.get(key, []) + inc.get(key, [])))
                    inc.pop(key)

            # Add any remaining keys from inc to curr
            curr.update(inc)
            return curr

        json_schema_extra: dict = merge_json_schema_extra(
            curr=curr_json_schema_extra or {}, inc=inc_json_schema_extra or {}
        )

        curr_detail = split_desc(curr_desc)
        inc_detail = split_desc(inc_desc)

        curr_title = getattr(current.default, "title", "") or ""
        inc_title = getattr(incoming.default, "title", "") or ""
        # Filter out empty titles and join
        provider_list = [t for t in [curr_title, inc_title] if t]
        providers = ",".join(provider_list)
        formatted_prov = ", ".join(provider_list)

        if SequenceMatcher(None, curr_detail, inc_detail).ratio() > 0.8:
            new_desc = f"{curr_detail} (provider: {formatted_prov})"
        else:
            new_desc = f"{curr_desc};\n    {inc_desc}"

        QF: Callable = Query if query else FieldInfo  # type: ignore[assignment]
        merged_default = QF(
            default=getattr(current.default, "default", None),
            title=providers,
            description=new_desc,
            json_schema_extra=json_schema_extra,
        )

        merged_type: type | None = (  # ty: ignore[invalid-assignment]
            Union[curr_type, inc_type] if curr_type != inc_type else curr_type  # type: ignore[assignment]  # noqa  # ty: ignore[invalid-type-form]
        )

        return DataclassField(curr_name, merged_type, merged_default)

    @staticmethod
    def _create_field(
        name: str,
        field: FieldInfo,
        provider_name: str | None = None,
        query: bool = False,
        force_optional: bool = False,
    ) -> DataclassField:
        new_name = name.replace(".", "_")
        annotation = field.annotation

        additional_description = ""
        choices: dict = {}
        if extra := field.json_schema_extra:
            providers: list = []
            for p, v in extra.items():  # type: ignore
                if isinstance(v, dict) and v.get("multiple_items_allowed"):
                    providers.append(p)
                    choices[p] = {
                        "multiple_items_allowed": True,
                        "choices": v.get("choices"),
                    }
                elif isinstance(v, list) and "multiple_items_allowed" in v:
                    # For backwards compatibility, before this was a list
                    providers.append(p)
                    choices[p] = {"multiple_items_allowed": True, "choices": None}
                elif isinstance(v, dict) and v.get("choices"):
                    choices[p] = {
                        "multiple_items_allowed": False,
                        "choices": v.get("choices"),
                    }

                if isinstance(v, dict) and v.get("x-widget_config"):
                    if p not in choices:
                        choices[p] = {"x-widget_config": v.get("x-widget_config")}
                    else:
                        choices[p]["x-widget_config"] = v.get("x-widget_config")

            if providers:
                if provider_name:
                    additional_description += " Multiple comma separated items allowed."
                else:
                    additional_description += (
                        " Multiple comma separated items allowed for provider(s): "
                        + ", ".join(providers)  # type: ignore[arg-type]
                        + "."
                    )

        # Auto-derive choices from Literal annotation for provider-specific fields
        # when no explicit choices are already declared for this provider.
        # This makes Literal annotations equivalent to manually declared choices,
        # so providers only need to declare the type annotation.
        if provider_name and provider_name not in choices:
            _ann = annotation
            _origin = get_origin(_ann)
            # Unwrap Optional[Literal[...]] = Union[Literal[...], None]
            if _origin is Union:
                _inner = [a for a in get_args(_ann) if a is not type(None)]
                if len(_inner) == 1:
                    _ann = _inner[0]
                    _origin = get_origin(_ann)
            if _origin is Literal:
                _literal_args = list(get_args(_ann))
                if _literal_args:
                    choices[provider_name] = {
                        "choices": _literal_args,
                    }

        provider_field = (
            f"(provider: {provider_name})" if provider_name != "openbb" else ""
        )
        description = (
            f"{field.description}{additional_description} {provider_field}"
            if provider_name and field.description
            else f"{field.description}{additional_description}"
        )

        if field.is_required():
            if force_optional:
                annotation = Optional[annotation]  # type: ignore  # noqa
                default = None
                # The route is shared by providers, so it stays optional; this
                # provider's widget still marks the input required.
                if query:
                    widget = choices.setdefault(provider_name, {})
                    widget["x-widget_config"] = {
                        "optional": False,
                        **(widget.get("x-widget_config") or {}),
                    }
            else:
                default = ...
        else:
            default = field.default

        if (
            hasattr(annotation, "__name__")
            and annotation.__name__ in ["Dict", "dict", "Data"]
            or field.kw_only is True
        ):
            return DataclassField(
                new_name,
                annotation,  # ty: ignore[invalid-argument-type]
                Body(
                    default=default,
                    title=provider_name,
                    description=description,
                    alias=field.alias or None,
                    json_schema_extra=choices,
                ),
            )

        if query:
            # We need to use query if we want the field description to show
            # up in the swagger, it's a fastapi limitation
            return DataclassField(
                new_name,
                annotation,  # ty: ignore[invalid-argument-type]
                Query(
                    default=default,
                    title=provider_name,
                    description=description,
                    alias=field.alias or None,
                    json_schema_extra=choices,
                ),
            )
        if provider_name:
            return DataclassField(
                new_name,
                annotation,  # ty: ignore[invalid-argument-type]
                Field(
                    default=default or None,
                    title=provider_name,
                    description=description,
                    json_schema_extra=choices,
                ),
            )

        return DataclassField(
            new_name,
            annotation,  # ty: ignore[invalid-argument-type]
            default,
        )

    @classmethod
    def _extract_params(
        cls,
        providers: Any,
    ) -> tuple[dict[str, TupleFieldType], dict[str, TupleFieldType]]:
        """Extract parameters from map."""
        standard: dict[str, TupleFieldType] = {}
        extra: dict[str, TupleFieldType] = {}
        standard_fields = (
            providers.get("openbb", {}).get("QueryParams", {}).get("fields", {})
        )

        for provider_name, model_details in providers.items():
            if provider_name == "openbb":
                for name, field in model_details["QueryParams"]["fields"].items():
                    incoming = cls._create_field(name, field, query=True)

                    standard[incoming.name] = (
                        incoming.name,
                        incoming.annotation,
                        incoming.default,
                    )
            else:
                for name, field in model_details["QueryParams"]["fields"].items():
                    s_name = to_snake_case(name)

                    if name in standard_fields:
                        # Provider redefines a standard field - merge descriptions
                        # Check if descriptions differ before merging
                        standard_desc = standard_fields[name].description or ""
                        provider_desc = field.description or ""

                        if provider_desc and provider_desc != standard_desc:
                            # Create a field with provider-specific description
                            incoming = cls._create_field(
                                s_name,
                                field,
                                provider_name,
                                query=True,
                                force_optional=False,
                            )
                            # Merge into the standard field
                            if s_name in standard:
                                current = DataclassField(*standard[s_name])
                                updated = cls._merge_fields(
                                    current, incoming, query=True
                                )
                                standard[s_name] = (
                                    updated.name,
                                    updated.annotation,
                                    updated.default,
                                )
                    else:
                        # Extra field not in standard - add to extra params
                        incoming = cls._create_field(
                            s_name,
                            field,
                            provider_name,
                            query=True,
                            force_optional=True,
                        )

                        if incoming.name in extra:
                            current = DataclassField(*extra[incoming.name])
                            updated = cls._merge_fields(current, incoming, query=True)
                        else:
                            updated = incoming

                        extra[updated.name] = (
                            updated.name,
                            updated.annotation,
                            updated.default,
                        )

        return standard, extra

    @classmethod
    def _extract_data(
        cls,
        providers: Any,
    ) -> tuple[dict[str, TupleFieldType], dict[str, TupleFieldType]]:
        standard: dict[str, TupleFieldType] = {}
        extra: dict[str, TupleFieldType] = {}

        for provider_name, model_details in providers.items():
            if provider_name == "openbb":
                for name, field in model_details["Data"]["fields"].items():
                    if (
                        name == "provider"
                        and field.description == "The data provider for the data."
                    ):  # noqa
                        continue
                    incoming = cls._create_field(name, field, "openbb")

                    standard[incoming.name] = (
                        incoming.name,
                        incoming.annotation,
                        incoming.default,
                    )
            else:
                for name, field in model_details["Data"]["fields"].items():
                    if name not in providers["openbb"]["Data"]["fields"]:
                        if (
                            name == "provider"
                            and field.description == "The data provider for the data."
                        ):  # noqa
                            continue
                        incoming = cls._create_field(
                            to_snake_case(name),
                            field,
                            provider_name,
                            force_optional=True,
                        )

                        if incoming.name in extra:
                            current = DataclassField(*extra[incoming.name])
                            updated = cls._merge_fields(current, incoming)
                        else:
                            updated = incoming

                        extra[updated.name] = (
                            updated.name,
                            updated.annotation,
                            updated.default,
                        )

        return standard, extra

    def _generate_params_dc(
        self, map_: MapType
    ) -> dict[str, dict[str, StandardParams | ExtraParams]]:
        """Generate dataclasses for params.

        This creates a dictionary of dataclasses that can be injected as a FastAPI
        dependency.

        Example
        -------
        @dataclass
        class CompanyNews(StandardParams):
            symbols: str = Query(...)
            page: int = Query(default=1)

        @dataclass
        class CompanyNews(ExtraParams):
            pageSize: int = Query(default=15, title="benzinga")
            displayOutput: int = Query(default="headline", title="benzinga")
            ...
            sort: str = Query(default=None, title="benzinga,polygon")
        """
        result: dict = {}

        for model_name, providers in map_.items():
            standard: dict
            extra: dict
            standard, extra = self._extract_params(providers)

            result[model_name] = {
                "standard": make_dataclass(
                    cls_name=model_name,
                    fields=list(standard.values()),  # type: ignore[arg-type]
                    bases=(StandardParams,),
                ),
                "extra": make_dataclass(
                    cls_name=model_name,
                    fields=list(extra.values()),  # type: ignore[arg-type]
                    bases=(ExtraParams,),
                ),
            }
        return result

    def _generate_model_providers_dc(self, map_: MapType) -> dict[str, ProviderChoices]:
        """Generate dataclasses for provider choices by model.

        This creates a dictionary that maps model names to dataclasses that can be
        injected as a FastAPI dependency.

        Example
        -------
        @dataclass
        class CompanyNews(ProviderChoices):
            provider: Literal["provider_a", "provider_b"]
        """
        result: dict = {}

        for model_name, providers in map_.items():
            choices = sorted(list(providers.keys()))
            if "openbb" in choices:
                choices.remove("openbb")

            result[model_name] = make_dataclass(
                cls_name=model_name,
                fields=[
                    (
                        "provider",
                        Literal[tuple(choices)],  # type: ignore
                        ... if len(choices) > 1 else choices[0],
                    )
                ],
                bases=(ProviderChoices,),
            )

        return result

    @staticmethod
    def _fields_to_pydantic(
        fields: list[TupleFieldType],
    ) -> dict[str, tuple[type | None, Any]]:
        """Convert dataclass fields to pydantic fields.

        Parameters
        ----------
        fields : list[TupleFieldType]
            List of (name, annotation, default) tuples.

        Returns
        -------
        dict[str, tuple[type | None, Any]]
            Dictionary mapping field names to (annotation, default) tuples.
        """
        return {name: (annotation, default) for name, annotation, default in fields}

    def _generate_data_dc(
        self, map_: MapType
    ) -> dict[str, dict[str, StandardData | ExtraData]]:
        """Generate dataclasses for data.

        This creates a dictionary of dataclasses.

        Example
        -------
        class EquityHistoricalData(StandardData):
            date: date
            open: PositiveFloat
            high: PositiveFloat
            low: PositiveFloat
            close: PositiveFloat
            adj_close: Optional[PositiveFloat]
            volume: PositiveFloat
        """
        result: dict = {}

        for model_name, providers in map_.items():
            standard: dict
            extra: dict
            standard, extra = self._extract_data(providers)
            result[model_name] = {
                "standard": create_model(  # type: ignore
                    model_name,
                    __base__=StandardData,
                    **self._fields_to_pydantic(list(standard.values())),
                ),
                "extra": create_model(  # ty: ignore[no-matching-overload]
                    model_name,
                    __base__=ExtraData,
                    **self._fields_to_pydantic(list(extra.values())),
                ),
            }

        return result

    def _generate_return_schema(
        self,
        data: dict[str, dict[str, StandardData | ExtraData]],
    ) -> dict[str, type[BaseModel]]:
        """Merge standard data with extra data into a single BaseModel to be injected as FastAPI dependency."""
        result: dict = {}
        for model_name, dataclasses in data.items():
            standard = dataclasses["standard"]
            extra = dataclasses["extra"]

            fields = getattr(standard, "model_fields", {}).copy()
            extra_fields = getattr(extra, "model_fields", {}).copy()
            fields.update(extra_fields)

            fields_dict: dict[str, tuple[Any, Any]] = {}

            for name, field in fields.items():
                fields_dict[name] = (
                    field.annotation,
                    Field(
                        default=field.default,
                        title=field.title,
                        description=field.description,
                        alias=field.alias,
                        json_schema_extra=field.json_schema_extra,
                    ),
                )

            model_config = ConfigDict(extra="allow", populate_by_name=True)

            result[model_name] = create_model(  # type: ignore
                model_name,
                __config__=model_config,
                **fields_dict,
            )

        return result

    def _get_provider_choices(self, available_providers: list[str]) -> type:
        return make_dataclass(
            cls_name="ProviderChoices",
            fields=[("provider", Literal[tuple(available_providers)])],  # type: ignore
            bases=(ProviderChoices,),
        )

    def _get_annotated_union(self, models: dict[str, Any]) -> Any:
        """Get annotated union."""

        def get_provider(v: type[BaseModel]):
            """Callable to discriminate which BaseModel to use."""
            return getattr(v, "_provider", None)

        args = set()
        for provider, model in models.items():
            data = model["data"]
            # We set the provider to use it in discriminator function
            setattr(data, "_provider", provider)
            if get_origin(data) is Annotated:
                metadata = data.__metadata__ + (Tag(provider),)
                annotated_args = (get_args(data)[0],) + metadata
                args.add(Annotated[annotated_args])
            else:
                args.add(Annotated[data, Tag(provider)])
        meta = Discriminator(get_provider) if len(args) > 1 else None
        return SerializeAsAny[Annotated[Union[tuple(args)], meta]]  # type: ignore  # noqa

    def _generate_return_annotations(
        self, original_models: dict[str, dict[str, Any]]
    ) -> dict[str, type[OBBject]]:
        """Generate return annotations for FastAPI.

        Example
        -------
        class Data(BaseModel):
            ...

        class EquityData(Data):
            price: float

        class YFEquityData(EquityData):
            yf_field: str

        class AVEquityData(EquityData):
            av_field: str

        class OBBject(BaseModel):
            results: List[
                SerializeAsAny[
                    Annotated[
                        Union[
                            Annotated[YFEquityData, Tag("yf")],
                            Annotated[AVEquityData, Tag("av")],
                        ],
                        Discriminator(get_provider),
                    ]
                ]
            ]
        """
        annotations = {}
        for name, models in original_models.items():
            outer = {model["results_type"] for model in models.values()}
            inner = self._get_annotated_union(models)
            full = Union[tuple((o[inner] if o else inner) for o in outer)]  # noqa
            annotations[name] = create_model(
                f"OBBject_{name}",
                __base__=OBBject[full],  # type: ignore
                __doc__=f"OBBject with results of type {name}",
            )
        return annotations
