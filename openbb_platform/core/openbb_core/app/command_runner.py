"""Command runner module."""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict, is_dataclass
from datetime import datetime
from inspect import Parameter, iscoroutinefunction, signature
from sys import exc_info
from time import perf_counter_ns
from typing import TYPE_CHECKING, Any, Optional
from warnings import catch_warnings, showwarning, warn

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, create_model

from openbb_core.app.extension_loader import ExtensionLoader
from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.app.model.abstract.warning import OpenBBWarning, cast_warning
from openbb_core.app.model.extension import CachedAccessor
from openbb_core.app.model.metadata import Metadata
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.model.stream import OBBStream
from openbb_core.app.provider_interface import ExtraParams
from openbb_core.app.static.package_builder import PathHandler
from openbb_core.env import Env
from openbb_core.provider.utils.helpers import maybe_coroutine, run_async, to_snake_case

if TYPE_CHECKING:
    from fastapi.routing import APIRoute

    from openbb_core.app.model.system_settings import SystemSettings
    from openbb_core.app.model.user_settings import UserSettings
    from openbb_core.app.router import CommandMap


class ExecutionContext:
    """Execution context."""

    # For checking if the command specifies no validation in the API Route
    _route_map = PathHandler.build_route_map()

    def __init__(
        self,
        command_map: "CommandMap",
        route: str,
        system_settings: "SystemSettings",
        user_settings: "UserSettings",
    ) -> None:
        """Initialize the execution context."""
        self.command_map = command_map
        self.route = route
        self.system_settings = system_settings
        self.user_settings = user_settings

    @property
    def api_route(self) -> "APIRoute":
        """API route."""
        return self._route_map[self.route]  # type: ignore


