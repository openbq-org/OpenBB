# OpenBB FINRA Provider

This extension integrates the public data of the [Financial Industry Regulatory Authority (FINRA)](https://www.finra.org/finra-data) into the OpenBB Platform.

Every dataset is read from FINRA's public services. **No API key or account is required.**

> This extension is not affiliated with, endorsed by, or authorized by FINRA.

## Installation

Install from PyPI:

```bash
pip install openbb-finra
```

Or from the source tree:

```bash
uv pip install -e openbb_platform/providers/finra
```

Then rebuild the Python interface:

```python
import openbb

openbb.build()
```

## Coverage

| Command | Description |
| ------- | ----------- |
| `equity.securities` | Every security FINRA publishes OTC or ATS volume for - stocks, ETFs, closed-end funds, and others - by type. |
| `equity.search` | Search stocks, ETFs, closed-end funds, and mutual funds by symbol, name, or ISIN. |
| `equity.profile` | Identifiers, classification, prices, dividends, valuation ratios, and volatility of securities. |
| `equity.darkpool.otc` | Weekly OTC and ATS share and trade volume - a symbol's full history, or the latest week of a tier. |
| `equity.shorts.short_interest` | Bi-monthly consolidated short interest and days to cover, back to 2017. |
| `fixedincome.bonds` | Every TRACE-reported bond of one type - CA, TS, TBA, MBS, ABS, or CMO - with its reference data and last sale. |
| `fixedincome.bond_prices` | Search TRACE-reported bonds - reference data with the last reported sale. |
| `fixedincome.bond_historical` | Daily end-of-day TRACE prices and yields of bonds. |

## Sources

**FINRA Query API** (`api.finra.org`) serves the OTC transparency and short interest datasets. Each symbol's full history is read in one request - the weekly summary back to December 2021, the consolidated short interest back to December 2017. Without a symbol, `equity.darkpool.otc` ranks every symbol of the tier's latest published week by share volume.

**The security list** is FINRA's traded universe - every symbol in the latest week of OTC and ATS volume for each tier, about 21,000 - classified by the bundled security types.
The classification of every symbol known at build time ships in `openbb_finra/assets/security_types.json.gz`, so a call reads the current universe in a handful of requests. A symbol that is new since the build is listed without a classification, because the Market Data Center lookup it came from now redirects to the FINRA Investments Explorer. It matches `security_type="all"` and `"other"` only, and a rebuild keeps the classification a symbol already has.
The asset is produced by the Hatchling build hook in `hatch_build.py`; it is reused when present and regenerated with `OPENBB_FINRA_FORCE_ASSET_REBUILD=1`, or at any time with `generate-finra-security-types`.

**FINRA Market Data Center** (`finra-markets.morningstar.com`) serves the security search and the reference profiles. Search matches ticker prefixes, words of names, and exact ISINs, capped by the service at between four and sixteen hits per security type. Profiles resolve tickers, CUSIPs, and Morningstar ids, up to 100 at a time.

**TRACE** (`services-dynarep.ddwa.finra.org`) serves the bond reference data, last sales, and end-of-day prices for corporate and agency bonds, Treasury notes and bonds, TBA contracts, and mortgage-backed, asset-backed, and collateralized mortgage obligation securities.

## Notes on the data

**Bond types are detected from identifiers.** `fixedincome.bond_prices` and `fixedincome.bond_historical` take CUSIPs or FINRA bond symbols, in any mix, and resolve each to its TRACE product in one request. Without identifiers, `bond_type` selects the product, and corporate and agency bonds are searched by default.

**Filters run on the server.** Issuer names match every word in any order, as substrings - `apple` finds `APPLE INC` and also `DR PEPPER SNAPPLE GROUP INC`.
Coupon, maturity, and last-sale yield bounds are applied by TRACE, and matured bonds are excluded unless `include_matured` is set.
For TBA and mortgage-backed securities, the issuer name matches the issuing agency. The mortgage-backed and CMO universes each hold millions of securities, so those searches need a filter or a `limit`.

**TRACE does not publish every standard field.** ISIN, LEI, currency, country, and issued amounts are not in the public datasets; passing them is an error rather than a silent no-op.

**Treasury history is on-the-run only.** End-of-day Treasury prices are published for the current benchmark notes and bonds. Other TRACE products carry about ten years of history.

**Values are passed through as published.** Rates and yields are percent numbers (`1.4` is 1.4%). Codes are decoded against FINRA's published code tables - coupon types, industry groups, and grades - and codes FINRA does not publish a decode for are passed through as they are.

## Standalone usage

The extension registers its own router, so installing `openbb-finra` alone still exposes every dataset under `/finra`.
The equity commands are served there only when `openbb-equity` is absent, and `fixedincome.bond_prices` only when `openbb-fixedincome` is absent; when they are installed, the same data is served through `obb.equity...` and `obb.fixedincome.corporate.bond_prices` with `provider="finra"`.

| Standard model | Owner | Standalone command |
| -------------- | ----- | ------------------ |
| `EquitySearch` | `openbb-equity` | `finra.equity.search` |
| `EquityInfo` | `openbb-equity` | `finra.equity.profile` |
| `OTCAggregate` | `openbb-equity` | `finra.equity.darkpool.otc` |
| `EquityShortInterest` | `openbb-equity` | `finra.equity.shorts.short_interest` |
| `BondPrices` | `openbb-fixedincome` | `finra.fixedincome.bond_prices` |

`finra.equity.securities`, `finra.fixedincome.bonds`, and `finra.fixedincome.bond_historical` have no standard model and are always served by this extension.

The fetchers can also be used directly, independent of the Python and API interfaces:

```python
from openbb_finra import finra_provider

finra_provider.fetcher_dict
```

## Example

```python
from openbb import obb

obb.finra.fixedincome.bond_prices(issuer_name="apple inc").to_df()
obb.finra.fixedincome.bond_historical(cusip="037833EH9").to_df()
obb.finra.equity.shorts.short_interest(symbol="AAPL").to_df()
```

## OpenBB Workspace

A bundled dashboard is served at `/api/v1/finra/apps.json`, with the widget IDs resolved against whichever extensions are installed. Start the API and add it as a Workspace backend:

```bash
openbb-api
```

The app has an equities tab - profile, short interest, and OTC volume linked by symbol, with the security search - and a bonds tab with the TRACE bond search and end-of-day history.

## Development

```bash
uv pip install -e '.'
uv pip install --group dev
pytest tests --cov=openbb_finra --cov-report=term-missing
```

The unit suite runs offline, replaying recorded FINRA responses from `tests/data`. Integration tests hit the live services and are excluded by default:

```bash
pytest integration -m integration
```

## OpenBB Documentation

OpenBB Platform documentation is available [here](https://docs.openbb.co/platform).

OpenBB Workspace documentation is available [here](https://docs.openbb.co/workspace).
