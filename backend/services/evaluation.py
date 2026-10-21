"""Evaluate complete inputs before applying report filters."""

import csv
from dataclasses import dataclass, replace
from decimal import DecimalException

from backend.loader.expense_loader import Expense, LoadResult
from backend.reporting.violation_report import ViolationReport, build_report
from backend.rules.base import PolicyViolation
from backend.rules.engine import RulesEngine
from backend.services.errors import ServiceError
from backend.services.sources import ReportSource


@dataclass(frozen=True)
class ReportEvaluation:
    """Named report results shared by validation and dashboard presentation."""

    employees: list[str]
    violations: dict[str, list[PolicyViolation]]
    selected: tuple[Expense, ...]
    engine: RulesEngine
    overview: ViolationReport
    report: ViolationReport


def with_submissions(source: ReportSource, expenses: tuple[Expense, ...]) -> ReportSource:
    if {expense.id for expense in source.loaded.expenses} & {expense.id for expense in expenses}:
        raise ServiceError(
            409, "Expense IDs in this CSV conflict with submitted claims. Use unique expense IDs."
        )
    return replace(
        source, loaded=LoadResult(source.loaded.expenses + expenses, source.loaded.errors)
    )


def load_report(
    source: ReportSource,
    employee: str | None,
    search: str,
    findings: dict[str, list[PolicyViolation]] | None = None,
) -> ReportEvaluation:
    loaded, policy = source.loaded, source.policy
    try:
        engine = RulesEngine(policy)
        violations = engine.run_detailed(loaded.expenses) if findings is None else findings
    except (OSError, ValueError, csv.Error, DecimalException) as error:
        raise ServiceError(
            status_code=503,
            detail="Unable to prepare the report. Check the stored expense CSV and policy JSON, then retry.",
        ) from error

    employees = sorted({expense.employee for expense in loaded.expenses})
    if employee and employee not in employees:
        raise ServiceError(status_code=422, detail="Choose an employee from the report.")

    # Evaluate the complete input before filtering: duplicate context must survive
    # employee and search filters, including custom duplicate-key configurations.
    query = search.strip().casefold()
    selected = tuple(
        expense
        for expense in loaded.expenses
        if (not employee or expense.employee == employee)
        and (
            not query
            or query
            in " ".join(
                (
                    expense.id,
                    expense.employee,
                    expense.date.isoformat(),
                    expense.category,
                    expense.description,
                )
            ).casefold()
        )
    )
    selected_ids = {expense.id for expense in selected}
    selected_violations = {key: value for key, value in violations.items() if key in selected_ids}
    all_report = build_report(
        loaded.expenses, violations, currency=policy["currency"], errors=loaded.errors
    )
    report = build_report(
        selected, selected_violations, currency=policy["currency"], errors=loaded.errors
    )
    return ReportEvaluation(employees, violations, selected, engine, all_report, report)
