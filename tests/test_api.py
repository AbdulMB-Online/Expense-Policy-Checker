"""Verify the API against real loaders, rules, reports, and isolated files."""

import asyncio
import json
from pathlib import Path
import shutil

import httpx
import pytest

from api.app import create_app
from api.sources import MAX_DATASETS, MAX_UPLOAD_BYTES
from loader.expense_loader import FIELDS
from scripts.sample_data import generate_sample


ROOT = Path(__file__).resolve().parents[1]


def get(app, path):
    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.get(path)
    return asyncio.run(request())


def upload(app, files, dataset=None):
    async def request():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/report/upload", files=files, data={"dataset": dataset} if dataset else {})
    return asyncio.run(request())


def uploaded_files(project):
    return {
        "expenses": ("October claims final.csv", (project / "data/expenses/sample_expenses.csv").read_bytes(), "text/csv"),
        "policy": ("Finance policy v2.json", (project / "data/policy/policy.json").read_bytes(), "application/json"),
    }


@pytest.fixture
def project(tmp_path):
    generate_sample(tmp_path / "data" / "expenses" / "sample_expenses.csv")
    policy = tmp_path / "data" / "policy" / "policy.json"
    policy.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "data" / "policy" / "policy.json", policy)
    return tmp_path


def test_real_pipeline_summary_and_rule_identities(project):
    result = get(create_app(project), "/api/report")
    assert result.status_code == 200
    data = result.json()
    assert data["overview"] == {
        "accepted_count": 72, "unflagged_count": 43, "flagged_count": 29,
        "violation_count": 44, "rejected_count": 28, "total_flagged_amount": "2662.10",
    }
    assert data["summary"] == data["overview"]
    assert len(data["claims"]) == 72
    assert [(group["name"], group["total_amount"]) for group in data["groups"]["employee"]] == [
        ("Anika Rao", "837.03"), ("Elena Brooks", "60.00"),
        ("Karan Mehta", "80.00"), ("Kavya Iyer", "800.02"),
        ("Lucía Torres", "175.02"), ("Mei Tan", "225.02"),
        ("Rohan Desai", "125.02"), ("Yusuf Khan", "359.99"),
    ]
    assert [(group["id"], len(group["claims"])) for group in data["groups"]["rule"]] == [
        ("amount_limit", 17), ("missing_receipt", 22), ("suspected_duplicate", 5),
    ]
    multiple = next(claim for claim in data["claims"] if claim["id"] == "EXP-005")
    assert {item["rule_id"] for item in multiple["violations"]} == {"amount_limit", "missing_receipt"}
    assert data["errors"][0]["line_number"] == 12
    assert data["errors"][0]["expense_id"] == "BAD-001"
    assert data["policy"]["categories"]["meals"]["max_amount"] == "50.00"


def test_employee_filter_keeps_overview_and_global_input_errors(project):
    data = get(create_app(project), "/api/report?employee=Karan%20Mehta").json()
    assert data["overview"]["total_flagged_amount"] == "2662.10"
    assert data["summary"]["total_flagged_amount"] == "80.00"
    assert data["summary"]["flagged_count"] == 2
    assert {claim["employee"] for claim in data["claims"]} == {"Karan Mehta"}
    assert len(data["employees"]) == 12
    assert "Karan Mehta" in data["employees"]
    assert len(data["errors"]) == 28


def test_search_does_not_remove_duplicate_evaluation_context(project):
    data = get(create_app(project), "/api/report?search=EXP-006").json()
    assert [claim["id"] for claim in data["claims"]] == ["EXP-006"]
    assert data["summary"]["flagged_count"] == 1
    assert data["summary"]["total_flagged_amount"] == "40.00"
    assert data["claims"][0]["violations"][0]["rule_id"] == "suspected_duplicate"
    assert "EXP-007" in data["claims"][0]["violations"][0]["reason"]


def test_employee_filter_preserves_custom_cross_employee_duplicates(project):
    policy_path = project / "data" / "policy" / "policy.json"
    policy = json.loads(policy_path.read_text())
    policy["duplicates"]["key_fields"] = ["amount"]
    policy_path.write_text(json.dumps(policy))
    data = get(create_app(project), "/api/report?employee=Karan%20Mehta").json()
    assert all("EXP-004" in claim["violations"][0]["reason"] for claim in data["claims"])


