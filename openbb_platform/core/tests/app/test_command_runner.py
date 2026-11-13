"""Test command runner."""

import warnings
from dataclasses import dataclass
from inspect import Parameter
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import Query
from fastapi.params import Query as QueryParam
from pydantic import BaseModel, ConfigDict

from openbb_core.app.command_runner import (
    CommandRunner,
    ExecutionContext,
    ParametersBuilder,
    StaticCommandRunner,
)
from openbb_core.app.model.abstract.warning import OpenBBWarning
from openbb_core.app.model.command_context import CommandContext
from openbb_core.app.model.extension import CachedAccessor, Extension
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.model.system_settings import SystemSettings
from openbb_core.app.model.user_settings import UserSettings
from openbb_core.app.provider_interface import ExtraParams
from openbb_core.app.router import CommandMap


class MockAPIRoute:
    """MockAPIRoute"""

    def __init__(self, route):
        """Initialize the mock API route."""
        self.route = route
        self.openapi_extra = {"no_validate": True}


class MockExecutionContext:
    """MockExecutionContext"""

    _route_map = {"mock/route": "mock_func"}

    def __init__(self, cmd_map, route, sys, user):
        """Initialize the mock execution context."""
        self.command_map = cmd_map
        self.route = route
        self.system_settings = sys
        self.user_settings = user

    @property
    def api_route(self) -> str:
        """Mock API route."""
        return MockAPIRoute(self.route)  # type: ignore


@pytest.fixture()
def execution_context():
    """Set up execution context."""
    sys = SystemSettings(logging_suppress=False)
    user = UserSettings()
    cmd_map = CommandMap()
    return MockExecutionContext(cmd_map, "mock/route", sys, user)


@pytest.fixture()
def mock_func():
    """Set up mock function."""

    def mock_func(
        a: int, b: int, c: float = 10.0, d: int = 5, provider_choices: dict = {}
    ) -> None:
        """Mock function."""

    return mock_func


@pytest.fixture()
def allow_command_output_extensions(monkeypatch):
    """Enable command-output OBBject extensions for the duration of a test."""
    from openbb_core.app.service.system_service import SystemService

    service = SystemService()
    monkeypatch.setattr(
        service,
        "system_settings",
        service.system_settings.model_copy(
            update={
                "allow_on_command_output": True,
                "allow_mutable_extensions": True,
            }
        ),
    )


def test_execution_context():
    """Test execution context."""
    sys = SystemSettings(logging_suppress=False)
    user = UserSettings()
    cmd_map = CommandMap()
    ctx = ExecutionContext(cmd_map, "mock/route", sys, user)

    assert isinstance(ctx, ExecutionContext)
    assert ctx.system_settings == sys
    assert ctx.user_settings == user
    assert ctx.command_map == cmd_map
    assert ctx.route == "mock/route"


def test_parameters_builder():
    """Test parameters builder."""
    assert ParametersBuilder()


@pytest.mark.parametrize(
    "input_func, expected_annotations",
    [
        (lambda x: x, {"x": Parameter(name="x", kind=Parameter.POSITIONAL_OR_KEYWORD)}),
        (
            lambda a, b, c=10: a + b + c,
            {
                "a": Parameter(name="a", kind=Parameter.POSITIONAL_OR_KEYWORD),
                "b": Parameter(name="b", kind=Parameter.POSITIONAL_OR_KEYWORD),
                "c": Parameter(
                    name="c", kind=Parameter.POSITIONAL_OR_KEYWORD, default=10
                ),
            },
        ),
        (
            lambda x, y, *, z: x + y + z,
            {
                "x": Parameter(name="x", kind=Parameter.POSITIONAL_OR_KEYWORD),
                "y": Parameter(name="y", kind=Parameter.POSITIONAL_OR_KEYWORD),
                "z": Parameter(name="z", kind=Parameter.KEYWORD_ONLY),
            },
        ),
    ],
)
def test_parameters_builder_get_polished_func(input_func, expected_annotations):
    """Test get_polished_func."""
    polished_func = ParametersBuilder.get_polished_func(input_func)

    assert polished_func.__annotations__ == expected_annotations
    assert polished_func.__signature__ == input_func.__signature__  # type: ignore[attr-defined]


def test_parameters_builder_get_polished_func_removes_authenticated_user_settings():
    def _f(a: int, __authenticated_user_settings=None):
        return a

    polished = ParametersBuilder.get_polished_func(_f)
    names = [p.name for p in polished.__signature__.parameters.values()]
    assert "__authenticated_user_settings" not in names


@pytest.mark.parametrize(
    "input_func, expected_params",
    [
        (lambda x: x, [Parameter("x", Parameter.POSITIONAL_OR_KEYWORD)]),
        (
            lambda a, b, c=10: a + b + c,
            [
                Parameter("a", Parameter.POSITIONAL_OR_KEYWORD),
                Parameter("b", Parameter.POSITIONAL_OR_KEYWORD),
                Parameter("c", Parameter.POSITIONAL_OR_KEYWORD, default=10),
            ],
        ),
        (
            lambda x, y, *, z: x + y + z,
            [
                Parameter("x", Parameter.POSITIONAL_OR_KEYWORD),
                Parameter("y", Parameter.POSITIONAL_OR_KEYWORD),
                Parameter("z", Parameter.KEYWORD_ONLY),
            ],
        ),
    ],
)
def test_parameters_builder_get_polished_parameter_list(input_func, expected_params):
    """Test get_polished_parameter_list."""
    param_list = ParametersBuilder.get_polished_parameter_list(input_func)

    assert param_list == expected_params


@pytest.mark.parametrize(
    "input_func, input_args, input_kwargs, expected_result",
    [
        (lambda x: x, (5,), {}, {"x": 5}),
        (lambda a, b, c=10: a + b + c, (2, 3), {}, {"a": 2, "b": 3, "c": 10}),
        (lambda x, y, *, z: x + y + z, (1, 2), {"z": 3}, {"x": 1, "y": 2, "z": 3}),
    ],
)
def test_parameters_builder_merge_args_and_kwargs(
    input_func, input_args, input_kwargs, expected_result
):
    """Test merge_args_and_kwargs."""
    result = ParametersBuilder.merge_args_and_kwargs(
        input_func, input_args, input_kwargs
    )

    assert result == expected_result


