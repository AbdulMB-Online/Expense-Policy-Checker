"""Load named inputs without using uploaded filenames as filesystem paths."""

import csv
import json
from dataclasses import dataclass
from decimal import DecimalException
from hashlib import sha256
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory

from backend.database.errors import RecordNotFoundError
from backend.database.serialization import expense_from_record
from backend.database.workspace import WorkspaceStore
from backend.loader.expense_loader import LoadError, LoadResult, load_expenses
from backend.loader.policy_loader import load_policy
from backend.services.errors import ServiceError
from backend.services.uploads import UploadedFile

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
DEFAULT_EXPENSES = Path("data/expenses/sample_expenses.csv")
DEFAULT_POLICY = Path("data/policy/policy.json")


@dataclass(frozen=True)
class ReportSource:
    loaded: LoadResult
    policy: dict
    expense_name: str
    policy_name: str
    expense_key: str = "stored"
    expense_contents: bytes = b""
    policy_contents: bytes = b""
    expense_artifact_id: str | None = None
    policy_artifact_id: str | None = None

    @property
    def submission_scope(self) -> str:
        return f"{self.expense_key}:{self.policy['currency']}"


def _stored(path: Path, loader):
    try:
        contents = path.read_bytes()
        return _parse(contents, loader, path.name), contents
    except (OSError, ValueError, csv.Error, DecimalException) as error:
        raise ServiceError(
            503,
            "Unable to prepare the report. Check the stored expense CSV and policy JSON, then retry.",
        ) from error


def _parse(contents, loader, internal_name):
    with TemporaryDirectory(prefix="expense-upload-") as directory:
        path = Path(directory) / internal_name
        path.write_bytes(contents)
        return loader(path)


def _uploaded(file: UploadedFile, loader, internal_name: str):
    # Original names are display metadata only, including Windows browser paths.
    name = Path((file.filename or internal_name).replace("\\", "/")).name
    name = "".join(char for char in name if char.isprintable())[:200] or internal_name
    contents = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise ServiceError(413, f"{name}: files must be 5 MiB or smaller.")
    try:
        parsed = _parse(contents, loader, internal_name)
    except (ValueError, csv.Error, DecimalException) as error:
        raise ServiceError(422, f"{name}: {error}") from error
    return parsed, name, sha256(contents).hexdigest(), contents


class SourceStore:
    """Immutable SQLite snapshots; uploaded files survive server restarts."""

    def __init__(self, root: Path, workspace: WorkspaceStore):
        self.root = root
        self.workspace = workspace

    def resolve(self, dataset: str | None) -> ReportSource:
        if dataset:
            try:
                key, parsed, policy, name, expense_artifact, policy_name, policy_artifact = (
                    self.workspace.datasets.dataset(dataset)
                )
            except RecordNotFoundError as error:
                raise ServiceError(404, str(error)) from error
            data = json.loads(parsed)
            loaded = LoadResult(
                tuple(expense_from_record(json.dumps(item)) for item in data["expenses"]),
                tuple(
                    LoadError(item["line_number"], item["expense_id"], tuple(item["reasons"]))
                    for item in data["errors"]
                ),
            )
            return ReportSource(
                loaded,
                json.loads(policy),
                name,
                policy_name,
                key,
                expense_artifact_id=expense_artifact,
                policy_artifact_id=policy_artifact,
            )
        loaded, contents = _stored(self.root / DEFAULT_EXPENSES, load_expenses)
        policy, policy_contents = _stored(self.root / DEFAULT_POLICY, load_policy)
        return ReportSource(
            loaded,
            policy,
            DEFAULT_EXPENSES.name,
            DEFAULT_POLICY.name,
            "stored",
            contents,
            policy_contents,
        )

    def prepare(
        self, expenses: UploadedFile | None, policy: UploadedFile | None, dataset: str | None
    ) -> ReportSource:
        if expenses is None and policy is None:
            raise ServiceError(422, "Choose an expense CSV or a policy JSON file.")
        # Reuse the current counterpart when replacing only one file. Both
        # uploaded files also work when the stored samples are unavailable.
        previous = (
            self.resolve(dataset) if dataset and (expenses is None or policy is None) else None
        )
        expense_artifact = policy_artifact = None
        if expenses is not None:
            loaded, expense_name, expense_key, expense_contents = _uploaded(
                expenses, load_expenses, "expenses.csv"
            )
        elif previous is not None:
            loaded, expense_name = previous.loaded, previous.expense_name
            expense_key = previous.expense_key
            expense_contents = previous.expense_contents
            expense_artifact = previous.expense_artifact_id
        else:
            loaded, expense_contents = _stored(self.root / DEFAULT_EXPENSES, load_expenses)
            expense_name = DEFAULT_EXPENSES.name
            expense_key = "stored"
        if policy is not None:
            settings, policy_name, _, policy_contents = _uploaded(
                policy, load_policy, "policy.json"
            )
        elif previous is not None:
            settings, policy_name = previous.policy, previous.policy_name
            policy_contents = previous.policy_contents
            policy_artifact = previous.policy_artifact_id
        else:
            settings, policy_contents = _stored(self.root / DEFAULT_POLICY, load_policy)
            policy_name = DEFAULT_POLICY.name
        return ReportSource(
            loaded,
            settings,
            expense_name,
            policy_name,
            expense_key,
            expense_contents,
            policy_contents,
            expense_artifact,
            policy_artifact,
        )

    def save(self, source: ReportSource, token: str | None = None, actor: str | None = None) -> str:
        token = token or token_urlsafe(24)
        return self.workspace.datasets.save_dataset(token, source, actor)

    def snapshot(self, source: ReportSource):
        key = (
            "stored-" + sha256(source.expense_contents + b"\0" + source.policy_contents).hexdigest()
        )
        return self.save(source, key)
