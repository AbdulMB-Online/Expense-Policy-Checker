"""Missing-receipt checks for a single expense."""

from .base import PolicyRule
from .helpers import _decimal_money, _money_text


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
