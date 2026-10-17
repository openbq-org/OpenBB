"""Test FRED fetchers."""

import datetime

import pytest
from openbb_core.app.service.user_service import UserService

from openbb_fred.models.ameribor import FredAmeriborFetcher
from openbb_fred.models.balance_of_payments import FredBalanceOfPaymentsFetcher
from openbb_fred.models.bond_indices import FredBondIndicesFetcher
from openbb_fred.models.commercial_paper import FREDCommercialPaperFetcher
from openbb_fred.models.commodity_spot_prices import FredCommoditySpotPricesFetcher
from openbb_fred.models.consumer_price_index import FREDConsumerPriceIndexFetcher
from openbb_fred.models.dwpcr_rates import FREDDiscountWindowPrimaryCreditRateFetcher
from openbb_fred.models.ecb_interest_rates import (
    FREDEuropeanCentralBankInterestRatesFetcher,
)
from openbb_fred.models.economic_calendar import FredEconomicCalendarFetcher
from openbb_fred.models.euro_short_term_rate import FredEuroShortTermRateFetcher
from openbb_fred.models.fed_projections import FREDPROJECTIONFetcher
from openbb_fred.models.federal_funds_rate import FredFederalFundsRateFetcher
from openbb_fred.models.ffrmc import FREDSelectedTreasuryConstantMaturityFetcher
from openbb_fred.models.high_quality_market import (
    FredHighQualityMarketCorporateBondFetcher,
)
from openbb_fred.models.iorb_rates import FREDIORBFetcher
from openbb_fred.models.manufacturing_outlook_ny import (
    FredManufacturingOutlookNYFetcher,
)
from openbb_fred.models.manufacturing_outlook_texas import (
    FredManufacturingOutlookTexasFetcher,
)
from openbb_fred.models.mortgage_indices import FredMortgageIndicesFetcher
from openbb_fred.models.non_farm_payrolls import FredNonFarmPayrollsFetcher
from openbb_fred.models.overnight_bank_funding_rate import (
    FredOvernightBankFundingRateFetcher,
)
from openbb_fred.models.personal_consumption_expenditures import (
    FredPersonalConsumptionExpendituresFetcher,
)
from openbb_fred.models.regional import FredRegionalDataFetcher
from openbb_fred.models.release_table import FredReleaseTableFetcher
from openbb_fred.models.retail_prices import FredRetailPricesFetcher
from openbb_fred.models.search import (
    FredSearchFetcher,
)
from openbb_fred.models.senior_loan_officer_survey import (
    FredSeniorLoanOfficerSurveyFetcher,
)
from openbb_fred.models.series import FredSeriesFetcher
from openbb_fred.models.sofr import FREDSOFRFetcher
from openbb_fred.models.sonia_rates import FREDSONIAFetcher
from openbb_fred.models.spot import FREDSpotRateFetcher
from openbb_fred.models.survey_of_economic_conditions_chicago import (
    FredSurveyOfEconomicConditionsChicagoFetcher,
)
from openbb_fred.models.tbffr import FREDSelectedTreasuryBillFetcher
from openbb_fred.models.tips_yields import FredTipsYieldsFetcher
from openbb_fred.models.tmc import FREDTreasuryConstantMaturityFetcher
from openbb_fred.models.university_of_michigan import FredUofMichiganFetcher
from openbb_fred.models.yield_curve import FREDYieldCurveFetcher

test_credentials = UserService().default_user_settings.credentials.model_dump(
    mode="json"
)
test_credentials["fred_api_key"] = (
    test_credentials.get("fred_api_key") or "MOCK_API_KEY"
)


def decompress_body(response):
    """Decompress a recorded response body, dropping its encoding header only on success."""
    import zlib

    headers = response.get("headers", {})
    encodings = [k for k in headers if k.lower() == "content-encoding"]
    body = response.get("body", {}).get("string")
    decompressed = False

    if encodings and isinstance(body, bytes):
        for wbits in (16 + zlib.MAX_WBITS, -zlib.MAX_WBITS):
            try:
                response["body"]["string"] = zlib.decompress(body, wbits)
                decompressed = True
                break
            except zlib.error:
                continue

    if decompressed:
        for key in encodings:
            headers.pop(key)

    return response


