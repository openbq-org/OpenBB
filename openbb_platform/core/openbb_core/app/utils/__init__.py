"""Utility functions for the OpenBB Core app."""

import ast
import json
from datetime import time
from typing import TYPE_CHECKING, Union

from pydantic import ValidationError

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.app.model.preferences import Preferences
from openbb_core.app.model.system_settings import SystemSettings
from openbb_core.app.utils_optional import require_optional
from openbb_core.provider.abstract.data import Data

if TYPE_CHECKING:
    from numpy import ndarray
    from pandas import DataFrame, Series

_MULTIINDEX_META = ("is_multiindex", "multiindex_names", "multiindex_columns")


def _multiindex_columns(names: list) -> list:
    """Get the column names that reset_index gives the levels of a MultiIndex."""
    return [n if n is not None else f"level_{i}" for i, n in enumerate(names)]


def basemodel_to_df(
    data: list[Data] | Data,
    index: str | None = None,
) -> "DataFrame":
    """Convert list of BaseModel to a Pandas DataFrame."""
    pd = require_optional("pandas")
    DataFrame, to_datetime = pd.DataFrame, pd.to_datetime  # type: ignore[union-attr]
    is_numeric_dtype = pd.api.types.is_numeric_dtype  # type: ignore[union-attr]

    if isinstance(data, list):
        df = DataFrame(
            [d.model_dump(exclude_none=True, exclude_unset=True) for d in data]
        )
    else:
        try:
            df = DataFrame(data.model_dump(exclude_none=True, exclude_unset=True))
        except ValueError:
            df = DataFrame(
                data.model_dump(exclude_none=True, exclude_unset=True),
                index=pd.Index(["values"]),  # type: ignore[union-attr]
            )

    if "is_multiindex" in df.columns:
        names = ast.literal_eval(df.multiindex_names.unique()[0])
        # The level columns follow the reset_index naming unless df_to_basemodel
        # had to rename them to avoid a clash, in which case it stores them.
        if "multiindex_columns" in df.columns:
            columns = ast.literal_eval(df.multiindex_columns.unique()[0])
        else:
            columns = _multiindex_columns(names)
        df = df.set_index(columns).rename_axis(names)
        df = df.drop(columns=[c for c in _MULTIINDEX_META if c in df.columns])

    # If the date column contains dates only, convert them to a date to avoid encoding time data.
    # Numeric values would be read as epoch offsets, so only text and datetimes are parsed.
    parsed = None
    if "date" in df.columns and not is_numeric_dtype(df["date"]):
        try:
            # Parse the column in a single call instead of once per row.
            parsed = to_datetime(df["date"])
        except ValueError:
            # A column that mixes UTC offsets - a series crossing a daylight
            # savings boundary, for instance - has no single datetime64
            # representation, so fall back to parsing each value on its own.
            try:
                parsed = df["date"].apply(to_datetime)
            except (TypeError, ValueError):
                # Not a date column after all, so leave it as it is.
                parsed = None

    if parsed is not None:
        df["date"] = parsed

        if parsed.dtype == object:
            if all(t.time() == time(0, 0) for t in parsed):
                df["date"] = parsed.apply(lambda x: x.date())
        elif (parsed == parsed.dt.normalize()).all():
            df["date"] = parsed.dt.date

    if index and index in df.columns:
        if index == "date":
            df.set_index("date", inplace=True)
            df.sort_index(axis=0, inplace=True)
        else:
            df = df.set_index(index) if index and index in df.columns else df

    return df


