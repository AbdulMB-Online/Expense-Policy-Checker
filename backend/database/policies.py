"""Reusable policy versions, including policies saved with imported datasets."""

import json
from contextlib import closing
from hashlib import sha256

from backend.database.core import Database, artifact
from backend.database.errors import storage_errors
from backend.database.serialization import encoded


def policy_record(policy):
    return {"id": sha256(encoded(policy).encode()).hexdigest(), "config": policy}


class PolicyRepository:
    def __init__(self, database: Database):
        self.database = database

    @storage_errors
    def list(self):
        with closing(self.database.connect()) as connection:
            rows = connection.execute(
                "SELECT id,body FROM policy_versions ORDER BY rowid DESC"
            ).fetchall()
        return [{"id": row[0], "config": json.loads(row[1])} for row in rows]

    @storage_errors
    def save(self, policy, name, contents, actor):
        record = policy_record(policy)
        with self.database.transaction() as connection:
            if not connection.execute(
                "SELECT 1 FROM policy_versions WHERE id=?", (record["id"],)
            ).fetchone():
                artifact_id = artifact(
                    connection, "policy_json", name, "application/json", contents, actor
                )
                connection.execute(
                    "INSERT INTO policy_versions VALUES (?,?,?,?)",
                    (record["id"], record["id"], encoded(policy), artifact_id),
                )
        return record
