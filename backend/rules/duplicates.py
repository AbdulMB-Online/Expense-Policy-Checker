"""Suspected-duplicate checks across a set of expenses."""

from backend.loader.expense_loader import Expense

from .base import PolicyRule


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


def _same_duplicate_key(left: Expense, right: Expense, key_fields: list) -> bool:
    return all(getattr(left, field) == getattr(right, field) for field in key_fields)