def df_to_basemodel(
    df: Union["DataFrame", "Series"], index: bool = False
) -> list[Data]:
    """Convert from a Pandas DataFrame to list of BaseModel."""
    pd = require_optional("pandas")
    MultiIndex, Series, to_datetime = pd.MultiIndex, pd.Series, pd.to_datetime  # type: ignore[union-attr]
    is_numeric_dtype = pd.api.types.is_numeric_dtype  # type: ignore[union-attr]

    is_multiindex = isinstance(df.index, MultiIndex)

    if not is_multiindex and (index or df.index.name):
        df = df.reset_index()
    if isinstance(df, Series):
        df = df.to_frame()

    # Check if df has multiindex.  If so, add the index names to the df and a boolean column
    if isinstance(df.index, MultiIndex):
        names = list(df.index.names)
        default_columns = _multiindex_columns(names)
        # A level whose column name is already taken, by a column or another level,
        # gets a free name instead so that reset_index does not fail.
        taken = set(df.columns) | set(_MULTIINDEX_META)
        columns = []
        for default in default_columns:
            column = default
            while column in taken:
                column = f"_{column}"
            taken.add(column)
            columns.append(column)
        df = df.rename_axis(columns).reset_index()
        df["is_multiindex"] = True
        df["multiindex_names"] = str(names)
        if columns != default_columns:
            df["multiindex_columns"] = str(columns)

    # Converting to JSON will add T00:00:00.000 to all dates with no time element unless we format it as a string first.
    # Numeric values would be read as epoch offsets, so only text and datetimes are parsed.
    if "date" in df.columns and not is_numeric_dtype(df["date"]):
        try:
            dates = df["date"].apply(to_datetime)
        except (TypeError, ValueError):
            # Not a date column after all, so leave it as it is.
            dates = None
        if dates is not None:
            df["date"] = dates
            if all(t.time() == time(0, 0) for t in df["date"]):
                df["date"] = df["date"].apply(lambda x: x.date().strftime("%Y-%m-%d"))

    return [
        Data(**d) for d in json.loads(df.to_json(orient="records", date_format="iso"))
    ]


def list_to_basemodel(data_list: list) -> list[Data]:
    """Convert a list to a list of BaseModel."""
    pd = require_optional("pandas")
    DataFrame, Series = pd.DataFrame, pd.Series  # type: ignore[union-attr]

    base_models = []
    for item in data_list:
        if isinstance(item, Data) or issubclass(type(item), Data):
            base_models.append(item)
        elif isinstance(item, dict):
            base_models.append(Data(**item))
        elif isinstance(item, (DataFrame, Series)):
            base_models.extend(df_to_basemodel(item))
        else:
            raise ValueError(f"Unsupported list item type: {type(item)}")
    return base_models


def dict_to_basemodel(data_dict: dict) -> Data:
    """Convert a dictionary to BaseModel."""
    try:
        return Data(**data_dict)
    except ValidationError as e:
        raise ValueError(
            f"Validation error when converting dict to BaseModel: {e}"
        ) from e


def ndarray_to_basemodel(array: "ndarray") -> list[Data]:
    """Convert a NumPy array to list of BaseModel."""
    # Assuming a 2D array where rows are records
    if array.ndim != 2:
        raise ValueError("Only 2D arrays are supported.")
    return [
        Data(**{f"column_{i}": value for i, value in enumerate(row)}) for row in array
    ]


def convert_to_basemodel(data) -> Data | list[Data]:
    """Dispatch function to convert different types to BaseModel."""
    np, pd = require_optional("numpy", "pandas")
    ndarray = np.ndarray  # type: ignore[union-attr]
    DataFrame, Series = pd.DataFrame, pd.Series  # type: ignore[union-attr]

    if isinstance(data, Data) or issubclass(type(data), Data):
        return data
    if isinstance(data, list):
        return list_to_basemodel(data)
    if isinstance(data, dict):
        return dict_to_basemodel(data)
    if isinstance(data, (DataFrame, Series)):
        return df_to_basemodel(data)
    if isinstance(data, ndarray):
        return ndarray_to_basemodel(data)
    raise ValueError(f"Unsupported data type: {type(data)}")


def get_target_column(df: "DataFrame", target: str) -> "Series":
    """Get target column from time series data."""
    if target not in df.columns:
        choices = ", ".join(df.columns)
        raise ValueError(
            f"Target column '{target}' not found in data. Choose from {choices}"
        )
    return df[target]


def get_target_columns(df: "DataFrame", target_columns: list[str]) -> "DataFrame":
    """Get target columns from time series data."""
    pd = require_optional("pandas")
    df_result = pd.DataFrame()  # type: ignore[union-attr]
    for target in target_columns:
        df_result[target] = get_target_column(df, target).to_frame()
    return df_result


def get_user_cache_directory() -> str:
    """Get user cache directory."""
    file = SystemSettings().model_dump()["user_settings_path"]

    with open(file) as settings_file:
        contents = settings_file.read()

    try:
        settings = json.loads(contents)["preferences"]
    except KeyError:
        settings = None
    cache_dir = (
        settings["cache_directory"]
        if settings and "cache_directory" in settings
        else Preferences().cache_directory
    )
    return cache_dir


def check_single_item(value: str | None, message: str | None = None) -> str | None:
    """Check that string contains a single item."""
    if value and isinstance(value, str) and ("," in value or ";" in value):
        raise OpenBBError(message if message else "multiple items not allowed")
    return value
