"""Use the database layer directly, without a web app or HTTP exceptions."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
import json
import sqlite3

import pytest

from backend.database.models import Receipt, SavedExpense
from backend.database.errors import ReceiptNotFoundError, StorageError, SubmissionConflictError
from backend.database.submissions import SubmissionStore
from backend.loader.expense_loader import Expense


@pytest.fixture
def expense():
    return Expense(
        id="USR-EXAMPLE", employee="Example Employee", date=date(2026, 10, 10),
        category="meals", amount=Decimal("20.00"), description="Client lunch",
        receipt_attached=True, submission_date=date(2026, 10, 20), nights=None,
    )


def test_reads_are_lazy_and_missing_receipts_use_a_domain_error(tmp_path):
    repository = SubmissionStore(tmp_path)
    assert repository.list("stored:USD") == ()
    with pytest.raises(ReceiptNotFoundError, match="No receipt is available"):
        repository.receipt("stored:USD", "unknown")
    assert not repository.path.exists()


def test_repository_round_trip_retry_and_conflict_without_http(tmp_path, expense):
    repository = SubmissionStore(tmp_path)
    receipt = Receipt("Lunch.pdf", "application/pdf", b"%PDF-1.4 receipt")
    checked = []
    claim_id = repository.save("stored:USD", "request-one", expense, receipt, checked.append)
    assert claim_id == expense.id
    assert checked == [(expense,)]
    assert repository.list("stored:USD") == (SavedExpense(expense, receipt.name),)
    assert repository.receipt("stored:USD", claim_id) == receipt
    retry = replace(expense, id="ANOTHER-SERVER-ID", submission_date=date(2026, 10, 21))
    assert repository.save("stored:USD", "request-one", retry, receipt, checked.append) == claim_id
    assert len(checked) == 1
    with pytest.raises(SubmissionConflictError, match="different details"):
        repository.save("stored:USD", "request-one", replace(expense, amount=Decimal("30.00")), receipt, checked.append)
    assert repository.list("stored:EUR") == ()
    assert repository.list("stored:USD") == (SavedExpense(expense, receipt.name),)


def test_caller_validation_failure_rolls_back_and_preserves_saved_receipt(tmp_path, expense):
    repository = SubmissionStore(tmp_path)
    receipt = Receipt("Lunch.pdf", "application/pdf", b"%PDF-1.4 receipt")
    repository.save("stored:USD", "first", expense, receipt, lambda records: None)
    candidate = replace(expense, id="USR-SECOND", amount=Decimal("30.00"))
    failure = ValueError("Caller validation failed")
    def reject(records):
        assert records == (expense, candidate)
        raise failure
    with pytest.raises(ValueError) as result:
        repository.save("stored:USD", "second", candidate, receipt, reject)
    assert result.value is failure
    assert repository.list("stored:USD") == (SavedExpense(expense, receipt.name),)
    assert repository.receipt("stored:USD", expense.id) == receipt
    with pytest.raises(ReceiptNotFoundError):
        repository.receipt("stored:USD", candidate.id)


@pytest.mark.parametrize("operation", ["list", "save", "receipt"])
@pytest.mark.parametrize("failure", [sqlite3.OperationalError("database unavailable"), OSError("storage unavailable")])
def test_storage_errors_hide_the_driver_from_callers(tmp_path, expense, monkeypatch, operation, failure):
    repository = SubmissionStore(tmp_path)
    repository.path.parent.mkdir()
    repository.path.touch()
    def fail():
        raise failure
    monkeypatch.setattr(repository, "_connect", fail)
    calls = {
        "list": lambda: repository.list("stored:USD"),
        "save": lambda: repository.save("stored:USD", "request", expense, None, lambda records: None),
        "receipt": lambda: repository.receipt("stored:USD", expense.id),
    }
    with pytest.raises(StorageError) as result:
        calls[operation]()
    assert result.value.__cause__ is failure


def test_existing_database_schema_and_records_remain_readable(tmp_path, expense):
    # Seed the exact pre-refactor schema independently of repository creation.
    repository = SubmissionStore(tmp_path)
    repository.path.parent.mkdir()
    record = {
        "id": expense.id, "employee": expense.employee, "date": "2026-10-10",
        "category": "meals", "amount": "20.00", "description": "Client lunch",
        "receipt_attached": True, "submission_date": "2026-10-20", "nights": None,
    }
    with sqlite3.connect(repository.path) as connection:
        connection.execute("""CREATE TABLE submissions (
            id TEXT PRIMARY KEY, scope TEXT NOT NULL, request_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL, record TEXT NOT NULL,
            receipt_name TEXT, receipt_type TEXT, receipt_data BLOB,
            UNIQUE(scope, request_id)
        )""")
        connection.execute("INSERT INTO submissions VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (
            expense.id, "stored:USD", "old-request", "old-fingerprint", json.dumps(record),
            "Original.pdf", "application/pdf", b"%PDF-1.4 original",
        ))
    assert repository.list("stored:USD") == (SavedExpense(expense, "Original.pdf"),)
    assert repository.receipt("stored:USD", expense.id) == Receipt("Original.pdf", "application/pdf", b"%PDF-1.4 original")
