import pytest

from openbb_core.env import Env


def test_str2bool_invalid_value_raises():
    try:
        Env.str2bool("maybe")
        assert False
    except ValueError as exc:
        assert "Failed to cast maybe to bool" in str(exc)


def test_str2bool_false_value():
    assert Env.str2bool("false") is False


def test_auto_build_property_uses_env_value():
    env = Env()
    original = env._environ.copy()
    try:
        env._environ["OPENBB_AUTO_BUILD"] = "true"
        assert env.AUTO_BUILD is True
    finally:
        env._environ = original


def _timeouts(environ):
    env = Env()
    original = env._environ
    try:
        env._environ = environ
        return env.COMMAND_TIMEOUTS
    finally:
        env._environ = original


def test_command_timeouts_default_and_per_provider():
    assert _timeouts({}) == {}
    assert _timeouts({"OPENBB_COMMAND_TIMEOUT": ""}) == {}
    assert _timeouts(
        {"OPENBB_COMMAND_TIMEOUT": "55", "OPENBB_COMMAND_TIMEOUT_CFTC": "90"}
    ) == {"": 55.0, "cftc": 90.0}


@pytest.mark.parametrize("value", ["abc", "0", "-5", "nan"])
def test_command_timeouts_reject_non_positive_values(value):
    for name in ("OPENBB_COMMAND_TIMEOUT", "OPENBB_COMMAND_TIMEOUT_FRED"):
        with pytest.raises(ValueError, match=name):
            _timeouts({name: value})
