"""Validate and save policies independently of expense datasets."""

from backend.database.policies import policy_record
from backend.loader.policy_loader import load_policy
from backend.services.sources import DEFAULT_POLICY, SourceStore, _stored, _uploaded
from backend.services.uploads import UploadedFile


class PolicyService:
    def __init__(self, sources: SourceStore):
        self.sources = sources
        self.repository = sources.workspace.policies

    def list(self):
        default, _ = _stored(self.sources.root / DEFAULT_POLICY, load_policy)
        record = policy_record(default)
        return [record, *(item for item in self.repository.list() if item["id"] != record["id"])]

    def save(self, upload: UploadedFile, user: dict):
        policy, name, _, contents = _uploaded(upload, load_policy, "policy.json")
        return self.repository.save(policy, name, contents, user["id"])
