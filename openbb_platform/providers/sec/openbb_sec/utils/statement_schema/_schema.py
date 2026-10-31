"""StatementSchema class: loads the split JSON schema and orchestrates extraction."""

from __future__ import annotations

import dataclasses
import json
import re
from collections import Counter
from typing import Any

from openbb_core.app.model.abstract.error import OpenBBError

from openbb_sec.utils.statement_schema._detection import (
    detect_reporting_currency,
    detect_type,
    filter_facts_as_of,
    get_filing_dates,
    get_fiscal_meta,
    preliminary_view,
)
from openbb_sec.utils.statement_schema._extraction import (
    compute_period_pit_meta,
    compute_ref_filings,
    extract_row_values,
    rescaled_facts,
)
from openbb_sec.utils.statement_schema._imputation import (
    _apply_hierarchical_articulation,
    enforce_identities,
    identity_diagnostics,
    impute,
    reconcile_fiscal_year_ends,
    reported_derived,
)
from openbb_sec.utils.statement_schema._rules import CF_SIGN_KEEP, CHAIN_SUBSETS
from openbb_sec.utils.statement_schema._types import (
    _SCHEMAS_DIR,
    QUARTERLY_FORMS,
    SEMI_ANNUAL_FORMS,
    CompanyType,
    Frequency,
    PreliminaryFacts,
    RowDef,
    RowResult,
    ScaledFacts,
    StatementName,
    StatementResult,
    ValidationWarning,
    _tolerance,
)

# CECL provision reconstruction: filers such as Bank of America report a single
# income-statement "provision for credit losses" line that combines the funded
# (financing-receivable) provision with the off-balance-sheet (unfunded
# commitment) provision, tagging the combined total with a company-specific
# extension absent from Company Facts. Only the standard component tags survive,
# so the standardized total is rebuilt as funded + unfunded for those filers.
_PROVISION_ROW_TAGS = ("provision_for_credit_losses", "provision_for_loan_losses")
_PROVISION_FUNDED_SOURCES = (
    "FinancingReceivableExcludingAccruedInterestCreditLossExpenseReversal",
    "ProvisionForLoanLossesExpensed",
)
_UNFUNDED_PROVISION_TAG = "OffBalanceSheetCreditLossLiabilityCreditLossExpenseReversal"


