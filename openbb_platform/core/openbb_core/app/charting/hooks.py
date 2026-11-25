"""Chart lifecycle hooks shared across every Platform interface.

Hooks are discovered through the ``openbb_charting_hooks`` entry-point group and
dispatched inside the engine's chart creation, so they run identically whether a
chart is requested from the Python interface, the REST API, the CLI, or MCP.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from importlib_metadata import entry_points

CHARTING_HOOKS_GROUP = "openbb_charting_hooks"


class ChartLifecycle(StrEnum):
    """Stages a chart passes through during creation."""

    RESOLVE_DATA = "resolve_data"
    PRE_FIGURE = "pre_figure"
    POST_FIGURE = "post_figure"
    PRE_RENDER = "pre_render"
    POST_RENDER = "post_render"


@dataclass
class HookContext:
    """Mutable state passed to lifecycle hooks.

    A hook may mutate the relevant field(s) in place and return ``None``, or
    return a (possibly new) ``HookContext`` to replace it for later hooks.

    Parameters
    ----------
    route : str
        The command route the chart is created for, e.g. ``/equity/price/historical``.
    stage : ChartLifecycle
        The lifecycle stage currently dispatching.
    data : Any
        The resolved input data (available from ``RESOLVE_DATA`` onward).
    figure : Any
        The engine figure object (available from ``POST_FIGURE`` onward).
    content : dict | None
        The serialized chart content (available from ``POST_FIGURE`` onward).
    settings : Any
        The resolved ``ChartingSettings`` for the engine.
    standard_params : dict
        The command's standard parameters.
    extra_params : dict
        The command's provider/extra parameters.
    provider : str | None
        The provider the OBBject was created with.
    extra : dict
        The OBBject ``extra`` mapping.
    kwargs : dict
        Remaining keyword arguments passed to the chart function.
    """

    route: str
    stage: ChartLifecycle
    data: Any = None
    figure: Any = None
    content: dict | None = None
    settings: Any = None
    standard_params: dict = field(default_factory=dict)
    extra_params: dict = field(default_factory=dict)
    provider: str | None = None
    extra: dict = field(default_factory=dict)
    kwargs: dict = field(default_factory=dict)


class ChartingHook:
    """Base class for a chart lifecycle hook.

    Subclass and override the stage method(s) you care about, then register the
    subclass under the ``openbb_charting_hooks`` entry-point group::

        [project.entry-points."openbb_charting_hooks"]
        my_hook = "my_pkg.hooks:MyHook"

    Set ``routes`` to restrict the hook to specific command routes (empty means
    all routes) and ``priority`` to control ordering (lower runs first).
    """

    name: str = ""
    routes: tuple[str, ...] = ()
    priority: int = 100

    def resolve_data(self, context: HookContext) -> HookContext | None:
        """Inspect or replace the input data before figure construction."""

    def pre_figure(self, context: HookContext) -> HookContext | None:
        """Run immediately before the figure is built."""

    def post_figure(self, context: HookContext) -> HookContext | None:
        """Inspect or mutate the figure and content after construction."""

    def pre_render(self, context: HookContext) -> HookContext | None:
        """Run immediately before the figure is rendered by the backend."""

    def post_render(self, context: HookContext) -> HookContext | None:
        """Run after the figure has been rendered."""


class ChartingHooksManager:
    """Discover and dispatch registered chart lifecycle hooks."""

    def __init__(self, hooks: list[ChartingHook] | None = None) -> None:
        """Initialize the manager, loading hooks from entry points if not given.

        Hooks are always ordered by ``priority`` (lower runs first), whether
        loaded from entry points or supplied explicitly.
        """
        loaded = hooks if hooks is not None else self._load_hooks()
        self._hooks: list[ChartingHook] = sorted(
            loaded, key=lambda hook: getattr(hook, "priority", 100)
        )

    @staticmethod
    def _load_hooks() -> list[ChartingHook]:
        """Load and instantiate hooks from the entry-point group."""
        hooks: list[ChartingHook] = []
        for entry_point in entry_points(group=CHARTING_HOOKS_GROUP):
            try:
                obj = entry_point.load()
            except Exception:  # noqa: BLE001, S112
                # A broken third-party hook must not break charting for everyone.
                continue
            hooks.append(obj() if isinstance(obj, type) else obj)
        return hooks

    @property
    def hooks(self) -> list[ChartingHook]:
        """Return the ordered list of registered hooks."""
        return self._hooks

    def dispatch(self, stage: ChartLifecycle, context: HookContext) -> HookContext:
        """Run every hook registered for ``stage`` against ``context``.

        Parameters
        ----------
        stage : ChartLifecycle
            The lifecycle stage to dispatch.
        context : HookContext
            The current context; mutated in place and/or replaced by hooks.

        Returns
        -------
        HookContext
            The resulting context after all applicable hooks have run.
        """
        context.stage = stage
        for hook in self._hooks:
            routes = getattr(hook, "routes", ())
            if routes and context.route not in routes:
                continue
            method = getattr(hook, stage.value, None)
            if method is None:
                continue
            result = method(context)
            if isinstance(result, HookContext):
                context = result
        return context


_HOOKS_MANAGER: ChartingHooksManager | None = None


def get_hooks_manager(reload: bool = False) -> ChartingHooksManager:
    """Return the process-wide hooks manager, loading hooks once.

    Parameters
    ----------
    reload : bool
        Force a fresh scan of the entry-point group. Primarily for tests that
        install hook packages after the first resolution.
    """
    global _HOOKS_MANAGER  # noqa: PLW0603
    if _HOOKS_MANAGER is None or reload:
        _HOOKS_MANAGER = ChartingHooksManager()
    return _HOOKS_MANAGER
