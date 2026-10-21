"""SQLite persistence for checks."""

import json
from contextlib import closing
from dataclasses import asdict
from hashlib import sha256
from uuid import uuid4

from backend.database.core import Database, add_revision
from backend.database.errors import (
    RecordNotFoundError,
    SubmissionConflictError,
    storage_errors,
)
from backend.database.serialization import (
    encoded,
    expense_to_record,
)


class CheckRepository:
    def __init__(self, database: Database):
        self.database = database

    @storage_errors
    def evaluate(self, scope, policy, expenses, errors, engine_version, evaluate, dataset_id):
        """Cache by immutable revision set, policy, and engine; publish atomically."""
        with self.database.transaction() as connection:
            revisions = []
            metadata = {}
            created_by = connection.execute(
                "SELECT created_by FROM datasets WHERE id=?", (dataset_id,)
            ).fetchone()[0]
            for expense in expenses:
                record = encoded(expense_to_record(expense))
                row = connection.execute(
                    "SELECT id,record,owner_id,origin FROM expenses WHERE scope=? AND external_id=?",
                    (scope, expense.id),
                ).fetchone()
                if row is None:
                    owner = connection.execute(
                        "SELECT id FROM users WHERE name=?", (expense.employee,)
                    ).fetchone()
                    internal_id = uuid4().hex
                    connection.execute(
                        "INSERT INTO expenses(id,scope,external_id,origin,owner_id,created_by,record) VALUES (?,?,?,'file',?,?,?)",
                        (
                            internal_id,
                            scope,
                            expense.id,
                            owner[0] if owner else None,
                            created_by,
                            record,
                        ),
                    )
                    add_revision(connection, internal_id)
                else:
                    internal_id = row[0]
                    if encoded(json.loads(row[1])) != record:
                        if row[3] == "submission":
                            raise SubmissionConflictError(
                                "This expense changed. Refresh the report."
                            )
                        # Stored sample files may change. Keep previous reviews and
                        # inputs attached to their original immutable revision.
                        connection.execute(
                            "UPDATE expenses SET record=?,revision=revision+1 WHERE id=?",
                            (record, internal_id),
                        )
                        add_revision(connection, internal_id)
                revision = connection.execute(
                    """SELECT r.id,e.owner_id,e.revision,e.origin FROM expenses e
                    JOIN expense_revisions r ON r.expense_id=e.id AND r.revision=e.revision WHERE e.id=?""",
                    (internal_id,),
                ).fetchone()
                revisions.append(revision[0])
                event = connection.execute(
                    "SELECT decision FROM review_events WHERE revision_id=?", (revision[0],)
                ).fetchone()
                metadata[expense.id] = {
                    "revision_id": revision[0],
                    "owner_id": revision[1],
                    "revision": revision[2],
                    "origin": revision[3],
                    "review_status": event[0] if event else "submitted",
                }
            policy_id = sha256(encoded(policy).encode()).hexdigest()
            fingerprint = sha256(
                encoded([dataset_id, scope, policy_id, revisions, errors, engine_version]).encode()
            ).hexdigest()
            previous = connection.execute(
                "SELECT id,created_at FROM check_runs WHERE fingerprint=?", (fingerprint,)
            ).fetchone()
            if previous:
                run_id, created_at = previous
                rows = connection.execute(
                    """SELECT e.external_id,c.findings FROM check_results c
                    JOIN expense_revisions r ON r.id=c.revision_id JOIN expenses e ON e.id=r.expense_id
                    WHERE c.run_id=? ORDER BY c.position""",
                    (run_id,),
                ).fetchall()
                findings = {key: json.loads(value) for key, value in rows if json.loads(value)}
            else:
                findings = {
                    key: [asdict(item) for item in value] for key, value in evaluate().items()
                }
                run_id = uuid4().hex
                connection.execute(
                    "INSERT INTO check_runs(id,fingerprint,dataset_id,scope,policy_id,engine_version,errors) VALUES (?,?,?,?,?,?,?)",
                    (
                        run_id,
                        fingerprint,
                        dataset_id,
                        scope,
                        policy_id,
                        engine_version,
                        encoded(errors),
                    ),
                )
                for position, (expense, revision_id) in enumerate(zip(expenses, revisions)):
                    connection.execute(
                        "INSERT INTO check_results VALUES (?,?,?,?)",
                        (run_id, revision_id, position, encoded(findings.get(expense.id, []))),
                    )
                created_at = connection.execute(
                    "SELECT created_at FROM check_runs WHERE id=?", (run_id,)
                ).fetchone()[0]
            return run_id, created_at, findings, metadata

    @storage_errors
    def check_run(self, key):
        with closing(self.database.connect()) as connection:
            run = connection.execute(
                """SELECT c.id,c.scope,c.engine_version,c.errors,c.created_at,p.body,c.dataset_id
                FROM check_runs c JOIN policy_versions p ON p.id=c.policy_id WHERE c.id=?""",
                (key,),
            ).fetchone()
            if not run:
                raise RecordNotFoundError("Check run not found.")
            claims = [
                {
                    "expense": json.loads(record),
                    "revision": revision,
                    "revision_id": revision_id,
                    "owner_id": owner,
                    "violations": json.loads(findings),
                    "receipt_artifact_id": receipt_id,
                }
                for record, revision, revision_id, owner, findings, receipt_id in connection.execute(
                    """SELECT r.record,r.revision,r.id,r.owner_id,c.findings,r.receipt_id
                          FROM check_results c JOIN expense_revisions r ON r.id=c.revision_id WHERE c.run_id=? ORDER BY c.position""",
                    (key,),
                )
            ]
        return {
            "id": run[0],
            "scope": run[1],
            "engine_version": run[2],
            "errors": json.loads(run[3]),
            "created_at": run[4],
            "policy": json.loads(run[5]),
            "dataset_id": run[6],
            "claims": claims,
        }
