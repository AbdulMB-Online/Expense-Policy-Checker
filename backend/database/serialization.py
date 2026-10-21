"""Lossless conversion between expense records and persisted JSON."""

import json
from dataclasses import asdict
from datetime import date
from decimal import Decimal

from backend.loader.expense_loader import Expense


def expense_to_record(expense: Expense) -> dict:
    return {
        **asdict(expense),
        "date": expense.date.isoformat(),
        "submission_date": expense.submission_date.isoformat(),
        "amount": str(expense.amount),
    }


def expense_from_record(record: str) -> Expense:
    data = json.loads(record)
    return Expense(
        **{
            **data,
            "date": date.fromisoformat(data["date"]),
            "submission_date": date.fromisoformat(data["submission_date"]),
            "amount": Decimal(data["amount"]),
        }
    )


def encoded(value: object) -> str:
    """Canonical JSON used for persisted snapshots and fingerprints."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False)