def scrub_response_cookies(response):
    """Drop every response cookie header so bot-detection sessions are never recorded."""
    headers = response.get("headers", {})

    for key in [k for k in headers if k.lower() == "set-cookie"]:
        headers.pop(key)

    return response


@pytest.fixture(scope="module")
def vcr_config():
    """VCR config."""
    return {
        "filter_headers": [
            ("User-Agent", None),
            ("Cookie", None),
        ],
        "filter_query_parameters": [
            ("api_key", "MOCK_API_KEY"),
        ],
        "before_record_response": [decompress_body, scrub_response_cookies],
    }


class TestFredRateFetchers:
    """Replay the recorded reference rate and policy rate fetchers."""

    @pytest.mark.record_http
    def test_fred_sofr_fetcher(self, credentials=test_credentials):
        """Test FREDSOFRFetcher."""
        params = {
            "start_date": datetime.date(2024, 6, 1),
            "end_date": datetime.date(2024, 6, 6),
        }

        fetcher = FREDSOFRFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_euro_short_term_rate_fetcher(self, credentials=test_credentials):
        """Test FREDEuroShortTermRateFetcher."""
        params = {
            "start_date": datetime.date(2024, 6, 1),
            "end_date": datetime.date(2024, 6, 6),
        }

        fetcher = FredEuroShortTermRateFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fredsonia_fetcher(self, credentials=test_credentials):
        """Test FREDSONIAFetcher."""
        params = {}

        fetcher = FREDSONIAFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_ameribor_fetcher(self, credentials=test_credentials):
        """Test FredAmeriborFetcher."""
        params = {
            "start_date": datetime.date(2023, 1, 1),
            "end_date": datetime.date(2023, 6, 6),
            "maturity": "overnight",
        }

        fetcher = FredAmeriborFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_federal_funds_rate_fetcher(self, credentials=test_credentials):
        """Test FRED Federal Funds Rate Fetcher."""
        params = {
            "start_date": datetime.date(2023, 1, 1),
            "end_date": datetime.date(2023, 6, 6),
            "effr_only": True,
        }

        fetcher = FredFederalFundsRateFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fredprojection_fetcher(self, credentials=test_credentials):
        """Test FREDPROJECTIONFetcher."""
        params = {}

        fetcher = FREDPROJECTIONFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_frediorb_fetcher(self, credentials=test_credentials):
        """Test FREDIORBFetcher."""
        params = {}

        fetcher = FREDIORBFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_discount_window_primary_credit_rate_fetcher(
        self, credentials=test_credentials
    ):
        """Test FREDDiscountWindowPrimaryCreditRateFetcher."""
        params = {
            "start_date": datetime.date(2023, 1, 1),
            "end_date": datetime.date(2023, 6, 6),
        }

        fetcher = FREDDiscountWindowPrimaryCreditRateFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_european_central_bank_interest_rates_fetcher(
        self,
        credentials=test_credentials,
    ):
        """Test FREDEuropeanCentralBankInterestRatesFetcher."""
        params = {
            "start_date": datetime.date(2023, 1, 1),
            "end_date": datetime.date(2023, 6, 6),
        }

        fetcher = FREDEuropeanCentralBankInterestRatesFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_commercial_paper_fetcher(self, credentials=test_credentials):
        """Test FREDCommercialPaperFetcher."""
        params = {
            "start_date": datetime.date(2024, 1, 1),
            "end_date": datetime.date(2024, 2, 1),
            "category": "asset_backed",
            "maturity": "30d",
        }

        fetcher = FREDCommercialPaperFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_overnight_bank_funding_rate_fetcher(
        self, credentials=test_credentials
    ):
        """Test FRED Overnight Bank Funding Rate Fetcher."""
        params = {
            "start_date": datetime.date(2024, 6, 1),
            "end_date": datetime.date(2024, 6, 6),
        }

        fetcher = FredOvernightBankFundingRateFetcher()
        result = fetcher.test(params, credentials)
        assert result is None


