"""EIA provider router."""

from collections import Counter
from typing import Literal

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.app.model.command_context import CommandContext
from openbb_core.app.model.example import APIEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.provider_interface import (
    ExtraParams,
    ProviderChoices,
    StandardParams,
)
from openbb_core.app.query import Query as OBBQuery
from openbb_core.app.router import Router

from openbb_us_eia import COMMODITY_INSTALLED
from openbb_us_eia.browsers import router as _browsers_router
from openbb_us_eia.eia_mcp import mcp_reverse_proxy
from openbb_us_eia.rss import router as _rss_router
from openbb_us_eia.utils import catalog
from openbb_us_eia.utils.catalog import dataset_summary, model_name

router = Router(
    prefix="",
    description="US Energy Information Administration (EIA) provider router.",
)
router.include_router(_rss_router)
router.include_router(_browsers_router)
router._api_router.add_api_route(
    path="/eia_mcp",
    endpoint=mcp_reverse_proxy,
    methods=["GET", "POST", "DELETE"],
    include_in_schema=False,
)


async def get_eia_apps_json() -> list[dict]:
    """Serve the EIA app definition for OpenBB Workspace."""
    import json
    from pathlib import Path

    apps_file = Path(__file__).parent / "assets" / "apps.json"
    try:
        with apps_file.open("r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:  # noqa: BLE001
        return []


router._api_router.add_api_route(
    path="/apps.json",
    endpoint=get_eia_apps_json,
    methods=["GET"],
    include_in_schema=False,
)

EiaGroup = Literal[
    "aeo",
    "coal",
    "crude_oil_imports",
    "densified_biomass",
    "electricity",
    "electricity_grid",
    "ieo",
    "international",
    "natural_gas",
    "nuclear_outages",
    "petroleum",
    "seds",
    "state_electricity_profiles",
    "total_energy",
]

WIDGET_CATEGORY = "EIA"
WIDGET_SOURCE = "EIA"

GROUP_TITLES: dict[str, str] = {
    "aeo": "Annual Energy Outlook",
    "coal": "Coal",
    "crude_oil_imports": "Petroleum",
    "densified_biomass": "Densified Biomass",
    "electricity": "Electricity",
    "electricity_grid": "Electric Grid Monitor",
    "ieo": "International Energy Outlook",
    "international": "International",
    "natural_gas": "Natural Gas",
    "nuclear_outages": "Nuclear Outages",
    "petroleum": "Petroleum",
    "seds": "State Energy Data System",
    "state_electricity_profiles": "State Electricity Profiles",
    "total_energy": "Total Energy",
}


def _widget_config(name: str, sub_category: str) -> dict[str, str | list[str]]:
    """Build proper-cased Workspace widget metadata."""
    return {
        "name": name,
        "category": WIDGET_CATEGORY,
        "subCategory": sub_category,
        "source": [WIDGET_SOURCE],
    }


@router.command(
    methods=["GET"],
    widget_config=_widget_config("EIA Dataset Catalog", "Reference"),
    examples=[
        APIEx(
            description="List every EIA dataset served by this extension.",
            parameters={},
        ),
        APIEx(
            description="List the coal datasets with their filters and data columns.",
            parameters={"group": "coal"},
        ),
    ],
)
async def datasets(group: EiaGroup | None = None) -> OBBject:
    """Catalog of EIA APIv2 datasets served by this extension."""
    rows: list[dict] = []
    for group_name, group_spec in catalog.load_catalog().items():
        if group is not None and group_name != group:
            continue
        for slug, spec in group_spec["datasets"].items():
            rows.append(
                {
                    "group": group_name,
                    "dataset": slug,
                    "name": spec["name"],
                    "category": spec["category"],
                    "route": spec["path"],
                    "frequencies": ",".join(spec["frequencies"]),
                    "default_frequency": spec["default_frequency"],
                    "data_columns": ",".join(spec["data_columns"]),
                    "filters": ",".join(
                        facet
                        for facet, detail in spec["facets"].items()
                        if detail.get("filterable", True)
                    ),
                    "start_period": spec["start_period"],
                    "end_period": spec["end_period"],
                    "description": spec["description"] or None,
                }
            )
    return OBBject(results=rows)


@router.command(
    methods=["GET"],
    widget_config=_widget_config("EIA Filter Values", "Reference"),
    examples=[
        APIEx(
            description="List the spot price series available from the petroleum group.",
            parameters={
                "group": "petroleum",
                "dataset": "spot_prices",
                "facet": "series",
            },
        ),
        APIEx(
            description="List the balancing authorities of the hourly grid monitor.",
            parameters={
                "group": "electricity_grid",
                "dataset": "demand",
                "facet": "respondent",
            },
        ),
    ],
)
async def facet_options(
    group: EiaGroup,
    facet: str,
    dataset: str | None = None,
) -> OBBject:
    """List the valid values for one filter (facet) of an EIA dataset."""
    from openbb_core.app.service.user_service import UserService
    from openbb_core.provider.utils.helpers import amake_request

    from openbb_us_eia.utils.helpers import API_BASE, response_callback

    dataset = dataset or catalog.dataset_choices(group)[0]
    spec = catalog.get_dataset(group, dataset)
    facets = spec["facets"]
    if facet not in facets:
        raise OpenBBError(
            ValueError(
                f"'{facet}' is not a filter of dataset '{dataset}'."
                f" Choices: {', '.join(facets)}"
            )
        )
    embedded = facets[facet].get("choices")
    if embedded:
        grouped: dict[str, dict] = {}
        for choice in embedded:
            slug = choice.get("param") or choice["value"]
            record = grouped.setdefault(
                slug, {"value": slug, "label": choice["label"], "code": []}
            )
            record["code"].append(choice["value"])
        results = [
            {**record, "code": ",".join(record["code"])} for record in grouped.values()
        ]
        return OBBject(results=sorted(results, key=lambda item: item["label"]))
    credentials = UserService().default_user_settings.credentials.model_dump(
        mode="json"
    )
    api_key = credentials.get("eia_api_key") or ""
    facet_id = facets[facet]["id"]
    response = await amake_request(
        f"{API_BASE}/{spec['path']}/facet/{facet_id}?api_key={api_key}",
        response_callback=response_callback,
    )
    values = response.get("response", {}).get("facets", [])  # ty: ignore[unresolved-attribute]
    results = [
        {
            "value": str(item.get("id")),
            "label": str(item.get("name") or item.get("id")),
            "code": str(item.get("id")),
        }
        for item in values
    ]
    return OBBject(results=sorted(results, key=lambda item: item["label"]))


def _group_operation_id(func, group: str, dataset: str) -> str:
    """Build a group-qualified OpenAPI operation id for a dataset command."""
    parts = [
        part.replace("_router", "").replace("openbb_", "")
        for part in func.__module__.split(".")
    ]
    return "_".join(dict.fromkeys([*parts, group, dataset]))


def _register_dataset_command(target: Router, group: str, dataset: str) -> None:
    """Register one dataset as a model command on a sub-router."""
    spec = catalog.get_dataset(group, dataset)

    async def _route(
        cc: CommandContext,
        provider_choices: ProviderChoices,
        standard_params: StandardParams,
        extra_params: ExtraParams,
    ) -> OBBject:
        return await OBBject.from_query(OBBQuery(**locals()))

    _route.__name__ = dataset
    _route.__qualname__ = dataset
    _route.__doc__ = dataset_summary(spec)
    command_kwargs: dict = {
        "model": model_name(group, dataset),
        "examples": [APIEx(parameters={"provider": "eia", "limit": 100})],
        "widget_config": _widget_config(
            spec["name"],
            spec.get("category") or GROUP_TITLES.get(group, group),
        ),
    }
    if dataset in _MULTI_GROUP_DATASETS:
        command_kwargs["operation_id"] = _group_operation_id(_route, group, dataset)
    target.command(**command_kwargs)(_route)


def _build_group_router(group: str, description: str, categorized: bool) -> Router:
    """Build one sub-router with a command per dataset of a catalog group.

    Parameters
    ----------
    group : str
        Catalog group name.
    description : str
        The sub-router (menu) description.
    categorized : bool
        Nest datasets under their EIA category as sub-sub-routers.

    Returns
    -------
    Router
        The assembled sub-router.
    """
    group_router = Router(prefix="", description=description)
    categories: dict[str, Router] = {}
    for dataset, spec in catalog.get_group(group)["datasets"].items():
        target = group_router
        if categorized and spec.get("category_slug"):
            slug = spec["category_slug"]
            if slug not in categories:
                categories[slug] = Router(
                    prefix="",
                    description=f"{spec['category']} datasets.",
                )
            target = categories[slug]
        _register_dataset_command(target, group, dataset)
    for slug, category_router in sorted(categories.items()):
        group_router.include_router(category_router, prefix=f"/{slug}")
    return group_router


_DATASET_GROUP_COUNTS = Counter(
    slug
    for group_spec in catalog.load_catalog().values()
    for slug in group_spec["datasets"]
)
_MULTI_GROUP_DATASETS = frozenset(
    slug for slug, count in _DATASET_GROUP_COUNTS.items() if count > 1
)


_coal_router = _build_group_router(
    "coal",
    "US coal production, consumption, quality, reserves, shipments, prices, and trade.",
    categorized=False,
)
_petroleum_router = _build_group_router(
    "petroleum",
    "US petroleum supply, disposition, prices, refining, movements, and stocks.",
    categorized=True,
)
_natural_gas_router = _build_group_router(
    "natural_gas",
    "US natural gas production, consumption, storage, trade, reserves, and prices.",
    categorized=True,
)
_electricity_router = _build_group_router(
    "electricity",
    "US electric power operations, generator inventory, plant fuel data, and retail sales.",
    categorized=False,
)
_electricity_grid_router = _build_group_router(
    "electricity_grid",
    "Hourly and daily electric grid monitor: demand, generation by fuel, and interchange.",
    categorized=False,
)
_state_profiles_router = _build_group_router(
    "state_electricity_profiles",
    "Annual state electricity profiles: rankings, capability, emissions, and net metering.",
    categorized=False,
)
_biomass_router = _build_group_router(
    "densified_biomass",
    "Densified biomass (wood pellet) capacity, production, feedstocks, sales, and inventories.",
    categorized=False,
)
_nuclear_router = _build_group_router(
    "nuclear_outages",
    "Daily US nuclear generator capacity and outages, nationally and by facility.",
    categorized=False,
)

router.include_router(_coal_router, prefix="/coal")
router.include_router(_petroleum_router, prefix="/petroleum")
router.include_router(_natural_gas_router, prefix="/natural_gas")
router.include_router(_electricity_router, prefix="/electricity")
router.include_router(_electricity_grid_router, prefix="/electricity_grid")
router.include_router(_state_profiles_router, prefix="/state_electricity_profiles")
router.include_router(_biomass_router, prefix="/densified_biomass")
router.include_router(_nuclear_router, prefix="/nuclear_outages")


@router.command(
    model="EiaCrudeOilImports",
    widget_config=_widget_config("Crude Oil Imports", "Petroleum"),
    examples=[
        APIEx(
            description="Monthly crude oil imports from Canada, by grade.",
            parameters={"provider": "eia", "origin": "canada", "limit": 100},
        ),
    ],
)
async def crude_oil_imports(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """US crude oil imports by origin, destination, and grade."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="EiaInternational",
    widget_config=_widget_config("International Energy Data", "International"),
    examples=[
        APIEx(
            description="Annual petroleum production for OPEC members.",
            parameters={
                "provider": "eia",
                "product": "total_petroleum_and_other_liquids",
                "activity": "production",
                "country": "opec",
                "limit": 100,
            },
        ),
    ],
)
async def international(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """International energy production, consumption, and trade statistics by country and region."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="EiaSeds",
    widget_config=_widget_config(
        "State Energy Data System (SEDS)", "State Energy Data System"
    ),
    examples=[
        APIEx(
            description="Total energy consumption per capita for Texas.",
            parameters={
                "provider": "eia",
                "series": "total_energy_consumption_per_capita",
                "state": "texas",
            },
        ),
    ],
)
async def seds(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """State Energy Data System (SEDS): annual state-level energy estimates back to 1960."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="EiaTotalEnergy",
    widget_config=_widget_config(
        "Total Energy (Monthly Energy Review)", "Total Energy"
    ),
    examples=[
        APIEx(
            description="Monthly total US electricity net generation.",
            parameters={"provider": "eia", "msn": "ELETPUS"},
        ),
    ],
)
async def total_energy(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Monthly Energy Review series covering all energy sources, by MSN mnemonic."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="EiaAeo",
    widget_config=_widget_config("Annual Energy Outlook", "Annual Energy Outlook"),
    examples=[
        APIEx(
            description="Reference-case projections from the 2025 Annual Energy Outlook.",
            parameters={
                "provider": "eia",
                "release": "2025",
                "scenario": "reference_case",
                "table": "total_energy_supply_disposition_and_price_summary",
                "region": "united_states",
            },
        ),
    ],
)
async def aeo(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Annual Energy Outlook: long-term US energy projections by release and scenario."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="EiaIeo",
    widget_config=_widget_config(
        "International Energy Outlook", "International Energy Outlook"
    ),
    examples=[
        APIEx(
            description="Reference-case projections from the 2023 International Energy Outlook.",
            parameters={
                "provider": "eia",
                "release": "2023",
                "table": "3",
                "limit": 500,
            },
        ),
    ],
)
async def ieo(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """International Energy Outlook: long-term world energy projections by release and scenario."""
    return await OBBject.from_query(OBBQuery(**locals()))


@router.command(
    model="EiaDataBrowser",
    widget_config=_widget_config("EIA API Data Browser", "Reference"),
    examples=[
        APIEx(
            description="Query any APIv2 route directly - Brent spot price, monthly.",
            parameters={
                "provider": "eia",
                "route": "petroleum/pri/spt",
                "frequency": "monthly",
                "facets": "product:EPCBRENT",
                "limit": 12,
            },
        ),
    ],
)
async def data_browser(
    cc: CommandContext,
    provider_choices: ProviderChoices,
    standard_params: StandardParams,
    extra_params: ExtraParams,
) -> OBBject:
    """Query any EIA APIv2 data route directly by path, with facet filters and pagination."""
    return await OBBject.from_query(OBBQuery(**locals()))


if not COMMODITY_INSTALLED:

    @router.command(
        model="PetroleumStatusReport",
        widget_config=_widget_config("Weekly Petroleum Status Report", "Petroleum"),
        examples=[
            APIEx(parameters={"provider": "eia"}),
            APIEx(
                description="Get the weekly estimates of the imports and exports of crude oil.",
                parameters={
                    "provider": "eia",
                    "category": "weekly_estimates",
                    "table": "imports",
                },
            ),
        ],
    )
    async def petroleum_status_report(
        cc: CommandContext,
        provider_choices: ProviderChoices,
        standard_params: StandardParams,
        extra_params: ExtraParams,
    ) -> OBBject:
        """EIA Weekly Petroleum Status Report."""
        return await OBBject.from_query(OBBQuery(**locals()))

    @router.command(
        model="ShortTermEnergyOutlook",
        widget_config=_widget_config(
            "Short-Term Energy Outlook", "Short-Term Energy Outlook"
        ),
        examples=[
            APIEx(parameters={"provider": "eia"}),
            APIEx(
                description="Get the US Energy Markets Summary table.",
                parameters={"provider": "eia", "table": "01"},
            ),
        ],
    )
    async def short_term_energy_outlook(
        cc: CommandContext,
        provider_choices: ProviderChoices,
        standard_params: StandardParams,
        extra_params: ExtraParams,
    ) -> OBBject:
        """Monthly short term (18 month) projections using EIA's STEO model."""
        return await OBBject.from_query(OBBQuery(**locals()))
