"""Exercise form -> validation -> durable receipt/claim -> real policy report."""

import asyncio
from datetime import date
import json
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

import httpx
import pytest

from api.app import create_app
from api.submissions import MAX_RECEIPT_BYTES
from database.submissions import SubmissionStore
from scripts.sample_data import generate_sample


ROOT = Path(__file__).resolve().parents[1]
PDF = b"%PDF-1.4\nA receipt\n%%EOF\n"
PNG = b"\x89PNG\r\n\x1a\nreceipt data"
JPEG = b"\xff\xd8\xff\xe0receipt data\xff\xd9"


def request(app, method, url, **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.request(method, url, **kwargs)
    return asyncio.run(run())


def form(**changes):
    return {"employee": "Submission Tester", "date": "2026-10-15", "category": "meals", "amount": "20.00", "description": "Client meeting lunch", "request_id": str(uuid4()), **changes}


@pytest.fixture
def project(tmp_path):
    generate_sample(tmp_path / "data/expenses/sample_expenses.csv")
    policy = tmp_path / "data/policy/policy.json"
    policy.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "data/policy/policy.json", policy)
    return tmp_path


def submit(app, data=None, receipt=None):
    files = {"receipt": receipt} if receipt else None
    return request(app, "POST", "/api/expenses", data=data if data is not None else form(), files=files)


def report(app, dataset=None):
    return request(app, "GET", "/api/report", params={"dataset": dataset} if dataset else {}).json()


def policy_upload(app, project, **changes):
    settings = json.loads((project / "data/policy/policy.json").read_text())
    settings.update(changes)
    return request(app, "POST", "/api/report/upload", files={"policy": ("Custom rules.json", json.dumps(settings), "application/json")}).json()


def test_clean_submission_persists_with_receipt_after_restart_and_preserves_csv(project):
    inputs = [project / "data/expenses/sample_expenses.csv", project / "data/policy/policy.json"]
    original = [path.read_bytes() for path in inputs]
    app = create_app(project)
    result = submit(app, receipt=("Lunch receipt.png", PNG, "image/png"))
    assert result.status_code == 201
    data = result.json()
    claim = data["claim"]
    assert claim["id"].startswith("USR-")
    assert claim["submission_date"] == date.today().isoformat()
    assert claim["status"] == "unflagged" and claim["violations"] == []
    assert claim["receipt_attached"] is True
    assert claim["origin"] == "submission"
    assert data["report"]["overview"]["accepted_count"] == 73
    assert data["report"]["overview"]["flagged_count"] == 29
    assert data["report"]["submissions"] == [claim]
    restarted = create_app(project)
    assert report(restarted)["submissions"] == [claim]
    downloaded = request(restarted, "GET", claim["receipt"]["download_url"])
    assert downloaded.status_code == 200 and downloaded.content == PNG
    assert downloaded.headers["content-type"] == "image/png"
    assert downloaded.headers["x-content-type-options"] == "nosniff"
    assert downloaded.headers["content-disposition"].startswith("attachment;")
    assert [path.read_bytes() for path in inputs] == original
    assert (project / "artifacts/submissions.sqlite3").exists()


def test_flagged_submission_saves_all_reasons_and_joins_both_report_groups(project):
    app = create_app(project)
    result = submit(app, form(amount="75.00"))
    assert result.status_code == 201
    data = result.json()
    claim = data["claim"]
    assert {flag["rule_id"] for flag in claim["violations"]} == {"amount_limit", "missing_receipt"}
    assert claim["receipt"] is None and not claim["receipt_attached"]
    assert data["report"]["overview"] == {
        "accepted_count": 73, "unflagged_count": 43, "flagged_count": 30,
        "violation_count": 46, "rejected_count": 28, "total_flagged_amount": "2737.10",
    }
    for grouping in ("employee", "rule"):
        groups = data["report"]["groups"][grouping]
        assert any(item["id"] == claim["id"] for group in groups for item in group["claims"])
        download = request(app, "GET", f"/api/report/download?group_by={grouping}&employee=Submission%20Tester")
        assert download.status_code == 200
        assert claim["id"] in download.text
        assert "Total flagged amount: USD 75.00" in download.text
    filtered = request(app, "GET", f'/api/report?search={claim["id"]}').json()
    assert filtered["claims"] == [claim]


