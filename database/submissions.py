"""SQLite repository for claims and receipts; no HTTP or policy dependencies."""

from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict
from datetime import date
from decimal import Decimal
from functools import wraps
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

from database.models import Receipt, SavedExpense
from loader.expense_loader import Expense


class StorageError(Exception):
    """The underlying submission storage could not be read or written."""


class SubmissionConflictError(Exception):
    """A saved request key was reused with different claim details."""


class ReceiptNotFoundError(Exception):
    """The requested claim has no receipt in this workspace."""


def _storage_errors(operation):
    """Keep driver and filesystem failures inside the database boundary."""
    @wraps(operation)
    def wrapped(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except (sqlite3.Error, OSError) as error:
            raise StorageError("Submission storage is unavailable.") from error
    return wrapped


def _record(expense: Expense) -> dict:
    return {**asdict(expense), "date": expense.date.isoformat(), "submission_date": expense.submission_date.isoformat(), "amount": str(expense.amount)}


def _expense(record: str) -> Expense:
    data = json.loads(record)
    return Expense(**{**data, "date": date.fromisoformat(data["date"]), "submission_date": date.fromisoformat(data["submission_date"]), "amount": Decimal(data["amount"])})


class SubmissionStore:
    """Own connections, schema, queries, and atomic claim/receipt persistence."""

    def __init__(self, root: Path):
        self.path = root / "artifacts" / "submissions.sqlite3"

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.execute("""CREATE TABLE IF NOT EXISTS submissions (
                id TEXT PRIMARY KEY, scope TEXT NOT NULL, request_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL, record TEXT NOT NULL,
                receipt_name TEXT, receipt_type TEXT, receipt_data BLOB,
                UNIQUE(scope, request_id)
            )""")
            connection.commit()
        except Exception:
            connection.close()
            raise
        return connection

    @staticmethod
    def _list(connection, scope):
        return tuple(SavedExpense(_expense(record), name) for record, name in connection.execute(
            "SELECT record, receipt_name FROM submissions WHERE scope = ? ORDER BY rowid", (scope,),
        ))

    @_storage_errors
    def list(self, scope: str) -> tuple[SavedExpense, ...]:
        if not self.path.exists():
            return ()
        with closing(self._connect()) as connection:
            return self._list(connection, scope)

    @_storage_errors
    def save(
        self, scope: str, request_id: str, expense: Expense, receipt: Receipt | None,
        validate: Callable[[tuple[Expense, ...]], object],
    ) -> str:
        record = _record(expense)
        comparable = {key: value for key, value in record.items() if key not in {"id", "submission_date"}}
        fingerprint = sha256(json.dumps(comparable, sort_keys=True).encode() + (
            receipt.name.encode() + receipt.contents if receipt else b""
        )).hexdigest()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT id, fingerprint FROM submissions WHERE scope = ? AND request_id = ?", (scope, request_id),
            ).fetchone()
            if previous:
                if previous[1] != fingerprint:
                    raise SubmissionConflictError("This submission was already saved with different details. Start a new expense.")
                return previous[0]
            saved = self._list(connection, scope)
            # The caller supplies validation. Running it inside this transaction
            # keeps its full-input check and the subsequent write atomic.
            validate(tuple(item.expense for item in saved) + (expense,))
            connection.execute("INSERT INTO submissions VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (
                expense.id, scope, request_id, fingerprint, json.dumps(record),
                receipt.name if receipt else None, receipt.media_type if receipt else None,
                receipt.contents if receipt else None,
            ))
            return expense.id

    @_storage_errors
    def receipt(self, scope: str, expense_id: str) -> Receipt:
        if self.path.exists():
            with closing(self._connect()) as connection:
                row = connection.execute("SELECT receipt_name, receipt_type, receipt_data FROM submissions WHERE scope = ? AND id = ?", (scope, expense_id)).fetchone()
            if row and row[2] is not None:
                return Receipt(*row)
        raise ReceiptNotFoundError("No receipt is available for this claim.")
