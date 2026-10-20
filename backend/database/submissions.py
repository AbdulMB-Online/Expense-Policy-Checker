"""SQLite repository for claims and receipts; no HTTP or policy dependencies."""

import json
from collections.abc import Callable
from contextlib import closing
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from backend.database.core import Database, add_revision, artifact
from backend.database.errors import (
    ReceiptNotFoundError,
    SubmissionConflictError,
    storage_errors,
)
from backend.database.models import Receipt, SavedExpense
from backend.database.schema import MAX_ATTACHMENT_BYTES
from backend.database.serialization import expense_from_record, expense_to_record
from backend.loader.expense_loader import Expense


class SubmissionStore:
    """Own connections, schema, queries, and atomic claim/receipt persistence."""

    def __init__(self, root: Path):
        self.database = Database(root)
        self.path = self.database.path

    def _connect(self):
        return self.database.connect()

    @staticmethod
    def _list(connection, scope):
        return tuple(
            SavedExpense(expense_from_record(record), name)
            for record, name in connection.execute(
                """SELECT e.record,a.name FROM expenses e LEFT JOIN artifacts a ON a.id=e.receipt_id
               WHERE e.scope=? AND e.origin='submission' ORDER BY e.rowid""",
                (scope,),
            )
        )

    @storage_errors
    def list(self, scope: str) -> tuple[SavedExpense, ...]:
        if not self.path.exists():
            return ()
        with closing(self._connect()) as connection:
            return self._list(connection, scope)

    @storage_errors
    def save(
        self,
        scope: str,
        request_id: str,
        expense: Expense,
        receipt: Receipt | None,
        validate: Callable[[tuple[Expense, ...]], object],
        *,
        owner_id: str | None = None,
        created_by: str | None = None,
    ) -> str:
        record = expense_to_record(expense)
        if receipt is not None and len(receipt.contents) > MAX_ATTACHMENT_BYTES:
            raise ValueError("Receipt must be 5 MiB or smaller.")
        comparable = {
            key: value for key, value in record.items() if key not in {"id", "submission_date"}
        }
        fingerprint = sha256(
            json.dumps(comparable, sort_keys=True).encode()
            + (receipt.name.encode() + receipt.contents if receipt else b"")
        ).hexdigest()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                """SELECT external_id,fingerprint FROM expenses WHERE scope=? AND request_id=?
                   AND created_by IS ? AND origin='submission'""",
                (scope, request_id, created_by),
            ).fetchone()
            if previous:
                if previous[1] != fingerprint:
                    raise SubmissionConflictError(
                        "This submission was already saved with different details. Start a new expense."
                    )
                return previous[0]
            saved = self._list(connection, scope)
            # The caller supplies validation. Running it inside this transaction
            # keeps its full-input check and the subsequent write atomic.
            validate(tuple(item.expense for item in saved) + (expense,))
            receipt_id = (
                artifact(
                    connection,
                    "receipt",
                    receipt.name,
                    receipt.media_type,
                    receipt.contents,
                    created_by,
                )
                if receipt
                else None
            )
            internal_id = uuid4().hex
            connection.execute(
                """INSERT INTO expenses(id,scope,external_id,origin,owner_id,created_by,request_id,fingerprint,record,receipt_id)
                VALUES (?,?,?,'submission',?,?,?,?,?,?)""",
                (
                    internal_id,
                    scope,
                    expense.id,
                    owner_id,
                    created_by,
                    request_id,
                    fingerprint,
                    json.dumps(record),
                    receipt_id,
                ),
            )
            add_revision(connection, internal_id)
            return expense.id

    @storage_errors
    def receipt(self, scope: str, expense_id: str) -> Receipt:
        if self.path.exists():
            with closing(self._connect()) as connection:
                row = connection.execute(
                    """SELECT a.name,a.media_type,a.contents FROM expenses e
                    JOIN artifacts a ON a.id=e.receipt_id WHERE e.scope=? AND e.external_id=?""",
                    (scope, expense_id),
                ).fetchone()
            if row and row[2] is not None:
                return Receipt(*row)
        raise ReceiptNotFoundError("No receipt is available for this claim.")
