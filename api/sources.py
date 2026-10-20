"""Load named inputs without using uploaded filenames as filesystem paths."""

from collections import OrderedDict
from dataclasses import dataclass
import csv
from decimal import DecimalException
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory
from threading import Lock

from fastapi import HTTPException, UploadFile

from loader.expense_loader import LoadResult, load_expenses
from loader.policy_loader import load_policy


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_DATASETS = 20
DEFAULT_EXPENSES = Path("data/expenses/sample_expenses.csv")
DEFAULT_POLICY = Path("data/policy/policy.json")


@dataclass(frozen=True)
class ReportSource:
    loaded: LoadResult
    policy: dict
    expense_name: str
    policy_name: str


def _stored(path: Path, loader):
    try:
        return loader(path)
    except (OSError, ValueError, csv.Error, DecimalException) as error:
        raise HTTPException(503, "Unable to prepare the report. Check the stored expense CSV and policy JSON, then retry.") from error


def _uploaded(file: UploadFile, loader, internal_name: str):
    # Original names are display metadata only, including Windows browser paths.
    name = Path((file.filename or internal_name).replace("\\", "/")).name
    name = "".join(char for char in name if char.isprintable())[:200] or internal_name
    contents = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"{name}: files must be 5 MiB or smaller.")
    try:
        with TemporaryDirectory(prefix="expense-upload-") as directory:
            path = Path(directory) / internal_name
            path.write_bytes(contents)
            parsed = loader(path)
    except (ValueError, csv.Error, DecimalException) as error:
        raise HTTPException(422, f"{name}: {error}") from error
    return parsed, name


class SourceStore:
    """Bounded, per-app snapshots; one review never replaces another's inputs."""

    def __init__(self, root: Path):
        self.root = root
        self._datasets: OrderedDict[str, ReportSource] = OrderedDict()
        self._lock = Lock()

    def resolve(self, dataset: str | None) -> ReportSource:
        if dataset:
            with self._lock:
                source = self._datasets.get(dataset)
            if source is None:
                raise HTTPException(404, "These uploaded files are no longer available. Upload them again or use the sample files.")
            return source
        return ReportSource(
            _stored(self.root / DEFAULT_EXPENSES, load_expenses),
            _stored(self.root / DEFAULT_POLICY, load_policy),
            DEFAULT_EXPENSES.name, DEFAULT_POLICY.name,
        )

    def prepare(self, expenses: UploadFile | None, policy: UploadFile | None, dataset: str | None) -> ReportSource:
        if expenses is None and policy is None:
            raise HTTPException(422, "Choose an expense CSV or a policy JSON file.")
        # Reuse the current counterpart when replacing only one file. Both
        # uploaded files also work when the stored samples are unavailable.
        previous = self.resolve(dataset) if dataset and (expenses is None or policy is None) else None
        if expenses is not None:
            loaded, expense_name = _uploaded(expenses, load_expenses, "expenses.csv")
        elif previous is not None:
            loaded, expense_name = previous.loaded, previous.expense_name
        else:
            loaded = _stored(self.root / DEFAULT_EXPENSES, load_expenses)
            expense_name = DEFAULT_EXPENSES.name
        if policy is not None:
            settings, policy_name = _uploaded(policy, load_policy, "policy.json")
        elif previous is not None:
            settings, policy_name = previous.policy, previous.policy_name
        else:
            settings = _stored(self.root / DEFAULT_POLICY, load_policy)
            policy_name = DEFAULT_POLICY.name
        return ReportSource(loaded, settings, expense_name, policy_name)

    def save(self, source: ReportSource) -> str:
        token = token_urlsafe(24)
        with self._lock:
            self._datasets[token] = source
            while len(self._datasets) > MAX_DATASETS:
                self._datasets.popitem(last=False)
        return token
