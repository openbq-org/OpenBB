"""IMF Port Volume Model."""

from __future__ import annotations

from datetime import date as dateType
from typing import Any

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.app.service.system_service import SystemService
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.port_volume import (
    PortVolumeData,
    PortVolumeQueryParams,
)
from pydantic import ConfigDict, Field, field_validator, model_validator

from openbb_imf.utils.constants import (
    PORT_COUNTRIES,
    PORT_COUNTRIES_CHOICES,
    PortCountries,
)
from openbb_imf.utils.port_watch_helpers import (
    get_port_id_choices,
    get_port_ids_by_country,
)

api_prefix = SystemService().system_settings.api_settings.prefix


class ImfPortVolumeQueryParams(PortVolumeQueryParams):
    """IMF Port Volume Query Parameters."""

    __json_schema_extra__ = {
        "port_code": {
            "multiple_items_allowed": True,
            "x-widget_config": {
                "optionsEndpoint": f"{api_prefix}/imf/portwatch/list_port_id_choices",
                "style": {"popupWidth": 350},
            },
        },
        "country": {
            "x-widget_config": {
                "options": PORT_COUNTRIES_CHOICES,
                "description": "Filter by country. This parameter is overridden by `port_code` if both are provided.",
                "style": {"popupWidth": 350},
            }
        },
        "start_date": {
            "description": "Start date for the data query. Minimum is 2019-01-01.",
            "x-widget_config": {
                "type": "date",
                "value": "2019-01-01",
            },
        },
    }

    port_code: str | None = Field(
        default=None,
        description="Port code to filter results by a specific port."
        + " This parameter is ignored if `country` parameter is provided."
        + " To get a list of available ports, use `obb.economy.shipping.port_info()`.",
    )
    country: PortCountries | None = Field(
        default=None,
        description="Country to focus on. Enter as a 3-letter ISO country code."
        + " This parameter is overridden by `port_code` if both are provided.",
    )

    @field_validator("port_code")
    @classmethod
    def validate_port_code(cls, v):
        """Validate port_code."""
        if isinstance(v, str):
            v = [v] if "," not in v else v.split(",")

        if (
            not isinstance(v, list) or not all(isinstance(item, str) for item in v)
        ):  # pragma: no cover -- unreachable: pydantic types the field as ``str | None`` so non-string/non-list inputs are rejected upstream
            raise OpenBBError("port_code must be a string or a list of strings.")

        port_id_choices = get_port_id_choices()
        port_id_map = {
            choice["value"].lower(): choice["label"] for choice in port_id_choices
        }

        country_name_to_iso = {}
        for iso_code, country_name in PORT_COUNTRIES.items():
            country_name_to_iso[country_name.lower()] = iso_code
            country_name_to_iso[country_name.lower().replace(" ", "_")] = iso_code

        new_values: list = []
        for item in v:
            if item == "all":
                return "all"

            if item.upper() in PORT_COUNTRIES.values():
                country_ports = get_port_ids_by_country(item)
                if country_ports:
                    new_values.extend(country_ports.split(","))
                    continue

            item_lower = (
                item.lower().split("(")[0].replace(" ", "_")
                if "(" in item
                else item.lower().replace(" ", "_")
            )
            item_lower = item_lower.replace(" - ", "_").replace("-", "_")

            if item in port_id_map:
                new_values.append(item)
            elif item in port_id_map.values():
                for k, v_ in port_id_map.items():
                    if v_ == item:
                        new_values.append(k)
                        break
            elif item_lower in [
                v_.replace(" - ", "_").replace("-", "_").lower().replace(" ", "_")
                for v_ in port_id_map.values()
            ]:
                values_snake = [
                    v_.replace(" - ", "_").replace("-", "_").lower().replace(" ", "_")
                    for v_ in port_id_map.values()
                ]
                idx = values_snake.index(item_lower)
                new_values.append(list(port_id_map.keys())[idx])
            elif item_lower in [
                v_.split(" - ")[0].lower().replace(" ", "_")
                for v_ in port_id_map.values()
            ]:
                first_parts = [
                    v_.split(" - ")[0].lower().replace(" ", "_")
                    for v_ in port_id_map.values()
                ]
                idx = first_parts.index(item_lower)
                new_values.append(list(port_id_map.keys())[idx])
            else:
                raise ValueError(
                    f"Invalid port_code: {item}. Must be a valid port ID or name.Available options: {port_id_choices}."
                )

        if not new_values:  # pragma: no cover -- unreachable: every loop iteration either appends to ``new_values``, early-returns ``"all"``, or raises at line 136
            raise ValueError("No valid port_code provided.")

        return ",".join(new_values)

    @model_validator(mode="before")
    @classmethod
    def validate_model(cls, values):
        """Validate the model before instantiation."""
        if values.get("start_date") is not None and values["start_date"] < dateType(
            2019, 1, 1
        ):
            raise OpenBBError(
                ValueError(
                    f"Minimum start_date is 2019-01-01. Got {values['start_date']} instead."
                )
            )
        if not values.get("port_code") and not values.get("country"):
            values["port_code"] = "port1114"

        return values


