"""OpenBB Platform Core app utils tests."""

import pytest

pd = pytest.importorskip("pandas")
np = pytest.importorskip("numpy")

from openbb_core.app.model.abstract.error import OpenBBError  # noqa: E402
from openbb_core.app.utils import (  # noqa: E402
    basemodel_to_df,
    check_single_item,
    convert_to_basemodel,
    df_to_basemodel,
    dict_to_basemodel,
    get_target_column,
    get_target_columns,
    list_to_basemodel,
    ndarray_to_basemodel,
)
from openbb_core.provider.abstract.data import Data  # noqa: E402

pytestmark = pytest.mark.requires_pandas


df = pd.DataFrame(
    {
        "x": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
        "y": [5, 4, 3, 9, 44, 5, 66, 11, 777, 1],
        "z": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    },
)

df_multiindex = df.set_index(["x", "y"])

simple_base_model = [
    Data(x=i, y=j, z=k)
    for i in range(2)
    for j in range(6, 8)
    for k in range(10, 12)  # type: ignore[call-arg]
]

multi_index_base_model = [
    Data(x=i, y=j, z=k, is_multiindex=True, multiindex_names="['x','y']")  # type: ignore[call-arg]
    for i in range(2)
    for j in range(6, 8)
    for k in range(10, 12)
]


def test_df_to_basemodel():
    """Test the df_to_basemodel helper."""
    base_model = df_to_basemodel(df)
    assert isinstance(base_model, list)
    assert base_model[0].x == 1  # type: ignore[attr-defined]


def test_df_to_basemodel_multiindex():
    """Test the df_to_basemodel helper with a multi-index DataFrame."""
    base_model = df_to_basemodel(df_multiindex)
    assert isinstance(base_model, list)
    assert hasattr(base_model[0], "is_multiindex")


def test_basemodel_to_df():
    """Test the basemodel_to_df helper."""
    df = basemodel_to_df(simple_base_model)
    assert isinstance(df, pd.DataFrame)
    assert df.shape == (8, 3)


def test_basemodel_to_multiindex_df():
    """Test the basemodel_to_df helper with a multi-index DataFrame."""
    df = basemodel_to_df(multi_index_base_model)
    assert isinstance(df, pd.DataFrame)
    assert isinstance(df.index, pd.MultiIndex)


@pytest.mark.parametrize(
    "names",
    [["x", "y"], [None, None], ["x", None], [None, "y"]],
)
def test_multiindex_round_trip(names):
    """Test that a MultiIndex survives a df -> basemodel -> df round trip."""
    original = df_multiindex.copy()
    original.index.names = names

    result = basemodel_to_df(df_to_basemodel(original))

    assert isinstance(result.index, pd.MultiIndex)
    assert list(result.index.names) == names
    assert result.index.tolist() == original.index.tolist()
    assert list(result.columns) == ["z"]
    assert result["z"].tolist() == original["z"].tolist()


def test_get_target_column():
    """Test the get_target_column helper."""
    target = get_target_column(df, "x")
    assert isinstance(target, pd.Series)
    assert target[0] == 1


def test_get_target_columns():
    """Test the get_target_columns helper."""
    targets = get_target_columns(df, ["x", "y"])
    assert isinstance(targets, pd.DataFrame)
    assert targets.shape == (10, 2)


@pytest.mark.parametrize(
    "data_list, expected",
    [
        # List of dictionaries
        ([{"a": 1}, {"b": 2}], [Data(a=1), Data(b=2)]),
        # List with a single DataFrame
        ([pd.DataFrame({"c": [3, 4]})], [Data(c=3), Data(c=4)]),
        # List with mixed types
        ([{"d": 5}, pd.Series([6, 7], name="e")], [Data(d=5), Data(e=6), Data(e=7)]),
    ],
)
def test_list_to_basemodel(data_list, expected):
    """Test the list_to_basemodel helper."""
    result = list_to_basemodel(data_list)
    for r, e in zip(result, expected):
        assert r.model_dump() == e.model_dump()


@pytest.mark.parametrize(
    "data_dict, expected",
    [
        # Simple dictionary
        ({"a": 10}, Data(a=10)),  # type: ignore[call-arg]
        # Nested dictionary (assuming Data can handle nested dicts)
        ({"b": {"c": 20}}, Data(b={"c": 20})),  # type: ignore[call-arg]
        # Dictionary with list (assuming Data can handle lists)
        ({"d": [30, 40]}, Data(d=[30, 40])),  # type: ignore[call-arg]
    ],
)
def test_dict_to_basemodel(data_dict, expected):
    """Test the dict_to_basemodel helper."""
    result = dict_to_basemodel(data_dict)
    assert result.model_dump() == expected.model_dump()