@pytest.mark.parametrize("contents, mime", [(PDF, "application/pdf"), (PNG, "image/png"), (JPEG, "image/jpeg")])
def test_receipt_types_and_exact_limit_pass(project, contents, mime):
    app = create_app(project)
    result = submit(app, form(amount="50.00"), ("Custom receipt name", contents, "application/octet-stream"))
    assert result.status_code == 201
    claim = result.json()["claim"]
    assert claim["status"] == "unflagged"
    receipt = request(app, "GET", claim["receipt"]["download_url"])
    assert receipt.content == contents
    assert receipt.headers["content-type"] == mime


def test_new_claim_rechecks_existing_csv_claims_for_duplicates(project):
    app = create_app(project)
    assert next(claim for claim in report(app)["claims"] if claim["id"] == "EXP-001")["status"] == "unflagged"
    result = submit(app, form(employee="Anika Rao", date="2026-10-05"), ("Receipt.pdf", PDF, "application/pdf"))
    assert result.status_code == 201
    data = result.json()
    new = data["claim"]
    assert [flag["rule_id"] for flag in new["violations"]] == ["suspected_duplicate"]
    old = next(claim for claim in data["report"]["claims"] if claim["id"] == "EXP-001")
    assert new["id"] in old["violations"][0]["reason"]
    filtered = request(app, "GET", f'/api/report?search={new["id"]}').json()
    assert "EXP-001" in filtered["claims"][0]["violations"][0]["reason"]


def test_new_claim_rechecks_earlier_submissions_and_retry_does_not_duplicate(project):
    app = create_app(project)
    payload = form()
    first = submit(app, payload).json()["claim"]
    retry = submit(app, payload)
    assert retry.status_code == 201 and retry.json()["claim"]["id"] == first["id"]
    assert len(report(app)["submissions"]) == 1
    conflict = submit(app, {**payload, "description": "Different claim"})
    assert conflict.status_code == 409
    second = submit(app, form()).json()["claim"]
    data = report(app)
    assert len(data["submissions"]) == 2
    assert all(claim["status"] == "flagged" for claim in data["submissions"])
    assert first["id"] in second["violations"][0]["reason"]


def test_concurrent_retries_save_one_claim_and_receipt(project):
    app = create_app(project)
    payload = form(amount="50.00")
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await asyncio.gather(*(client.post("/api/expenses", data=payload, files={"receipt": ("Receipt.pdf", PDF)}) for _ in range(3)))
    results = asyncio.run(run())
    assert all(result.status_code == 201 for result in results)
    assert len({result.json()["claim"]["id"] for result in results}) == 1
    assert len(report(app)["submissions"]) == 1


@pytest.mark.parametrize("changes, field", [
    ({"employee": "   "}, "employee"), ({"description": "   "}, "description"),
    ({"date": "2026-02-30"}, "date"), ({"date": "10/10/2026"}, "date"),
    ({"amount": "-1.00"}, "amount"), ({"amount": "1.001"}, "amount"),
    ({"amount": "NaN"}, "amount"), ({"category": "unknown"}, "category"),
    ({"category": "hotel"}, "nights"), ({"category": "hotel", "nights": "0"}, "nights"),
])
def test_invalid_form_fields_do_not_save_claim_or_receipt(project, changes, field):
    app = create_app(project)
    result = submit(app, form(**changes), ("Receipt.pdf", PDF))
    assert result.status_code == 422
    assert field in result.json()["detail"]["fields"]
    assert report(app)["submissions"] == []
    assert not (project / "artifacts/submissions.sqlite3").exists()


def test_missing_fields_bad_request_keys_and_stale_context_are_rejected(project):
    app = create_app(project)
    for payload in ({}, form(request_id="not-a-uuid"), form(dataset="expired"), form(employee="x" * 201)):
        assert submit(app, payload).status_code in {404, 422}
    assert report(app)["submissions"] == []