def test_parameters_builder_merge_args_and_kwargs_skips_existing_parameter_key():
    def _f(a: int, **kwargs):
        return a

    result = ParametersBuilder.merge_args_and_kwargs(
        _f,
        (),
        {"a": 1, "kwargs": {"a": 99, "x": 2}, "x": 3, "filter_query": "q"},
    )
    assert result["a"] == 99
    assert result["x"] == 3
    assert "filter_query" not in result


@pytest.mark.parametrize(
    "kwargs, system_settings, user_settings, expected_result",
    [
        (
            {"cc": "existing_cc"},
            SystemSettings(logging_suppress=False),
            UserSettings(),
            {"cc": "mock_cc"},
        ),
    ],
)
def test_parameters_builder_update_command_context(
    kwargs, system_settings, user_settings, expected_result
):
    """Test update_command_context."""

    def other_mock_func(
        cc: CommandContext,
        a: int,
        b: int,
    ) -> None:
        """Mock function."""

    result = ParametersBuilder.update_command_context(
        other_mock_func, kwargs, system_settings, user_settings
    )

    assert isinstance(result["cc"], CommandContext)
    assert result["cc"].system_settings == system_settings
    assert result["cc"].user_settings == user_settings


def test_parameters_builder_validate_kwargs(mock_func):
    """Test validate_kwargs."""
    # TODO: add more test cases with @pytest.mark.parametrize

    result = ParametersBuilder.validate_kwargs(
        mock_func, {"a": 1, "b": "2", "c": 3.0, "d": 4}
    )

    assert result == {"a": 1, "b": 2, "c": 3.0, "d": 4, "provider_choices": {}}


@pytest.mark.parametrize(
    "extra_params, base, expect",
    [
        (
            {"exists": ...},
            ExtraParams,
            None,
        ),
        (
            {"inexistent_field": ...},
            ExtraParams,
            OpenBBWarning,
        ),
    ],
)
def test_parameters_builder__warn_kwargs(extra_params, base, expect):
    """Test _warn_kwargs."""

    @dataclass
    class SomeModel(base):  # type: ignore[misc,valid-type]
        """SomeModel"""

        exists: QueryParam = Query(...)

    class Model(BaseModel):
        """Model"""

        model_config = ConfigDict(arbitrary_types_allowed=True)
        extra_params: SomeModel

    if expect is not None:
        with pytest.warns(expect) as warning_info:
            ParametersBuilder._warn_kwargs(extra_params, Model)
        assert len(warning_info) > 0
    else:
        ParametersBuilder._warn_kwargs(extra_params, Model)


def test_parameters_builder_as_dict_exception_path():
    class _Bad:
        def __iter__(self):
            raise RuntimeError("boom")

    assert ParametersBuilder._as_dict(_Bad()) == {}


def test_parameters_builder_build(mock_func, execution_context):
    """Test build."""
    # TODO: add more test cases with @pytest.mark.parametrize

    with patch("openbb_core.app.provider_interface.ProviderInterface") as mock_pi:
        mock_pi.available_providers = ["provider1", "provider2"]

        result = ParametersBuilder.build(
            args=(1, 2),
            kwargs={
                "c": 3,
                "d": "4",
                "provider_choices": {"provider": "provider1"},
            },
            func=mock_func,
            execution_context=execution_context,
        )

        assert result == {
            "a": 1,
            "b": 2,
            "c": 3.0,
            "d": 4,
            "provider_choices": {"provider": "provider1"},
        }


def test_command_runner():
    """Test command runner."""
    assert CommandRunner()


def test_command_runner_properties():
    """Test properties."""
    sys = SystemSettings(logging_suppress=False)
    user = UserSettings()
    cmd_map = CommandMap()
    runner = CommandRunner(cmd_map, sys, user)

    assert isinstance(runner, CommandRunner)
    assert runner.system_settings == sys
    assert runner.user_settings == user
    assert runner.command_map == cmd_map


def test_command_runner_default_user_settings_reads_live_user_service_singleton():
    """When no ``user_settings`` is passed, the default comes from the live
    ``UserService()`` singleton's ``default_user_settings`` — mirroring
    ``system_settings``' own ``SystemService().system_settings`` default —
    not a fresh ``UserService.read_from_file()`` disk re-read.

    A fresh classmethod re-read would bypass any layered-TOML ``[user]``
    overrides that ``apply_config_to_services`` merged onto the singleton
    instance, since that function patches the singleton in place rather
    than rewriting the on-disk JSON.
    """
    sentinel = UserSettings()
    with patch(
        "openbb_core.app.service.user_service.UserService",
    ) as mock_user_service_cls:
        mock_user_service_cls.return_value.default_user_settings = sentinel
        runner = CommandRunner()

    mock_user_service_cls.assert_called_once()
    assert runner.user_settings is sentinel


@patch("openbb_core.app.command_runner.CommandRunner")
def test_command_runner_run(_):
    """Test run."""
    runner = CommandRunner()

    with patch(  # type: ignore
        "openbb_core.app.command_runner.StaticCommandRunner",
        **{"return_value.run": True},
    ):
        assert runner.run("mock/route")


@pytest.mark.asyncio
@patch("openbb_core.app.router.CommandMap.get_command")
@patch("openbb_core.app.command_runner.StaticCommandRunner._execute_func")
async def test_static_command_runner_run(
    mock_execute_func, mock_get_command, execution_context
):
    """Test static command runner run."""

    def other_mock_func(a: int, b: int, c: int, d: int) -> list[int]:
        """Mock function."""
        return [a, b, c, d]

    class MockOBBject:
        """Mock OBBject"""

        def __init__(self, results):
            """Initialize the mock object."""
            self.results = results
            self.extra = {}
            self.extra["metadata"] = {"test": "test"}
            self.provider = None

    mock_get_command.return_value = other_mock_func
    mock_execute_func.return_value = MockOBBject(results=[1, 2, 3, 4])

    result = await StaticCommandRunner.run(execution_context, 1, 2, c=3, d=4)

    assert result.results == [1, 2, 3, 4]
    assert hasattr(result, "extra")
    assert result.extra.get("metadata") is not None


