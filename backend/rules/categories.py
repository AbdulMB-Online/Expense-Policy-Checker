"""Restricted, unknown, and review-required category checks."""

from .base import PolicyRule
from .helpers import _category_settings


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


def _known_or_restricted(policy_data: dict, category: str) -> bool:
    if _category_settings(policy_data, category) is not None:
        return True
    restricted = policy_data.get("restricted_categories") if isinstance(policy_data, dict) else None
    return isinstance(restricted, list) and category in restricted
