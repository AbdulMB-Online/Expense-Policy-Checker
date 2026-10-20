"""Run policy rules against validated expenses.

Policy money stays in ``Decimal``. An amount equal to the configured limit
passes. When ``reporting.collect_all_violations`` is true, ``RulesEngine.run_all``
keeps every violation for an expense. Future expense dates are compared with
each claim's submission date unless a reference date is injected.
"""

from datetime import date
from decimal import Decimal

from loader.expense_loader import Expense

from .base import PolicyRule, PolicyViolation


class AmountLimitRule(PolicyRule):
    """Flag an amount that is above the category limit in the policy data.

    ``per_expense`` compares the full amount. ``per_night`` compares the stay
    total with ``max_amount * nights``. A null maximum means the category has
    no amount limit. The exact limit passes.
    """

    rule_id = "amount_limit"
    rule_name = "Amount limit"

    def evaluate(self, expense, all_expenses: list) -> str | None:
        settings = self.policy_data.get("categories", {}).get(expense.category)
        if settings is None:
            return None
        maximum = settings.get("max_amount")
        if maximum is None:
            return None
        limit = _decimal_money(maximum)
        basis = settings.get("limit_basis", "per_expense")
        if basis == "per_night":
            return self._per_night(expense, limit)
        return self._per_expense(expense, limit)

    def _per_expense(self, expense: Expense, limit: Decimal) -> str | None:
        if expense.amount <= limit:
            return None
        return (
            f"Amount {_money_text(expense.amount)} exceeds the {expense.category} "
            f"limit of {_money_text(limit)} per expense."
        )

    def _per_night(self, expense: Expense, limit: Decimal) -> str | None:
        nights = expense.nights
        if type(nights) is not int or nights < 1:
            return None
        stay_limit = limit * nights
        if expense.amount <= stay_limit:
            return None
        noun = "night" if nights == 1 else "nights"
        return (
            f"Amount {_money_text(expense.amount)} exceeds the {expense.category} "
            f"limit of {_money_text(limit)} per night for {nights} {noun}."
        )


class MissingReceiptRule(PolicyRule):
    """Flag a missing receipt using the category receipt settings.

    ``above_threshold`` requires a receipt only when the amount is strictly
    above the policy threshold. An amount equal to the threshold passes.
    ``always`` requires a receipt at any amount. ``unconfigured`` does not
    flag a missing receipt.
    """

    rule_id = "missing_receipt"
    rule_name = "Missing receipt"

    def evaluate(self, expense, all_expenses: list) -> str | None:
        settings = self.policy_data.get("categories", {}).get(expense.category)
        if settings is None or expense.receipt_attached:
            return None
        receipt = settings.get("receipt", {})
        mode = receipt.get("mode", "unconfigured")
        if mode == "unconfigured":
            return None
        if mode == "always":
            return f"Receipt is missing for {expense.category} expense {_money_text(expense.amount)}."
        if mode != "above_threshold":
            return None
        threshold = _decimal_money(receipt["threshold"])
        if expense.amount <= threshold:
            return None
        return (
            f"Receipt is missing for {expense.category} expense {_money_text(expense.amount)}, "
            f"which is above the {_money_text(threshold)} threshold."
        )


class DuplicateRule(PolicyRule):
    """Flag another expense that matches ``duplicates.key_fields``.

    The default key is employee, date, amount, and category. A field such as
    ``nights`` is compared only when the policy lists it. ``duplicates.flag``
    chooses ``all_matches`` or ``later_matches``. ``duplicates.require_different_ids``
    controls whether the same id can match.
    """

    rule_id = "suspected_duplicate"
    rule_name = "Suspected duplicate"

    def evaluate(self, expense, all_expenses: list) -> str | None:
        settings = self.policy_data.get("duplicates", {})
        key_fields = self._key_fields()
        matches = [
            other
            for other in all_expenses
            if other is not expense and _same_duplicate_key(expense, other, key_fields)
        ]
        if settings.get("require_different_ids", True):
            matches = [other for other in matches if other.id != expense.id]
        if not matches:
            return None
        if settings.get("flag", "all_matches") == "later_matches":
            first = next(
                item for item in all_expenses if _same_duplicate_key(expense, item, key_fields)
            )
            if first is expense:
                return None
        other_ids = ", ".join(other.id for other in matches)
        return f"Duplicate of {other_ids} on {', '.join(key_fields)}."

    def _key_fields(self) -> list:
        return self.policy_data.get("duplicates", {}).get(
            "key_fields", ["employee", "date", "amount", "category"]
        )


