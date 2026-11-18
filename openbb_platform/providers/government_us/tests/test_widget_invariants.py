"""Invariants every built widget in this provider must satisfy."""

import pytest
from fastapi import FastAPI
from openbb_platform_api.utils.widgets import build_json

from openbb_government_us.congress.congress_router import router as congress_router
from openbb_government_us.treasury.treasury_router import router as treasury_router
from openbb_government_us.usda.usda_router import router as usda_router

ROUTERS = (
    ("treasury", treasury_router, "/api/v1/ustreasury"),
    ("usda", usda_router, "/api/v1/usda"),
    ("congress", congress_router, "/api/v1/uscongress"),
)


def _widgets(router, prefix) -> dict:
    """Build the widgets.json entries for one router."""
    app = FastAPI()
    app.include_router(router.api_router, prefix=prefix)
    return build_json(app.openapi(), {})


@pytest.fixture(scope="module")
def built() -> list[tuple[str, str, dict]]:
    """Return every built widget as (namespace, widget_id, config)."""
    return [
        (namespace, widget_id, config)
        for namespace, router, prefix in ROUTERS
        for widget_id, config in _widgets(router, prefix).items()
    ]


class TestWidgetParamTypes:
    """A param's declared type must match the type of its option values."""

    def test_text_params_carry_string_options(self, built):
        """A text param with a numeric option value crashes the frontend.

        The Workspace lower-cases text option values, so a numeric one raises
        'toLowerCase is not a function' and takes the whole widget down.
        """
        offenders = [
            (widget_id, param["paramName"], option["value"])
            for _, widget_id, config in built
            for param in config.get("params") or []
            if param.get("type") in (None, "text")
            for option in param.get("options") or []
            if option.get("value") is not None and not isinstance(option["value"], str)
        ]
        assert not offenders, f"text params with non-string options: {offenders}"

    def test_number_params_carry_numeric_options(self, built):
        """A number param must not carry string option values."""
        offenders = [
            (widget_id, param["paramName"], option["value"])
            for _, widget_id, config in built
            for param in config.get("params") or []
            if param.get("type") == "number"
            for option in param.get("options") or []
            if option.get("value") is not None
            and not isinstance(option["value"], (int, float))
        ]
        assert not offenders, f"number params with non-numeric options: {offenders}"

    def test_option_labels_are_strings(self, built):
        """Every option label renders as text."""
        offenders = [
            (widget_id, param["paramName"], option.get("label"))
            for _, widget_id, config in built
            for param in config.get("params") or []
            for option in param.get("options") or []
            if not isinstance(option.get("label"), str)
        ]
        assert not offenders, f"options with non-string labels: {offenders}"


def _columns(config: dict) -> list[dict]:
    """Return a widget's column definitions."""
    columns = (config.get("data") or {}).get("table", {}).get("columnsDefs")

    return columns if isinstance(columns, list) else []


class TestWidgetGroupEmitters:
    """A column advertised as clickable must actually emit."""

    def test_group_headers_have_a_click_handler(self, built):
        """A '\u25b8' header promises a click action, so it must carry one."""
        offenders = [
            (widget_id, column.get("field"), column.get("headerName"))
            for _, widget_id, config in built
            for column in _columns(config)
            if "\u25b8" in (column.get("headerName") or "")
            and not column.get("renderFn")
        ]
        assert not offenders, f"columns promising a click but not emitting: {offenders}"

    def test_cell_on_click_names_a_group_param(self, built):
        """A cellOnClick groupBy must name the param it writes into."""
        offenders = [
            (widget_id, column.get("field"))
            for _, widget_id, config in built
            for column in _columns(config)
            if column.get("renderFn") == "cellOnClick"
            and (column.get("renderFnParams") or {}).get("actionType") == "groupBy"
            and not (column.get("renderFnParams") or {}).get("groupByParamName")
        ]
        assert not offenders, f"groupBy columns with no target param: {offenders}"

    def test_group_emitters_target_a_real_param(self, built):
        """The param a column writes into must exist on some widget."""
        names = {
            param.get("paramName")
            for _, _, config in built
            for param in config.get("params") or []
        }
        offenders = [
            (widget_id, column.get("field"), target)
            for _, widget_id, config in built
            for column in _columns(config)
            if column.get("renderFn") == "cellOnClick"
            and (target := (column.get("renderFnParams") or {}).get("groupByParamName"))
            and target not in names
        ]
        assert not offenders, f"groupBy columns targeting no known param: {offenders}"

    def test_the_columns_fixture_is_not_vacuous(self, built):
        """Guard the checks above against silently iterating nothing."""
        clickable = [
            column
            for _, _, config in built
            for column in _columns(config)
            if column.get("renderFn") == "cellOnClick"
        ]
        assert len(clickable) >= 3, "expected several clickable columns to check"


