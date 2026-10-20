"""Versioned SQLite schema and connections shared by all repositories."""

import json
import sqlite3
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from backend.database.schema import (
    DEMO_USERS,
    SCHEMA,
    SCHEMA_VERSION,
)


def artifact(connection, kind, name, media_type, contents, user_id=None):
    """Write file bytes only on upload; metadata queries never fetch BLOBs."""
    key = uuid4().hex
    connection.execute(
        "INSERT INTO artifacts(id,kind,name,media_type,contents,size,sha256,uploaded_by) VALUES (?,?,?,?,?,?,?,?)",
        (
            key,
            kind,
            name,
            media_type,
            contents,
            len(contents),
            sha256(contents).hexdigest(),
            user_id,
        ),
    )
    return key


def add_revision(connection, expense_id):
    row = connection.execute(
        "SELECT revision,record,owner_id,receipt_id FROM expenses WHERE id=?", (expense_id,)
    ).fetchone()
    key = uuid4().hex
    connection.execute(
        "INSERT INTO expense_revisions(id,expense_id,revision,record,owner_id,receipt_id) VALUES (?,?,?,?,?,?)",
        (key, expense_id, *row),
    )
    return key


class Database:
    def __init__(self, root: Path):
        # Retain the original location so existing local receipts are migrated.
        self.path = Path(root) / "artifacts" / "submissions.sqlite3"

    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN IMMEDIATE")
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise sqlite3.DatabaseError("Database schema is newer than this application")
            if version == 0:
                for statement in SCHEMA:
                    connection.execute(statement)
                connection.executemany("INSERT INTO users VALUES (?,?,?)", DEMO_USERS)
                self._migrate_legacy(connection)
                connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            connection.commit()
            return connection
        except Exception:
            connection.rollback()
            connection.close()
            raise

    @staticmethod
    def _migrate_legacy(connection):
        if not connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='submissions'"
        ).fetchone():
            return
        for (
            key,
            scope,
            request,
            fingerprint,
            record,
            name,
            media_type,
            contents,
        ) in connection.execute("SELECT * FROM submissions").fetchall():
            employee = json.loads(record)["employee"]
            owner = connection.execute("SELECT id FROM users WHERE name=?", (employee,)).fetchone()
            receipt_id = (
                artifact(connection, "receipt", name, media_type, contents)
                if contents is not None
                else None
            )
            internal_id = uuid4().hex
            connection.execute(
                """INSERT INTO expenses(id,scope,external_id,origin,owner_id,request_id,fingerprint,record,receipt_id)
                VALUES (?,?,?,'submission',?,?,?,?,?)""",
                (
                    internal_id,
                    scope,
                    key,
                    owner[0] if owner else None,
                    request,
                    fingerprint,
                    record,
                    receipt_id,
                ),
            )
            add_revision(connection, internal_id)
        # The legacy table remains for recovery, but is no longer read or written.

    @contextmanager
    def transaction(self):
        connection = self.connect()
        try:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
        finally:
            connection.close()