@pytest.mark.asyncio
@patch("openbb_core.app.logs.logging_service.LoggingService")
@patch("openbb_core.app.command_runner.ParametersBuilder.build")
@patch("openbb_core.app.command_runner.StaticCommandRunner._command")
@patch("openbb_core.app.command_runner.StaticCommandRunner._chart")
async def test_static_command_runner_execute_func(
    mock_chart,
    mock_command,
    mock_parameters_builder_build,
    mock_logging_service,
    execution_context,
    mock_func,
):
    """Test execute_func."""

    static_command_runner = StaticCommandRunner()

    mock_parameters_builder_build.return_value = {
        "a": 1,
        "b": 2,
        "c": 3.0,
        "d": 4,
        "provider_choices": {"provider": ["provider1", "provider2"]},
        "chart": True,
    }
    mock_logging_service.log.return_value = None
    mock_command.return_value = OBBject(
        results=[1, 2, 3, 4],
        provider="mock_provider",
        accessors={"charting": Mock()},  # type: ignore
    )
    mock_chart.return_value = None

    result = await static_command_runner._execute_func(
        "mock/route", (1, 2, 3, 4), execution_context, mock_func, {"chart": True}
    )

    assert result.results == [1, 2, 3, 4]
    mock_logging_service.assert_called_once()
    mock_parameters_builder_build.assert_called_once()
    mock_command.assert_called_once()
    mock_chart.assert_called_once()


def test_static_command_runner_chart():
    """``_chart`` invokes ``obbject.charting.show`` when the charting accessor is registered."""
    mock_charting = Mock()
    OBBject.accessors.add("charting")
    try:
        mock_obbject = OBBject(
            results=[
                {"date": "1990", "value": 100},
                {"date": "1991", "value": 200},
                {"date": "1992", "value": 300},
            ],
            provider="mock_provider",
        )
        # ``charting`` is a dynamic accessor — bypass Pydantic by writing through __dict__
        object.__setattr__(mock_obbject, "charting", mock_charting)

        StaticCommandRunner._chart(mock_obbject)

        mock_charting.show.assert_called_once_with(render=False)
    finally:
        OBBject.accessors.discard("charting")


def test_static_command_runner_chart_raises_when_charting_not_installed(monkeypatch):
    """``_chart`` raises ``OpenBBError`` when the charting accessor is not registered."""
    from openbb_core.app.charting.manager import ChartingManager
    from openbb_core.app.model.abstract.error import OpenBBError
    from openbb_core.env import Env

    # Resolve to an accessor guaranteed not registered, so the test is
    # deterministic whether or not a charting engine is installed.
    monkeypatch.setattr(
        ChartingManager,
        "accessor_name",
        classmethod(lambda cls: "not_a_charting_accessor"),
    )
    obbject = OBBject(results=[{"x": 1}], provider="mock_provider")

    # Force DEBUG_MODE so the suppressed exception is re-raised
    with (
        patch.object(Env, "DEBUG_MODE", new=True),
        pytest.raises(OpenBBError, match="No charting extension is installed"),
    ):
        StaticCommandRunner._chart(obbject)


@pytest.mark.asyncio
async def test_static_command_runner_command():
    """Test command."""

    class MockOBBject:
        """Mock OBBject"""

        def __init__(self, results, **kwargs):
            self.results = results
            self.extra = {}
            self.provider = kwargs.get("provider_choices").provider  # type: ignore

    class MockProviderChoices:
        """Mock ProviderChoices"""

        def __init__(self, provider):
            self.provider = provider

    def other_mock_func(**kwargs):
        return MockOBBject([1, 2, 3, 4], **kwargs)

    mock_provider_choices = MockProviderChoices(provider="mock_provider")

    result = await StaticCommandRunner._command(
        func=other_mock_func,
        kwargs={"provider_choices": mock_provider_choices},
    )

    assert result.results == [1, 2, 3, 4]
    assert result.provider == "mock_provider"


def test_extension_immutable_preserves_original_and_does_not_set_extension_modified(
    monkeypatch,
):
    """Immutable extensions must run against a copy and must not mutate the original OBBject."""
    monkeypatch.setattr(
        "openbb_core.app.service.system_service.SystemService",
        lambda: SimpleNamespace(
            system_settings=SimpleNamespace(
                allow_on_command_output=True, allow_mutable_extensions=False
            )
        ),
    )
    ext = Extension(name="imm_ext_test", on_command_output=True, immutable=True)

    def imm_accessor(self):
        # Mutate the (copied) obbject if called
        if isinstance(getattr(self, "results", None), list):
            self.results.append("modified_by_imm")

    # Attach accessor to OBBject class for binding on instances (monkeypatch will revert)
    monkeypatch.setattr(OBBject, ext.name, imm_accessor, raising=False)

    fake_loader = SimpleNamespace(on_command_output_callbacks={"*": [ext]})
    monkeypatch.setattr(
        "openbb_core.app.command_runner.ExtensionLoader", lambda: fake_loader
    )

    obb = OBBject(results=[1], provider="mock_provider")

    StaticCommandRunner._trigger_command_output_callbacks("any/route", obb)

    # original must remain unchanged
    assert obb.results == [1]
    # immutable extension should not mark the original as modified
    assert getattr(obb, "_extension_modified", False) is False


def test_extension_mutable_modifies_original_and_sets_extension_modified_and_route_scoping(
    monkeypatch,
):
    """Mutable extensions must modify the original OBBject and set the modification flag;
    registration must be route-scoped.
    """
    monkeypatch.setattr(
        "openbb_core.app.service.system_service.SystemService",
        lambda: SimpleNamespace(
            system_settings=SimpleNamespace(
                allow_mutable_extensions=True, allow_on_command_output=True
            )
        ),
    )
    ext = Extension(name="mut_ext_test", on_command_output=True, immutable=False)

    def mut_accessor(self):
        if isinstance(getattr(self, "results", None), list):
            self.results.append("modified_by_mut")

    monkeypatch.setattr(
        "openbb_core.app.model.obbject.OBBject.accessors",
        OBBject.accessors | {ext.name},
    )
    monkeypatch.setattr(
        OBBject, ext.name, CachedAccessor(ext.name, mut_accessor), raising=False
    )

    # register the extension only for "mock/route"
    fake_loader = SimpleNamespace(on_command_output_callbacks={"mock/route": [ext]})
    monkeypatch.setattr(
        "openbb_core.app.command_runner.ExtensionLoader", lambda: fake_loader
    )

    obb = OBBject(results=[], provider="mock_provider")

    # not executed for other routes
    StaticCommandRunner._trigger_command_output_callbacks("other/route", obb)
    assert obb.results == []

    # executed for the registered route and should mutate original
    StaticCommandRunner._trigger_command_output_callbacks("mock/route", obb)
    assert obb.results == ["modified_by_mut"]
    assert getattr(obb, "_extension_modified", False) is True