def test_no_matches_returns_an_empty_scoped_report(project):
    data = get(create_app(project), "/api/report?search=does-not-exist").json()
    assert data["summary"]["flagged_count"] == 0
    assert data["summary"]["total_flagged_amount"] == "0.00"
    assert data["groups"] == {"employee": [], "rule": []}


@pytest.mark.parametrize("grouping", ["employee", "rule"])
def test_download_matches_filtered_report_and_preserves_data(project, grouping):
    inputs = [project / "data" / "expenses" / "sample_expenses.csv", project / "data" / "policy" / "policy.json"]
    original = [path.read_bytes() for path in inputs]
    result = get(create_app(project), f"/api/report/download?group_by={grouping}&employee=Karan%20Mehta")
    assert result.status_code == 200
    assert result.headers["content-type"].startswith("text/plain")
    assert f'expense-report-{grouping}.txt' in result.headers["content-disposition"]
    assert "Total flagged amount: USD 80.00" in result.text
    assert "REJECTED INPUT ROWS: 28" in result.text
    assert "EMPLOYEE: Anika Rao" not in result.text
    assert [path.read_bytes() for path in inputs] == original


@pytest.mark.parametrize("query", ["employee=Unknown", "search=" + "a" * 201])
def test_invalid_filters_are_rejected(project, query):
    assert get(create_app(project), f"/api/report?{query}").status_code == 422


def test_invalid_download_group_is_rejected(project):
    assert get(create_app(project), "/api/report/download?group_by=unknown").status_code == 422


@pytest.mark.parametrize("relative, contents", [
    ("data/expenses/sample_expenses.csv", None),
    ("data/expenses/sample_expenses.csv", b"bad headers\n"),
    ("data/expenses/sample_expenses.csv", b"\xff"),
    ("data/policy/policy.json", None),
    ("data/policy/policy.json", b"{}"),
])
def test_unusable_data_has_a_readable_service_error(project, relative, contents):
    path = project / relative
    if contents is None:
        path.unlink()
    else:
        path.write_bytes(contents)
    result = get(create_app(project), "/api/report")
    assert result.status_code == 503
    assert result.json()["detail"].startswith("Unable to prepare the report.")
    assert str(project) not in result.text


def test_empty_claims_and_reload_after_changes(project):
    app = create_app(project)
    assert get(app, "/api/report").json()["overview"]["accepted_count"] == 72
    (project / "data" / "expenses" / "sample_expenses.csv").write_text(",".join(FIELDS) + "\n")
    data = get(app, "/api/report").json()
    assert data["overview"]["accepted_count"] == 0
    assert data["overview"]["total_flagged_amount"] == "0.00"
    assert data["period"] is None


def test_health_and_optional_built_frontend(project):
    dist = project / "frontend" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<html>Dashboard</html>")
    app = create_app(project)
    assert get(app, "/api/health").json() == {"status": "ok"}
    assert "Dashboard" in get(app, "/").text
    assert get(app, "/api/report").status_code == 200


def test_upload_uses_contents_and_names_and_preserves_stored_files(project):
    app = create_app(project)
    files = uploaded_files(project)
    policy = json.loads(files["policy"][1])
    policy["categories"]["meals"]["max_amount"] = "100.00"
    files["policy"] = (files["policy"][0], json.dumps(policy).encode(), "text/plain")
    result = upload(app, files)
    assert result.status_code == 200
    data = result.json()
    assert data["sources"] == {"expenses": "October claims final.csv", "policy": "Finance policy v2.json"}
    assert data["dataset_id"]
    assert data["policy"]["categories"]["meals"]["max_amount"] == "100.00"
    assert not any(v["rule_id"] == "amount_limit" for claim in data["claims"] if claim["id"] == "EXP-005" for v in claim["violations"])
    assert data["overview"]["rejected_count"] == 28
    stored = get(app, "/api/report").json()
    assert stored["dataset_id"] is None
    assert stored["policy"]["categories"]["meals"]["max_amount"] == "50.00"
    assert (project / "data/expenses/sample_expenses.csv").read_bytes() == files["expenses"][1]
    assert not (project / files["expenses"][0]).exists()


