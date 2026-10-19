"""Apply a validated expense policy to validated expenses.

``load_policy`` leaves money limits as strings. This module converts those
strings with ``Decimal`` and does not read expense or policy files.

Findings for one expense are produced in this order:

1. ``restricted_category``
2. ``unknown_category``
3. ``review_required``
4. ``missing_nights`` or ``invalid_nights``
5. ``max_nights_per_stay``
6. ``amount_limit``
7. ``receipt_required``
8. ``submission_deadline``
9. ``duplicate``

A category listed in ``restricted_categories`` and omitted from ``categories``
is both restricted and unknown. Both findings are reported, with different
rule identifiers. A configured category, including ``other``, is not unknown.

A submission dated before the expense is allowed. The deadline is only a
maximum number of days after the expense date.

A nightly limit compares the stay total with ``max_amount * nights``. That is
the nightly rate check, and it is skipped when nights are missing or below 1.
An equal amount or an equal night count is within its maximum. A null maximum
means that limit is not applied. Receipt thresholds compare the expense total.

When ``reporting.collect_all_violations`` is false, the first finding in the
order above is kept and every duplicate finding is still reported. Flagged
amount adds an expense amount once when that expense has any finding.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from loader.expense_loader import Expense

AMOUNT_LIMIT = "amount_limit"
RECEIPT_REQUIRED = "receipt_required"
RESTRICTED_CATEGORY = "restricted_category"
UNKNOWN_CATEGORY = "unknown_category"
REVIEW_REQUIRED = "review_required"
MISSING_NIGHTS = "missing_nights"
INVALID_NIGHTS = "invalid_nights"
MAX_NIGHTS = "max_nights_per_stay"
SUBMISSION_DEADLINE = "submission_deadline"
DUPLICATE = "duplicate"

VIOLATION = "violation"
ONCE_PER_EXPENSE = "once_per_expense"


@dataclass(frozen=True)
class Finding:
    """One policy finding for a single expense."""

    expense_id: str
    rule: str
    classification: str
    explanation: str


@dataclass(frozen=True)
class ExpenseResult:
    """Findings for one expense. Clean expenses have an empty findings tuple."""

    expense_id: str
    findings: tuple[Finding, ...]


@dataclass(frozen=True)
class EvaluationResult:
    """Evaluation of a batch, preserving the input expense order."""

    results: tuple[ExpenseResult, ...]
    flagged_amount: Decimal


def evaluate_expenses(expenses: Iterable[Expense], policy: dict) -> EvaluationResult:
    """Evaluate each expense in input order.

    Pass ``LoadResult.expenses`` and the dictionary returned by ``load_policy``.
    Rejected loader rows are not part of that sequence and are not evaluated.
    """
    counting = policy["reporting"]["flagged_amount_counting"]
    if counting != ONCE_PER_EXPENSE:
        raise ValueError("flagged_amount_counting: expected once_per_expense")
    ordered = tuple(expenses)
    grouped = [_expense_findings(expense, policy) for expense in ordered]
    for index, finding in _duplicate_findings(ordered, policy):
        grouped[index].append(finding)
    collect_all = policy["reporting"]["collect_all_violations"]
    results = []
    flagged_amount = Decimal("0.00")
    for expense, findings in zip(ordered, grouped, strict=True):
        selected = _select_findings(findings, collect_all)
        if selected:
            flagged_amount += expense.amount
        results.append(ExpenseResult(expense.id, selected))
    return EvaluationResult(tuple(results), flagged_amount)


def _expense_findings(expense: Expense, policy: dict) -> list[Finding]:
    findings = []
    category = expense.category
    if category in policy["restricted_categories"]:
        findings.append(_finding(
            expense,
            RESTRICTED_CATEGORY,
            VIOLATION,
            f"Category {category} is restricted.",
        ))
    settings = policy["categories"].get(category)
    if settings is None:
        action = policy["unknown_category_action"]
        findings.append(_finding(
            expense,
            UNKNOWN_CATEGORY,
            action,
            (
                f"Category {category} is outside the configured categories; "
                f"the policy action is {action}."
            ),
        ))
    else:
        if settings.get("review_required"):
            findings.append(_finding(
                expense,
                REVIEW_REQUIRED,
                REVIEW_REQUIRED,
                f"Category {category} requires review.",
            ))
        findings.extend(_nights_findings(expense, category, settings))
        amount_finding = _amount_finding(expense, category, settings)
        if amount_finding is not None:
            findings.append(amount_finding)
        receipt_finding = _receipt_finding(expense, category, settings)
        if receipt_finding is not None:
            findings.append(receipt_finding)
    submission_finding = _submission_finding(expense, policy["submission"])
    if submission_finding is not None:
        findings.append(submission_finding)
    return findings


def _amount_finding(expense: Expense, category: str, settings: dict) -> Finding | None:
    maximum = settings["max_amount"]
    if maximum is None:
        return None
    limit = _decimal_money(maximum)
    basis = settings["limit_basis"]
    if basis == "per_expense":
        return _per_expense_amount(expense, category, limit)
    if basis == "per_night":
        return _per_night_amount(expense, category, limit)
    raise ValueError("limit_basis: expected per_expense or per_night")


def _per_expense_amount(expense: Expense, category: str, limit: Decimal) -> Finding | None:
    if expense.amount <= limit:
        return None
    return _finding(
        expense,
        AMOUNT_LIMIT,
        VIOLATION,
        (
            f"Amount {_money_text(expense.amount)} exceeds the {category} "
            f"limit of {_money_text(limit)} per expense."
        ),
    )


def _per_night_amount(expense: Expense, category: str, limit: Decimal) -> Finding | None:
    """Flag a stay whose total is above the nightly limit times nights.

    ``amount > limit * nights`` is the nightly-rate comparison. Missing and
    non-positive nights are handled by the nights check and are not divided.
    """
    nights = _positive_nights(expense.nights)
    if nights is None:
        return None
    stay_limit = limit * nights
    if expense.amount <= stay_limit:
        return None
    return _finding(
        expense,
        AMOUNT_LIMIT,
        VIOLATION,
        (
            f"Amount {_money_text(expense.amount)} exceeds the {category} "
            f"limit of {_money_text(limit)} per night for {_night_phrase(nights)} "
            f"(stay limit {_money_text(stay_limit)})."
        ),
    )


def _receipt_finding(expense: Expense, category: str, settings: dict) -> Finding | None:
    receipt = settings["receipt"]
    mode = receipt["mode"]
    if mode == "unconfigured" or expense.receipt_attached:
        return None
    if mode == "always":
        return _finding(
            expense,
            RECEIPT_REQUIRED,
            VIOLATION,
            f"A receipt is required for every {category} expense.",
        )
    if mode == "above_threshold":
        threshold = _decimal_money(receipt["threshold"])
        if expense.amount <= threshold:
            return None
        return _finding(
            expense,
            RECEIPT_REQUIRED,
            VIOLATION,
            (
                f"A receipt is required for {category} expenses above "
                f"{_money_text(threshold)}; the amount is {_money_text(expense.amount)}."
            ),
        )
    raise ValueError("receipt.mode: expected above_threshold, always, or unconfigured")


def _nights_findings(expense: Expense, category: str, settings: dict) -> list[Finding]:
    if not _needs_nights(settings):
        return []
    nights = _positive_nights(expense.nights)
    if nights is None:
        return [_nights_problem(expense, category)]
    maximum = settings.get("max_nights_per_stay")
    if maximum is not None and nights > maximum:
        return [_finding(
            expense,
            MAX_NIGHTS,
            VIOLATION,
            (
                f"Stay of {_night_phrase(nights)} exceeds the {category} "
                f"maximum of {_night_phrase(maximum)}."
            ),
        )]
    return []


def _needs_nights(settings: dict) -> bool:
    if settings.get("nights_required"):
        return True
    if settings.get("max_nights_per_stay") is not None:
        return True
    return settings["limit_basis"] == "per_night" and settings["max_amount"] is not None


def _nights_problem(expense: Expense, category: str) -> Finding:
    if expense.nights is None:
        return _finding(
            expense,
            MISSING_NIGHTS,
            VIOLATION,
            f"Category {category} requires a number of nights.",
        )
    return _finding(
        expense,
        INVALID_NIGHTS,
        VIOLATION,
        (
            f"Category {category} requires a positive number of nights; "
            f"received {expense.nights}."
        ),
    )


def _submission_finding(expense: Expense, submission: dict) -> Finding | None:
    elapsed = (expense.submission_date - expense.date).days
    # The policy stores only a maximum. An earlier submission is within it.
    if elapsed < 0:
        return None
    maximum = submission["max_days_after_expense"]
    inclusive = submission["inclusive"]
    too_late = elapsed > maximum if inclusive else elapsed >= maximum
    if not too_late:
        return None
    window = "inclusive" if inclusive else "exclusive"
    return _finding(
        expense,
        SUBMISSION_DEADLINE,
        VIOLATION,
        f"Submitted {elapsed} days after the expense; the limit is {maximum} days, {window}.",
    )


def _duplicate_findings(expenses: tuple[Expense, ...], policy: dict) -> list[tuple[int, Finding]]:
    settings = policy["duplicates"]
    key_fields = settings["key_fields"]
    groups: dict[tuple[object, ...], list[int]] = {}
    for index, expense in enumerate(expenses):
        key = tuple(getattr(expense, field) for field in key_fields)
        groups.setdefault(key, []).append(index)
    findings = []
    field_list = ", ".join(key_fields)
    for indexes in groups.values():
        for index in _indexes_to_flag(expenses, indexes, settings):
            other_ids = [expenses[other].id for other in indexes if other != index]
            findings.append((index, _finding(
                expenses[index],
                DUPLICATE,
                settings["classification"],
                f"Same {field_list} as {', '.join(other_ids)}.",
            )))
    return findings


def _indexes_to_flag(expenses: tuple[Expense, ...], indexes: list[int], settings: dict) -> list[int]:
    if len(indexes) < 2:
        return []
    if settings["require_different_ids"]:
        distinct_ids = {expenses[index].id for index in indexes}
        if len(distinct_ids) < 2:
            return []
    if settings["flag"] == "later_matches":
        return indexes[1:]
    if settings["flag"] == "all_matches":
        return list(indexes)
    raise ValueError("duplicates.flag: expected all_matches or later_matches")


def _select_findings(findings: list[Finding], collect_all: bool) -> tuple[Finding, ...]:
    if collect_all:
        return tuple(findings)
    selected = []
    kept_primary = False
    for finding in findings:
        if finding.rule == DUPLICATE:
            selected.append(finding)
        elif not kept_primary:
            selected.append(finding)
            kept_primary = True
    return tuple(selected)


def _positive_nights(nights: int | None) -> int | None:
    if type(nights) is int and nights > 0:
        return nights
    return None


def _decimal_money(value: str) -> Decimal:
    """Convert one policy money string. Float values are rejected."""
    if not isinstance(value, str):
        raise ValueError("policy money values must stay decimal strings until evaluation")
    return Decimal(value)


def _money_text(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"


def _night_phrase(nights: int) -> str:
    noun = "night" if nights == 1 else "nights"
    return f"{nights} {noun}"


def _finding(expense: Expense, rule: str, classification: str, explanation: str) -> Finding:
    return Finding(expense.id, rule, classification, explanation)