def test_results_only_flag_sets_attribute_and_accessor_runs(monkeypatch):
    """Extensions that declare results_only should toggle the _results_only attribute
    and still run their accessor.
    """
    monkeypatch.setattr(
        "openbb_core.app.service.system_service.SystemService",
        lambda: SimpleNamespace(
            system_settings=SimpleNamespace(
                allow_on_command_output=True, allow_mutable_extensions=False
            )
        ),
    )
    ext = Extension(
        name="ro_ext_test", on_command_output=True, results_only=True, immutable=True
    )

    called = {"hit": False}

    def ro_accessor(self):
        called["hit"] = True

    monkeypatch.setattr(
        "openbb_core.app.model.obbject.OBBject.accessors",
        OBBject.accessors | {ext.name},
    )
    monkeypatch.setattr(
        OBBject, ext.name, CachedAccessor(ext.name, ro_accessor), raising=False
    )

    fake_loader = SimpleNamespace(on_command_output_callbacks={"*": [ext]})
    monkeypatch.setattr(
        "openbb_core.app.command_runner.ExtensionLoader", lambda: fake_loader
    )

    obb = OBBject(results=[1, 2, 3], provider="mock_provider")

    StaticCommandRunner._trigger_command_output_callbacks("any/route", obb)

    # results_only attribute must be set on the output OBBject
    assert getattr(obb, "_results_only", False) is True
    # accessor should have been called (even if on a copy for immutable extensions)
    assert called["hit"] is True


def test_warn_kwargs_allows_chart_params_for_dataclass_extra_params():
    from openbb_core.app.provider_interface import ExtraParams

    @dataclass
    class Extras(ExtraParams):
        valid_field: str = ""

    class Model(BaseModel):
        model_config = ConfigDict(arbitrary_types_allowed=True)
        extra_params: Extras

    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ParametersBuilder._warn_kwargs({"chart_params": {}}, Model)
    assert not [w for w in caught if issubclass(w.category, OpenBBWarning)]


def test_extract_params_returns_dict_directly():
    out = StaticCommandRunner._extract_params(
        {"standard_params": {"a": 1}}, "standard_params"
    )
    assert out == {"a": 1}


def test_extract_params_with_object_having_dict():
    class P:
        def __init__(self):
            self.symbol = "AAPL"
            self.limit = 5

    out = StaticCommandRunner._extract_params({"extra_params": P()}, "extra_params")
    assert out == {"symbol": "AAPL", "limit": 5}


def test_extract_params_missing_key_returns_default_dict():
    out = StaticCommandRunner._extract_params({}, "standard_params")
    assert out == {}


def test_chart_merges_extra_params_chart_params():
    """``_chart`` should pull ``chart_params`` out of ``obbject._extra_params`` and pass them to ``charting.show``."""
    mock_charting = Mock()
    OBBject.accessors.add("charting")
    try:
        obb = OBBject(results=[{"x": 1}], provider="mock")
        object.__setattr__(obb, "charting", mock_charting)
        object.__setattr__(obb, "_extra_params", {"chart_params": {"title": "Hello"}})

        StaticCommandRunner._chart(obb)

        kwargs = mock_charting.show.call_args.kwargs
        assert kwargs["render"] is False
        assert kwargs["title"] == "Hello"
    finally:
        OBBject.accessors.discard("charting")


def test_chart_merges_top_level_chart_params_kwarg():
    """``chart_params`` passed as a kwarg should be flattened into the call."""
    mock_charting = Mock()
    OBBject.accessors.add("charting")
    try:
        obb = OBBject(results=[{"x": 1}], provider="mock")
        object.__setattr__(obb, "charting", mock_charting)

        StaticCommandRunner._chart(obb, chart_params={"theme": "dark"})

        kwargs = mock_charting.show.call_args.kwargs
        assert kwargs["theme"] == "dark"
    finally:
        OBBject.accessors.discard("charting")


def test_chart_merges_nested_kwargs_chart_params():
    """``kwargs['chart_params']`` (one level deep) should also be flattened."""
    mock_charting = Mock()
    OBBject.accessors.add("charting")
    try:
        obb = OBBject(results=[{"x": 1}], provider="mock")
        object.__setattr__(obb, "charting", mock_charting)

        StaticCommandRunner._chart(obb, kwargs={"chart_params": {"width": 800}})

        kwargs = mock_charting.show.call_args.kwargs
        assert kwargs["width"] == 800
    finally:
        OBBject.accessors.discard("charting")


def test_chart_warns_in_non_debug_mode_on_failure(monkeypatch):
    """Without DEBUG_MODE, a chart failure should be downgraded to an OpenBBWarning."""
    from openbb_core.app.charting.manager import ChartingManager

    monkeypatch.setattr(
        ChartingManager,
        "accessor_name",
        classmethod(lambda cls: "not_a_charting_accessor"),
    )
    obb = OBBject(results=[{"x": 1}], provider="mock")
    with pytest.warns(OpenBBWarning, match="No charting extension is installed"):
        StaticCommandRunner._chart(obb)


class _APIRouteWithDep:
    def __init__(self):
        def get_user_id():
            return "u1"

        class Dep:
            dependency = staticmethod(get_user_id)

        self.dependencies = [Dep()]
        self.openapi_extra = {}


class _Ctx(ExecutionContext):
    def __init__(self, user, system, route="mock/route"):
        super().__init__(CommandMap(), route, system, user)
        self._api_route = _APIRouteWithDep()

    @property
    def api_route(self):
        return self._api_route