class TestFredFixedIncomeFetchers:
    """Replay the recorded treasury, corporate and mortgage curve fetchers."""

    @pytest.mark.record_http
    def test_fred_spot_rate_fetcher(self, credentials=test_credentials):
        """Test FREDSpotRateFetcher."""
        params = {
            "start_date": datetime.date(2023, 1, 1),
            "end_date": datetime.date(2023, 6, 6),
        }

        fetcher = FREDSpotRateFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_high_quality_market_corporate_bond_fetcher(
        self, credentials=test_credentials
    ):
        """Test FredHighQualityMarketCorporateBondFetcher."""
        params = {"date": "2023-01-01"}

        fetcher = FredHighQualityMarketCorporateBondFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_treasury_constant_maturity_fetcher(
        self, credentials=test_credentials
    ):
        """Test FREDTreasuryConstantMaturityFetcher."""
        params = {
            "start_date": datetime.date(2023, 1, 1),
            "end_date": datetime.date(2023, 6, 6),
        }

        fetcher = FREDTreasuryConstantMaturityFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_selected_treasury_constant_maturity_fetcher(
        self, credentials=test_credentials
    ):
        """Test FREDSelectedTreasuryConstantMaturityFetcher."""
        params = {
            "start_date": datetime.date(2023, 1, 1),
            "end_date": datetime.date(2023, 6, 6),
        }

        fetcher = FREDSelectedTreasuryConstantMaturityFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_selected_treasury_bill_fetcher(self, credentials=test_credentials):
        """Test FREDSelectedTreasuryBillFetcher."""
        params = {
            "start_date": datetime.date(2023, 1, 1),
            "end_date": datetime.date(2023, 6, 6),
        }

        fetcher = FREDSelectedTreasuryBillFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_yield_curve_fetcher(self, credentials=test_credentials):
        """Test FREDYieldCurveFetcher."""
        params = {"date": "2024-05-14,2023-05-14,2022-03-16,2021-05-14,2020-05-14"}

        fetcher = FREDYieldCurveFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_bond_indices_fetcher(self, credentials=test_credentials):
        """Test FredBondIndicesFetcher."""
        params = {
            "category": "us",
            "index": "corporate",
            "start_date": datetime.date(2024, 6, 1),
            "end_date": datetime.date(2024, 6, 4),
        }

        fetcher = FredBondIndicesFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_mortgage_indices_fetcher(self, credentials=test_credentials):
        """Test FredMortgageIndicesFetcher."""
        params = {
            "index": "jumbo_30y",
            "start_date": datetime.date(2024, 6, 1),
            "end_date": datetime.date(2024, 6, 4),
        }

        fetcher = FredMortgageIndicesFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_tips_yields_fetcher(self, credentials=test_credentials):
        """Test FRED TIPS Yields."""
        params = {
            "start_date": datetime.date(2024, 7, 17),
            "end_date": datetime.date(2024, 7, 17),
            "maturity": "10",
        }

        fetcher = FredTipsYieldsFetcher()
        result = fetcher.test(params, credentials)
        assert result is None


class TestFredEconomyFetchers:
    """Replay the recorded macroeconomic indicator fetchers."""

    @pytest.mark.record_http
    def test_fredcpi_fetcher(self, credentials=test_credentials):
        """Test FREDConsumerPriceIndexFetcher."""
        params = {"country": "portugal,spain"}

        fetcher = FREDConsumerPriceIndexFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_regional_fetcher(self, credentials=test_credentials):
        """Test FredRegionalFetcher."""
        params = {
            "symbol": "942",
            "is_series_group": True,
            "start_date": datetime.date(1975, 1, 1),
            "frequency": "q",
            "units": "Index 1980:Q1=100",
            "region_type": "state",
            "season": "nsa",
        }

        fetcher = FredRegionalDataFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_balance_of_payments_fetcher(self, credentials=test_credentials):
        """Test FredBalanceOfPaymentsFetcher."""
        params = {
            "country": "united_states",
            "start_date": datetime.date(2020, 1, 1),
            "end_date": datetime.date(2024, 3, 31),
        }

        fetcher = FredBalanceOfPaymentsFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_retail_prices_fetcher(self, credentials=test_credentials):
        """Test FREDRetailPricesFetcher."""
        params = {"item": "eggs", "start_date": datetime.date(2024, 1, 1)}

        fetcher = FredRetailPricesFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_non_farm_payrolls_fetcher(self, credentials=test_credentials):
        """Test FredNonFarmPayrollsFetcher."""
        params = {
            "date": "2024-06-01",
            "category": "avg_earnings_weekly",
        }

        fetcher = FredNonFarmPayrollsFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_personal_consumption_expenditures_fetcher(
        self, credentials=test_credentials
    ):
        """Test FRED Personal Consumption Expenditures Fetcher."""
        params = {
            "date": "2024-05-01",
            "category": "pce_price_index",
        }

        fetcher = FredPersonalConsumptionExpendituresFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_commodity_spot_prices_fetcher(self, credentials=test_credentials):
        """Test FRED Commodity Spot Prices."""
        params = {
            "start_date": datetime.date(2024, 7, 1),
            "end_date": datetime.date(2024, 7, 10),
            "commodity": "natural_gas",
        }

        fetcher = FredCommoditySpotPricesFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_economic_calendar_fetcher(self, credentials=test_credentials):
        """Test FRED Economic Calendar Fetcher."""
        params = {
            "start_date": datetime.date(2025, 7, 1),
            "end_date": datetime.date(2025, 7, 2),
        }

        fetcher = FredEconomicCalendarFetcher()
        result = fetcher.test(params, credentials)
        assert result is None


