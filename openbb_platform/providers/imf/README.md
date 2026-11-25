# OpenBB IMF Provider Extension

This package adds the `openbb-imf` provider extension to the Open Data Platform by OpenBB.

It provides everything you need - endpoints, tools, and metadata - to access and explore the entirety of
<https://data.imf.org>, without any previous experience working with it.

## Installation

Install from PyPI with:

```sh
pip install openbb-imf
```

Then build the Python static assets by running:

```sh
openbb-build
```

The package also ships a precomputed IMF SDMX metadata catalog at
`openbb_imf/assets/imf_cache.json.xz`. Released wheels and sdists
carry it verbatim — it is materialized from `api.imf.org/external/sdmx/3.0`
by a Hatchling build hook (`hatch_build.py`) at packaging time. If the
IMF API is unreachable, the hook copies the catalog from the latest
`openbb-imf` wheel on PyPI instead, unless `OPENBB_IMF_FORCE_CACHE_REBUILD=1`
is set, in which case the build fails. End users have nothing to do;
developers can refresh it with either:

```sh
generate-imf-cache                                  # standalone script
OPENBB_IMF_FORCE_CACHE_REBUILD=1 pip install -e .   # via the build hook
```

## Quick Start

The fastest way to get started is by connecting to the OpenBB Workspace as a custom backend.

### Start Server

```sh
openbb-api
```

This starts the FastAPI server over localhost on port 6900.

### Add to Workspace

