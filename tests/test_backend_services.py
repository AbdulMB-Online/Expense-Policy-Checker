"""Exercise extracted workflows with plain Python inputs and isolated roots."""

from dataclasses import dataclass
from datetime import date
from io import BytesIO
from pathlib import Path
import shutil
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from backend.api.app import create_app
from backend.database.submissions import SubmissionStore
from backend.database.workspace import WorkspaceStore
from backend.services.errors import ServiceError
from backend.services.expenses import ExpenseService
from backend.services.reports import ReportService
from backend.services.sources import SourceStore


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class MemoryUpload:
    filename: str
    file: BytesIO


@pytest.fixture
def services(tmp_path):
    shutil.copytree(ROOT / "data", tmp_path / "data")
    workspace = WorkspaceStore(tmp_path)
    submissions = SubmissionStore(tmp_path)
    reports = ReportService(SourceStore(tmp_path, workspace), submissions, workspace)
    expenses = ExpenseService(reports, submissions, workspace)
    return workspace, reports, expenses


def expense_values():
    return {
        "employee": "Anika Rao",
        "date": date.today().isoformat(),
        "category": "meals",
        "amount": "12.34",
        "description": "Service layer receipt",
        "nights": "",
    }


def test_services_accept_plain_uploads_and_preserve_idempotent_receipts(services):
    workspace, reports, expenses = services
    _, employee = workspace.sessions.login("employee-anika")
    receipt = b"%PDF-1.4\nservice test\n%%EOF"
    key = str(uuid4())
    results = [
        expenses.submit(
            expense_values(), key, None,
            MemoryUpload("receipt.pdf", BytesIO(receipt)), employee,
        )
        for _ in range(2)
    ]
    claim = results[0]["claim"]
    assert results[1]["claim"]["id"] == claim["id"]
    assert claim["amount"] == "12.34"
    assert claim["owner_id"] == employee["id"]
    assert claim["receipt"]["name"] == "receipt.pdf"
    source = reports.resolve_source(None, employee)
    assert reports.submissions.receipt(source.submission_scope, claim["id"]).contents == receipt
    assert len(reports.submissions.list(source.submission_scope)) == 1


def test_service_identity_failure_does_not_save_a_submission(services):
    workspace, reports, expenses = services
    _, employee = workspace.sessions.login("employee-anika")
    with pytest.raises(ServiceError) as failure:
        expenses.submit(
            {**expense_values(), "employee": "Karan Mehta"},
            str(uuid4()), None, None, employee,
        )
    assert failure.value.status_code == 403
    source = reports.resolve_source(None, employee)
    assert reports.submissions.list(source.submission_scope) == ()


def test_application_roots_isolate_sessions_and_serve_their_own_frontend(tmp_path):
    first_root, second_root = tmp_path / "first", tmp_path / "second"
    for root, page in ((first_root, "First dashboard"), (second_root, "Second dashboard")):
        dist = root / "frontend" / "dist"
        dist.mkdir(parents=True)
        (dist / "index.html").write_text(page)

    with TestClient(create_app(first_root)) as first, TestClient(create_app(second_root)) as second:
        assert first.post("/api/demo/login", json={"user_id": "employee-anika"}).status_code == 200
        second.cookies.update(first.cookies)
        assert first.get("/api/session").status_code == 200
        assert second.get("/api/session").status_code == 401
        assert first.get("/").text == "First dashboard"
        assert second.get("/").text == "Second dashboard"
        assert first.get("/api/health").json() == {"status": "ok"}
        assert first.get("/api/health").headers["cache-control"] == "no-store"