class ParametersBuilder:
    """Build parameters for a function."""

    @staticmethod
    def get_polished_parameter_list(func: Callable) -> list[Parameter]:
        """Get the signature parameters values as a list."""
        sig = signature(func)
        parameter_list = list(sig.parameters.values())

        return parameter_list

    @staticmethod
    def get_polished_func(func: Callable) -> Callable:
        """Remove __authenticated_user_settings from the function signature and annotations."""
        func = deepcopy(func)
        sig = signature(func)
        parameter_map = dict(sig.parameters)

        if "__authenticated_user_settings" in parameter_map:
            parameter_map.pop("__authenticated_user_settings")

        parameter_list = list(parameter_map.values())
        new_signature = signature(func).replace(parameters=parameter_list)

        func.__signature__ = new_signature  # type: ignore
        func.__annotations__ = parameter_map

        return func

    @classmethod
    def merge_args_and_kwargs(
        cls,
        func: Callable,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge args and kwargs into a single dict."""
        args = deepcopy(args)
        kwargs_copy = deepcopy(kwargs)
        parameter_list = cls.get_polished_parameter_list(func=func)
        parameter_map = {}

        for index, parameter in enumerate(parameter_list):
            if index < len(args):
                parameter_map[parameter.name] = args[index]
            elif parameter.name in kwargs:
                parameter_map[parameter.name] = kwargs[parameter.name]
            elif parameter.default is not parameter.empty:
                parameter_map[parameter.name] = parameter.default
            else:
                parameter_map[parameter.name] = None

        if "kwargs" in parameter_map:
            merged_kwargs = parameter_map.get("kwargs") or {}
            if not isinstance(merged_kwargs, dict):
                merged_kwargs = dict(merged_kwargs)

            for key, value in kwargs_copy.items():
                if key in {"filter_query", "kwargs"} or key in parameter_map:
                    continue
                merged_kwargs[key] = value

            parameter_map.update(merged_kwargs)
            parameter_map.pop("kwargs", None)

        return parameter_map

    @staticmethod
    def update_command_context(
        func: Callable,
        kwargs: dict[str, Any],
        system_settings: "SystemSettings",
        user_settings: "UserSettings",
    ) -> dict[str, Any]:
        """Update the command context with the available user and system settings."""
        from openbb_core.app.model.command_context import CommandContext

        argcount = func.__code__.co_argcount  # ty: ignore[unresolved-attribute]
        if (
            "cc" in func.__code__.co_varnames[:argcount]  # ty: ignore[unresolved-attribute]
        ):
            kwargs["cc"] = CommandContext(
                user_settings=user_settings,
                system_settings=system_settings,
            )

        return kwargs

    @staticmethod
    def _warn_kwargs(
        extra_params: dict[str, Any],
        model: type[BaseModel],
    ) -> None:
        """Warn if kwargs received and ignored by the validation model."""
        # We only check the extra_params annotation because ignored fields
        # will always be there
        fields = (model if isinstance(model, type) else type(model)).model_fields
        annotation = getattr(fields.get("extra_params", None), "annotation", None)
        if is_dataclass(annotation) and any(
            t is ExtraParams for t in getattr(annotation, "__bases__", [])
        ):
            valid = asdict(annotation())
            for p in extra_params:
                if "chart_params" in p:
                    continue
                if p not in valid:
                    warn(
                        message=f"Parameter '{p}' not found.",
                        category=OpenBBWarning,
                    )

    @staticmethod
    def _as_dict(obj: Any) -> dict[str, Any]:
        """Safely convert an object to a dict."""
        try:
            if isinstance(obj, dict):
                return obj
            return asdict(obj) if is_dataclass(obj) else dict(obj)
        except Exception:
            return {}

    @staticmethod
    def validate_kwargs(
        func: Callable,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate kwargs and if possible coerce to the correct type."""
        sig = signature(func)
        fields: dict[str, tuple[Any, Any]] = {}
        for name, param in sig.parameters.items():
            if param.kind is Parameter.VAR_KEYWORD:
                continue
            annotation = (
                Any if param.annotation is Parameter.empty else param.annotation
            )
            default = ... if param.default is Parameter.empty else param.default
            fields[name] = (annotation, default)
        # We allow extra fields to return with model with 'cc: CommandContext'
        config = ConfigDict(extra="allow", arbitrary_types_allowed=True)
        ValidationModel = create_model(func.__name__, __config__=config, **fields)  # type: ignore
        # Validate and coerce
        model = ValidationModel(**kwargs)
        ParametersBuilder._warn_kwargs(
            ParametersBuilder._as_dict(kwargs.get("extra_params", {})),
            ValidationModel,
        )
        return dict(model)

    @classmethod
    def build(
        cls,
        args: tuple[Any, ...],
        execution_context: ExecutionContext,
        func: Callable,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the parameters for a function."""
        func = cls.get_polished_func(func=func)
        system_settings = execution_context.system_settings
        user_settings = execution_context.user_settings
        kwargs = cls.merge_args_and_kwargs(
            func=func,
            args=args,
            kwargs=kwargs,
        )
        kwargs = cls.update_command_context(
            func=func,
            kwargs=kwargs,
            system_settings=system_settings,
            user_settings=user_settings,
        )
        kwargs = cls.validate_kwargs(
            func=func,
            kwargs=kwargs,
        )
        return kwargs


class StaticCommandRunner:
    """Static Command Runner."""

    @classmethod
    async def _command(
        cls,
        func: Callable,
        kwargs: dict[str, Any],
        show_warnings: bool = True,
    ) -> OBBject:
        """Run a command and return the output."""
        obbject = await maybe_coroutine(func, **kwargs)
        if isinstance(obbject, (OBBject, OBBStream)):
            obbject.provider = getattr(
                kwargs.get("provider_choices"),
                "provider",
                getattr(obbject, "provider", None),
            )
        return obbject

    @classmethod
    def _chart(
        cls,
        obbject: OBBject,
        **kwargs,
    ) -> None:
        """Create a chart from the command output."""
        from openbb_core.app.charting import ChartingManager

        try:
            accessor = ChartingManager.accessor_name()
            if accessor not in obbject.accessors:
                raise OpenBBError(
                    "No charting extension is installed. Install `openbb-charting`"
                    " or set `system_settings.charting_extension` to your engine."
                )
            # Here we will pop the chart_params kwargs and flatten them into the kwargs.
            chart_params = {}
            extra_params = getattr(obbject, "_extra_params", {})

            if extra_params and "chart_params" in extra_params:
                chart_params = extra_params.get("chart_params", {})

            if kwargs.get("chart_params"):
                chart_params.update(kwargs.pop("chart_params", {}))
            # Verify that kwargs is not nested as kwargs so we don't miss any chart params.
            if (
                "kwargs" in kwargs
                and "chart_params" in kwargs["kwargs"]
                and kwargs["kwargs"].get("chart_params")
            ):
                chart_params.update(kwargs.pop("kwargs", {}).get("chart_params", {}))

            if chart_params:
                kwargs.update(chart_params)

            getattr(obbject, accessor).show(render=False, **kwargs)
        except Exception as e:
            if Env().DEBUG_MODE:
                raise OpenBBError(e) from e
            warn(str(e), OpenBBWarning)

    @classmethod
    def _extract_params(cls, kwargs, key) -> dict:
        """Extract params models from kwargs and convert to a dictionary."""
        params = kwargs.get(key, {})
        if hasattr(params, "__dict__"):
            return params.__dict__
        return params

    @classmethod
    async def _execute_func(
        cls,
        route: str,
        args: tuple[Any, ...],
        execution_context: ExecutionContext,
        func: Callable,
        kwargs: dict[str, Any],
    ) -> OBBject:
        """Execute a function and return the output."""
        user_settings = execution_context.user_settings
        system_settings = execution_context.system_settings
        raised_warnings: list = []
        custom_headers: dict[str, Any] | None = None

        try:
            with catch_warnings(record=True) as warning_list:
                # If we're on Jupyter we need to pop here because we will lose "chart" after
                # ParametersBuilder.build. This needs to be fixed in a way that chart is
                # added to the function signature and shared for jupyter and api
                # We can check in the router decorator if the given function has a chart
                # in the charting extension then we add it there. This way we can remove
                # the chart parameter from the commands.py and package_builder, it will be
                # added to the function signature in the router decorator
                # If the ProviderInterface is not in use, we need to pass a copy of the
                # kwargs dictionary before it is validated, otherwise we lose those items.
                chart = kwargs.pop("chart", False)
                kwargs_copy = deepcopy(kwargs)
                kwargs = ParametersBuilder.build(
                    args=args,
                    execution_context=execution_context,
                    func=func,
                    kwargs=kwargs,
                )
                kwargs = kwargs if kwargs is not None else {}
                # If **kwargs is in the function signature, we need to make sure to pass
                # All kwargs to the function so dependency injection happens
                # and kwargs are actually made available as locals within the function.
                if "kwargs" in kwargs_copy:
                    for k, v in kwargs_copy["kwargs"].items():
                        if k not in kwargs:
                            kwargs[k] = v
                # If we're on the api we need to remove "chart" here because the parameter is added on
                # commands.py and the function signature does not expect "chart"
                kwargs.pop("chart", None)
                # We also pop custom headers
                model_headers = system_settings.api_settings.custom_headers or {}
                custom_headers = {
                    name: kwargs.pop(name.replace("-", "_"), default)
                    for name, default in model_headers.items() or {}
                } or None

                obbject = await cls._command(func, kwargs)
                # The output might be from a router command with 'no_validate=True'
                # It might be of a different type than OBBject.
                # In this case, we avoid accessing those attributes.
                if isinstance(obbject, OBBject):
                    # This section prepares the obbject to pass to the charting service.
                    obbject._route = route
                    std_params = cls._extract_params(kwargs, "standard_params") or (
                        kwargs if "data" in kwargs else {}
                    )
                    extra_params = cls._extract_params(kwargs, "extra_params") or kwargs
                    obbject._standard_params = std_params
                    obbject._extra_params = extra_params
                    if chart and obbject.results:
                        if "extra_params" not in kwargs_copy:
                            kwargs_copy["extra_params"] = {}
                        # Restore any kwargs passed that were removed by the ParametersBuilder
                        for k in kwargs_copy.copy():
                            if k == "chart":
                                kwargs_copy.pop("chart", None)
                                continue
                            if (
                                not extra_params or k not in extra_params
                            ) and k != "extra_params":
                                kwargs_copy["extra_params"][k] = kwargs_copy.pop(
                                    k, None
                                )

                        cls._chart(obbject, **kwargs_copy)

                raised_warnings = warning_list if warning_list else []
        finally:
            if raised_warnings:
                if isinstance(obbject, (OBBject, OBBStream)):
                    obbject.warnings = [cast_warning(w) for w in raised_warnings]
                for w in raised_warnings:
                    if user_settings.preferences.show_warnings:
                        showwarning(
                            message=w.message,
                            category=w.category,
                            filename=w.filename,
                            lineno=w.lineno,
                            file=w.file,
                            line=w.line,
                        )

            if system_settings.logging_suppress is False:
                from openbb_core.app.logs.logging_service import LoggingService

                ls = LoggingService(system_settings, user_settings)
                ls.log(
                    user_settings=user_settings,
                    system_settings=system_settings,
                    route=route,
                    func=func,
                    kwargs=kwargs,
                    exec_info=exc_info(),
                    custom_headers=custom_headers,
                )

        return obbject

    @classmethod
    async def run(
        cls,
        execution_context: ExecutionContext,
        /,
        *args,
        **kwargs,
    ) -> OBBject:
        """Run a command and return the OBBject as output."""
        timestamp = datetime.now()
        start_ns = perf_counter_ns()

        command_map = execution_context.command_map
        route = execution_context.route

        if func := command_map.get_command(route=route):
            obbject = await cls._execute_func(
                route=route,
                args=args,
                execution_context=execution_context,
                func=func,
                kwargs=kwargs,
            )
        else:
            raise AttributeError(f"Invalid command : route={route}")

        duration = perf_counter_ns() - start_ns

        if execution_context.user_settings.preferences.metadata and isinstance(
            obbject, (OBBject, OBBStream)
        ):
            try:
                obbject.extra["metadata"] = Metadata(
                    arguments=kwargs,
                    duration=duration,
                    route=route,
                    timestamp=timestamp,
                )
            except Exception as e:
                if Env().DEBUG_MODE:
                    raise OpenBBError(e) from e
                warn(str(e), OpenBBWarning)

            # Remove the dependency injection objects embedded in the kwargs
            deps = execution_context.api_route.dependencies
            dependency_param_names: set[str] = set()
            if deps:
                for dep in deps:
                    dep_name = getattr(dep.dependency, "__name__", "")
                    dep_name = to_snake_case(dep_name).replace("get_", "")
                    dependency_param_names.add(dep_name)

                if isinstance(obbject, OBBject):
                    for dep_key in dependency_param_names:
                        _ = obbject._extra_params.pop(dep_key, None)  # type: ignore

            meta = getattr(obbject.extra.get("metadata"), "arguments", {})

            # Non-provider endpoints need to have execution info added because it might have been discarded.
            if meta and (
                not meta.get("provider_choices", {})
                and not meta.get("standard_params", {})
                and not meta.get("extra_params", {})
            ):
                for k, v in kwargs.items():
                    if k == "kwargs":
                        for key, value in kwargs["kwargs"].items():
                            if key not in dependency_param_names and value:
                                obbject.extra["metadata"].arguments["extra_params"][
                                    key
                                ] = value
                        continue
                    if k not in dependency_param_names and v:
                        obbject.extra["metadata"].arguments["standard_params"][k] = v

        if isinstance(obbject, OBBject):
            try:
                cls._trigger_command_output_callbacks(route, obbject)
            except Exception as e:
                if Env().DEBUG_MODE:
                    raise OpenBBError(e) from e
                warn(str(e), OpenBBWarning)
            # We need to remove callables that were added to
            # kwargs representing dependency injections
            metadata = obbject.extra.get("metadata")
            if metadata:
                arguments = obbject.extra["metadata"].arguments

                for section in ("standard_params", "extra_params", "provider_choices"):
                    params = arguments.get(section)

                    if not isinstance(params, dict):
                        continue

                    for key, value in params.copy().items():
                        if callable(value) or not value:
                            del obbject.extra["metadata"].arguments[section][key]
                            continue
                        try:
                            jsonable_encoder(value)
                        except (TypeError, ValueError):
                            del obbject.extra["metadata"].arguments[section][key]
                            continue

        return obbject

    @classmethod
    def _trigger_command_output_callbacks(cls, route: str, obbject: OBBject) -> None:
        """Trigger command output callbacks for extensions."""
        loader = ExtensionLoader()
        callbacks = loader.on_command_output_callbacks
        if not callbacks:
            return

        # For each extension registered for all routes or the specific route,
        # we call its accessor on the OBBject.
        # We check if the accessor is immutable or not to decide whether to pass
        # a copy of the OBBject or the original one.
        # We set the _extension_modified attribute to True if any extension
        # mutates the OBBject so we can pass this information to the interface.
        # We also set the _results_only attribute to True if any extension
        # indicates that only results should be returned.
        results_only = False
        executed_keys: set[str] = set()
        ordered_extensions: list = []
        all_on_command_output_exts: list = []

        def _extension_key(ext) -> str:
            if key := getattr(ext, "identifier", None):
                return str(key)
            if path := getattr(ext, "import_path", None):
                return f"{path}:{getattr(ext, 'name', id(ext))}"
            return str(getattr(ext, "name", id(ext)))

        def _clone_for_immutable(source: OBBject) -> OBBject | None:
            try:
                new_source = source.model_copy()
                new_source = OBBject.model_validate(source.model_dump())
                return source.model_validate(new_source)
            except Exception as e:
                warn(
                    f"Skipped immutable callback because the OBBject could not be duplicated. {e}",
                    OpenBBWarning,
                )
                return None

        for ext_list in callbacks.values():
            all_on_command_output_exts.extend(ext_list)

        for ext in callbacks.get("*", []):
            key = _extension_key(ext)
            if key not in executed_keys:
                executed_keys.add(key)
                ordered_extensions.append(ext)

        for ext in callbacks.get(route, []):
            key = _extension_key(ext)
            if key not in executed_keys:
                executed_keys.add(key)
                ordered_extensions.append(ext)

        try:
            for ext in ordered_extensions:
                if ext.results_only is True:
                    results_only = True

                if ext.command_output_paths and route not in ext.command_output_paths:
                    continue

                accessors: set = getattr(type(obbject), "accessors", set())
                if ext.name not in accessors:
                    continue

                descriptor = type(obbject).__dict__.get(ext.name)
                if not isinstance(descriptor, CachedAccessor):
                    continue

                factory = descriptor._accessor

                target = _clone_for_immutable(obbject) if ext.immutable else obbject

                if target is None:
                    continue

                if iscoroutinefunction(factory):
                    run_async(factory, target)
                else:
                    result = factory(target)
                    if callable(result):
                        result()

                if ext.immutable is False:
                    object.__setattr__(obbject, "_extension_modified", True)

            if results_only is True:
                object.__setattr__(obbject, "_results_only", True)
                object.__setattr__(obbject, "_extension_modified", True)

        except Exception as e:
            raise OpenBBError(e) from e

        for ext in all_on_command_output_exts:
            if ext.name in type(obbject).__dict__:
                object.__setattr__(
                    obbject,
                    ext.name,
                    "Accessor is not callable outside of function execution.",
                )


class CommandRunner:
    """Command runner."""

    def __init__(
        self,
        command_map: Optional["CommandMap"] = None,
        system_settings: Optional["SystemSettings"] = None,
        user_settings: Optional["UserSettings"] = None,
    ) -> None:
        """Initialize the command runner."""
        from openbb_core.app.router import CommandMap
        from openbb_core.app.service.system_service import SystemService
        from openbb_core.app.service.user_service import UserService

        self._command_map = command_map or CommandMap()
        self._system_settings = system_settings or SystemService().system_settings
        self._user_settings = user_settings or UserService().default_user_settings

    def init_logging_service(self) -> None:
        """Initialize the logging service."""
        from openbb_core.app.logs.logging_service import LoggingService

        _ = LoggingService(
            system_settings=self._system_settings, user_settings=self._user_settings
        )

    @property
    def command_map(self) -> "CommandMap":
        """Command map."""
        return self._command_map

    @property
    def system_settings(self) -> "SystemSettings":
        """System settings."""
        return self._system_settings

    @property
    def user_settings(self) -> "UserSettings":
        """User settings."""
        return self._user_settings

    @user_settings.setter
    def user_settings(self, user_settings: "UserSettings") -> None:
        self._user_settings = user_settings

    async def run(
        self,
        route: str,
        user_settings: Optional["UserSettings"] = None,
        /,
        *args,
        **kwargs,
    ) -> OBBject:
        """Run a command and return the OBBject as output."""

        self._user_settings = user_settings or self._user_settings

        execution_context = ExecutionContext(
            command_map=self._command_map,
            route=route,
            system_settings=self._system_settings,
            user_settings=self._user_settings,
        )

        return await StaticCommandRunner.run(execution_context, *args, **kwargs)

    def sync_run(
        self,
        route: str,
        user_settings: Optional["UserSettings"] = None,
        /,
        *args,
        **kwargs,
    ) -> OBBject:
        """Run a command and return the OBBject as output."""
        return run_async(self.run, route, user_settings, *args, **kwargs)
