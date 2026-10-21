"""Amount limit checks for a single expense."""

from decimal import Decimal

from backend.loader.expense_loader import Expense

from .base import PolicyRule
from .helpers import _decimal_money, _money_text


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