@pytest.mark.asyncio
async def test_run_populates_metadata_and_strips_dependencies():
    """Lines 446-475: metadata enabled -> Metadata wrapped, dep keys stripped."""
    user = UserSettings()
    user.preferences.metadata = True
    sys_ = SystemSettings(logging_suppress=True)
    ctx = _Ctx(user, sys_)

    obb = OBBject(results=[{"x": 1}], provider="p")
    object.__setattr__(obb, "_extra_params", {"user_id": "abc", "limit": 5})

    async def _fake_execute(**_kwargs):
        return obb

    with (
        patch.object(
            StaticCommandRunner, "_execute_func", new=AsyncMock(return_value=obb)
        ),
        patch.object(CommandMap, "get_command", return_value=lambda: None),
    ):
        result = await StaticCommandRunner.run(ctx)

    assert result is obb
    assert "metadata" in result.extra
    # dependency key 'user_id' must be removed from _extra_params
    assert "user_id" not in result._extra_params  # type: ignore


@pytest.mark.asyncio
async def test_run_callback_strips_callable_arguments():
    """Lines 499-502: callable / falsy values in arguments are removed."""
    user = UserSettings()
    user.preferences.metadata = True
    sys_ = SystemSettings(logging_suppress=True)
    ctx = _Ctx(user, sys_)

    obb = OBBject(results=[{"x": 1}], provider="p")
    object.__setattr__(obb, "_extra_params", {})

    async def _fake_execute(**_kwargs):
        return obb

    with (
        patch.object(
            StaticCommandRunner, "_execute_func", new=AsyncMock(return_value=obb)
        ),
        patch.object(CommandMap, "get_command", return_value=lambda: None),
    ):
        await StaticCommandRunner.run(ctx, fn=lambda: None, empty="")
    # fn (callable) and empty (falsy) should be stripped from extra_params if metadata exists
    args = obb.extra["metadata"].arguments
    assert "fn" not in args.get("extra_params", {})
    assert "empty" not in args.get("extra_params", {})


@pytest.mark.asyncio
async def test_run_invalid_route_raises_attribute_error():
    user = UserSettings()
    sys_ = SystemSettings(logging_suppress=True)
    ctx = _Ctx(user, sys_, route="does/not/exist")
    with (
        patch.object(CommandMap, "get_command", return_value=None),
        pytest.raises(AttributeError, match="Invalid command"),
    ):
        await StaticCommandRunner.run(ctx)


