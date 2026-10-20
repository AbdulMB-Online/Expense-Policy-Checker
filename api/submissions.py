"""Validate form and upload input; persistence belongs to database.submissions."""

import csv
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile

from database.models import Receipt
from loader.expense_loader import Expense, FIELDS, load_expenses


MAX_RECEIPT_BYTES = 5 * 1024 * 1024


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
