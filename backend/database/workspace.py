"""Compose focused repositories sharing one workspace database."""

from pathlib import Path

from backend.database.artifacts import ArtifactRepository
from backend.database.checks import CheckRepository
from backend.database.core import Database
from backend.database.datasets import DatasetRepository
from backend.database.reviews import ReviewRepository
from backend.database.sessions import SessionRepository


class WorkspaceStore:
    def __init__(self, root: Path):
        self.database = Database(root)
        self.sessions = SessionRepository(self.database)
        self.datasets = DatasetRepository(self.database)
        self.checks = CheckRepository(self.database)
        self.reviews = ReviewRepository(self.database)
        self.artifacts = ArtifactRepository(self.database)