class RestrictedCategoryRule(PolicyRule):
    """Flag a category listed in ``restricted_categories``.

    A restricted category is not treated as unknown, even when it is absent
    from ``categories``. Known-category checks still apply when the same name
    is also configured there.
    """

    rule_id = "restricted_category"
    rule_name = "Restricted category"

    def evaluate(self, expense, all_expenses: list) -> str | None:
        restricted = self.policy_data.get("restricted_categories")
        if not isinstance(restricted, list) or expense.category not in restricted:
            return None
        return f"Category {expense.category} is restricted."


class UnknownCategoryRule(PolicyRule):
    """Flag a category that is neither configured nor restricted.

    ``unknown_category_action`` decides the outcome. ``review_required`` flags
    the category as unknown. Any other action does not flag it here. Restricted
    names are handled by ``RestrictedCategoryRule`` instead.
    """

    rule_id = "unknown_category"
    rule_name = "Unknown category"

    def evaluate(self, expense, all_expenses: list) -> str | None:
        if _known_or_restricted(self.policy_data, expense.category):
            return None
        if self.policy_data.get("unknown_category_action") != "review_required":
            return None
        return f"Category {expense.category} is unknown."


class SubmissionDeadlineRule(PolicyRule):
    """Flag a submission that is past ``submission.max_days_after_expense``.

    Elapsed time is the number of calendar days from the expense date to the
    submission date. ``inclusive`` true allows an elapsed time equal to the
    limit, so day 30 of a 30-day limit passes and day 31 fails. ``inclusive``
    false rejects an elapsed time equal to the limit. Missing or non-calendar
    dates produce no violation.
    """

    rule_id = "submission_deadline"
    rule_name = "Submission deadline"

    def evaluate(self, expense, all_expenses: list) -> str | None:
        submission = self.policy_data.get("submission")
        if not isinstance(submission, dict):
            return None
        limit = submission.get("max_days_after_expense")
        inclusive = submission.get("inclusive")
        if type(limit) is not int or type(inclusive) is not bool:
            return None
        expense_day = _calendar_day(getattr(expense, "date", None))
        submitted = _calendar_day(getattr(expense, "submission_date", None))
        if expense_day is None or submitted is None:
            return None
        elapsed = (submitted - expense_day).days
        late = elapsed > limit if inclusive else elapsed >= limit
        if not late:
            return None
        return (
            f"Submitted {elapsed} days after the expense date, "
            f"beyond the {limit}-day deadline."
        )


class FutureExpenseDateRule(PolicyRule):
    """Flag an expense date after the configured reference date.

    The default reference is that expense's submission date, which keeps
    results independent of the machine clock. Pass ``reference_date`` to
    compare every expense with one calendar date instead. The expense date
    must be strictly later than the reference; the same day passes. Missing
    or non-calendar dates produce no violation.
    """

    rule_id = "future_expense_date"
    rule_name = "Future expense date"

    def __init__(self, policy_data: dict, *, reference_date: date | None = None):
        super().__init__(policy_data)
        self.reference_date = reference_date

    def evaluate(self, expense, all_expenses: list) -> str | None:
        expense_day = _calendar_day(getattr(expense, "date", None))
        if self.reference_date is None:
            reference = _calendar_day(getattr(expense, "submission_date", None))
            reference_name = "submission date"
        else:
            reference = _calendar_day(self.reference_date)
            reference_name = "reference date"
        if expense_day is None or reference is None:
            return None
        if expense_day <= reference:
            return None
        return (
            f"Expense date {expense_day.isoformat()} is after the "
            f"{reference_name} {reference.isoformat()}."
        )


class MissingHotelNightsRule(PolicyRule):
    """Flag missing or unusable nights when ``nights_required`` is true.

    ``None`` is missing. A value that is not an int, or an int below 1, is
    invalid. ``bool`` is not an int. Categories that do not require nights are
    left alone. Invalid values do not raise.
    """

    rule_id = "missing_hotel_nights"
    rule_name = "Missing hotel nights"

    def evaluate(self, expense, all_expenses: list) -> str | None:
        settings = _category_settings(self.policy_data, expense.category)
        if settings is None or settings.get("nights_required") is not True:
            return None
        nights = getattr(expense, "nights", None)
        if nights is None:
            return f"Nights are required for {expense.category} but none were provided."
        if type(nights) is not int or nights < 1:
            return f"Nights for {expense.category} must be a positive integer."
        return None


class MaxHotelStayRule(PolicyRule):
    """Flag a stay longer than ``max_nights_per_stay``.

    ``null`` and a missing maximum mean no stay-length limit is configured.
    Only a positive int night count is compared. A stay equal to the maximum
    passes. Missing or invalid nights produce no violation from this rule.
    """

    rule_id = "max_hotel_stay"
    rule_name = "Maximum hotel stay"

    def evaluate(self, expense, all_expenses: list) -> str | None:
        settings = _category_settings(self.policy_data, expense.category)
        if settings is None or "max_nights_per_stay" not in settings:
            return None
        maximum = settings.get("max_nights_per_stay")
        if maximum is None or type(maximum) is not int:
            return None
        nights = getattr(expense, "nights", None)
        if type(nights) is not int or nights < 1 or nights <= maximum:
            return None
        night_noun = "night" if nights == 1 else "nights"
        max_noun = "night" if maximum == 1 else "nights"
        return (
            f"Stay of {nights} {night_noun} exceeds the {expense.category} "
            f"maximum of {maximum} {max_noun}."
        )