class ImfPortVolumeData(PortVolumeData):
    """IMF Port Volume Data Model."""

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={
            "x-widget_config": {
                "$.description": (
                    "Daily count of port calls, estimates of import volumes and export volumes "
                    "(in metric tons) for 1666 ports around the world, using"
                    " real-time data on vessel movements—Automatic Identification System (AIS)"
                    " signals of vessels—as our primary data source."
                    " More info at [IMF PortWatch](https://portwatch.imf.org/datasets/959214444157458aad969389b3ebe1a0/about)."
                ),
                "$.refetchInterval": False,
                "$.category": "IMF Utilities",
                "$.subCategory": "Port Watch",
                "$.source": ["UN Global Platform; IMF PortWatch"],
            }
        },
    )

    __alias_dict__ = {
        "port_code": "portid",
        "port_name": "portname",
        "country_code": "ISO3",
        "imports": "import",
        "imports_cargo": "import_cargo",
        "imports_tanker": "import_tanker",
        "imports_container": "import_container",
        "imports_general_cargo": "import_general_cargo",
        "imports_dry_bulk": "import_dry_bulk",
        "imports_roro": "import_roro",
        "exports": "export",
        "exports_cargo": "export_cargo",
        "exports_tanker": "export_tanker",
        "exports_container": "export_container",
        "exports_general_cargo": "export_general_cargo",
        "exports_dry_bulk": "export_dry_bulk",
        "exports_roro": "export_roro",
    }

    country_code: str = Field(
        description="3-letter ISO country code of the country where the port is located.",
    )
    portcalls: int = Field(
        description="Total number of ships entering the port at this date."
        + " This is the sum of portcalls_container, portcalls_dry_bulk,"
        + " portcalls_general_cargo, portcalls_roro and portcalls_tanker.",
        title="Port Calls",
    )
    portcalls_tanker: int = Field(
        description="Number of tankers transiting through the chokepoint or making a port call.",
        title="Tanker Port Calls",
    )
    portcalls_container: int = Field(
        description="Number of containers transiting through the chokepoint or making a port call.",
        title="Container Port Calls",
    )
    portcalls_general_cargo: int = Field(
        description="Number of general cargo ships transiting through the chokepoint or making a port call.",
        title="General Cargo Port Calls",
    )
    portcalls_dry_bulk: int = Field(
        description="Number of dry bulk carriers transiting through the chokepoint or making a port call.",
        title="Dry Bulk Port Calls",
    )
    portcalls_roro: int = Field(
        description="Number of Ro-Ro ships transiting through the chokepoint or making a port call.",
        title="Ro-Ro Port Calls",
    )
    imports: float = Field(
        description="Total import volume (in metric tons) of all ships entering the port at this date."
        + " This is the sum of import_container, import_dry_bulk, import_general_cargo, import_roro and import_tanker."
    )
    imports_cargo: float = Field(
        description="Total import volume (in metric tons) of all ships (excluding tankers)"
        + " entering the port at this date."
        + " This is the sum of import_container, import_dry_bulk, import_general_cargo and import_roro."
    )
    imports_tanker: float = Field(
        description="Total import volume (in metric tons) of tankers entering the port at this date.",
        title="Tanker Imports",
        json_schema_extra={
            "x-unit_measurement": "metric_tons",
            "x-widget_config": {
                "suffix": "mt",
            },
        },
    )
    imports_container: float = Field(
        description="Total import volume (in metric tons) of all container ships entering the port at this date.",
        title="Container Imports",
        json_schema_extra={
            "x-unit_measurement": "metric_tons",
            "x-widget_config": {
                "suffix": "mt",
            },
        },
    )
    imports_general_cargo: float = Field(
        description="Total import volume (in metric tons) of general cargo ships entering the port at this date.",
        title="General Cargo Imports",
        json_schema_extra={
            "x-unit_measurement": "metric_tons",
            "x-widget_config": {
                "suffix": "mt",
            },
        },
    )
    imports_dry_bulk: float = Field(
        description="Total import volume (in metric tons) of dry bulk carriers entering the port at this date.",
        title="Dry Bulk Imports",
        json_schema_extra={
            "x-unit_measurement": "metric_tons",
            "x-widget_config": {
                "suffix": "mt",
            },
        },
    )
    imports_roro: float = Field(
        description="Total import volume (in metric tons) of Ro-Ro ships entering the port at this date.",
        title="Ro-Ro Imports",
        json_schema_extra={
            "x-unit_measurement": "metric_tons",
            "x-widget_config": {
                "suffix": "mt",
            },
        },
    )
    exports: float = Field(
        description="Total export volume (in metric tons) of all ships entering the port at this date."
        + " This is the sum of export_container, export_dry_bulk, export_general_cargo, export_roro and export_tanker.",
        json_schema_extra={
            "x-unit_measurement": "metric_tons",
            "x-widget_config": {
                "suffix": "mt",
            },
        },
    )
    exports_cargo: float = Field(
        description="Total export volume (in metric tons) of all ships (excluding tankers)"
        + " entering the port at this date."
        + " This is the sum of export_container, export_dry_bulk, export_general_cargo and export_roro.",
        json_schema_extra={
            "x-unit_measurement": "metric_tons",
            "x-widget_config": {
                "suffix": "mt",
            },
        },
    )
    exports_tanker: float = Field(
        description="Total export volume (in metric tons) of tankers entering the port at this date.",
        title="Tanker Exports",
        json_schema_extra={
            "x-unit_measurement": "metric_tons",
            "x-widget_config": {
                "suffix": "mt",
            },
        },
    )
    exports_container: float = Field(
        description="Total export volume (in metric tons) of all container ships entering the port at this date.",
        title="Container Exports",
        json_schema_extra={
            "x-unit_measurement": "metric_tons",
            "x-widget_config": {
                "suffix": "mt",
            },
        },
    )
    exports_general_cargo: float = Field(
        description="Total export volume (in metric tons) of general cargo ships entering the port at this date.",
        title="General Cargo Exports",
        json_schema_extra={
            "x-unit_measurement": "metric_tons",
            "x-widget_config": {
                "suffix": "mt",
            },
        },
    )
    exports_dry_bulk: float = Field(
        description="Total export volume (in metric tons) of dry bulk carriers entering the port at this date.",
        title="Dry Bulk Exports",
        json_schema_extra={
            "x-unit_measurement": "metric_tons",
            "x-widget_config": {
                "suffix": "mt",
            },
        },
    )
    exports_roro: float = Field(
        description="Total export volume (in metric tons) of Ro-Ro ships entering the port at this date.",
        title="Ro-Ro Exports",
        json_schema_extra={
            "x-unit_measurement": "metric_tons",
            "x-widget_config": {
                "suffix": "mt",
            },
        },
    )


