"""Hotel night and stay-length checks."""

from .base import PolicyRule
from .helpers import _category_settings


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
