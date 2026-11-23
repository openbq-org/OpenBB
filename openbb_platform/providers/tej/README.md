# TEJ Provider

This package provides access to Taiwan Economic Journal (TEJ) data within the OpenBB Platform.

> **Note:** TEJ primarily provides market data for companies listed on the Taiwan Stock Exchange (TWSE) and Taipei Exchange (TPEx).

## Installation

```bash
pip install openbb-tej
```

## Used Tej Tables

- TWN/AINVFINA for financial statements
- TWN/APRCD for stock prices

## Credentials

You need a TEJ API key to use this provider.
-   **Environment Variable**: `OPENBB_TEJ_API_KEY`
-   **OpenBB Settings**: `tej_api_key`

## To Get Trial API Key

Go to [TEJ Website](https://api.tej.com.tw/trial.html)
