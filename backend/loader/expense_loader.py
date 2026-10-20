"""Read CSV expenses without mixing validation with policy decisions."""

import csv
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

FIELDS = (
    "id",
    "employee",
    "date",
    "category",
    "amount",
    "description",
    "receipt_attached",
    "submission_date",
    "nights",
)


@dataclass(frozen=True)
class Expense:
    id: str
    employee: str
    date: date
    category: str
    amount: Decimal
    description: str
    receipt_attached: bool
    submission_date: date
    nights: int | None


@dataclass(frozen=True)
class LoadError:
    line_number: int
    expense_id: str | None
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class LoadResult:
    expenses: tuple[Expense, ...]
    errors: tuple[LoadError, ...]


def load_expenses(path: str | Path) -> LoadResult:
    """Collect row errors; raise file-level exceptions for unusable input."""
    expenses = []
    errors = []
    accepted_ids = set()
    with Path(path).open(encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source, strict=True)
        headers = next(reader, None)
        if headers is None or len(headers) != len(FIELDS) or set(headers) != set(FIELDS):
            raise ValueError(f"CSV headers must contain exactly: {', '.join(FIELDS)}")
        id_index = headers.index("id")
        while True:
            line_number = reader.line_num + 1
            values = next(reader, None)
            if values is None:
                break
            if not values:
                continue
            if len(values) != len(headers):
                expense_id = values[id_index].strip() or None if id_index < len(values) else None
                errors.append(
                    LoadError(
                        line_number,
                        expense_id,
                        (f"Expected {len(headers)} fields, got {len(values)}",),
                    )
                )
                continue
            row = {key: value.strip() for key, value in zip(headers, values)}
            reasons = [
                f"{key}: required field is empty"
                for key in FIELDS
                if key != "nights" and not row[key]
            ]
            parsed_dates = {}
            amount = None
            nights = None
            for field in ("date", "submission_date"):
                if not row[field]:
                    continue
                try:
                    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", row[field]):
                        raise ValueError
                    parsed_dates[field] = date.fromisoformat(row[field])
                except ValueError:
                    reasons.append(f"{field}: expected a real date in YYYY-MM-DD format")
            if row["nights"]:
                if not re.fullmatch(r"[0-9]+", row["nights"]) or not row["nights"].strip("0"):
                    reasons.append("nights: expected a positive integer")
                else:
                    try:
                        nights = int(row["nights"])
                    except ValueError:
                        reasons.append("nights: integer is too large")
            if row["amount"]:
                if not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,2})?", row["amount"]):
                    reasons.append(
                        "amount: expected a nonnegative decimal with at most two decimal places"
                    )
                else:
                    amount = Decimal(row["amount"])
            if row["receipt_attached"] and row["receipt_attached"].lower() not in {"true", "false"}:
                reasons.append("receipt_attached: expected true or false")
            if row["id"] in accepted_ids:
                reasons.append("id: duplicates a previously accepted record")
            if reasons:
                errors.append(LoadError(line_number, row["id"] or None, tuple(reasons)))
                continue
            expenses.append(
                Expense(
                    id=row["id"],
                    employee=row["employee"],
                    date=parsed_dates["date"],
                    category=row["category"],
                    amount=amount,
                    description=row["description"],
                    receipt_attached=row["receipt_attached"].lower() == "true",
                    submission_date=parsed_dates["submission_date"],
                    nights=nights,
                )
            )
            accepted_ids.add(row["id"])
    return LoadResult(tuple(expenses), tuple(errors))