@pytest.mark.asyncio
async def test_execute_func_merges_inner_kwargs_into_validated_kwargs(monkeypatch):
    user = UserSettings()
    sys_ = SystemSettings(logging_suppress=True)
    ctx = _Ctx(user, sys_)

    def my_endpoint(**kwargs):
        return kwargs

    monkeypatch.setattr(
        ParametersBuilder,
        "build",
        staticmethod(lambda **_k: {"a": 1}),
    )

    obb = OBBject(results=[{"x": 1}], provider="p")
    with patch.object(StaticCommandRunner, "_command", new=AsyncMock(return_value=obb)):
        out = await StaticCommandRunner._execute_func(
            route="mock/route",
            args=(),
            execution_context=ctx,
            func=my_endpoint,
            kwargs={"kwargs": {"extra_flag": True}},
        )

    assert out._extra_params.get("extra_flag") is True  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_execute_func_chart_restores_kwargs_into_extra_params(monkeypatch):
    user = UserSettings()
    sys_ = SystemSettings(logging_suppress=True)
    ctx = _Ctx(user, sys_)

    def my_endpoint(**kwargs):
        return kwargs

    monkeypatch.setattr(
        ParametersBuilder,
        "build",
        staticmethod(lambda **_k: {"extra_params": {"existing": 1}}),
    )

    obb = OBBject(results=[{"x": 1}], provider="p")
    captured = {}

    def _fake_chart(_obb, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(StaticCommandRunner, "_chart", staticmethod(_fake_chart))

    with patch.object(StaticCommandRunner, "_command", new=AsyncMock(return_value=obb)):
        await StaticCommandRunner._execute_func(
            route="mock/route",
            args=(),
            execution_context=ctx,
            func=my_endpoint,
            kwargs={"chart": True, "outside": "v"},
        )

    assert "chart" not in captured
    assert captured["extra_params"]["outside"] == "v"


@pytest.mark.asyncio
async def test_execute_func_collects_and_shows_warnings(monkeypatch):
    user = UserSettings()
    user.preferences.show_warnings = True
    sys_ = SystemSettings(logging_suppress=True)
    ctx = _Ctx(user, sys_)

    def my_endpoint(**kwargs):
        return kwargs

    monkeypatch.setattr(ParametersBuilder, "build", staticmethod(lambda **_k: {}))

    obb = OBBject(results=[{"x": 1}], provider="p")

    async def _warn_and_return(*_args, **_kwargs):
        warnings.warn("warn-me", OpenBBWarning)
        return obb

    shown = {"count": 0}

    def _fake_showwarning(**_kwargs):
        shown["count"] += 1

    monkeypatch.setattr("openbb_core.app.command_runner.showwarning", _fake_showwarning)

    with patch.object(StaticCommandRunner, "_command", new=_warn_and_return):
        out = await StaticCommandRunner._execute_func(
            route="mock/route",
            args=(),
            execution_context=ctx,
            func=my_endpoint,
            kwargs={},
        )

    assert out.warnings
    assert shown["count"] >= 1


@pytest.mark.asyncio
async def test_run_metadata_assignment_failure_warns_when_not_debug(monkeypatch):
    from openbb_core.env import Env

    user = UserSettings()
    user.preferences.metadata = True
    sys_ = SystemSettings(logging_suppress=True)
    ctx = _Ctx(user, sys_)

    obb = OBBject(results=[{"x": 1}], provider="p")

    class _BadExtra(dict):
        def __setitem__(self, key, value):  # noqa: ARG002
            raise TypeError("cannot set")

    object.__setattr__(obb, "extra", _BadExtra())

    monkeypatch.setattr(CommandMap, "get_command", lambda *_a, **_k: lambda: None)
    monkeypatch.setattr(
        StaticCommandRunner, "_execute_func", AsyncMock(return_value=obb)
    )
    monkeypatch.setattr(Env, "DEBUG_MODE", False)

    with pytest.warns(OpenBBWarning):
        out = await StaticCommandRunner.run(ctx)

    assert out is obb


@pytest.mark.asyncio
async def test_run_populates_metadata_from_nested_kwargs_and_warns_on_callback_error(
    monkeypatch,
):
    user = UserSettings()
    user.preferences.metadata = True
    sys_ = SystemSettings(logging_suppress=True)
    ctx = _Ctx(user, sys_)

    obb = OBBject(results=[{"x": 1}], provider="p")
    object.__setattr__(obb, "_extra_params", {})

    monkeypatch.setattr(CommandMap, "get_command", lambda *_a, **_k: lambda: None)
    monkeypatch.setattr(
        StaticCommandRunner, "_execute_func", AsyncMock(return_value=obb)
    )

    def _boom(*_a, **_k):
        raise RuntimeError("cb-boom")

    monkeypatch.setattr(
        StaticCommandRunner, "_trigger_command_output_callbacks", staticmethod(_boom)
    )

    with pytest.warns(OpenBBWarning):
        out = await StaticCommandRunner.run(ctx, kwargs={"alpha": 1})

    meta = out.extra["metadata"].arguments
    assert meta["extra_params"].get("alpha") == 1


@pytest.mark.asyncio
async def test_command_runner_run_delegates_to_static_runner(monkeypatch):
    runner = CommandRunner(
        command_map=CommandMap(),
        system_settings=SystemSettings(logging_suppress=True),
        user_settings=UserSettings(),
    )

    expected = OBBject(results=[{"ok": True}], provider="p")

    async def _fake_run(ctx, *args, **kwargs):
        assert ctx.route == "mock/route"
        return expected

    monkeypatch.setattr(StaticCommandRunner, "run", _fake_run)
    out = await runner.run("mock/route")
    assert out is expected


def test_command_runner_sync_run_uses_run_async(monkeypatch):
    runner = CommandRunner(
        command_map=CommandMap(),
        system_settings=SystemSettings(logging_suppress=True),
        user_settings=UserSettings(),
    )

    expected = OBBject(results=[{"ok": True}], provider="p")

    def _fake_run_async(func, route, user_settings, *args, **kwargs):
        assert route == "mock/route"
        return expected

    monkeypatch.setattr("openbb_core.app.command_runner.run_async", _fake_run_async)
    out = runner.sync_run("mock/route")
    assert out is expected


def test_command_runner_init_logging_service(monkeypatch):
    runner = CommandRunner(
        command_map=CommandMap(),
        system_settings=SystemSettings(logging_suppress=True),
        user_settings=UserSettings(),
    )

    called = {"ok": False}

    class _LS:
        def __init__(self, system_settings=None, user_settings=None):
            called["ok"] = system_settings is not None and user_settings is not None

    monkeypatch.setattr("openbb_core.app.logs.logging_service.LoggingService", _LS)
    runner.init_logging_service()
    assert called["ok"] is True


def test_trigger_callbacks_skips_non_cached_accessor(
    monkeypatch, allow_command_output_extensions
):
    from types import SimpleNamespace

    from openbb_core.app.model.extension import Extension

    ext = Extension(name="plain_attr_ext", on_command_output=True, immutable=False)
    fake_loader = SimpleNamespace(on_command_output_callbacks={"*": [ext]})
    monkeypatch.setattr(
        "openbb_core.app.command_runner.ExtensionLoader", lambda: fake_loader
    )
    monkeypatch.setattr(
        "openbb_core.app.model.obbject.OBBject.accessors",
        OBBject.accessors | {ext.name},
    )
    monkeypatch.setattr(OBBject, ext.name, object(), raising=False)

    obb = OBBject(results=[1], provider="p")
    StaticCommandRunner._trigger_command_output_callbacks("mock/route", obb)


def test_trigger_callbacks_runs_callable_result(
    monkeypatch, allow_command_output_extensions
):
    from types import SimpleNamespace

    from openbb_core.app.model.extension import CachedAccessor, Extension

    ext = Extension(name="callable_result_ext", on_command_output=True, immutable=False)
    fake_loader = SimpleNamespace(on_command_output_callbacks={"*": [ext]})
    monkeypatch.setattr(
        "openbb_core.app.command_runner.ExtensionLoader", lambda: fake_loader
    )
    monkeypatch.setattr(
        "openbb_core.app.model.obbject.OBBject.accessors",
        OBBject.accessors | {ext.name},
    )

    hit = {"called": False}

    def _factory(_obb):
        def _inner():
            hit["called"] = True

        return _inner

    monkeypatch.setattr(
        OBBject, ext.name, CachedAccessor(ext.name, _factory), raising=False
    )

    obb = OBBject(results=[1], provider="p")
    StaticCommandRunner._trigger_command_output_callbacks("mock/route", obb)
    assert hit["called"] is True


def test_command_runner_user_settings_setter():
    runner = CommandRunner(
        command_map=CommandMap(),
        system_settings=SystemSettings(logging_suppress=True),
        user_settings=UserSettings(),
    )
    new_user = UserSettings()
    runner.user_settings = new_user
    assert runner.user_settings is new_user


def test_trigger_callbacks_identifier_and_import_path_key_paths(
    monkeypatch, allow_command_output_extensions
):
    from types import SimpleNamespace

    from openbb_core.app.model.extension import Extension

    ext1 = Extension(name="k1", on_command_output=True, immutable=False)
    ext1.identifier = "id-1"
    ext2 = Extension(name="k2", on_command_output=True, immutable=False)
    ext2.import_path = "pkg.mod"
    fake_loader = SimpleNamespace(on_command_output_callbacks={"*": [ext1, ext2]})
    monkeypatch.setattr(
        "openbb_core.app.command_runner.ExtensionLoader", lambda: fake_loader
    )

    obb = OBBject(results=[1], provider="p")
    StaticCommandRunner._trigger_command_output_callbacks("mock/route", obb)


def test_trigger_callbacks_immutable_clone_failure_warns(
    monkeypatch, allow_command_output_extensions
):
    from types import SimpleNamespace

    from openbb_core.app.model.extension import CachedAccessor, Extension

    ext = Extension(name="imm_fail_ext", on_command_output=True, immutable=True)
    fake_loader = SimpleNamespace(on_command_output_callbacks={"*": [ext]})
    monkeypatch.setattr(
        "openbb_core.app.command_runner.ExtensionLoader", lambda: fake_loader
    )
    monkeypatch.setattr(
        "openbb_core.app.model.obbject.OBBject.accessors",
        OBBject.accessors | {ext.name},
    )

    def _factory(_obb):
        return None

    monkeypatch.setattr(
        OBBject, ext.name, CachedAccessor(ext.name, _factory), raising=False
    )

    def _boom(*_args, **_kwargs):
        raise ValueError("clone boom")

    monkeypatch.setattr(OBBject, "model_copy", _boom)

    obb = OBBject(results=[1], provider="p")
    with pytest.warns(OpenBBWarning, match="could not be duplicated"):
        StaticCommandRunner._trigger_command_output_callbacks("mock/route", obb)


def test_trigger_callbacks_command_output_paths_skip(
    monkeypatch, allow_command_output_extensions
):
    from types import SimpleNamespace

    from openbb_core.app.model.extension import CachedAccessor, Extension

    ext = Extension(name="path_scoped_ext", on_command_output=True, immutable=False)
    ext.command_output_paths = ["other/route"]
    fake_loader = SimpleNamespace(on_command_output_callbacks={"*": [ext]})
    monkeypatch.setattr(
        "openbb_core.app.command_runner.ExtensionLoader", lambda: fake_loader
    )
    monkeypatch.setattr(
        "openbb_core.app.model.obbject.OBBject.accessors",
        OBBject.accessors | {ext.name},
    )

    called = {"ok": False}

    def _factory(_obb):
        called["ok"] = True

    monkeypatch.setattr(
        OBBject, ext.name, CachedAccessor(ext.name, _factory), raising=False
    )

    obb = OBBject(results=[1], provider="p")
    StaticCommandRunner._trigger_command_output_callbacks("mock/route", obb)
    assert called["ok"] is False


def test_trigger_callbacks_async_factory_path(
    monkeypatch, allow_command_output_extensions
):
    from types import SimpleNamespace

    from openbb_core.app.model.extension import CachedAccessor, Extension

    ext = Extension(name="async_ext", on_command_output=True, immutable=False)
    fake_loader = SimpleNamespace(on_command_output_callbacks={"*": [ext]})
    monkeypatch.setattr(
        "openbb_core.app.command_runner.ExtensionLoader", lambda: fake_loader
    )
    monkeypatch.setattr(
        "openbb_core.app.model.obbject.OBBject.accessors",
        OBBject.accessors | {ext.name},
    )

    async def _factory(_obb):
        return None

    called = {"ok": False}

    def _fake_run_async(func, arg):
        called["ok"] = True

    monkeypatch.setattr("openbb_core.app.command_runner.run_async", _fake_run_async)
    monkeypatch.setattr(
        OBBject, ext.name, CachedAccessor(ext.name, _factory), raising=False
    )

    obb = OBBject(results=[1], provider="p")
    StaticCommandRunner._trigger_command_output_callbacks("mock/route", obb)
    assert called["ok"] is True


def test_trigger_callbacks_factory_exception_raises_openbb_error(
    monkeypatch, allow_command_output_extensions
):
    from types import SimpleNamespace

    from openbb_core.app.model.abstract.error import OpenBBError
    from openbb_core.app.model.extension import CachedAccessor, Extension

    ext = Extension(name="boom_ext", on_command_output=True, immutable=False)
    fake_loader = SimpleNamespace(on_command_output_callbacks={"*": [ext]})
    monkeypatch.setattr(
        "openbb_core.app.command_runner.ExtensionLoader", lambda: fake_loader
    )
    monkeypatch.setattr(
        "openbb_core.app.model.obbject.OBBject.accessors",
        OBBject.accessors | {ext.name},
    )

    def _factory(_obb):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        OBBject, ext.name, CachedAccessor(ext.name, _factory), raising=False
    )

    obb = OBBject(results=[1], provider="p")
    with pytest.raises(OpenBBError):
        StaticCommandRunner._trigger_command_output_callbacks("mock/route", obb)


