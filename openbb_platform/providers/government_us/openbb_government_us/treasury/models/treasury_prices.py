"""US Government Treasury Prices."""

from datetime import date as dateType
from typing import Any, Literal

from openbb_core.app.model.abstract.error import OpenBBError
from openbb_core.provider.abstract.fetcher import Fetcher
from openbb_core.provider.standard_models.treasury_prices import (
    TreasuryPricesData,
    TreasuryPricesQueryParams,
)
from openbb_core.provider.utils.errors import EmptyDataError
from pydantic import Field

from openbb_government_us.utils.serializers import OmitNoneMixin


class UsTreasuryPricesQueryParams(TreasuryPricesQueryParams):
    """US Government Treasury Prices Query."""

    cusip: str | None = Field(description="Filter by CUSIP.", default=None)
    security_type: Literal["bill", "note", "bond", "tips", "frn"] | None = Field(
        description="Filter by security type.",
        default=None,
    )


class UsTreasuryPricesData(OmitNoneMixin, TreasuryPricesData):
    """US Government Treasury Prices Data."""

    date: dateType = Field(
        description="The price date the quotes were sourced for.",
    )


class UsTreasuryPricesFetcher(
    Fetcher[
        UsTreasuryPricesQueryParams,
        list[UsTreasuryPricesData],
    ]
):
    """US Government Treasury Prices Fetcher."""

    @staticmethod
    def transform_query(
        params: dict[str, Any],
    ) -> UsTreasuryPricesQueryParams:
        """Transform query params."""
        from datetime import date, timedelta

        today = date.today()
        last_bd = (
            today - timedelta(today.weekday() - 4) if today.weekday() > 4 else today
        )
        if params.get("date") is None:
            params["date"] = last_bd
        return UsTreasuryPricesQueryParams(**params)

    @staticmethod
    def extract_data(
        query: UsTreasuryPricesQueryParams,
        credentials: dict[str, str] | None,
        **kwargs: Any,
    ) -> str:
        """Extract the raw data from US Treasury website."""
        import re

        from openbb_core.provider.utils.helpers import (
            get_requests_session,
            make_request,
        )

        from openbb_government_us.treasury.utils.helpers import get_random_agent

        # FedInvest answers 403 to the download unless it carries the session cookie
        # and CSRF token of the price form. The cookies are set for the www host.
        base = "https://www.treasurydirect.gov/GA-FI/FedInvest/"
        url = base + "securityPriceDetail"

        HEADERS = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-CA,en-US;q=0.7,en;q=0.3",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": base + "selectSecurityPriceDate",
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://www.treasurydirect.gov",
            "User-Agent": get_random_agent(),
        }

        payload = (
            f"priceDateDay={query.date.day}"  # type: ignore
            f"&priceDateMonth={query.date.month}"  # type: ignore
            f"&priceDateYear={query.date.year}"  # type: ignore
            "&fileType=csv"
            "&csv=CSV+FORMAT"
        )

        session = get_requests_session()
        form = make_request(
            url=base + "selectSecurityPriceDate", headers=HEADERS, session=session
        )

        if form.status_code != 200:
            raise OpenBBError("Error with the request: " + str(form.status_code))

        token = re.search(r'name="_csrf" value="([^"]+)"', form.text)

        if token is None:
            raise OpenBBError("The Treasury price form carried no CSRF token.")

        r = make_request(
            url=url,
            method="POST",
            headers=HEADERS,
            data=payload + "&_csrf=" + token.group(1),
            session=session,
        )

        if r.status_code != 200:
            raise OpenBBError("Error with the request: " + str(r.status_code))

        if r.encoding != "ISO-8859-1":
            raise OpenBBError(f"Expected ISO-8859-1 encoding but got: {r.encoding}")

        return r.content.decode("utf-8")

    @staticmethod
    def transform_data(
        query: UsTreasuryPricesQueryParams,
        data: str,
        **kwargs: Any,
    ) -> list[UsTreasuryPricesData]:
        """Transform the data."""
        from math import isnan  # noqa
        from io import StringIO
        from pandas import Index, read_csv, to_datetime

        try:
            if not data:
                raise EmptyDataError("Data not found")
            results = read_csv(StringIO(data), header=0)
            results.columns = Index(
                [
                    "cusip",
                    "security_type",
                    "rate",
                    "maturity_date",
                    "call_date",
                    "bid",
                    "offer",
                    "eod_price",
                ]
            )
            results["date"] = query.date.strftime("%Y-%m-%d")  # type: ignore
            for col in ["maturity_date", "call_date"]:
                results[col] = (
                    (
                        to_datetime(results[col], format="%m/%d/%Y").dt.strftime(
                            "%Y-%m-%d"
                        )
                    )
                    .fillna("-")
                    .replace("-", None)
                )

        except Exception as e:
            raise OpenBBError(e) from e

        if query.security_type is not None:
            results = results[
                results["security_type"].str.contains(query.security_type, case=False)
            ]
        if query.cusip is not None:
            results = results[results["cusip"] == query.cusip]

        def clean_nan(d: dict) -> dict:
            """Replace nan values with None for Pydantic validation."""
            return {
                k: None if isinstance(v, float) and isnan(v) else v
                for k, v in d.items()
            }

        return [
            UsTreasuryPricesData.model_validate(clean_nan(d))
            for d in results.to_dict("records")
        ]