@pytest.mark.parametrize("grouping", ["employee", "rule"])
def test_uploaded_context_survives_filters_refresh_and_download(project, grouping):
    app = create_app(project)
    files = uploaded_files(project)
    # A changed amount proves requests keep the uploaded input rather than
    # silently reading the sample under its default name.
    files["expenses"] = ("renamed.txt", files["expenses"][1].replace(b"40.00", b"41.00"), "application/octet-stream")
    data = upload(app, files).json()
    token = data["dataset_id"]
    filtered = get(app, f"/api/report?dataset={token}&employee=Karan%20Mehta&search=EXP-006").json()
    assert filtered["summary"]["total_flagged_amount"] == "41.00"
    assert filtered["claims"][0]["violations"][0]["rule_id"] == "suspected_duplicate"
    assert filtered["overview"] == data["overview"]
    downloaded = get(app, f"/api/report/download?dataset={token}&group_by={grouping}&search=EXP-006")
    assert downloaded.status_code == 200
    assert "Total flagged amount: USD 41.00" in downloaded.text
    assert get(app, f"/api/report?dataset={token}").json()["sources"]["expenses"] == "renamed.txt"


def test_replacing_one_file_keeps_the_other_active_file(project):
    app = create_app(project)
    files = uploaded_files(project)
    first = upload(app, {"expenses": files["expenses"]}).json()
    assert first["sources"]["policy"] == "policy.json"
    second = upload(app, {"policy": files["policy"]}, first["dataset_id"]).json()
    assert second["sources"] == {"expenses": files["expenses"][0], "policy": files["policy"][0]}
    third = upload(app, {"expenses": ("other.csv", files["expenses"][1])}, second["dataset_id"]).json()
    assert third["sources"] == {"expenses": "other.csv", "policy": files["policy"][0]}
    assert get(app, f'/api/report?dataset={first["dataset_id"]}').json()["sources"] == first["sources"]


@pytest.mark.parametrize("field, contents", [
    ("expenses", b"wrong headers\n"), ("expenses", b"\xff"),
    ("expenses", b""), ("policy", b"{}"), ("policy", b"not json"),
])
def test_failed_upload_has_file_reason_and_keeps_previous_snapshot(project, field, contents):
    app = create_app(project)
    files = uploaded_files(project)
    token = upload(app, files).json()["dataset_id"]
    result = upload(app, {field: ("My invalid file", contents)}, token)
    assert result.status_code == 422
    assert result.json()["detail"].startswith("My invalid file:")
    assert "expense-upload-" not in result.text
    assert get(app, f"/api/report?dataset={token}").json()["overview"]["total_flagged_amount"] == "2662.10"


def test_uploaded_paths_are_only_display_names_and_need_no_stored_files(tmp_path):
    files = uploaded_files(ROOT)
    files["expenses"] = ("../../claimed.csv", files["expenses"][1])
    files["policy"] = (r"C:\fakepath\rules.json", files["policy"][1])
    app = create_app(tmp_path)
    result = upload(app, files)
    assert result.status_code == 200
    assert result.json()["sources"] == {"expenses": "claimed.csv", "policy": "rules.json"}
    assert list(tmp_path.iterdir()) == []


def test_upload_limits_missing_inputs_and_snapshot_isolation(project):
    app = create_app(project)
    assert upload(app, {}).status_code == 422
    too_large = upload(app, {"expenses": ("large.csv", b"x" * (MAX_UPLOAD_BYTES + 1))})
    assert too_large.status_code == 413
    token = upload(app, uploaded_files(project)).json()["dataset_id"]
    assert get(create_app(project), f"/api/report?dataset={token}").status_code == 404
    assert get(app, "/api/report/download?dataset=missing").status_code == 404
    assert upload(app, {"policy": uploaded_files(project)["policy"]}, "missing").status_code == 404
    # Replacing both inputs needs no old counterpart, so a stale review token
    # must not prevent recovery after an API restart or cache eviction.
    assert upload(app, uploaded_files(project), "missing").status_code == 200


def test_snapshot_cache_is_bounded_and_expiry_is_actionable(project):
    app = create_app(project)
    files = uploaded_files(project)
    first = upload(app, files).json()["dataset_id"]
    for _ in range(MAX_DATASETS):
        last = upload(app, files).json()["dataset_id"]
    expired = get(app, f"/api/report?dataset={first}")
    assert expired.status_code == 404
    assert "Upload them again" in expired.json()["detail"]
    assert get(app, f"/api/report?dataset={last}").status_code == 200