def test_execution_context_api_route_property_access(monkeypatch):
    """Test ExecutionContext.api_route accesses _route_map[self.route]."""
    from unittest.mock import MagicMock

    mock_route = MagicMock()
    route_map = {"/test/path": mock_route}
    monkeypatch.setattr(ExecutionContext, "_route_map", route_map)

    ctx = ExecutionContext(
        command_map=MagicMock(),
        route="/test/path",
        system_settings=MagicMock(),
        user_settings=MagicMock(),
    )
    assert ctx.api_route is mock_route


def test_merge_args_and_kwargs_converts_non_dict_kwargs_field():
    def endpoint(a, **kwargs):
        return None

    merged = ParametersBuilder.merge_args_and_kwargs(
        endpoint,
        args=(),
        kwargs={"a": 1, "kwargs": [("x", 2)], "y": 3},
    )

    assert merged["a"] == 1
    assert merged["x"] == 2
    assert merged["y"] == 3
    assert "kwargs" not in merged


def test_validate_kwargs_skips_var_keyword_parameter():
    def endpoint(a: int, **kwargs):
        return None

    out = ParametersBuilder.validate_kwargs(endpoint, {"a": "5", "extra": 9})

    assert out["a"] == 5
    assert out["extra"] == 9


@pytest.mark.asyncio
async def test_execute_func_chart_removes_chart_kwarg(monkeypatch):
    user = UserSettings()
    sys_ = SystemSettings(logging_suppress=True)
    ctx = _Ctx(user, sys_)

    def my_endpoint(**kwargs):
        return kwargs

    monkeypatch.setattr(ParametersBuilder, "build", staticmethod(lambda **_k: {}))

    obb = OBBject(results=[{"x": 1}], provider="p")
    captured = {}

    def _fake_chart(_obb, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(StaticCommandRunner, "_chart", staticmethod(_fake_chart))

    with patch.object(StaticCommandRunner, "_command", new=AsyncMock(return_value=obb)):

        class _NoPopChartDict(dict):
            def pop(self, key, default=None):
                if key == "chart":
                    return self.get(key, default)
                return super().pop(key, default)

        await StaticCommandRunner._execute_func(
            route="mock/route",
            args=(),
            execution_context=ctx,
            func=my_endpoint,
            kwargs=_NoPopChartDict({"chart": True, "outside": "v"}),
        )

    assert captured["chart"] is True
    assert captured["extra_params"]["outside"] == "v"


@pytest.mark.asyncio
async def test_run_metadata_assignment_failure_raises_when_debug(monkeypatch):
    from openbb_core.app.model.abstract.error import OpenBBError

    user = UserSettings()
    user.preferences.metadata = True
    sys_ = SystemSettings(logging_suppress=True)
    ctx = _Ctx(user, sys_)

    obb = OBBject(results=[{"x": 1}], provider="p")

    class _BadExtra(dict):
        def __setitem__(self, key, value):
            raise TypeError("cannot set")

    object.__setattr__(obb, "extra", _BadExtra())

    monkeypatch.setattr(CommandMap, "get_command", lambda *_a, **_k: lambda: None)
    monkeypatch.setattr(
        StaticCommandRunner, "_execute_func", AsyncMock(return_value=obb)
    )
    monkeypatch.setattr(
        "openbb_core.app.command_runner.Env",
        type("E", (), {"DEBUG_MODE": True}),
    )

    with pytest.raises(OpenBBError):
        await StaticCommandRunner.run(ctx)


@pytest.mark.asyncio
async def test_run_callback_failure_raises_when_debug(monkeypatch):
    from openbb_core.app.model.abstract.error import OpenBBError

    user = UserSettings()
    user.preferences.metadata = False
    sys_ = SystemSettings(logging_suppress=True)
    ctx = _Ctx(user, sys_)

    obb = OBBject(results=[{"x": 1}], provider="p")

    monkeypatch.setattr(CommandMap, "get_command", lambda *_a, **_k: lambda: None)
    monkeypatch.setattr(
        StaticCommandRunner, "_execute_func", AsyncMock(return_value=obb)
    )

    def _boom(*_a, **_k):
        raise RuntimeError("cb-boom")

    monkeypatch.setattr(
        StaticCommandRunner, "_trigger_command_output_callbacks", staticmethod(_boom)
    )
    monkeypatch.setattr(
        "openbb_core.app.command_runner.Env",
        type("E", (), {"DEBUG_MODE": True}),
    )

    with pytest.raises(OpenBBError):
        await StaticCommandRunner.run(ctx)


@pytest.mark.asyncio
async def test_run_metadata_cleanup_skips_non_dict_and_removes_unjsonable(monkeypatch):
    from types import SimpleNamespace

    user = UserSettings()
    user.preferences.metadata = False
    sys_ = SystemSettings(logging_suppress=True)
    ctx = _Ctx(user, sys_)

    bad_value = object()
    metadata_obj = SimpleNamespace(
        arguments={
            "standard_params": "not_a_dict",
            "extra_params": {"bad": bad_value, "ok": 1},
            "provider_choices": {},
        }
    )

    obb = OBBject(results=[{"x": 1}], provider="p")
    obb.extra["metadata"] = metadata_obj

    monkeypatch.setattr(CommandMap, "get_command", lambda *_a, **_k: lambda: None)
    monkeypatch.setattr(
        StaticCommandRunner, "_execute_func", AsyncMock(return_value=obb)
    )
    monkeypatch.setattr(
        StaticCommandRunner,
        "_trigger_command_output_callbacks",
        staticmethod(lambda *_a, **_k: None),
    )

    def _fake_jsonable_encoder(value):
        if value is bad_value:
            raise TypeError("nope")
        return value

    monkeypatch.setattr(
        "openbb_core.app.command_runner.jsonable_encoder",
        _fake_jsonable_encoder,
    )

    out = await StaticCommandRunner.run(ctx)
    assert "bad" not in out.extra["metadata"].arguments["extra_params"]
    assert out.extra["metadata"].arguments["extra_params"]["ok"] == 1


def test_provider_loop_is_one_per_provider():
    """Each provider gets one running loop; the openbb_ package prefix is ignored."""
    from openbb_core.app.command_runner import _provider_loop

    assert _provider_loop("loop_a") is _provider_loop("openbb_loop_a")
    assert _provider_loop("loop_a") is not _provider_loop("loop_b")
    assert _provider_loop("loop_a").is_running()


def test_static_command_runner_command_runs_on_the_provider_loop():
    """A provider's commands share one loop, never the caller's."""
    import asyncio

    async def which_loop(**kwargs):
        return asyncio.get_running_loop()

    which_loop.__module__ = "openbb_loopcheck.router"

    async def main():
        first = await StaticCommandRunner._command(which_loop, {})
        second = await StaticCommandRunner._command(which_loop, {})
        return asyncio.get_running_loop(), first, second

    caller, first, second = asyncio.run(main())
    assert first is second
    assert first is not caller


def test_static_command_runner_command_uses_provider_choices():
    """The provider in provider_choices picks the loop."""
    import asyncio

    from openbb_core.app.command_runner import _provider_loop

    async def which_loop(**kwargs):
        return asyncio.get_running_loop()

    which_loop.__module__ = "openbb_router_package.router"
    kwargs = {"provider_choices": SimpleNamespace(provider="chosen_provider")}

    loop = asyncio.run(StaticCommandRunner._command(which_loop, kwargs))
    assert loop is _provider_loop("chosen_provider")


def test_static_command_runner_blocking_command_blocks_only_its_provider():
    """A CPU-bound command no longer freezes other providers or the caller's loop."""
    import asyncio
    import time

    def slow(**kwargs):
        time.sleep(0.6)
        return "slow"

    slow.__module__ = "openbb_slow_provider.router"

    async def fast(**kwargs):
        return "fast"

    fast.__module__ = "openbb_fast_provider.router"

    async def main():
        started = time.perf_counter()
        slow_task = asyncio.ensure_future(StaticCommandRunner._command(slow, {}))
        await asyncio.sleep(0.05)
        assert await StaticCommandRunner._command(fast, {}) == "fast"
        fast_done = time.perf_counter() - started
        await asyncio.sleep(0.05)
        caller_done = time.perf_counter() - started
        assert await slow_task == "slow"
        return fast_done, caller_done

    fast_done, caller_done = asyncio.run(main())
    assert fast_done < 0.4
    assert caller_done < 0.5
