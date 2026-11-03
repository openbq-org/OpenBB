"""Common descriptions for model fields."""

QUERY_DESCRIPTIONS = {
    "symbol": "Symbol to get data for.",
    "start_date": "Start date of the data, in YYYY-MM-DD format.",
    "end_date": "End date of the data, in YYYY-MM-DD format.",
    "interval": "Time interval of the data to return.",
    "period": "Time period of the data to return.",
    "date": "A specific date to get data for.",
    "as_of_date": "Point-in-time date (YYYY-MM-DD) to return data as it was known on that date.",
    "limit": "The number of data entries to return.",
    "country": "The country to get data.",
    "countries": "The country or countries to get data.",
    "units": "The unit of measurement for the data.",
    "frequency": "The frequency of the data.",
}

DATA_DESCRIPTIONS = {
    "symbol": "Symbol representing the entity requested in the data.",
    "cik": "Central Index Key (CIK) for the requested entity.",
    "date": "The date of the data.",
    "open": "The open price.",
    "high": "The high price.",
    "low": "The low price.",
    "close": "The close price.",
    "volume": "The trading volume.",
    "adj_close": "The adjusted close price.",
    "vwap": "Volume Weighted Average Price over the period.",
    "prev_close": "The previous close price.",
}
