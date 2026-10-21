"""SQLite persistence for sessions."""

import time
from contextlib import closing
from hashlib import sha256
from secrets import token_urlsafe

from backend.database.core import Database
from backend.database.errors import (
    AccessError,
    RecordNotFoundError,
    storage_errors,
)


class SessionRepository:
    def __init__(self, database: Database):
        self.database = database

    @storage_errors
    def users(self):
        with closing(self.database.connect()) as connection:
            return [
                dict(zip(("id", "name", "role"), row))
                for row in connection.execute("SELECT id,name,role FROM users ORDER BY role,name")
            ]

    @storage_errors
    def login(self, user_id):
        with self.database.transaction() as connection:
            user = connection.execute(
                "SELECT id,name,role FROM users WHERE id=?", (user_id,)
            ).fetchone()
            if user is None:
                raise RecordNotFoundError("Choose a demo account.")
            token = token_urlsafe(32)
            connection.execute("DELETE FROM sessions WHERE expires_at<=?", (int(time.time()),))
            connection.execute(
                "INSERT INTO sessions VALUES (?,?,?)",
                (sha256(token.encode()).hexdigest(), user_id, int(time.time()) + 86400),
            )
            return token, dict(zip(("id", "name", "role"), user))

    @storage_errors
    def session(self, token):
        if not token:
            raise AccessError("Choose a demo account to continue.")
        with closing(self.database.connect()) as connection:
            row = connection.execute(
                """SELECT u.id,u.name,u.role FROM sessions s JOIN users u ON u.id=s.user_id
                WHERE s.token_hash=? AND s.expires_at>?""",
                (sha256(token.encode()).hexdigest(), int(time.time())),
            ).fetchone()
        if row is None:
            raise AccessError("Your demo session expired. Choose an account again.")
        return dict(zip(("id", "name", "role"), row))

    @storage_errors
    def logout(self, token):
        with self.database.transaction() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_hash=?",
                (sha256((token or "").encode()).hexdigest(),),
            )