class StatementSchema:
    """Schema for standardized financial statement extraction."""

    def __init__(self) -> None:
        with open(_SCHEMAS_DIR / "_meta.json") as f:
            meta = json.load(f)

        self._version: str = meta.get("version", "unknown")
        self._generated: str = meta.get("generated", "unknown")
        self._detection: dict = meta.get("detection", {})

        self._statements: dict = {}
        for stmt_file in ("income_statement", "balance_sheet", "cash_flow"):
            with open(_SCHEMAS_DIR / f"{stmt_file}.json") as f:
                self._statements[stmt_file] = json.load(f)

        self._row_defs: dict[str, dict[str, list[RowDef]]] = {}

        for stmt_name, types in self._statements.items():
            self._row_defs[stmt_name] = {}

            for stype, rows in types.items():
                self._row_defs[stmt_name][stype] = [
                    RowDef(
                        tag=r["tag"],
                        label=r["label"],
                        description=r.get("description", ""),
                        parent=r.get("parent"),
                        sequence=r.get("sequence", 0),
                        factor=r.get("factor", "+"),
                        balance=r.get("balance", ""),
                        unit=r.get("unit", "monetary"),
                        period_type=r["period_type"],
                        xbrl_tags=tuple(
                            {"tag": x["tag"], "namespace": x["namespace"]}
                            for x in r["xbrl_tags"]
                        ),
                    )
                    for r in rows
                ]

        self._insurance_is_signals: list[str] = self._detection.get(
            "insurance_is_signals", []
        )
        self._insurance_bs_signals: list[str] = self._detection.get(
            "insurance_bs_signals", []
        )
        self._financial_signals: list[str] = self._detection.get(
            "financial_signals", []
        )
        self._diversified_signals: list[str] = self._detection.get(
            "diversified_signals", []
        )
        self._industrial_signals: list[str] = self._detection.get(
            "industrial_signals", []
        )
        self._min_financial_signals: int = self._detection.get(
            "min_financial_signals", 2
        )
        self._measures: dict[str, list[str]] = self._detection.get("measures", {})
        self._min_insurance_share: float = self._detection.get(
            "min_insurance_share", 0.0
        )
        self._min_financial_share: float = self._detection.get(
            "min_financial_share", 0.0
        )

    @property
    def version(self) -> str:
        return self._version

    @property
    def generated(self) -> str:
        return self._generated

    def get_rows(
        self, statement: StatementName, company_type: CompanyType
    ) -> list[RowDef]:
        return self._row_defs.get(statement, {}).get(company_type, [])

    def get_row(
        self, tag: str, statement: StatementName, company_type: CompanyType
    ) -> RowDef | None:
        for row in self.get_rows(statement, company_type):
            if row.tag == tag:
                return row
        return None

    def get_tag_chain(
        self, tag: str, statement: StatementName, company_type: CompanyType
    ) -> tuple[dict[str, str], ...]:
        row = self.get_row(tag, statement, company_type)
        return row.xbrl_tags if row else ()

    def get_period_type(
        self, tag: str, statement: StatementName, company_type: CompanyType
    ) -> str | None:
        row = self.get_row(tag, statement, company_type)
        return row.period_type if row else None

    def detect_type(self, facts: dict[str, Any]) -> CompanyType:
        return detect_type(
            facts,
            insurance_is_signals=self._insurance_is_signals,
            insurance_bs_signals=self._insurance_bs_signals,
            financial_signals=self._financial_signals,
            diversified_signals=self._diversified_signals,
            industrial_signals=self._industrial_signals,
            min_financial_signals=self._min_financial_signals,
            revenue_measures=self._measures.get("revenue", []),
            insurance_measures=self._measures.get("insurance", []),
            financial_measures=self._measures.get("financial", []),
            min_insurance_share=self._min_insurance_share,
            min_financial_share=self._min_financial_share,
        )

    def get_filing_dates(
        self,
        facts: dict[str, Any],
        frequency: Frequency = "annual",
        include_preliminary: bool = False,
    ) -> set[str]:
        return get_filing_dates(
            facts, frequency, include_preliminary=include_preliminary
        )

    def get_fiscal_meta(
        self,
        facts: dict[str, Any],
        frequency: Frequency,
        dates: set[str],
    ) -> dict[str, dict[str, Any]]:
        return get_fiscal_meta(facts, frequency, dates)

    def _detect_reporting_currency(self, facts: dict[str, Any]) -> str:
        return detect_reporting_currency(facts)

    @staticmethod
    def _preliminary_facts(
        facts: dict[str, Any],
        include_preliminary: bool,
        pit_mode: bool,
        as_of_date: Any = None,
    ) -> dict[str, Any]:
        """Return facts restated at each filer's scale, in the preliminary view when preliminary data is requested."""
        if as_of_date is not None:
            facts = filter_facts_as_of(facts, as_of_date)

        if not isinstance(facts, (ScaledFacts, PreliminaryFacts)):
            facts = rescaled_facts(facts)

        if not include_preliminary or (
            isinstance(facts, PreliminaryFacts) and facts.pit_mode == pit_mode
        ):
            return facts
        return preliminary_view(facts, pit_mode)

    def _compute_ref_filings(
        self,
        facts: dict[str, Any],
        rows_def: list[RowDef],
        frequency: Frequency,
        currency: str,
        include_preliminary: bool = False,
        pit_mode: bool = False,
    ) -> dict[str, str]:
        return compute_ref_filings(
            facts,
            rows_def,
            frequency,
            currency,
            include_preliminary=include_preliminary,
            pit_mode=pit_mode,
        )

    def extract_row_values(
        self,
        facts: dict[str, Any],
        row_def: RowDef,
        frequency: Frequency,
        currency: str,
        ref_filed_map: dict[str, str] | None = None,
        cross_targets: dict[str, float] | None = None,
        statement: StatementName | None = None,
        include_preliminary: bool = False,
        annual_ref_map: dict[str, str] | None = None,
    ) -> tuple[dict[str, float], dict[str, str]]:
        return extract_row_values(
            facts,
            row_def,
            frequency,
            currency,
            ref_filed_map=ref_filed_map,
            cross_targets=cross_targets,
            statement=statement or "",
            include_preliminary=include_preliminary,
            annual_ref_map=annual_ref_map,
        )

    def extract(  # noqa: PLR0912
        self,
        company_facts: dict[str, Any],
        statement: StatementName,
        *,
        frequency: Frequency = "annual",
        company_type: CompanyType | None = None,
        filing_dates: set[str] | None = None,
        skip_imputation: bool = False,
        ref_filed_map: dict[str, str] | None = None,
        cross_identities: dict[str, dict[str, float]] | None = None,
        pit_mode: bool = False,
        include_preliminary: bool = False,
        annual_ref_map: dict[str, str] | None = None,
        as_of_date: Any = None,
    ) -> StatementResult:
        facts = self._preliminary_facts(
            company_facts.get("facts", company_facts),
            include_preliminary,
            pit_mode,
            as_of_date=as_of_date,
        )

        if company_type is None:
            company_type = self.detect_type(facts)

        if filing_dates is None:
            filing_dates = self.get_filing_dates(
                facts, frequency, include_preliminary=include_preliminary
            )

        _preliminary_dates: set[str] = set()
        if include_preliminary:
            confirmed_dates = self.get_filing_dates(facts, frequency)
            _preliminary_dates = filing_dates - confirmed_dates

        currency = self._detect_reporting_currency(facts)
        rows_def = self.get_rows(statement, company_type)
        result_rows: list[RowResult] = []

        if ref_filed_map is None:
            ref_filed_map = self._compute_ref_filings(
                facts,
                rows_def,
                frequency,
                currency,
                include_preliminary=include_preliminary,
                pit_mode=pit_mode,
            )

        if statement == "balance_sheet":
            ref_filed_map = dict(ref_filed_map)

            for anchor_tag in ("total_assets", "total_liabilities_and_equity"):
                ref_filed_map.update(
                    self._compute_ref_filings(
                        facts,
                        [rd for rd in rows_def if rd.tag == anchor_tag],
                        frequency,
                        currency,
                        include_preliminary=include_preliminary,
                        pit_mode=pit_mode,
                    )
                )

        if frequency == "quarterly" and annual_ref_map is None:
            annual_ref_map = self._compute_ref_filings(
                facts,
                rows_def,
                "annual",
                currency,
                include_preliminary=include_preliminary,
                pit_mode=pit_mode,
            )

        apply_cf_sign = statement == "cash_flow"

        for row_def in rows_def:
            cross_targets = (
                cross_identities.get(row_def.tag) if cross_identities else None
            )
            values, sources = self.extract_row_values(
                facts,
                row_def,
                frequency,
                currency,
                ref_filed_map,
                cross_targets,
                statement,
                include_preliminary=include_preliminary,
                annual_ref_map=annual_ref_map,
            )
            values = {d: v for d, v in values.items() if d in filing_dates}
            sources = {d: s for d, s in sources.items() if d in filing_dates}

            for broad, narrow in CHAIN_SUBSETS.get(row_def.tag, ()):
                narrow_ns, narrow_tag = narrow.split(":")
                narrow_values, narrow_sources = self.extract_row_values(
                    facts,
                    dataclasses.replace(
                        row_def,
                        xbrl_tags=({"tag": narrow_tag, "namespace": narrow_ns},),
                    ),
                    frequency,
                    currency,
                    ref_filed_map,
                    None,
                    statement,
                    include_preliminary=include_preliminary,
                    annual_ref_map=annual_ref_map,
                )
                broad_pattern = re.compile(re.escape(broad) + r"(?![A-Za-z])")

                for d, v in list(values.items()):
                    n_val = narrow_values.get(d)

                    if (
                        n_val is not None
                        and broad_pattern.search(sources.get(d, ""))
                        and n_val - v > _tolerance(n_val, v)
                    ):
                        values[d] = n_val
                        sources[d] = narrow_sources.get(d, narrow)

            if (
                apply_cf_sign
                and row_def.balance == "credit"
                and row_def.factor != "0"
                and row_def.tag not in CF_SIGN_KEEP
            ):
                values = {d: (-v or 0) for d, v in values.items()}

            result_rows.append(
                RowResult(
                    tag=row_def.tag,
                    label=row_def.label,
                    description=row_def.description,
                    parent=row_def.parent,
                    sequence=row_def.sequence,
                    factor=row_def.factor,
                    balance=row_def.balance,
                    unit=row_def.unit,
                    period_type=row_def.period_type,
                    values=values,
                    sources=sources,
                )
            )

        self._combine_unfunded_provision(
            result_rows,
            statement,
            company_type,
            facts,
            frequency,
            currency,
            ref_filed_map,
        )

        diagnostics: list[ValidationWarning] = []

        if statement == "cash_flow":
            eop_row = next(
                (r for r in result_rows if r.tag == "cash_at_end_of_period"), None
            )
            eop_def = next(
                (rd for rd in rows_def if rd.tag == "cash_at_end_of_period"), None
            )

            if eop_row and eop_def:
                standalone, standalone_src = extract_row_values(
                    facts, eop_def, frequency, currency
                )
                for date in filing_dates:
                    if date not in eop_row.values and date in standalone:
                        eop_row.values[date] = standalone[date]
                        eop_row.sources[date] = standalone_src.get(date, "standalone")

        if not skip_imputation:
            result_rows, diagnostics = impute(
                result_rows,
                statement,
                company_type,
                filing_dates,
                facts,
                frequency=frequency,
            )

        if statement == "cash_flow":
            tag_map = {r.tag: r for r in result_rows}
            eop_row = tag_map.get("cash_at_end_of_period")
            bop_row = tag_map.get("cash_at_beginning_of_period")

            if eop_row and bop_row:
                sorted_dates = sorted(filing_dates)

                for i, date in enumerate(sorted_dates):
                    if i > 0:
                        prev_date = sorted_dates[i - 1]
                        prev_val = eop_row.values.get(prev_date)
                        if prev_val is not None:
                            bop_row.values[date] = prev_val
                            bop_row.sources[date] = (
                                f"derived: cash_at_end_of_period({prev_date})"
                            )

        if statement == "cash_flow" and not skip_imputation:
            tag_map = {r.tag: r for r in result_rows}
            _eop = tag_map.get("cash_at_end_of_period")
            _bop = tag_map.get("cash_at_beginning_of_period")
            _nc = tag_map.get("net_change_in_cash")

            if _eop and _bop and _nc:
                for date in filing_dates:
                    _ev = _eop.values.get(date)
                    _bv = _bop.values.get(date)
                    _nv = _nc.values.get(date)

                    if _ev is None or _bv is None or _nv is None:
                        continue

                    _diff = abs(_bv + _nv - _ev)

                    if _diff > _tolerance(_ev, _bv, _nv):
                        _bop_src = _bop.sources.get(date, "")
                        _nc_src = _nc.sources.get(date, "")
                        _eop_src = _eop.sources.get(date, "")
                        _flows = [
                            v
                            for t in (
                                "net_cash_from_operating_activities",
                                "net_cash_from_investing_activities",
                                "net_cash_from_financing_activities",
                            )
                            if t in tag_map
                            and (v := tag_map[t].values.get(date)) is not None
                        ]
                        _fx = tag_map.get("effect_of_exchange_rate_changes")
                        _flow_sum = (
                            sum(_flows)
                            + ((_fx.values.get(date) if _fx else None) or 0.0)
                            if len(_flows) == 3
                            else None
                        )

                        if (
                            "derived:" in _bop_src
                            and _flow_sum is not None
                            and (
                                abs(_bv + _flow_sum - _ev)
                                <= _tolerance(_ev, _bv, _flow_sum)
                                or 10 * abs(_bv + _flow_sum - _ev) <= _diff
                            )
                        ):
                            _nc.values[date] = _ev - _bv
                            _nc.sources[date] = (
                                "corrected: cash_at_end_of_period"
                                " - cash_at_beginning_of_period"
                            )
                            _apply_hierarchical_articulation(result_rows, {date})
                        elif "derived:" in _bop_src:
                            _bop.values[date] = _ev - _nv
                            _bop.sources[date] = (
                                "identity-enforced: cash_at_end_of_period"
                                " - net_change_in_cash"
                            )
                        # The branches below are unreachable: cash_at_beginning
                        # has no XBRL tags and is never imputed, so a present
                        # ``_bv`` always carries a "derived:" source and the
                        # first branch above always wins.
                        elif (
                            "imputed:" in _nc_src
                        ):  # pragma: no cover - bop is always derived
                            _nc.values[date] = _ev - _bv
                            _nc.sources[date] = (
                                "identity-enforced: cash_at_end_of_period"
                                " - cash_at_beginning_of_period"
                            )
                        elif (
                            "standalone" in _eop_src
                        ):  # pragma: no cover - bop is always derived
                            _eop.values[date] = _bv + _nv
                            _eop.sources[date] = (
                                "identity-enforced: cash_at_beginning_of_period"
                                " + net_change_in_cash"
                            )
                        else:  # pragma: no cover - bop is always derived
                            diagnostics.append(
                                ValidationWarning(
                                    date=date,
                                    tag="cash_at_end_of_period",
                                    expected=_bv + _nv,
                                    actual=_ev,
                                    formula="cash_at_beginning_of_period + net_change_in_cash",
                                    identity="cash_at_end_of_period = cash_at_beginning_of_period + net_change_in_cash",
                                )
                            )

        if not skip_imputation:
            enforce_identities(
                result_rows,
                statement,
                filing_dates,
                facts,
                currency,
                derived=reported_derived,
                frequency=frequency,
            )
            diagnostics = identity_diagnostics(result_rows, statement, filing_dates)

        pruned_dates = set()

        for date in filing_dates:
            if any(r.values.get(date) is not None for r in result_rows):
                pruned_dates.add(date)

        result_rows = [
            r
            for r in result_rows
            if not r.values
            or any(v != 0 for v in r.values.values())
            or any(
                s.startswith(("imputed", "corrected", "reconciled", "derived"))
                for s in r.sources.values()
            )
        ]

        fiscal_data = self.get_fiscal_meta(facts, frequency, pruned_dates)
        pit_meta = compute_period_pit_meta(
            facts,
            rows_def,
            frequency,
            currency,
            ref_filed_map,
            include_preliminary=include_preliminary,
        )
        for d, fmeta in fiscal_data.items():
            if d in pit_meta:
                fmeta.update(pit_meta[d])

        final_preliminary = _preliminary_dates & pruned_dates
        if final_preliminary:
            for row in result_rows:
                for date in final_preliminary:
                    if date in row.sources and not row.sources[date].startswith(
                        "preliminary:"
                    ):
                        row.sources[date] = f"preliminary:{row.sources[date]}"

        return StatementResult(
            statement=statement,
            company_type=company_type,
            frequency=frequency,
            currency=currency,
            dates=sorted(pruned_dates),
            rows=result_rows,
            fiscal_data=fiscal_data,
            diagnostics=diagnostics,
            preliminary_dates=final_preliminary,
        )

    def _combine_unfunded_provision(
        self,
        result_rows: list[RowResult],
        statement: StatementName,
        company_type: CompanyType,
        facts: dict[str, Any],
        frequency: Frequency,
        currency: str,
        ref_filed_map: dict[str, str],
    ) -> None:
        """Fold the unfunded-commitment CECL provision into the funded provision.

        Applies only to financial filers whose provision was sourced from a
        funded-component tag and that do not report a distinct "net interest
        income after provision for loan losses" (``InterestIncomeExpenseAfter
        ProvisionForLoanLoss``). The presence of that tag signals a filer such
        as Citigroup that lists the funded provision as its own income-statement
        line, so combining would break the ``net_interest_income_after_provision``
        identity; those filers are left unchanged.
        """
        if company_type != "financial" or statement not in (
            "income_statement",
            "cash_flow",
        ):
            return

        if "InterestIncomeExpenseAfterProvisionForLoanLoss" in facts.get("us-gaap", {}):
            return

        prov_row = next((r for r in result_rows if r.tag in _PROVISION_ROW_TAGS), None)

        if prov_row is None or not prov_row.values:
            return

        unfunded_def = RowDef(
            tag=_UNFUNDED_PROVISION_TAG,
            label="",
            description="",
            parent=None,
            sequence=0,
            factor="+",
            balance="debit",
            unit="monetary",
            period_type="duration",
            xbrl_tags=({"tag": _UNFUNDED_PROVISION_TAG, "namespace": "us-gaap"},),
        )
        unfunded_vals, _ = extract_row_values(
            facts, unfunded_def, frequency, currency, ref_filed_map
        )

        for date, src in list(prov_row.sources.items()):
            if not any(t in src for t in _PROVISION_FUNDED_SOURCES):
                continue

            add = unfunded_vals.get(date)

            if add is None:
                continue

            prov_row.values[date] = prov_row.values.get(date, 0) + add
            prov_row.sources[date] = (
                f"{src}+us-gaap:{_UNFUNDED_PROVISION_TAG}(combined)"
            )

    def extract_all(  # noqa: PLR0912
        self,
        company_facts: dict[str, Any],
        *,
        frequency: Frequency = "annual",
        company_type: CompanyType | None = None,
        skip_imputation: bool = False,
        pit_mode: bool = False,
        include_preliminary: bool = False,
        annual_results: dict[str, StatementResult] | None = None,
        as_of_date: Any = None,
    ) -> dict[str, StatementResult]:
        facts = self._preliminary_facts(
            company_facts.get("facts", company_facts),
            include_preliminary,
            pit_mode,
            as_of_date=as_of_date,
        )

        if company_type is None:
            company_type = self.detect_type(facts)

        filing_dates = self.get_filing_dates(
            facts, frequency, include_preliminary=include_preliminary
        )

        if not filing_dates and frequency == "quarterly" and as_of_date is None:
            forms_seen: set[str] = set()

            for ns_facts in facts.values():
                for tag_data in ns_facts.values():
                    for entries in tag_data.get("units", {}).values():
                        for entry in entries:
                            f = entry.get("form", "")
                            if f:
                                forms_seen.add(f)
            annual_only = forms_seen & {"20-F", "20-F/A", "40-F", "40-F/A"}
            has_interim = forms_seen & (QUARTERLY_FORMS | SEMI_ANNUAL_FORMS)
            entity = company_facts.get("entityName", "this company")

            if annual_only and not has_interim:
                ftype = "20-F" if forms_seen & {"20-F", "20-F/A"} else "40-F"
                raise OpenBBError(
                    f"{entity} files {ftype} (annual only) and does not "
                    "report interim (quarterly/semi-annual) data via "
                    "10-Q or 6-K filings. Only period='annual' is available."
                )

            raise OpenBBError(
                f"No quarterly filing dates found for {entity}. "
                "Only period='annual' may be available."
            )

        _STMTS: tuple[StatementName, ...] = (
            "income_statement",
            "balance_sheet",
            "cash_flow",
        )

        currency = self._detect_reporting_currency(facts)
        all_rows = []

        for stmt in _STMTS:
            all_rows.extend(self.get_rows(stmt, company_type))

        shared_ref_map = self._compute_ref_filings(
            facts,
            all_rows,
            frequency,
            currency,
            include_preliminary=include_preliminary,
            pit_mode=pit_mode,
        )

        annual_ref_map = (
            self._compute_ref_filings(
                facts,
                all_rows,
                "annual",
                currency,
                include_preliminary=include_preliminary,
                pit_mode=pit_mode,
            )
            if frequency == "quarterly"
            else None
        )

        results: dict[str, StatementResult] = {}
        cross_identities: dict[str, dict[str, float]] = {}

        for stmt in _STMTS:
            results[stmt] = self.extract(
                facts,
                stmt,
                skip_imputation=skip_imputation,
                frequency=frequency,
                company_type=company_type,
                filing_dates=filing_dates,
                ref_filed_map=shared_ref_map,
                cross_identities=cross_identities,
                pit_mode=pit_mode,
                include_preliminary=include_preliminary,
                annual_ref_map=annual_ref_map,
            )

            for r in results[stmt].rows:
                if r.tag not in cross_identities:
                    cross_identities[r.tag] = {}
                cross_identities[r.tag].update(r.values)

        date_sets = [set(r.dates) for r in results.values()]
        common_dates = date_sets[0] & date_sets[1] & date_sets[2]

        if frequency == "quarterly" and common_dates:
            annual_dates = sorted(self.get_filing_dates(facts, "annual"))
            common_dates |= set(annual_dates) & set().union(*date_sets)

            if annual_dates:
                sorted_q = sorted(common_dates)
                fy_groups: dict[str, list[str]] = {}

                for qd in sorted_q:
                    fy_end = None
                    for ad in annual_dates:
                        if qd <= ad:
                            fy_end = ad
                            break
                    if fy_end:
                        fy_groups.setdefault(fy_end, []).append(qd)

                completed = dict(fy_groups)

                if len(completed) > 2:
                    size_counts = Counter(len(v) for v in completed.values())
                    expected = size_counts.most_common(1)[0][0]

                    for fy_end in sorted(completed.keys()):
                        if len(completed[fy_end]) < expected:
                            for qd in completed[fy_end]:
                                common_dates.discard(qd)
                        else:
                            break

        aligned = sorted(common_dates)
        aligned_fiscal = self.get_fiscal_meta(facts, frequency, common_dates)
        pit_meta = compute_period_pit_meta(
            facts,
            all_rows,
            frequency,
            currency,
            shared_ref_map,
            include_preliminary=include_preliminary,
        )
        for d, fmeta in aligned_fiscal.items():
            if d in pit_meta:
                fmeta.update(pit_meta[d])

        all_preliminary: set[str] = set()
        for stmt_result in results.values():
            all_preliminary |= stmt_result.preliminary_dates
        aligned_preliminary = all_preliminary & common_dates

        for stmt_result in results.values():
            stmt_result.dates = aligned
            stmt_result.fiscal_data = aligned_fiscal
            stmt_result.preliminary_dates = aligned_preliminary

            for row in stmt_result.rows:
                row.values = {d: v for d, v in row.values.items() if d in common_dates}
                row.sources = {
                    d: s for d, s in row.sources.items() if d in common_dates
                }

        if frequency == "quarterly":
            if annual_results is None:
                annual_results = self.extract_all(
                    facts,
                    frequency="annual",
                    company_type=company_type,
                    skip_imputation=skip_imputation,
                    pit_mode=pit_mode,
                    include_preliminary=include_preliminary,
                )

            for stmt in _STMTS:
                reconcile_fiscal_year_ends(
                    results[stmt],
                    annual_results[stmt],
                    {rd.tag for rd in self.get_rows(stmt, company_type)},
                    facts,
                    currency,
                )

                if skip_imputation:
                    results[stmt].diagnostics = []

        elif not skip_imputation:
            for stmt in _STMTS:
                results[stmt].diagnostics = identity_diagnostics(
                    results[stmt].rows, stmt, results[stmt].dates
                )

        return results

    @staticmethod
    def merge_facts(*facts_list: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, dict] = {}

        for raw in facts_list:
            facts = raw.get("facts", raw)

            for ns, tags in facts.items():
                if ns not in merged:
                    merged[ns] = {}

                for tag_name, tag_data in tags.items():
                    if tag_name not in merged[ns]:
                        merged[ns][tag_name] = {}
                    src_label = tag_data.get("label", "")
                    src_desc = tag_data.get("description", "")

                    if "label" not in merged[ns][tag_name] and src_label:
                        merged[ns][tag_name]["label"] = src_label

                    if "description" not in merged[ns][tag_name] and src_desc:
                        merged[ns][tag_name]["description"] = src_desc

                    src_units = tag_data.get("units", {})

                    if "units" not in merged[ns][tag_name]:
                        merged[ns][tag_name]["units"] = {}

                    for unit_key, entries in src_units.items():
                        if unit_key not in merged[ns][tag_name]["units"]:
                            merged[ns][tag_name]["units"][unit_key] = []

                        existing = merged[ns][tag_name]["units"][unit_key]
                        seen = set()

                        for e in existing:
                            key = (
                                e.get("end", ""),
                                e.get("start", ""),
                                e.get("val"),
                                e.get("form", ""),
                                e.get("filed", ""),
                            )
                            seen.add(key)

                        for e in entries:
                            key = (
                                e.get("end", ""),
                                e.get("start", ""),
                                e.get("val"),
                                e.get("form", ""),
                                e.get("filed", ""),
                            )
                            if key not in seen:
                                existing.append(e)
                                seen.add(key)

        return merged
