"""Example class to represent endpoint examples."""

from abc import abstractmethod
from datetime import date, datetime, timedelta
from typing import Any, Literal, _GenericAlias  # type: ignore

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    model_validator,
)

QUOTE_TYPES = {str, date}


class Example(BaseModel):
    """Example model."""

    scope: str = Field(frozen=True)

    model_config = ConfigDict(validate_assignment=True)

    @abstractmethod
    def to_python(self, **kwargs) -> str:
        """Return a Python code representation of the example."""


class APIEx(Example):
    """API Example model."""

    scope: Literal["api"] = "api"
    description: str | None = Field(
        default=None, description="Optional description unless more than 3 parameters"
    )
    parameters: dict[str, str | int | float | bool | list[str] | list[dict[str, Any]]]

    @computed_field  # type: ignore[misc]
    @property
    def provider(self) -> str | None:
        """Return the provider from the parameters."""
        return self.parameters.get("provider")  # type: ignore

    @model_validator(mode="before")
    @classmethod
    def validate_model(cls, values: dict) -> dict:
        """Validate model."""
        parameters = values.get("parameters", {})
        provider = parameters.get("provider")

        if provider is not None and not isinstance(provider, str):
            raise ValueError("Provider must be a string.")

        # `provider`, when present, is a meta-parameter rather than a real
        # query parameter, so don't count it toward the description threshold.
        non_provider_count = len(parameters) - (1 if "provider" in parameters else 0)
        if non_provider_count > 3 and not values.get("description"):
            raise ValueError(
                "Description is required when there are more than 3 parameters."
            )

        return values

    @staticmethod
    def _unpack_type(type_: type) -> set:
        """Unpack types from types, example Union[List[str], int] -> {typing._GenericAlias, int}."""
        if hasattr(type_, "__args__") and type(type_) is not _GenericAlias:
            return set().union(*map(APIEx._unpack_type, type_.__args__))  # type: ignore
        return {type_} if isinstance(type_, type) else {type(type_)}

    @staticmethod
    def _shift(i: int) -> float:
        """Return a transformation of the integer."""
        return 2 * (i + 1) / (2 * i) % 1 + 1

    @staticmethod
    def mock_data(
        dataset: Literal["timeseries", "panel"],
        size: int = 5,
        sample: dict[str, Any] | None = None,
        multiindex: dict[str, Any] | None = None,
    ) -> list[dict]:
        """Generate mock data from a sample.

        Parameters
        ----------
        dataset : str
            The type of data to return:
            - 'timeseries': Time series data
            - 'panel': Panel data (multiindex)

        size : int
            The size of the data to return, default is 5.
        sample : Optional[Dict[str, Any]], optional
            A sample of the data to return, by default None.
        multiindex_names : Optional[List[str]], optional
            The names of the multiindex, by default None.

        Timeseries default sample:
        {
            "date": "2023-01-01",
            "open": 110.0,
            "high": 120.0,
            "low": 100.0,
            "close": 115.0,
            "volume": 10000,
        }

        Panel default sample:
        {
            "portfolio_value": 100000,
            "risk_free_rate": 0.02,
        }
        multiindex: {"asset_manager": "AM", "time": 0}

        Returns
        -------
        List[Dict]
            A list of dictionaries with the mock data.
        """
        if dataset == "timeseries":
            sample = sample or {
                "date": "2023-01-01",
                "open": 110.0,
                "high": 120.0,
                "low": 100.0,
                "close": 115.0,
                "volume": 10000,
            }
            result = []
            for i in range(1, size + 1):
                s = APIEx._shift(i)
                obs = {}
                for k, v in sample.items():
                    if k == "date":
                        obs[k] = (
                            datetime.strptime(v, "%Y-%m-%d") + timedelta(days=i)
                        ).strftime("%Y-%m-%d")
                    else:
                        obs[k] = round(v * s, 2)
                result.append(obs)
            return result
        if dataset == "panel":
            sample = sample or {
                "portfolio_value": 100000.0,
                "risk_free_rate": 0.02,
            }
            multiindex = multiindex or {"asset_manager": "AM", "time": 0}
            multiindex_names = list(multiindex.keys())
            idx_1 = multiindex_names[0]
            idx_2 = multiindex_names[1]
            items_per_idx = 2
            item: dict[str, Any] = {
                "is_multiindex": True,
                "multiindex_names": str(multiindex_names),
            }
            # Iterate over the number of items to create and add them to the result
            result = []
            for i in range(1, size + 1):
                item[idx_1] = f"{idx_1}_{i}"
                for j in range(items_per_idx):
                    item[idx_2] = j
                    for k, v in sample.items():
                        if isinstance(v, str):
                            item[k] = f"{v}_{j}"
                        else:
                            item[k] = round(v * APIEx._shift(i + j), 2)
                    result.append(item.copy())
            return result
        raise ValueError(f"Dataset '{dataset}' not found.")

    def to_python(self, **kwargs) -> str:
        """Return a Python code representation of the example."""
        indentation = kwargs.get("indentation", "")
        func_path = kwargs.get("func_path", ".func_router.func_name")
        param_types: dict[str, type] = kwargs.get("param_types", {})
        prompt = kwargs.get("prompt", "")

        eg = ""
        if self.description:
            eg += f"{indentation}{prompt}# {self.description}\n"

        eg += f"{indentation}{prompt}obb{func_path}("
        for k, v in self.parameters.items():
            if k in param_types and (type_ := param_types.get(k)):
                if isinstance(v, str) and QUOTE_TYPES.intersection(
                    self._unpack_type(type_)
                ):
                    eg += f"{k}='{v}', "
                else:
                    eg += f"{k}={v}, "
            elif isinstance(v, str):
                # Value is a string but param type is unknown — quote it
                eg += f"{k}='{v}', "
            else:
                eg += f"{k}={v}, "

        eg = indentation + eg.strip(", ") + ")\n"

        return eg


class PythonEx(Example):
    """Python Example model."""

    scope: Literal["python"] = "python"
    description: str
    code: list[str]

    def to_python(self, **kwargs) -> str:
        """Return a Python code representation of the example."""
        indentation = kwargs.get("indentation", "")
        prompt = kwargs.get("prompt", "")

        eg = ""
        if self.description:
            eg += f"{indentation}{prompt}# {self.description}\n"

        for line in self.code:
            eg += f"{indentation}{prompt}{line}\n"

        return eg


def filter_list(
    examples: list[Example],
    providers: list[str],
) -> list[Example]:
    """Filter list of examples."""
    return [
        e
        for e in examples
        if (isinstance(e, APIEx) and (not e.provider or e.provider in providers))
        or e.scope != "api"
    ]
