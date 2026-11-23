
"""TEJ Equity Historical Price Model."""

from datetime import datetime
from typing import Any, List

import tejapi
from dateutil.relativedelta import relativedelta
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.equity_historical import (
    EquityHistoricalData,
    EquityHistoricalQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

class TEJEquityHistoricalQueryParams(EquityHistoricalQueryParams):
    """TEJ Equity Historical Price Query."""

class TEJEquityHistoricalData(EquityHistoricalData):
    """TEJ Equity Historical Price Data."""
    # TEJ specific fields mapping to standard model
    # We might need to override field names if we want to show original names too,
    # but for now we map to standard fields.

class TEJEquityHistoricalFetcher(
    Fetcher[
        TEJEquityHistoricalQueryParams,
        List[TEJEquityHistoricalData],
    ]
):
    """TEJ Equity Historical Price Fetcher."""

    @staticmethod
    def transform_query(params: dict[str, Any]) -> TEJEquityHistoricalQueryParams:
        """Transform the query params."""
        transformed_params = params.copy()

        now = datetime.now().date()
        if params.get("start_date") is None:
            transformed_params["start_date"] = now - relativedelta(years=1)
        
        if params.get("end_date") is None:
            transformed_params["end_date"] = now

        return TEJEquityHistoricalQueryParams(**transformed_params)

    @staticmethod
    def extract_data(
        query: TEJEquityHistoricalQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> Any:
        """Return the raw data from the TEJ endpoint."""
        if credentials:
            # Map 'tej_api_key' (prefixed by openbb) to tejapi config
            api_key = credentials.get("tej_api_key")
            if api_key:
                tejapi.ApiConfig.api_key = api_key

        # Map query params to tejapi parameters
        # symbols: comma separated string to list
        tickers = query.symbol.split(",") if query.symbol else []
        
        # Prepare tejapi arguments for TWN/APRCD
        # coid: Stock ID
        # mdate: Date range
        # columns: Select specific columns to reduce data transfer
        
        tej_params = {
            "datatable_code": "TWN/APRCD",
            "coid": tickers,
            "mdate": {
                "gte": query.start_date,
                "lte": query.end_date,
            },
            "opts": {
                "columns": ["mdate", "open_d", "high_d", "low_d", "close_d", "volume"]
            },
            "paginate": True
        }

        try:
            data = tejapi.get(**tej_params)
        except Exception as e:
             # Wrap tejapi errors or re-raise
             raise RuntimeError(f"TEJ API Error: {str(e)}") from e

        return data

    @staticmethod
    def transform_data(
        query: TEJEquityHistoricalQueryParams, data: Any, **kwargs: Any
    ) -> List[TEJEquityHistoricalData]:
        """Return the transformed data."""
        # data is a pandas DataFrame from tejapi
        if data is None or data.empty:
             raise EmptyDataError("No data returned from TEJ for the given query.")

        # Rename columns to match EquityHistoricalData fields
        # TWN/APRCD columns: mdate, open_d, high_d, low_d, close_d, volume
        rename_map = {
            "mdate": "date",
            "open_d": "open",
            "high_d": "high",
            "low_d": "low",
            "close_d": "close",
            "volume": "volume", 
        }
        
        df = data.rename(columns=rename_map)
        
        # Convert to list of dicts for model validation
        records = df.to_dict("records")

        return [
            TEJEquityHistoricalData.model_validate(d) for d in records
        ]
