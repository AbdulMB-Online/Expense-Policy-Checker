"""SQLite persistence for datasets."""

import json
from contextlib import closing
from dataclasses import asdict
from hashlib import sha256

from backend.database.core import Database, artifact
from backend.database.errors import (
    RecordNotFoundError,
    storage_errors,
)
from backend.database.serialization import (
    encoded,
    expense_to_record,
)


class DatasetRepository:
    def __init__(self, database: Database):
        self.database = database

    @storage_errors
    def save_dataset(self, key, source, actor=None):
        with self.database.transaction() as connection:
            existing = connection.execute("SELECT 1 FROM datasets WHERE id=?", (key,)).fetchone()
            if existing:
                return key
            expense_artifact = source.expense_artifact_id or artifact(
                connection,
                "expense_csv",
                source.expense_name,
                "text/csv",
                source.expense_contents,
                actor,
            )
            policy_artifact = source.policy_artifact_id or artifact(
                connection,
                "policy_json",
                source.policy_name,
                "application/json",
                source.policy_contents,
                actor,
            )
            fingerprint = sha256(encoded(source.policy).encode()).hexdigest()
            connection.execute(
                "INSERT OR IGNORE INTO policy_versions VALUES (?,?,?,?)",
                (fingerprint, fingerprint, encoded(source.policy), policy_artifact),
            )
            parsed = {
                "expenses": [expense_to_record(item) for item in source.loaded.expenses],
                "errors": [asdict(item) for item in source.loaded.errors],
            }
            connection.execute(
                """INSERT INTO datasets(id,expense_key,expense_artifact_id,policy_id,policy_artifact_id,parsed,created_by)
                VALUES (?,?,?,?,?,?,?)""",
                (
                    key,
                    source.expense_key,
                    expense_artifact,
                    fingerprint,
                    policy_artifact,
                    encoded(parsed),
                    actor,
                ),
            )
        return key

    @storage_errors
    def dataset(self, key):
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                """SELECT d.expense_key,d.parsed,p.body,a.name,a.id,b.name,b.id
                FROM datasets d JOIN policy_versions p ON p.id=d.policy_id
                JOIN artifacts a ON a.id=d.expense_artifact_id JOIN artifacts b ON b.id=d.policy_artifact_id
                WHERE d.id=?""",
                (key,),
            ).fetchone()
        if row is None:
            raise RecordNotFoundError(
                "These uploaded files were not found. Choose a saved dataset or upload files again."
            )
        return row

    @storage_errors
    def datasets(self, user):
        with closing(self.database.connect()) as connection:
            rows = connection.execute("""SELECT d.id,d.created_at,a.name,b.name,d.expense_key,p.body
                FROM datasets d JOIN artifacts a ON a.id=d.expense_artifact_id JOIN artifacts b ON b.id=d.policy_artifact_id
                JOIN policy_versions p ON p.id=d.policy_id
                WHERE d.id NOT LIKE 'stored-%' ORDER BY d.rowid DESC""").fetchall()
            return [
                dict(zip(("id", "created_at", "expenses", "policy"), row[:4]))
                for row in rows
                if user["role"] == "reviewer"
                or connection.execute(
                    "SELECT 1 FROM expenses WHERE scope=? AND owner_id=? LIMIT 1",
                    (f"{row[4]}:{json.loads(row[5])['currency']}", user["id"]),
                ).fetchone()
            ]
