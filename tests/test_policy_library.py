"""Policy authoring persists independently and uses the existing evaluation pipeline."""

import asyncio
import json
import shutil
import sqlite3
from pathlib import Path

import httpx
import pytest

from backend.api.app import create_app
from backend.scripts.sample_data import generate_sample


@pytest.fixture
def project(tmp_path):
    generate_sample(tmp_path / "data/expenses/sample_expenses.csv")
    policy = tmp_path / "data/policy/policy.json"
    policy.parent.mkdir(parents=True)
    shutil.copyfile(Path(__file__).resolve().parents[1] / "data/policy/policy.json", policy)
    return tmp_path


def test_saved_policy_survives_restart_and_rechecks_existing_dataset(project):
    async def run():
        app = create_app(project)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            await client.post("/api/demo/login", json={"user_id": "reviewer-finance"})
            original = (await client.get("/api/report")).json()
            policies = (await client.get("/api/policies")).json()
            assert len(policies) == 1
            assert policies[0]["id"] == original["policy"]["id"]
            policy = policies[0]["config"]
            policy["name"] = "Travel policy"
            policy["categories"]["meals"]["max_amount"] = "100.00"
            contents = json.dumps(policy).encode()
            files = {"policy": ("Travel policy.json", contents, "application/json")}
            saved = await client.post("/api/policies", files=files)
            assert saved.status_code == 201
            new_id = saved.json()["id"]
            assert new_id != original["policy"]["id"]
            # Saving a policy does not apply it or create an expense dataset.
            assert (await client.get("/api/report")).json()["policy"]["id"] == original["policy"]["id"]
            assert (await client.get("/api/datasets")).json() == []
            assert (await client.post("/api/policies", files=files)).json()["id"] == new_id
            assert len((await client.get("/api/policies")).json()) == 2
            imported = await client.post("/api/report/upload", files={"expenses": (
                "Custom expenses.csv", (project / "data/expenses/sample_expenses.csv").read_bytes(), "text/csv"
            )})
            dataset = imported.json()["dataset_id"]
            applied = await client.post("/api/report/upload", files=files, data={"dataset": dataset})
            assert applied.status_code == 200
            report = applied.json()
            assert report["sources"]["expenses"] == "Custom expenses.csv"
            assert report["policy"]["id"] == new_id
            assert report["overview"]["accepted_count"] == original["overview"]["accepted_count"]
            assert report["overview"]["violation_count"] < original["overview"]["violation_count"]
            old = (await client.get(f"/api/report?dataset={dataset}")).json()
            assert old["policy"]["id"] == original["policy"]["id"]
        restarted = create_app(project)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url="http://test") as client:
            await client.post("/api/demo/login", json={"user_id": "reviewer-finance"})
            assert new_id in [item["id"] for item in (await client.get("/api/policies")).json()]
    asyncio.run(run())


def test_policy_validation_and_reviewer_permissions(project):
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(project)), base_url="http://test") as client:
            files = {"policy": ("Bad.json", b'{}', "application/json")}
            assert (await client.get("/api/policies")).status_code == 401
            assert (await client.post("/api/policies", files=files)).status_code == 401
            await client.post("/api/demo/login", json={"user_id": "employee-anika"})
            assert (await client.get("/api/policies")).status_code == 403
            assert (await client.post("/api/policies", files=files)).status_code == 403
            await client.post("/api/demo/login", json={"user_id": "reviewer-finance"})
            invalid = await client.post("/api/policies", files=files)
            assert invalid.status_code == 422
            assert "missing fields" in invalid.json()["detail"]
            assert len((await client.get("/api/policies")).json()) == 1
    asyncio.run(run())


def test_login_uses_registered_database_user_and_stored_role(project):
    app = create_app(project)
    app.state.services.workspace.sessions.users()
    with sqlite3.connect(project / "artifacts/submissions.sqlite3") as connection:
        connection.execute("INSERT INTO users(id,name,role) VALUES (?,?,?)", ("employee-new", "New Employee", "employee"))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            accounts = (await client.get("/api/demo/accounts")).json()
            assert {"id": "employee-new", "name": "New Employee", "role": "employee"} in accounts
            signed_in = await client.post("/api/demo/login", json={"user_id": "employee-new", "role": "reviewer"})
            assert signed_in.status_code == 200
            assert signed_in.json()["role"] == "employee"
            assert (await client.get("/api/policies")).status_code == 403
            assert (await client.get("/api/session")).json()["name"] == "New Employee"
            assert (await client.post("/api/demo/login", json={"user_id": "unknown-user"})).status_code == 404
    asyncio.run(run())