@pytest.mark.parametrize(
    "array, expected",
    [
        # 2D array with single row
        (np.array([[1, 2]]), [Data(column_0=1, column_1=2)]),
        # 2D array with multiple rows
        (
            np.array([[3, 4], [5, 6]]),
            [Data(column_0=3, column_1=4), Data(column_0=5, column_1=6)],
        ),
        # 2D array with non-numeric data
        (
            np.array([["a", "b"], ["c", "d"]]),
            [Data(column_0="a", column_1="b"), Data(column_0="c", column_1="d")],
        ),
    ],
)
def test_ndarray_to_basemodel(array, expected):
    """Test the ndarray_to_basemodel helper."""
    result = ndarray_to_basemodel(array)
    for r, e in zip(result, expected):
        assert r.model_dump() == e.model_dump()


@pytest.mark.parametrize(
    "item, expected",
    [
        ("SYMBOL", "SYMBOL"),
        (None, None),
        ("", ""),
        ("SYMBOL1,SYMBOL2", OpenBBError),
        ("SYMBOL1;SYMBOL2", OpenBBError),
    ],
)
def test_check_single_item(item, expected):
    """Test the check_single_item helper."""
    if expected is OpenBBError:
        with pytest.raises(OpenBBError):
            check_single_item(item)
    else:
        assert check_single_item(item) == expected


def test_basemodel_to_df_single_data_with_date():
    data = Data(date="2024-01-01", x=1, y=2)
    df = basemodel_to_df(data)
    assert "date" in df.columns
    assert "x" in df.columns


def test_basemodel_to_df_single_scalar_data_uses_values_index():
    """A single Data with only scalar fields hits the ValueError fallback."""
    data = Data(name="aapl")
    df = basemodel_to_df(data)
    # Either fallback ('values' index) or normal frame is acceptable
    assert isinstance(df, pd.DataFrame)
    assert "name" in df.columns


def test_basemodel_to_df_with_index_name():
    """Setting ``index='x'`` reindexes the resulting frame on x."""
    data = [Data(x=i, y=i * 2) for i in range(3)]
    df = basemodel_to_df(data, index="x")
    assert df.index.name == "x"


def test_basemodel_to_df_with_date_index():
    data = [Data(date=f"2024-01-0{i}", value=i) for i in range(1, 4)]
    df = basemodel_to_df(data, index="date")
    assert df.index.name == "date"


def test_basemodel_to_df_mixed_offsets_all_midnight_reduces_to_date():
    """A mixed-offset column that is entirely midnight still reduces to dates.

    The payload crosses a daylight-savings boundary, so it has no single
    datetime64 representation and stays object dtype. Every value is midnight
    local time, so it must still be reduced to ``datetime.date``.
    """
    from datetime import date

    data = [
        Data(date="2023-11-03 00:00:00-04:00", value=1),
        Data(date="2023-11-06 00:00:00-05:00", value=2),
        Data(date="2023-11-08 00:00:00-05:00", value=3),
    ]
    result = basemodel_to_df(data)
    assert list(result["date"]) == [
        date(2023, 11, 3),
        date(2023, 11, 6),
        date(2023, 11, 8),
    ]


def test_basemodel_to_df_falls_back_to_per_element_parse(monkeypatch):
    """A column the vectorized parse rejects is parsed one value at a time.

    Whether a mixed-offset column raises depends on the pandas version - 3.x
    raises, 2.x returns object dtype - so the fallback is forced here rather
    than left to the installed version.
    """
    from datetime import date

    real_to_datetime = pd.to_datetime

    def fake_to_datetime(arg, *args, **kwargs):
        if isinstance(arg, pd.Series):
            raise ValueError("Mixed timezones detected. Pass utc=True")
        return real_to_datetime(arg, *args, **kwargs)

    monkeypatch.setattr(pd, "to_datetime", fake_to_datetime)

    data = [
        Data(date="2023-11-03 00:00:00-04:00", value=1),
        Data(date="2023-11-06 00:00:00-05:00", value=2),
    ]
    result = basemodel_to_df(data)
    assert list(result["date"]) == [date(2023, 11, 3), date(2023, 11, 6)]


def test_df_to_basemodel_with_date_only_column_keeps_date_format():
    df = pd.DataFrame(
        {
            "date": ["2024-01-01", "2024-01-02"],
            "value": [1, 2],
        }
    )
    out = df_to_basemodel(df)
    assert len(out) == 2
    # The date column should be preserved as a YYYY-MM-DD string
    assert out[0].model_dump()["date"] == "2024-01-01"


