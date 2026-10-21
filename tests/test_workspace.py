"""Exercise ownership, durable BLOBs, immutable checks, and review races."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sqlite3
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from backend.api.app import create_app
from backend.database.core import Database
from backend.database.schema import SCHEMA_VERSION
from backend.rules.engine import RulesEngine
from backend.scripts.sample_data import generate_sample


ROOT = Path(__file__).resolve().parents[1]
PDF = b"%PDF-1.4\nOriginal receipt\n%%EOF\n"


@pytest.fixture
def project(tmp_path):
    generate_sample(tmp_path / "data/expenses/sample_expenses.csv")
    policy = tmp_path / "data/policy/policy.json"
    policy.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "data/policy/policy.json", policy)
    return tmp_path


def client(project, user="reviewer-finance"):
    result = TestClient(create_app(project))
    assert result.post("/api/demo/login", json={"user_id": user}).status_code == 200
    return result


def submit(client, employee="Anika Rao", **changes):
    payload = {"employee": employee, "date": date.today().isoformat(), "category": "meals", "amount": "20.00",
               "description": "Lunch", "request_id": str(uuid4()), **changes}
    response = client.post("/api/expenses", data=payload, files={"receipt": ("Lunch.pdf", PDF, "application/pdf")})
    assert response.status_code == 201, response.text
    return response.json()


def review(client, report, claim, decision="approved", comment=""):
    return client.post(f"/api/expenses/{claim['id']}/review", json={"run_id": report["run_id"],
        "revision_id": claim["revision_id"], "decision": decision, "comment": comment})


def test_sessions_and_employee_isolation_cover_reports_exports_receipts_and_actions(project):
    anonymous = TestClient(create_app(project))
    assert anonymous.get("/api/report").status_code == 401
    assert anonymous.post("/api/expenses", data={}).status_code == 401
    assert anonymous.get("/api/health").json() == {"status": "ok"}
    employee = client(project, "employee-anika")
    own = submit(employee)
    assert own["claim"]["owner_id"] == "employee-anika"
    assert {item["employee"] for item in own["report"]["claims"]} == {"Anika Rao"}
    assert own["report"]["employees"] == ["Anika Rao"] and own["report"]["errors"] == []
    assert own["report"]["overview"]["accepted_count"] == len(own["report"]["claims"])
    assert employee.post("/api/expenses", data={"employee": "Karan Mehta", "date": date.today().isoformat(),
        "category": "meals", "amount": "20.00", "description": "Spoof", "request_id": str(uuid4())}).status_code == 403
    other = client(project, "employee-karan")
    assert other.get(own["claim"]["receipt"]["download_url"]).status_code == 404
    assert other.get(f"/api/expenses/{own['claim']['id']}/history").status_code == 404
    assert other.get("/api/report?employee=Anika%20Rao").status_code == 422
    assert other.get("/api/artifacts").status_code == 403
    assert other.post("/api/report/upload", files={"policy": ("p.json", b"{}")}).status_code == 403
    assert review(other, own["report"], own["claim"]).status_code == 403
    export = other.get("/api/report/download")
    assert export.status_code == 200 and "Anika Rao" not in export.text
    assert "BAD-" not in export.text
    reviewer = client(project)
    artifact_id = reviewer.get("/api/artifacts").json()[0]["id"]
    assert other.get(f"/api/artifacts/{artifact_id}").status_code == 403
    assert employee.get("/api/session").headers["cache-control"] == "no-store"
    cookie = employee.cookies.get("expense_session")
    restarted = TestClient(create_app(project))
    restarted.cookies.set("expense_session", cookie)
    assert restarted.get("/api/session").json()["id"] == "employee-anika"
    with sqlite3.connect(Database(project).path) as connection:
        assert connection.execute("SELECT 1 FROM sessions WHERE token_hash=?", (cookie,)).fetchone() is None
    employee.post("/api/demo/logout")
    assert employee.get("/api/report").status_code == 401


def test_original_inputs_receipts_and_exports_are_blobs_and_survive_restart(project, monkeypatch):
    reviewer = client(project)
    csv = (project / "data/expenses/sample_expenses.csv").read_bytes()
    policy = (project / "data/policy/policy.json").read_bytes()
    uploaded = reviewer.post("/api/report/upload", files={"expenses": ("October.csv", csv), "policy": ("Rules.json", policy)})
    assert uploaded.status_code == 200
    report = uploaded.json()
    dataset = report["dataset_id"]
    employee = client(project, "employee-anika")
    saved = submit(employee, dataset=dataset)
    claim = saved["claim"]
    export = reviewer.get(f"/api/report/download?dataset={dataset}")
    assert export.status_code == 200
    restarted = client(project)
    restored = restarted.get(f"/api/report?dataset={dataset}").json()
    assert restored["run_id"] == saved["report"]["run_id"]
    assert restored["generated_at"] == saved["report"]["generated_at"]
    assert any(item["id"] == dataset for item in restarted.get("/api/datasets").json())
    assert restarted.get(claim["receipt"]["download_url"]).content == PDF
    artifacts = restarted.get("/api/artifacts").json()
    for name, contents in (("October.csv", csv), ("Rules.json", policy), ("Lunch.pdf", PDF)):
        metadata = next(item for item in artifacts if item["name"] == name)
        assert metadata["size"] == len(contents) and metadata["sha256"] == sha256(contents).hexdigest()
        assert "contents" not in metadata
        assert restarted.get(f"/api/artifacts/{metadata['id']}").content == contents
    assert restarted.get(f"/api/artifacts/{export.headers['x-artifact-id']}").content == export.content
    # Ordinary reads must use the saved engine findings, even after restart.
    monkeypatch.setattr(RulesEngine, "run_detailed", lambda *_: pytest.fail("cached report reran the engine"))
    assert restarted.get(f"/api/report?dataset={dataset}&search=EXP-005").status_code == 200
    with sqlite3.connect(Database(project).path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert connection.execute("SELECT COUNT(*) FROM artifacts WHERE typeof(contents)<>'blob'").fetchone()[0] == 0
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_review_and_resubmission_preserve_history_original_receipt_and_prior_check(project):
    employee = client(project, "employee-anika")
    submitted = submit(employee)
    claim = submitted["claim"]
    reviewer = client(project)
    assert review(reviewer, submitted["report"], claim, "changes_requested").status_code == 422
    requested = review(reviewer, submitted["report"], claim, "changes_requested", "Explain the client meeting")
    assert requested.status_code == 200
    assert review(reviewer, submitted["report"], claim).status_code == 409
    old_run = submitted["report"]["run_id"]
    response = employee.put(f"/api/expenses/{claim['id']}", data={"date": claim["date"], "category": "meals", "amount": "25.00",
        "description": "Client meeting with Acme", "revision": 1})
    assert response.status_code == 200, response.text
    updated = response.json()
    new = next(item for item in updated["claims"] if item["id"] == claim["id"])
    assert new["revision"] == 2 and new["revision_id"] != claim["revision_id"]
    assert new["review_status"] == "submitted" and updated["run_id"] != old_run
    assert employee.get(new["receipt"]["download_url"]).content == PDF
    assert review(reviewer, submitted["report"], claim).status_code == 409
    approved = review(reviewer, updated, new)
    assert approved.status_code == 200
    visible = employee.get("/api/report").json()
    final = next(item for item in visible["claims"] if item["id"] == claim["id"])
    assert final["review_status"] == "approved" and final["status"] == "unflagged"
    history = employee.get(f"/api/expenses/{claim['id']}/history").json()
    assert [(item["revision"], item["decision"]) for item in history] == [(1, "changes_requested"), (2, "approved")]
    assert history[0]["comment"] == "Explain the client meeting"
    original = reviewer.get(f"/api/check-runs/{old_run}").json()
    original_claim = next(item for item in original["claims"] if item["expense"]["id"] == claim["id"])
    assert original_claim["expense"]["amount"] == "20.00" and original_claim["revision"] == 1
    assert reviewer.get(f"/api/artifacts/{original_claim['receipt_artifact_id']}").content == PDF
    assert employee.get(f"/api/check-runs/{old_run}").status_code == 403
    with sqlite3.connect(Database(project).path) as connection:
        records = connection.execute("SELECT record FROM expense_revisions WHERE expense_id=(SELECT id FROM expenses WHERE external_id=?) ORDER BY revision", (claim["id"],)).fetchall()
        assert [json.loads(item[0])["amount"] for item in records] == ["20.00", "25.00"]
        assert connection.execute("SELECT COUNT(*) FROM check_results WHERE run_id=?", (old_run,)).fetchone()[0] > 0


def test_replacing_receipt_retains_original_blob_and_retry_keys_are_per_account(project):
    employee = client(project, "employee-anika")
    other = client(project, "employee-karan")
    request_id = str(uuid4())
    submitted = submit(employee, request_id=request_id)
    second = submit(other, employee="Karan Mehta", request_id=request_id)
    assert second["claim"]["id"] != submitted["claim"]["id"]
    reviewer = client(project)
    current = reviewer.get("/api/report").json()
    claim = next(item for item in current["claims"] if item["id"] == submitted["claim"]["id"])
    assert review(reviewer, current, claim, "changes_requested", "Replace the receipt").status_code == 200
    replacement = b"%PDF-1.4\nReplacement receipt\n%%EOF"
    updated = employee.put(f"/api/expenses/{claim['id']}", data={"date": claim["date"], "category": "meals", "amount": "20.00",
        "description": "Lunch", "revision": 1}, files={"receipt": ("New.pdf", replacement)})
    assert updated.status_code == 200
    new = next(item for item in updated.json()["claims"] if item["id"] == claim["id"])
    assert employee.get(new["receipt"]["download_url"]).content == replacement
    original = reviewer.get(f"/api/check-runs/{current['run_id']}").json()
    original_claim = next(item for item in original["claims"] if item["expense"]["id"] == claim["id"])
    assert reviewer.get(f"/api/artifacts/{original_claim['receipt_artifact_id']}").content == PDF


def test_competing_reviewers_write_one_decision_and_self_review_is_denied(project):
    employee = client(project, "employee-anika")
    submitted = submit(employee)
    reviewers = [client(project), client(project, "reviewer-backup")]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda reviewer: review(reviewer, submitted["report"], submitted["claim"]), reviewers))
    assert sorted(result.status_code for result in results) == [200, 409]
    assert len(employee.get(f"/api/expenses/{submitted['claim']['id']}/history").json()) == 1
    mine = submit(reviewers[0], employee="Morgan Finance")
    assert review(reviewers[0], mine["report"], mine["claim"]).status_code == 403
    assert review(reviewers[1], mine["report"], mine["claim"]).status_code == 200


def test_unmatched_import_is_hidden_until_explicit_mapping(project):
    reviewer = client(project)
    csv = (project / "data/expenses/sample_expenses.csv").read_bytes().replace(b"Anika Rao", b"Unmatched Employee")
    imported = reviewer.post("/api/report/upload", files={"expenses": ("Imported.csv", csv)}).json()
    dataset = imported["dataset_id"]
    claim = next(item for item in imported["claims"] if item["id"] == "EXP-001")
    assert claim["owner_id"] is None
    assert review(reviewer, imported, claim).status_code == 409  # Run belongs to a different input.
    decision = {"run_id": imported["run_id"], "revision_id": claim["revision_id"], "decision": "approved"}
    assert reviewer.post(f"/api/expenses/EXP-001/review?dataset={dataset}", json=decision).status_code == 409
    employee = client(project, "employee-anika")
    assert employee.get(f"/api/report?dataset={dataset}").status_code == 404
    mapped = reviewer.post(f"/api/expenses/EXP-001/owner?dataset={dataset}", json={"user_id": "employee-anika"})
    assert mapped.status_code == 200
    report = employee.get(f"/api/report?dataset={dataset}").json()
    assert [item["id"] for item in report["claims"]] == ["EXP-001"]
    assert report["claims"][0]["owner_id"] == "employee-anika"
    assert any(item["id"] == dataset for item in employee.get("/api/datasets").json())
    assert reviewer.post(f"/api/expenses/EXP-001/owner?dataset={dataset}", json={"user_id": "employee-karan"}).status_code == 409


def test_duplicate_explanations_do_not_expose_other_employee_ids(project):
    reviewer = client(project)
    policy = json.loads((project / "data/policy/policy.json").read_text())
    policy["duplicates"]["key_fields"] = ["amount"]
    imported = reviewer.post("/api/report/upload", files={"policy": ("Cross employee.json", json.dumps(policy))}).json()
    employee = client(project, "employee-karan")
    report = employee.get(f"/api/report?dataset={imported['dataset_id']}").json()
    assert all(item["employee"] == "Karan Mehta" for item in report["claims"])
    for claim in report["claims"]:
        for finding in claim["violations"]:
            if finding["rule_id"] == "suspected_duplicate":
                assert "EXP-" not in finding["reason"]


def test_policy_or_input_change_creates_a_new_run_and_rejects_stale_decision(project):
    reviewer = client(project)
    initial = reviewer.get("/api/report").json()
    claim = next(item for item in initial["claims"] if item["id"] == "EXP-005")
    submit(client(project, "employee-anika"))
    assert review(reviewer, initial, claim).status_code == 409
    fresh = reviewer.get("/api/report").json()
    assert fresh["run_id"] != initial["run_id"]
    assert review(reviewer, fresh, next(item for item in fresh["claims"] if item["id"] == claim["id"])).status_code == 200
    policy = json.loads((project / "data/policy/policy.json").read_text())
    policy["categories"]["meals"]["max_amount"] = "100.00"
    changed = reviewer.post("/api/report/upload", files={"policy": ("Higher limit.json", json.dumps(policy))}).json()
    assert changed["run_id"] != fresh["run_id"]
    assert all(item["rule_id"] != "amount_limit" for item in next(item for item in changed["claims"] if item["id"] == "EXP-005")["violations"])
