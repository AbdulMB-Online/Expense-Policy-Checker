"""Build and render reports independently of file loading and CLI interaction.

Use ``RulesEngine.run_detailed`` for rule identities and reasons. Amounts are
whole claim amounts, not the portion above a policy limit. Each flagged claim
counts once in the overall total. A claim may appear in several rule groups,
so those group subtotals must not be added to obtain the overall total.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, localcontext

from backend.loader.expense_loader import Expense, LoadError
from backend.rules.base import PolicyViolation


@dataclass(frozen=True)
class FlaggedExpense:
    expense: Expense
    violations: tuple[PolicyViolation, ...]


@dataclass(frozen=True)
class ReportGroup:
    key: str
    name: str
    expenses: tuple[FlaggedExpense, ...]

    @property
    def total_flagged_amount(self) -> Decimal:
        return _total_amount(self.expenses)


@dataclass(frozen=True)
class ViolationReport:
    currency: str
    total_expenses: int
    flagged_expenses: tuple[FlaggedExpense, ...]
    errors: tuple[LoadError, ...]

    @property
    def flagged_count(self) -> int:
        return len(self.flagged_expenses)

    @property
    def violation_count(self) -> int:
        return sum(len(item.violations) for item in self.flagged_expenses)

    @property
    def total_flagged_amount(self) -> Decimal:
        return _total_amount(self.flagged_expenses)


def build_report(
    expenses: Iterable[Expense],
    violations: Mapping[str, Sequence[PolicyViolation]],
    *,
    currency: str,
    errors: Iterable[LoadError] = (),
) -> ViolationReport:
    """Combine validated claims and detailed engine output into a snapshot.

    Currency is the policy currency; this function does not convert money.
    Rejected rows stay separate and never contribute to claim totals. Reject
    duplicate input IDs or unknown result IDs rather than silently misreporting
    amounts. Empty violation lists are treated as unflagged expenses.
    """
    expense_list = tuple(expenses)
    ids = [expense.id for expense in expense_list]
    if len(set(ids)) != len(ids):
        raise ValueError("Report expenses must have unique IDs")
    unknown_ids = violations.keys() - set(ids)
    if unknown_ids:
        raise ValueError(
            f"Violations reference unknown expense IDs: {', '.join(sorted(unknown_ids))}"
        )
    flagged = tuple(
        FlaggedExpense(expense, tuple(violations[expense.id]))
        for expense in expense_list
        if violations.get(expense.id)
    )
    return ViolationReport(currency, len(expense_list), flagged, tuple(errors))


def group_report(report: ViolationReport, *, group_by: str = "employee") -> tuple[ReportGroup, ...]:
    """Sort groups by name and preserve source claim order within each group.

    Employee groups retain all reasons. Rule groups show only that rule's
    reasons, retaining each matching claim once even if it has several reasons
    for the rule. Group identity uses rule IDs, never reason-text matching.
    """
    if group_by not in {"employee", "rule"}:
        raise ValueError("group_by must be 'employee' or 'rule'")
    groups: dict[str, list[FlaggedExpense]] = {}
    names: dict[str, str] = {}
    for item in report.flagged_expenses:
        if group_by == "employee":
            key = item.expense.employee
            names[key] = key
            groups.setdefault(key, []).append(item)
        else:
            by_rule: dict[str, list[PolicyViolation]] = {}
            for violation in item.violations:
                names[violation.rule_id] = violation.rule_name
                by_rule.setdefault(violation.rule_id, []).append(violation)
            for key, reasons in by_rule.items():
                groups.setdefault(key, []).append(FlaggedExpense(item.expense, tuple(reasons)))
    keys = sorted(groups, key=lambda key: (names[key].casefold(), names[key], key))
    return tuple(ReportGroup(key, names[key], tuple(groups[key])) for key in keys)


def render_report(report: ViolationReport, *, group_by: str = "employee") -> str:
    """Return a terminal-ready report; do not print, prompt, or write files."""
    groups = group_report(report, group_by=group_by)
    lines = [
        "EXPENSE POLICY REPORT",
        f"Currency: {report.currency} | Grouped by: {group_by}",
        "",
        f"Accepted claims: {report.total_expenses}",
        f"Rejected rows: {len(report.errors)}",
        f"Flagged claims: {report.flagged_count}",
        f"Violation reasons: {report.violation_count}",
        f"Total flagged amount: {report.currency} {report.total_flagged_amount:.2f}",
    ]
    if not groups:
        lines.extend(["", "No violations detected by the configured checks."])
    if group_by == "rule" and groups:
        lines.extend(
            [
                "",
                "Claims may appear under multiple rules; the overall total counts each claim once.",
            ]
        )
    for group in groups:
        label = "EMPLOYEE" if group_by == "employee" else "RULE"
        lines.extend(
            [
                "",
                f"{label}: {group.name}",
                f"Flagged claims: {len(group.expenses)} | Flagged amount: {report.currency} {group.total_flagged_amount:.2f}",
            ]
        )
        for item in group.expenses:
            expense = item.expense
            fields = [expense.id, expense.date.isoformat()]
            if group_by == "rule":
                fields.append(expense.employee)
            fields.extend([expense.category, f"{report.currency} {expense.amount:.2f}"])
            lines.append(f"  {' | '.join(fields)}")
            for violation in item.violations:
                lines.append(f"    - {violation.reason}")
    if report.errors:
        lines.extend(["", f"REJECTED INPUT ROWS: {len(report.errors)}"])
        for error in report.errors:
            expense_id = error.expense_id if error.expense_id is not None else "ID unavailable"
            lines.append(f"  Line {error.line_number} | {expense_id}")
            lines.extend(f"    - {reason}" for reason in error.reasons)
    return "\n".join(lines) + "\n"


def _total_amount(expenses: tuple[FlaggedExpense, ...]) -> Decimal:
    """Sum loader-valid money exactly, including amounts beyond 28 digits."""
    amounts = [item.expense.amount for item in expenses]
    with localcontext() as context:
        digits = max((len(amount.as_tuple().digits) for amount in amounts), default=1)
        context.prec = max(context.prec, digits + len(str(len(amounts))) + 2)
        return sum(amounts, Decimal("0.00"))