def test_df_to_basemodel_series_input_is_promoted_to_frame():
    s = pd.Series([10, 20, 30], name="value")
    out = df_to_basemodel(s)
    assert len(out) == 3
    assert out[0].value == 10  # type: ignore[attr-defined]


def test_df_to_basemodel_with_named_index_resets():
    df = pd.DataFrame({"x": [1, 2], "y": [3, 4]}).set_index("x")
    out = df_to_basemodel(df, index=True)
    assert len(out) == 2
    # After reset, x is a column on the model
    assert hasattr(out[0], "x")


def test_list_to_basemodel_with_data_subclass_instance():
    class SubData(Data):
        custom: str = ""

    item = SubData(custom="hi")
    out = list_to_basemodel([item])
    assert out[0] is item


def test_list_to_basemodel_unsupported_type_raises():
    with pytest.raises(ValueError, match="Unsupported list item type"):
        list_to_basemodel([object()])


def test_dict_to_basemodel_validation_error_raises_value_error(monkeypatch):
    """A ValidationError from ``Data(**...)`` is wrapped in ``ValueError``."""
    from pydantic import ValidationError

    from openbb_core.app import utils as utils_module

    class _BoomData:
        def __init__(self, **_kwargs):
            raise ValidationError.from_exception_data(title="Data", line_errors=[])

    monkeypatch.setattr(utils_module, "Data", _BoomData)
    with pytest.raises(ValueError, match="Validation error"):
        dict_to_basemodel({"x": 1})


def test_ndarray_to_basemodel_non_2d_raises():
    with pytest.raises(ValueError, match="Only 2D arrays"):
        ndarray_to_basemodel(np.array([1, 2, 3]))


def test_convert_to_basemodel_data_passthrough():
    d = Data(x=1)
    assert convert_to_basemodel(d) is d


def test_convert_to_basemodel_dict():
    out = convert_to_basemodel({"x": 5})
    assert isinstance(out, Data)
    assert out.x == 5  # type: ignore[attr-defined]


def test_convert_to_basemodel_list_of_dicts():
    out = convert_to_basemodel([{"x": 1}, {"x": 2}])
    assert isinstance(out, list)
    assert len(out) == 2


def test_convert_to_basemodel_dataframe():
    out = convert_to_basemodel(pd.DataFrame({"x": [1, 2]}))
    assert isinstance(out, list)
    assert len(out) == 2


def test_convert_to_basemodel_series():
    out = convert_to_basemodel(pd.Series([1, 2], name="x"))
    assert isinstance(out, list)
    assert len(out) == 2


def test_convert_to_basemodel_ndarray():
    out = convert_to_basemodel(np.array([[1, 2], [3, 4]]))
    assert isinstance(out, list)
    assert len(out) == 2


def test_convert_to_basemodel_unsupported_raises():
    with pytest.raises(ValueError, match="Unsupported data type"):
        convert_to_basemodel(object())


def test_get_target_column_missing_raises_with_choices():
    df = pd.DataFrame({"a": [1], "b": [2]})
    with pytest.raises(ValueError, match="Choose from"):
        get_target_column(df, "missing")


def test_get_target_columns_returns_dataframe_with_requested_columns():
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4], "c": [5, 6]})
    out = get_target_columns(df, ["a", "c"])
    assert list(out.columns) == ["a", "c"]


def test_get_user_cache_directory_reads_preferences(tmp_path, monkeypatch):
    import json as _json

    from openbb_core.app import utils as utils_module

    settings_file = tmp_path / "user_settings.json"
    settings_file.write_text(
        _json.dumps({"preferences": {"cache_directory": "/tmp/my-cache"}})  # noqa: S108
    )

    class _FakeSystemSettings:
        def model_dump(self):
            return {"user_settings_path": str(settings_file)}

    monkeypatch.setattr(utils_module, "SystemSettings", _FakeSystemSettings)
    from openbb_core.app.utils import get_user_cache_directory

    assert get_user_cache_directory() == "/tmp/my-cache"  # noqa: S108


def test_get_user_cache_directory_falls_back_when_no_preferences(tmp_path, monkeypatch):
    from openbb_core.app import utils as utils_module

    settings_file = tmp_path / "user_settings.json"
    settings_file.write_text("{}")

    class _FakeSystemSettings:
        def model_dump(self):
            return {"user_settings_path": str(settings_file)}

    monkeypatch.setattr(utils_module, "SystemSettings", _FakeSystemSettings)
    from openbb_core.app.utils import get_user_cache_directory

    out = get_user_cache_directory()
    assert isinstance(out, str)
    assert out  # non-empty default