class TestWidgetIdentity:
    """Every widget must be addressable and described."""

    def test_every_widget_has_an_id_and_name(self, built):
        """A widget with no id or name cannot be placed in an app."""
        offenders = [
            widget_id
            for _, widget_id, config in built
            if not config.get("widgetId") or not config.get("name")
        ]
        assert not offenders, f"widgets missing an id or name: {offenders}"

    def test_widget_ids_are_unique_within_a_namespace(self, built):
        """Two widgets sharing an id would collide in a layout."""
        seen: dict[str, set] = {}

        for namespace, widget_id, _ in built:
            bucket = seen.setdefault(namespace, set())
            assert widget_id not in bucket, f"duplicate widget id: {widget_id}"
            bucket.add(widget_id)


def _apps(namespace: str) -> list[dict]:
    """Load one namespace's app definition."""
    import json
    from pathlib import Path

    import openbb_government_us

    path = (
        Path(openbb_government_us.__file__).parent / namespace / "assets" / "apps.json"
    )

    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def _declared(namespace: str) -> set:
    """Return the param names a namespace synchronizes via groups."""
    return {
        group["paramName"]
        for app in _apps(namespace)
        for group in app.get("groups") or []
    }


class TestAppGroups:
    """A cellOnClick emitter only works if apps.json declares its group.

    Scoped to the treasury app; the congress app predates these checks and is
    deliberately left alone.
    """

    def test_every_emitter_has_a_declared_group(self, built):
        """A groupBy target with no group in apps.json does nothing when clicked."""
        orphans = [
            (namespace, widget_id, target)
            for namespace, widget_id, config in built
            if namespace == "treasury"
            for column in _columns(config)
            if (target := (column.get("renderFnParams") or {}).get("groupByParamName"))
            and target not in _declared(namespace)
        ]
        assert not orphans, f"emitters with no declared group: {orphans}"

    def test_every_group_member_accepts_its_param(self, built):
        """A widget listed in a group must expose the synchronized param."""
        widgets = {widget_id: config for _, widget_id, config in built}
        offenders = []

        for app in _apps("treasury"):
            for group in app.get("groups") or []:
                for widget_id in group["widgetIds"]:
                    config = widgets.get(widget_id)
                    names = {
                        param.get("paramName")
                        for param in (config or {}).get("params") or []
                    }

                    if config is None or group["paramName"] not in names:
                        offenders.append((widget_id, group["paramName"]))

        assert not offenders, f"group members missing their param: {offenders}"

    def test_groups_declare_their_widgets(self, built):
        """A group with no widgetIds is inert - no widget ever joins it."""
        for app in _apps("treasury"):
            for group in app.get("groups") or []:
                assert set(group) >= {
                    "name",
                    "type",
                    "paramName",
                    "widgetIds",
                }, group
                assert group["type"] in ("param", "endpointParam"), group
                assert group["widgetIds"], (
                    f"group '{group['name']}' lists no widgetIds, so nothing"
                    " joins it and clicking does nothing"
                )

    def test_every_emitting_widget_joins_its_own_group(self, built):
        """The emitting widget must itself be a member, or its clicks go nowhere."""
        offenders = []

        for app in _apps("treasury"):
            members = {
                group["paramName"]: set(group["widgetIds"])
                for group in app.get("groups") or []
            }

            for namespace, widget_id, config in built:
                if namespace != "treasury":
                    continue

                for column in _columns(config):
                    target = (column.get("renderFnParams") or {}).get(
                        "groupByParamName"
                    )

                    if target and widget_id not in members.get(target, set()):
                        offenders.append((widget_id, target))

        assert not offenders, f"emitters not listed in their group: {offenders}"

    def test_the_group_check_is_not_vacuous(self, built):
        """Guard against the checks above iterating nothing."""
        emitters = [
            column
            for _, _, config in built
            for column in _columns(config)
            if (column.get("renderFnParams") or {}).get("groupByParamName")
        ]
        assert len(emitters) >= 8, f"expected many emitters, found {len(emitters)}"


