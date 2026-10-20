"""Run amount, receipt, and duplicate rules against validated expenses.

Policy money stays in ``Decimal``. An amount equal to the configured limit
passes. ``RulesEngine.run_all`` keeps every violation when one expense breaks
more than one rule.
"""

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


class RulesEngine:
    """Apply every rule and collect every violation by expense id."""

    def __init__(self, policy_data: dict):
        self.rules = [
            AmountLimitRule(policy_data),
            MissingReceiptRule(policy_data),
            DuplicateRule(policy_data),
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
        """
        expense_list = list(expenses)
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
            if messages:
                violations.setdefault(expense.id, []).extend(messages)
        return violations


def _same_duplicate_key(left: Expense, right: Expense, key_fields: list) -> bool:
    return all(getattr(left, field) == getattr(right, field) for field in key_fields)


def _decimal_money(value: str) -> Decimal:
    """Convert a policy money string. Float values are rejected."""
    if not isinstance(value, str):
        raise ValueError("policy money values must stay decimal strings until evaluation")
    return Decimal(value)


def _money_text(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"