class TestFredSurveyFetchers:
    """Replay the recorded sentiment and regional Fed survey fetchers."""

    @pytest.mark.record_http
    def test_fred_university_of_michigan_fetcher(self, credentials=test_credentials):
        """Test FredUofMichiganFetcher."""
        params = {
            "start_date": datetime.date(2022, 6, 1),
            "end_date": datetime.date(2024, 5, 31),
        }

        fetcher = FredUofMichiganFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_senior_loan_officer_survey_fetcher(
        self, credentials=test_credentials
    ):
        """Test FredSeniorLoanOfficerSurveyFetcher."""
        params = {
            "category": "auto",
            "start_date": datetime.date(2022, 6, 1),
            "end_date": datetime.date(2024, 5, 31),
        }

        fetcher = FredSeniorLoanOfficerSurveyFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_survey_of_economic_conditions_chicago_fetcher(
        self,
        credentials=test_credentials,
    ):
        """Test FredSurveyOfEconomicConditionsChicagoFetcher."""
        params = {
            "start_date": datetime.date(2024, 3, 1),
            "end_date": datetime.date(2024, 5, 31),
        }

        fetcher = FredSurveyOfEconomicConditionsChicagoFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_manufacturing_outlook_texas_fetcher(
        self,
        credentials=test_credentials,
    ):
        """Test FredManufacturingOutlookTexasFetcher."""
        params = {
            "start_date": datetime.date(2024, 3, 1),
            "end_date": datetime.date(2024, 5, 31),
        }

        fetcher = FredManufacturingOutlookTexasFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_manufacturing_outlook_ny_fetcher(self, credentials=test_credentials):
        """Test FRED manufacturing outlook NY fetcher."""
        params = {
            "start_date": datetime.date(2024, 6, 30),
            "end_date": datetime.date(2024, 10, 1),
            "topic": "hours_worked",
        }

        fetcher = FredManufacturingOutlookNYFetcher()
        result = fetcher.test(params, credentials)
        assert result is None


class TestFredNativeFetchers:
    """Replay the recorded FRED-native search, series and release table fetchers."""

    @pytest.mark.record_http
    def test_fred_search_fetcher(self, credentials=test_credentials):
        """Test FredSearchFetcher."""
        params = {
            "query": "leading index",
            "limit": 20,
            "tag_names": "gdp",
            "exclude_tag_names": "oecd",
        }

        fetcher = FredSearchFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_series_fetcher(self, credentials=test_credentials):
        """Test FredSeriesFetcher."""
        params = {
            "symbol": "SP500",
            "filter_variable": "frequency",
            "filter_value": "w",
        }

        fetcher = FredSeriesFetcher()
        result = fetcher.test(params, credentials)
        assert result is None

    @pytest.mark.record_http
    def test_fred_release_table_fetcher(self, credentials=test_credentials):
        """Test FredReleaseTableFetcher."""
        params = {
            "date": "2024-07-14",
            "release_id": "483",
            "element_id": "1217633",
        }

        fetcher = FredReleaseTableFetcher()
        result = fetcher.test(params, credentials)
        assert result is None
