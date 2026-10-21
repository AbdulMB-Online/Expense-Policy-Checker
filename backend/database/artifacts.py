"""SQLite persistence for artifacts."""

from contextlib import closing

from backend.database.core import Database, artifact
from backend.database.errors import (
    RecordNotFoundError,
    storage_errors,
)
from backend.database.serialization import (
    encoded,
)


class ArtifactRepository:
    def __init__(self, database: Database):
        self.database = database

    @storage_errors
    def save_export(self, run_id, user_id, name, contents, filters):
        with self.database.transaction() as connection:
            key = artifact(connection, "report", name, "text/plain", contents, user_id)
            connection.execute(
                "INSERT INTO exports VALUES (?,?,?,?)", (key, run_id, user_id, encoded(filters))
            )
            return key

    @storage_errors
    def artifacts(self):
        with closing(self.database.connect()) as connection:
            return [
                dict(
                    zip(
                        (
                            "id",
                            "kind",
                            "name",
                            "media_type",
                            "size",
                            "sha256",
                            "uploaded_by",
                            "created_at",
                        ),
                        row,
                    )
                )
                for row in connection.execute(
                    "SELECT id,kind,name,media_type,size,sha256,uploaded_by,created_at FROM artifacts ORDER BY rowid DESC"
                )
            ]

    @storage_errors
    def artifact(self, key):
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                "SELECT name,media_type,contents FROM artifacts WHERE id=?", (key,)
            ).fetchone()
        if row is None:
            raise RecordNotFoundError("Attachment not found.")
        return row
