"""A real discoverable fixture extension for charting-resolution tests.

These tests exercise the *production* plugin-resolution path: one small but real
OpenBB extension package is written to disk **once** for the whole ``charting``
test package, together with the ``.dist-info`` directory that makes it a real
distribution, and is then discovered through real entry points by the real
``ExtensionLoader`` / ``importlib_metadata``. No service or entry point is
mocked — scenarios are driven through a real ``SystemSettings`` on the real
``SystemService`` singleton.

Discovery is driven by putting the package directory on ``sys.path``, which is
the same path-scanning ``importlib_metadata`` applies to every installed
distribution. Writing the ``.dist-info`` directly rather than shelling out to
``pip install -e`` keeps the suite runnable in an environment with no ``pip``
(a bare ``uv venv``, for one) and leaves the interpreter's site-packages
untouched.

The fixture engine registers under its own accessor name (``fake_charting``), so
its mere presence never changes default resolution; tests opt into it via the
``charting_extension`` / ``charting_backend`` config.
"""

from __future__ import annotations

import contextlib
import importlib
import sys

import pytest

from openbb_core.app.extension_loader import ExtensionLoader
from openbb_core.app.model.abstract.singleton import SingletonMeta
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.model.system_settings import SystemSettings
from openbb_core.app.service.system_service import SystemService

PACKAGE_NAME = "openbb_charting_fake"
DIST_NAME = "openbb-charting-fake"
DIST_VERSION = "0.0.1"
ENGINE_ACCESSORS = ("fake_charting", "fake_boom_charting")

ENGINE_INIT = '''\
"""Real fixture charting engine extension."""

from openbb_core.app.model.extension import Extension


class FakeCharting:
    """Drop-in alternate charting engine accessor."""

    def __init__(self, obbject):
        self._obbject = obbject

    @classmethod
    def functions(cls):
        return ["fake_alt_chart"]

    @classmethod
    def get_backend_class(cls):
        from openbb_charting_fake.backends import PrimaryBackend

        return PrimaryBackend

    def show(self, render=True, **kwargs):
        return None


class FakeBoomCharting:
    """Engine whose ``functions()`` raises, to exercise error handling."""

    def __init__(self, obbject):
        self._obbject = obbject

    @classmethod
    def functions(cls):
        raise RuntimeError("functions boom")

    def show(self, render=True, **kwargs):
        return None


engine_ext = Extension(name="fake_charting", description="fake engine")
FakeCharting = engine_ext.obbject_accessor(FakeCharting)

boom_ext = Extension(name="fake_boom_charting", description="fake boom engine")
FakeBoomCharting = boom_ext.obbject_accessor(FakeBoomCharting)
'''

ENGINE_HOOK = '''\
"""Real lifecycle hook for the fixture extension."""

from openbb_core.app.charting import ChartingHook


class RecordingHook(ChartingHook):
    """Patches chart content so dispatch can be observed."""

    name = "recording"
    priority = 5

    def post_figure(self, context):
        context.content = {"hooked": True}
        return context
'''

ENGINE_BACKENDS = '''\
"""Real rendering backends for the fixture extension."""


class PrimaryBackend:
    """Minimal backend constructed with charting settings."""

    def __init__(self, charting_settings):
        self.charting_settings = charting_settings

    def send_table(self, *args, **kwargs):
        return "table"

    def send_url(self, *args, **kwargs):
        return "url"


class SecondaryBackend:
    """A second backend, so config can disambiguate between several."""

    def __init__(self, charting_settings):
        self.charting_settings = charting_settings

    def send_table(self, *args, **kwargs):
        return "table"

    def send_url(self, *args, **kwargs):
        return "url"
'''

ENGINE_METADATA = f"""\
Metadata-Version: 2.1
Name: {DIST_NAME}
Version: {DIST_VERSION}
Requires-Python: >=3.11,<4
Requires-Dist: openbb-core
"""

# The INI form of the ``[project.entry-points.*]`` tables a build backend emits.
ENGINE_ENTRY_POINTS = """\
[openbb_obbject_extension]
fake_engine = openbb_charting_fake:engine_ext
fake_boom_engine = openbb_charting_fake:boom_ext

[openbb_charting_hooks]
fake_hook = openbb_charting_fake.hook:RecordingHook
fake_broken_hook = openbb_charting_fake.hook:DoesNotExist

[openbb_charting_backend]
fake_backend = openbb_charting_fake.backends:PrimaryBackend
fake_secondary_backend = openbb_charting_fake.backends:SecondaryBackend
"""


def _reset_extension_loader() -> None:
    """Drop the ExtensionLoader singleton so it re-scans real entry points."""
    SingletonMeta._instances.pop(ExtensionLoader, None)  # type: ignore[arg-type]
    importlib.invalidate_caches()


@pytest.fixture(scope="package", autouse=True)
def fake_charting_extension(tmp_path_factory):
    """Write the real fixture distribution once for the whole package.

    The fixture engine, hooks, and backends register through genuine entry
    points; individual tests select them via ``charting_config``.
    """
    work = tmp_path_factory.mktemp("charting_fixture")
    pkg_dir = work / PACKAGE_NAME
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text(ENGINE_INIT, encoding="utf-8")
    (pkg_dir / "hook.py").write_text(ENGINE_HOOK, encoding="utf-8")
    (pkg_dir / "backends.py").write_text(ENGINE_BACKENDS, encoding="utf-8")

    # A real ``.dist-info`` beside the package is what makes the directory a
    # discoverable distribution rather than a bare importable package.
    dist_info = work / f"{PACKAGE_NAME}-{DIST_VERSION}.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(ENGINE_METADATA, encoding="utf-8")
    (dist_info / "entry_points.txt").write_text(ENGINE_ENTRY_POINTS, encoding="utf-8")

    pristine_accessors = set(OBBject.accessors)
    src = str(work)
    # On ``sys.path`` the distribution is found by the same path scan
    # ``importlib_metadata`` runs over site-packages, and ``entry_point.load()``
    # can import the package.
    if src not in sys.path:
        sys.path.insert(0, src)
    _reset_extension_loader()

    try:
        yield {
            "engine": "fake_engine",
            "accessor": "fake_charting",
            "boom_accessor": "fake_boom_charting",
            "backend": "fake_backend",
            "secondary_backend": "fake_secondary_backend",
        }
    finally:
        with contextlib.suppress(ValueError):
            sys.path.remove(src)
        for name in [m for m in sys.modules if m.startswith(PACKAGE_NAME)]:
            del sys.modules[name]
        for accessor in ENGINE_ACCESSORS:
            if accessor in OBBject.accessors and accessor not in pristine_accessors:
                OBBject.accessors.discard(accessor)
                with contextlib.suppress(AttributeError):
                    delattr(OBBject, accessor)
        _reset_extension_loader()


@pytest.fixture
def charting_config():
    """Drive real charting config on the real SystemService singleton.

    Yields a setter; the original ``SystemSettings`` is restored on teardown.
    """
    service = SystemService()
    original = service.system_settings

    def _set(**overrides):
        service.system_settings = SystemSettings(logging_suppress=True, **overrides)

    try:
        yield _set
    finally:
        service.system_settings = original