class ReviewRequiredRule(PolicyRule):
    """Flag categories the policy classifies as requiring review.

    A known category is flagged only when its ``review_required`` value is
    true. An unknown category is flagged only when ``unknown_category_action``
    is ``review_required``. Restricted categories are not given this
    classification through the unknown-category action. Other violations are
    not reclassified as review-required.
    """

    rule_id = "review_required"
    rule_name = "Review required"

    def evaluate(self, expense, all_expenses: list) -> str | None:
        settings = _category_settings(self.policy_data, expense.category)
        if settings is not None:
            if settings.get("review_required") is True:
                return f"Category {expense.category} requires review."
            return None
        restricted = self.policy_data.get("restricted_categories")
        if isinstance(restricted, list) and expense.category in restricted:
            return None
        if self.policy_data.get("unknown_category_action") != "review_required":
            return None
        return f"Category {expense.category} requires review."


class RulesEngine:
    """Apply every rule and collect violations by expense id."""

    def __init__(self, policy_data: dict, *, reference_date: date | None = None):
        self.policy_data = policy_data
        self.reference_date = reference_date
        self.rules = [
            AmountLimitRule(policy_data),
            MissingReceiptRule(policy_data),
            DuplicateRule(policy_data),
            RestrictedCategoryRule(policy_data),
            UnknownCategoryRule(policy_data),
            SubmissionDeadlineRule(policy_data),
            FutureExpenseDateRule(policy_data, reference_date=reference_date),
            MissingHotelNightsRule(policy_data),
            MaxHotelStayRule(policy_data),
            ReviewRequiredRule(policy_data),
        ]

    def run_all(self, expenses) -> dict[str, list[str]]:
        """Return each violating expense id mapped to every violation message.

        An expense that breaks two rules appears once, with both messages.
        An amount exactly at its limit is not a violation. Expenses with no
        violations are omitted.
        """
        return {
            expense_id: [violation.reason for violation in violations]
            for expense_id, violations in self.run_detailed(expenses).items()
        }

    def run_detailed(self, expenses) -> dict[str, list[PolicyViolation]]:
        """Keep rule identities alongside reasons, without parsing message text.

        Like ``run_all``, omit clean expenses and preserve expense/rule order.
        Each rule is evaluated once per expense. New rules can supply stable
        ``rule_id`` and ``rule_name`` attributes; class names are the fallback.
        ``reporting.collect_all_violations`` false keeps the first violation
        in rule order. A missing flag still collects every violation.
        """
        expense_list = list(expenses)
        reporting = self.policy_data.get("reporting") if isinstance(self.policy_data, dict) else None
        collect_all = not (
            isinstance(reporting, dict) and reporting.get("collect_all_violations") is False
        )
        violations: dict[str, list[PolicyViolation]] = {}
        for expense in expense_list:
            messages = []
            for rule in self.rules:
                message = rule.evaluate(expense, expense_list)
                if message is not None:
                    messages.append(PolicyViolation(
                        rule_id=getattr(rule, "rule_id", type(rule).__name__),
                        rule_name=getattr(rule, "rule_name", type(rule).__name__),
                        reason=message,
                    ))
                    if not collect_all:
                        break
            if messages:
                violations.setdefault(expense.id, []).extend(messages)
        return violations


def _category_settings(policy_data: dict, category: str) -> dict | None:
    categories = policy_data.get("categories") if isinstance(policy_data, dict) else None
    if not isinstance(categories, dict):
        return None
    settings = categories.get(category)
    if not isinstance(settings, dict):
        return None
    return settings


def _known_or_restricted(policy_data: dict, category: str) -> bool:
    if _category_settings(policy_data, category) is not None:
        return True
    restricted = policy_data.get("restricted_categories") if isinstance(policy_data, dict) else None
    return isinstance(restricted, list) and category in restricted


def _calendar_day(value) -> date | None:
    """Return a calendar date. Datetimes and other values are not calendar days."""
    if type(value) is date:
        return value
    return None


def _same_duplicate_key(left: Expense, right: Expense, key_fields: list) -> bool:
    return all(getattr(left, field) == getattr(right, field) for field in key_fields)


def _decimal_money(value: str) -> Decimal:
    """Convert a policy money string. Float values are rejected."""
    if not isinstance(value, str):
        raise ValueError("policy money values must stay decimal strings until evaluation")
    return Decimal(value)


def _money_text(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"