class ImfPortVolumeFetcher(Fetcher[ImfPortVolumeQueryParams, list[ImfPortVolumeData]]):
    """IMF Port Volume Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> ImfPortVolumeQueryParams:
        """Transform query parameters to the model."""
        if (start_date := params.get("start_date")) and start_date < dateType(
            2019, 1, 1
        ):
            raise OpenBBError(
                ValueError(
                    "start_date must be after 2019-01-01 for IMF Port Volume data."
                )
            )

        if country := params.pop("country", None):
            params["port_code"] = (
                params["port_code"]
                if params.get("port_code")
                else get_port_ids_by_country(country)
            )

        return ImfPortVolumeQueryParams(**params)

    @staticmethod
    async def aextract_data(
        query: ImfPortVolumeQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> list:
        """Extract data from the IMF Port Volume API."""
        import asyncio  # noqa
        from openbb_imf.utils.port_watch_helpers import get_daily_port_activity_data

        port_codes = (
            get_port_ids_by_country(query.country)
            if query.country
            else (
                query.port_code.split(",")
                if isinstance(query.port_code, str)
                else query.port_code
            )
        )

        if not port_codes:
            raise OpenBBError("Expected values as valid portIDs, got None instead.")

        output: list = []

        async def fetch_port_data(port_code: str):
            """Fetch data for a single port."""
            try:
                data = await get_daily_port_activity_data(
                    port_code, query.start_date, query.end_date
                )
                if data:
                    output.extend(data)
            except Exception as e:
                raise OpenBBError(
                    f"Failed to fetch data for port {port_code}: {e} -> {e.args}"
                ) from e

        tasks = [fetch_port_data(port_code=port_code) for port_code in port_codes]

        tasks_results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in tasks_results:
            if isinstance(result, Exception):
                raise OpenBBError(
                    f"Error fetching port data: {result} -> {result.args[0]}"
                )

        if not output:
            raise OpenBBError(
                f"No data found for the specified port(s). {port_codes}"
                " Ensure the port_code is correct and available in the IMF PortWatch dataset."
            )
        return output

    @staticmethod
    def transform_data(
        query: ImfPortVolumeQueryParams,
        data: list,
        **kwargs: Any,
    ) -> list[ImfPortVolumeData]:
        """Transform the raw data into the model."""
        return [
            ImfPortVolumeData(**item)
            for item in sorted(data, key=lambda x: (x.get("date"), x.get("portname")))
        ]
