"""Shared records returned by the submission repository."""

from dataclasses import dataclass

from backend.loader.expense_loader import Expense


@dataclass(frozen=True)
class Receipt:
    name: str
    media_type: str
    contents: bytes


@dataclass(frozen=True)
class SavedExpense:
    expense: Expense
    receipt_name: str | None
