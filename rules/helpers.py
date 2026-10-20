"""Shared helpers for policy rule evaluation."""

from datetime import date
from decimal import Decimal


def _category_settings(policy_data: dict, category: str) -> dict | None:
    categories = policy_data.get("categories") if isinstance(policy_data, dict) else None
    if not isinstance(categories, dict):
        return None
    settings = categories.get(category)
    if not isinstance(settings, dict):
        return None
    return settings


def _decimal_money(value: str) -> Decimal:
    """Convert a policy money string. Float values are rejected."""
    if not isinstance(value, str):
        raise ValueError("policy money values must stay decimal strings until evaluation")
    return Decimal(value)


def _money_text(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}"


def _calendar_day(value) -> date | None:
    """Return a calendar date. Datetimes and other values are not calendar days."""
    if type(value) is date:
        return value
    return None
