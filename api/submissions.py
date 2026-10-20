"""Validate form records and persist claims and receipts atomically."""

from contextlib import closing
import csv
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile

from loader.expense_loader import Expense, FIELDS, load_expenses


MAX_RECEIPT_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class Receipt:
    name: str
    media_type: str
    contents: bytes


@dataclass(frozen=True)
class SavedExpense:
    expense: Expense
    receipt_name: str | None


def read_receipt(file: UploadFile | None) -> Receipt | None:
    if file is None:
        return None
    contents = file.file.read(MAX_RECEIPT_BYTES + 1)
    if len(contents) > MAX_RECEIPT_BYTES:
        raise HTTPException(413, "Receipt must be 5 MiB or smaller.")
    if contents.startswith(b"%PDF-"):
        media_type = "application/pdf"
    elif contents.startswith(b"\x89PNG\r\n\x1a\n"):
        media_type = "image/png"
    elif contents.startswith(b"\xff\xd8\xff"):
        media_type = "image/jpeg"
    else:
        raise HTTPException(422, {"message": "Choose a PDF, PNG, or JPEG receipt.", "fields": {"receipt": "The file contents must be PDF, PNG, or JPEG."}})
    name = Path((file.filename or "receipt").replace("\\", "/")).name
    name = "".join(char for char in name if char.isprintable())[:200] or "receipt"
    return Receipt(name, media_type, contents)


def parse_expense(values: dict, policy: dict, attached: bool) -> Expense:
    """Use the CSV loader's validation so form and imported rows agree."""
    row = {
        **values, "id": "USR-" + uuid4().hex.upper(),
        "receipt_attached": "true" if attached else "false",
        "submission_date": date.today().isoformat(),
    }
    with TemporaryDirectory(prefix="expense-form-") as directory:
        path = Path(directory) / "record.csv"
        with path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerow(row)
        result = load_expenses(path)
    fields = {}
    if result.errors:
        for reason in result.errors[0].reasons:
            field, _, message = reason.partition(": ")
            fields[field] = message
    settings = policy["categories"].get(values["category"].strip())
    if settings is None:
        fields["category"] = "Choose a category from the active policy."
    elif (settings.get("nights_required") or settings["limit_basis"] == "per_night") and not values["nights"].strip():
        fields["nights"] = "Enter the number of nights for this category."
    if fields:
        raise HTTPException(422, {"message": "Please correct the highlighted expense details.", "fields": fields})
    return result.expenses[0]


def validate_request_id(value: str) -> str:
    try:
        return str(UUID(value))
    except ValueError as error:
        raise HTTPException(422, "Start a new submission and try again.") from error


def _record(expense: Expense) -> dict:
    return {**asdict(expense), "date": expense.date.isoformat(), "submission_date": expense.submission_date.isoformat(), "amount": str(expense.amount)}


def _expense(record: str) -> Expense:
    data = json.loads(record)
    return Expense(**{**data, "date": date.fromisoformat(data["date"]), "submission_date": date.fromisoformat(data["submission_date"]), "amount": Decimal(data["amount"])})


class SubmissionStore:
    """SQLite keeps a receipt and its claim in one durable transaction."""

    def __init__(self, root: Path):
        self.path = root / "artifacts" / "submissions.sqlite3"

    def _connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        connection.execute("""CREATE TABLE IF NOT EXISTS submissions (
            id TEXT PRIMARY KEY, scope TEXT NOT NULL, request_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL, record TEXT NOT NULL,
            receipt_name TEXT, receipt_type TEXT, receipt_data BLOB,
            UNIQUE(scope, request_id)
        )""")
        connection.commit()
        return connection

    @staticmethod
    def _list(connection, scope):
        return tuple(SavedExpense(_expense(record), name) for record, name in connection.execute(
            "SELECT record, receipt_name FROM submissions WHERE scope = ? ORDER BY rowid", (scope,),
        ))

    def list(self, scope: str) -> tuple[SavedExpense, ...]:
        if not self.path.exists():
            return ()
        with closing(self._connect()) as connection:
            return self._list(connection, scope)

    def save(self, scope: str, request_id: str, expense: Expense, receipt: Receipt | None, validate) -> str:
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
                    raise HTTPException(409, "This submission was already saved with different details. Start a new expense.")
                return previous[0]
            saved = self._list(connection, scope)
            # Check every rule with existing CSV and submitted claims before
            # committing. Policy flags are saved; input or engine errors aren't.
            validate(tuple(item.expense for item in saved) + (expense,))
            connection.execute("INSERT INTO submissions VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (
                expense.id, scope, request_id, fingerprint, json.dumps(record),
                receipt.name if receipt else None, receipt.media_type if receipt else None,
                receipt.contents if receipt else None,
            ))
            return expense.id

    def receipt(self, scope: str, expense_id: str) -> Receipt:
        if self.path.exists():
            with closing(self._connect()) as connection:
                row = connection.execute("SELECT receipt_name, receipt_type, receipt_data FROM submissions WHERE scope = ? AND id = ?", (scope, expense_id)).fetchone()
            if row and row[2] is not None:
                return Receipt(*row)
        raise HTTPException(404, "No receipt is available for this claim.")
