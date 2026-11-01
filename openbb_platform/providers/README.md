# Providers

In this folder you can find the providers that were created or are supported by OpenBB.

## Recommended structure

Every provider is located within a directory, with the following structure:

```{.bash}
openbb_platform
└───providers
    └───<provider_name>
        |   README.md
        │   pyproject.toml
        │   uv.lock
        |───tests
        └───openbb_<provider_name>
            │   __init__.py
            |───models
            |   |───<some model>.py
            |   └───...
            └───utils
                |───<some helper>.py
                └───...
```

The models define the data structures that are used to query the provider endpoints and store the response data.

## Available providers

The directory already includes several first-party providers, for example:

- `cryptocompare/` – real-time and historical cryptocurrency data via CryptoCompare.
- `polygon/` – US market equities, forex, and crypto data from Polygon.io.
- `fmp/` – Financial Modeling Prep fundamentals, market data, and news.

See [CONTRIBUTING file](../CONTRIBUTING.md) for more details
