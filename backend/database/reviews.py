"""SQLite persistence for reviews."""

from contextlib import closing

from backend.database.core import Database, add_revision, artifact
from backend.database.errors import (
    AccessError,
    RecordNotFoundError,
    SubmissionConflictError,
    storage_errors,
)
from backend.database.schema import MAX_ATTACHMENT_BYTES
from backend.database.serialization import (
    encoded,
    expense_from_record,
    expense_to_record,
)


class ReviewRepository:
    def __init__(self, database: Database):
        self.database = database

    @storage_errors
    def expense(self, scope, external_id, user):
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                "SELECT id,owner_id,record,revision FROM expenses WHERE scope=? AND external_id=?",
                (scope, external_id),
            ).fetchone()
        if row is None or (user["role"] != "reviewer" and row[1] != user["id"]):
            raise RecordNotFoundError("Expense not found.")
        return row

    @storage_errors
    def history(self, scope, external_id, user):
        row = self.expense(scope, external_id, user)
        with closing(self.database.connect()) as connection:
            return [
                dict(
                    zip(
                        ("revision", "decision", "comment", "reviewer", "created_at", "run_id"),
                        item,
                    )
                )
                for item in connection.execute(
                    """SELECT r.revision,v.decision,v.comment,u.name,v.created_at,v.run_id
                FROM expense_revisions r JOIN review_events v ON v.revision_id=r.id JOIN users u ON u.id=v.reviewer_id
                WHERE r.expense_id=? ORDER BY r.revision""",
                    (row[0],),
                )
            ]

    @storage_errors
    def review(self, scope, external_id, reviewer, run_id, revision_id, decision, comment):
        if reviewer["role"] != "reviewer":
            raise AccessError("A reviewer account is required.")
        with self.database.transaction() as connection:
            row = connection.execute(
                """SELECT e.owner_id,r.id FROM expenses e JOIN expense_revisions r
                ON r.expense_id=e.id AND r.revision=e.revision WHERE e.scope=? AND e.external_id=?""",
                (scope, external_id),
            ).fetchone()
            if not row:
                raise RecordNotFoundError("Expense not found.")
            if row[0] is None:
                raise SubmissionConflictError(
                    "Map this expense to an employee before reviewing it."
                )
            if row[0] == reviewer["id"]:
                raise AccessError("You cannot review your own expense.")
            if (
                row[1] != revision_id
                or not connection.execute(
                    "SELECT 1 FROM check_results WHERE run_id=? AND revision_id=?",
                    (run_id, revision_id),
                ).fetchone()
            ):
                raise SubmissionConflictError("This expense changed. Refresh before reviewing it.")
            # Recheck the complete duplicate context under the write lock: a
            # different submission may have changed since the API loaded it.
            changed = connection.execute(
                """SELECT 1 FROM check_results c JOIN expense_revisions r ON r.id=c.revision_id
                JOIN expenses e ON e.id=r.expense_id WHERE c.run_id=? AND r.revision<>e.revision LIMIT 1""",
                (run_id,),
            ).fetchone()
            added = connection.execute(
                """SELECT 1 FROM expenses e WHERE e.scope=? AND e.origin='submission'
                AND NOT EXISTS (SELECT 1 FROM check_results c JOIN expense_revisions r ON r.id=c.revision_id
                    WHERE c.run_id=? AND r.expense_id=e.id AND r.revision=e.revision) LIMIT 1""",
                (scope, run_id),
            ).fetchone()
            if changed or added:
                raise SubmissionConflictError(
                    "The checks changed. Refresh before reviewing this expense."
                )
            if connection.execute(
                "SELECT 1 FROM review_events WHERE revision_id=?", (revision_id,)
            ).fetchone():
                raise SubmissionConflictError(
                    "This expense has already been reviewed. Refresh to see the decision."
                )
            connection.execute(
                "INSERT INTO review_events(revision_id,run_id,reviewer_id,decision,comment) VALUES (?,?,?,?,?)",
                (revision_id, run_id, reviewer["id"], decision, comment),
            )

    @storage_errors
    def map_owner(self, scope, external_id, owner_id):
        with self.database.transaction() as connection:
            if not connection.execute("SELECT 1 FROM users WHERE id=?", (owner_id,)).fetchone():
                raise RecordNotFoundError("Employee account not found.")
            row = connection.execute(
                "SELECT id,owner_id FROM expenses WHERE scope=? AND external_id=?",
                (scope, external_id),
            ).fetchone()
            if not row:
                raise RecordNotFoundError("Expense not found.")
            if row[1] is not None:
                raise SubmissionConflictError("This expense already belongs to an account.")
            connection.execute(
                "UPDATE expenses SET owner_id=?,revision=revision+1 WHERE id=?", (owner_id, row[0])
            )
            add_revision(connection, row[0])

    @storage_errors
    def resubmit(self, scope, external_id, user, expense, receipt, expected_revision, validate):
        if receipt is not None and len(receipt.contents) > MAX_ATTACHMENT_BYTES:
            raise ValueError("Receipt must be 5 MiB or smaller.")
        with self.database.transaction() as connection:
            row = connection.execute(
                """SELECT e.id,e.owner_id,e.revision,e.receipt_id,v.decision,e.origin
                FROM expenses e JOIN expense_revisions r ON r.expense_id=e.id AND r.revision=e.revision
                LEFT JOIN review_events v ON v.revision_id=r.id WHERE e.scope=? AND e.external_id=?""",
                (scope, external_id),
            ).fetchone()
            if not row or row[1] != user["id"]:
                raise RecordNotFoundError("Expense not found.")
            if row[5] != "submission":
                raise SubmissionConflictError("Correct imported expenses in a new CSV upload.")
            if row[2] != expected_revision or row[4] != "changes_requested":
                raise SubmissionConflictError(
                    "Only the current expense with requested changes can be resubmitted."
                )
            candidates = tuple(
                expense_from_record(item[0])
                for item in connection.execute(
                    "SELECT record FROM expenses WHERE scope=? AND origin='submission' AND id<>? ORDER BY rowid",
                    (scope, row[0]),
                )
            )
            validate(candidates + (expense,))
            receipt_id = (
                artifact(
                    connection,
                    "receipt",
                    receipt.name,
                    receipt.media_type,
                    receipt.contents,
                    user["id"],
                )
                if receipt
                else row[3]
            )
            connection.execute(
                "UPDATE expenses SET record=?,receipt_id=?,revision=revision+1 WHERE id=?",
                (encoded(expense_to_record(expense)), receipt_id, row[0]),
            )
            add_revision(connection, row[0])