@pytest.mark.parametrize("name, contents", [("fake.pdf", b"not a PDF"), ("empty.png", b""), ("attack.html", b"<script>alert(1)</script>")])
def test_invalid_receipt_contents_do_not_save(project, name, contents):
    app = create_app(project)
    result = submit(app, receipt=(name, contents, "application/pdf"))
    assert result.status_code == 422
    assert "receipt" in result.json()["detail"]["fields"]
    assert report(app)["submissions"] == []


def test_receipt_size_limit_and_path_names(project):
    app = create_app(project)
    result = submit(app, receipt=("large.pdf", b"%PDF-" + b"x" * MAX_RECEIPT_BYTES))
    assert result.status_code == 413 and report(app)["submissions"] == []
    saved = submit(app, receipt=("../../Réceipt.pdf", PDF)).json()["claim"]
    assert saved["receipt"]["name"] == "Réceipt.pdf"
    attachment = request(app, "GET", saved["receipt"]["download_url"])
    assert "R%C3%A9ceipt.pdf" in attachment.headers["content-disposition"]
    assert not (project / "Réceipt.pdf").exists()
    assert request(app, "GET", "/api/receipts/unknown").status_code == 404


def test_hotel_submission_uses_nights_for_policy_limit(project):
    app = create_app(project)
    result = submit(app, form(category="hotel", amount="400.00", nights="2"), ("Stay.pdf", PDF))
    assert result.status_code == 201
    assert result.json()["claim"]["nights"] == 2
    assert result.json()["claim"]["status"] == "unflagged"


def test_submissions_use_active_custom_policy_and_recheck_when_policy_changes(project):
    app = create_app(project)
    policy = json.loads((project / "data/policy/policy.json").read_text())
    policy["categories"]["meals"]["max_amount"] = "100.00"
    uploaded = policy_upload(app, project, categories=policy["categories"])
    result = submit(app, form(dataset=uploaded["dataset_id"], amount="75.00"), ("Receipt.pdf", PDF))
    assert result.status_code == 201
    claim = result.json()["claim"]
    assert claim["status"] == "unflagged"
    assert "dataset=" in claim["receipt"]["download_url"]
    assert report(app, uploaded["dataset_id"])["submissions"][0]["status"] == "unflagged"
    # Same expense source, standard policy: re-evaluate using its lower limit.
    assert report(app)["submissions"][0]["violations"][0]["rule_id"] == "amount_limit"
    euro = policy_upload(app, project, currency="EUR")
    assert report(app, euro["dataset_id"])["submissions"] == []
    assert request(app, "GET", f'/api/receipts/{claim["id"]}?dataset={euro["dataset_id"]}').status_code == 404


def test_uploaded_csv_workspace_is_separate_and_restored_after_reupload(project):
    app = create_app(project)
    csv = (project / "data/expenses/sample_expenses.csv").read_bytes().replace(b"Anika Rao", b"Another employee")
    uploaded = request(app, "POST", "/api/report/upload", files={"expenses": ("Any claims.csv", csv)}).json()
    saved = submit(app, form(dataset=uploaded["dataset_id"]), ("Receipt.pdf", PDF)).json()["claim"]
    assert report(app)["submissions"] == []
    assert len(report(app, uploaded["dataset_id"])["submissions"]) == 1
    restarted = create_app(project)
    restored = request(restarted, "POST", "/api/report/upload", files={"expenses": ("Renamed.csv", csv)}).json()
    assert restored["submissions"][0]["id"] == saved["id"]
    assert request(restarted, "GET", restored["submissions"][0]["receipt"]["download_url"]).content == PDF


def test_policy_failure_rolls_back_claim_and_receipt(project, monkeypatch):
    app = create_app(project)
    from rules.engine import RulesEngine
    def fail(*_args):
        raise ValueError("invalid engine configuration")
    with monkeypatch.context() as patch:
        patch.setattr(RulesEngine, "run_detailed", fail)
        assert submit(app, receipt=("Receipt.pdf", PDF)).status_code == 503
    assert report(app)["submissions"] == []


def test_storage_failure_has_retry_message_without_claim(project, monkeypatch):
    app = create_app(project)
    def fail(*_args):
        raise sqlite3.OperationalError("disk full")
    monkeypatch.setattr(SubmissionStore, "_connect", fail)
    result = submit(app)
    assert result.status_code == 503
    assert "retry" in result.json()["detail"]
    assert report(app)["submissions"] == []