See the documentation [here](https://docs.openbb.co/python/quickstart/workspace) for more details.

### Click to Open App

Once added, click on the app to open the dashboard.

The dashboard contains widgets with metadata and information, as well ones for exploring and retrieving the data.

## Implementation Details

IMF is a SDMX API, and they organize their data by "dataflows". You can think of these as databases.
Each one has their own definitions for parameters and output. Some definitions are shared, others are domain-specific.
In SDMX, query models are expressed as dimensions, and data models as attributes.

The extension comes with a base level of metadata used for normalizing, translating, and validating inputs and outputs.
When mapping requires a code list that is not included, a network request is made to retrieve it.

User input is validated by calling the constraints API for each dimension.
The cached metadata contains all the potential values for parameters,
but the availability of each is determined by other choices - country, frequency, etc.
When making the actual request for data, parameters are tested for compatibility in the sequence defined by the data structure definition.
Invalid parameter combinations are returned as helpful error messages with descriptions of what went wrong and what the valid choices are.

The output converts ID codes into human-readable labels, and includes dataset and series metadata in a separate object.

### Indicators

In this library, we refer to indicators as "indicator-like" dimensions within individual dataflows.
It includes dimensions like `COICOP_1999`, so items such as CPI All Items, or Clothing and footwear,
are considered.

The IMF codes for these values - `_T`, `CP01`, etc. - are used to construct ticker-like symbols.

### Presentation Tables

Presentation tables are built from hierarchical code lists defining the parent-child relationship
between individual series.

Internally, table IDs are prefixed with `H_` - i.e, `H_BOP_BOP_AGG_STANDARD_PRESENTATION`.

The symbology allows entering references to tables, or indicators.

### Symbology

The Open Data Platform generally refers to all time series IDs as a `symbol`.
Requesting time series data or presentation tables requires a symbol constructed from
the dataflow ID and the indicator-like dimensions, split with `::`.

`CPI::CPI` returns all series for `CPI` under the `TYPE_OF_INDEX` dimension.

`CPI::CPI_CP01` returns just component of CPI, Food and non-alcoholic beverages.

The symbol mapper matches the items after `::` intelligently to its corresponding dimension.
Entering, `CPI::CP01`,  gets the same result as, `CPI::CPI_CP01`.

`CPI::CPI__T` returns just the top-level, All Items.

`CPI::H_CPI_BY_COMPONENT` returns the entire presentation table, Consumer Price Index (CPI) by Component.

Use, `obb.imf.list_tables()`, for a list of tables and their symbol.

Use, `obb.economy.available_indicators(provider='imf', ...)`, to search for, or list all, individual time series and symbols within specific dataflows.
(If `openbb-economy` is not installed, the same endpoints are aliased onto `obb.imf.available_indicators` / `obb.imf.indicators`.)

This example lists all the indicators in the CPI and PI dataflows.

```python
from openbb import obb

indicators = obb.economy.available_indicators(provider="imf", dataflows="CPI,PI")

print(indicators.to_dict("records"))
```

```sh
...
 {'symbol_root': 'CP01',
  'symbol': 'CPI::CP01',
  'description': 'Food and non-alcoholic beverages',
  'agency_id': 'IMF.STA',
  'dataflow_id': 'CPI',
  'dataflow_name': 'Consumer Price Index (CPI)',
  'structure_id': 'DSD_CPI',
  'dimension_id': 'COICOP_1999',
  'long_description': 'Food and non-alcholoic beverages consumer price index is produced using prices related to food items and non-alcoholic beverages such as fresh produce, packaged foods, and beverages excluding alcoholic drinks, aggregated by their respective consumer expenditure weights.',
  'member_of': ['CPI::H_CPI_BY_COMPONENT'],
  'extra_dimensions': ['TYPE_OF_TRANSFORMATION']}
...
```

## Coverage

All data available from <https://data.imf.org/en/Data-Explorer> can be retrieved, via `obb.economy.indicators(provider='imf', **kwargs)`. When `openbb-economy` is not installed, the same fetcher is aliased onto `obb.imf.indicators`.

Additionally, the extension exposes IMF Port Watch endpoints under `obb.imf.portwatch.*` — these cover country activity, monthly TradeNow indices, container metrics, and disruption events / sankey / map data sourced from the UN Global Platform / IMF Port Watch (not part of the SDMX Data Explorer).

The extension creates a router path, `imf`, that exposes presentation tables, the dataflow-aware indicator catalog, choice helpers for UI widgets, and the Port Watch subrouter.

### Endpoints

Data endpoints exposed via the standard `openbb-economy` routes when that extension is
installed (provider `imf`):

- `obb.economy.available_indicators` (provider `imf`)
- `obb.economy.indicators` (provider `imf`)
- `obb.economy.balance_of_payments` (provider `imf`)
- `obb.economy.cpi` (provider `imf`)
- `obb.economy.direction_of_trade` (provider `imf`)
- `obb.economy.shipping.chokepoint_info` (provider `imf`)
- `obb.economy.shipping.chokepoint_volume` (provider `imf`)
- `obb.economy.shipping.port_info` (provider `imf`)
- `obb.economy.shipping.port_volume` (provider `imf`)

When `openbb-economy` is absent the same fetchers register under IMF-prefixed model
names and the IMF router exposes equivalent paths: `obb.imf.available_indicators`,
`obb.imf.indicators`, `obb.imf.balance_of_payments`, `obb.imf.cpi`,
`obb.imf.direction_of_trade`, `obb.imf.port_info`, `obb.imf.port_volume`,
`obb.imf.chokepoint_info`, `obb.imf.chokepoint_volume`.

IMF-native endpoints (always under `obb.imf.*`):

- `obb.imf.list_dataflows`
- `obb.imf.list_dataflow_choices`
- `obb.imf.get_dataflow_dimensions`
- `obb.imf.list_tables`
- `obb.imf.list_table_choices`
- `obb.imf.presentation_table`
- `obb.imf.presentation_table_choices`
- `obb.imf.indicator_choices`
- `obb.imf.list_bop_country_choices`
- `obb.imf.list_cpi_country_choices`

IMF Port Watch endpoints (`obb.imf.portwatch.*` — UN Global Platform / IMF Port Watch
data not part of the SDMX Data Explorer):

- `obb.imf.portwatch.country_activity`
- `obb.imf.portwatch.monthly_trade`
- `obb.imf.portwatch.container_metrics`
- `obb.imf.portwatch.disruption_events`
- `obb.imf.portwatch.disruption_sankey`
- `obb.imf.portwatch.disruptions_map`
- `obb.imf.portwatch.list_port_id_choices`
- `obb.imf.portwatch.list_container_port_choices`
- `obb.imf.portwatch.list_country_choices`
- `obb.imf.portwatch.list_disruption_event_choices`
- `obb.imf.portwatch.list_tradenow_region_choices`

"Choices" endpoints are utilized by OpenBB Workspace to populate widget dropdown menus.