class TestNoSelfFilteringEmitters:
    """A widget must not filter its own data on a param it emits."""

    @staticmethod
    def _emitted(data_model) -> set:
        """Return the group params a Data model's columns emit."""
        emitted = set()

        for field in data_model.model_fields.values():
            config = (field.json_schema_extra or {}).get("x-widget_config") or {}
            target = (config.get("renderFnParams") or {}).get("groupByParamName")

            if target:
                emitted.add(target)

        return emitted

    def test_no_fetcher_filters_on_a_param_it_emits(self):
        """Emitting into a param the same endpoint filters by collapses the table.

        Clicking a row would re-fetch that widget scoped to the clicked row, so
        the table shows only the row just clicked. The emitting param must be a
        ghost - declared for grouping, absent from the query model.
        """
        from openbb_government_us.congress import congress_gov_provider
        from openbb_government_us.treasury import us_treasury_provider
        from openbb_government_us.usda import usda_provider

        offenders = []

        for provider in (us_treasury_provider, usda_provider, congress_gov_provider):
            for name, fetcher in provider.fetcher_dict.items():
                from typing import get_args

                query_model = fetcher.query_params_type
                returned = fetcher.return_type
                data_model = next(
                    (
                        arg
                        for arg in get_args(returned) or (returned,)
                        if hasattr(arg, "model_fields")
                    ),
                    None,
                )

                if data_model is None:
                    continue

                clash = self._emitted(data_model) & set(query_model.model_fields)

                if clash:
                    offenders.append((name, sorted(clash)))

        assert not offenders, f"widgets that filter on a param they emit: {offenders}"


class TestNoDuplicatePlacements:
    """A widget belongs in one place; repeating it fakes distinct widgets."""

    def test_no_widget_is_placed_twice_in_a_tab(self):
        """The same widget with different presets is not three widgets."""
        offenders = []

        for app in _apps("treasury"):
            for name, tab in (app.get("tabs") or {}).items():
                placed = [widget["i"] for widget in tab.get("layout") or []]

                for widget_id in set(placed):
                    if placed.count(widget_id) > 1:
                        offenders.append((name, widget_id, placed.count(widget_id)))

        assert not offenders, f"widgets placed more than once in a tab: {offenders}"

    def test_no_widget_is_placed_in_two_tabs(self):
        """A widget duplicated across tabs is the same widget, not two."""
        seen: dict[str, str] = {}
        offenders = []

        for app in _apps("treasury"):
            for name, tab in (app.get("tabs") or {}).items():
                for widget in tab.get("layout") or []:
                    widget_id = widget["i"]

                    if widget_id in seen:
                        offenders.append((widget_id, seen[widget_id], name))
                    else:
                        seen[widget_id] = name

        assert not offenders, f"widgets placed in more than one tab: {offenders}"

    def test_every_placed_widget_exists(self, built):
        """A layout entry naming an unbuilt widget renders as an error card."""
        ids = {widget_id for _, widget_id, _ in built}
        offenders = [
            (name, widget["i"])
            for app in _apps("treasury")
            for name, tab in (app.get("tabs") or {}).items()
            for widget in tab.get("layout") or []
            if widget["i"] not in ids
        ]
        assert not offenders, f"layout references unbuilt widgets: {offenders}"


def test_amendment_text_viewer_opens_on_an_amendment_with_text(built):
    """House amendments carry no published text, so the default is a Senate one."""
    config = next(
        config
        for _, widget_id, config in built
        if widget_id == "uscongress_amendment_text_congress_gov_obb"
    )
    values = {p["paramName"]: p.get("value") for p in config["params"]}
    assert values["amendment_id"] == "119-samdt-2"
