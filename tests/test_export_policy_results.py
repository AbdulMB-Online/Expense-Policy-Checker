import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from loader.expense_loader import FIELDS, load_expenses
from loader.policy_loader import load_policy
from rules.engine import RulesEngine
from scripts.export_policy_results import export_policy_results
from scripts.export_expenses import export_expenses


ROOT = Path(__file__).resolve().parents[1]


def test_exports_engine_results_summary_and_loader_errors(tmp_path):
    source = ROOT / "data" / "expenses" / "sample_expenses.csv"
    policy_path = ROOT / "data" / "policy" / "policy.json"
    existing_export = export_expenses(source, tmp_path / "sample_expenses.json")
    before = existing_export.read_bytes()
    output = export_policy_results(source, policy_path, tmp_path / "nested" / "policy_check_results.json")
    loaded = load_expenses(source)
    violations = RulesEngine(load_policy(policy_path)).run_all(loaded.expenses)
    text = output.read_text(encoding="utf-8")
    payload = json.loads(text)
    assert text == json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    assert [item["expense_id"] for item in payload["results"]] == [expense.id for expense in loaded.expenses]
    assert len(payload["results"]) == len(set(item["expense_id"] for item in payload["results"]))
    flagged = 0
    for expense, item in zip(loaded.expenses, payload["results"], strict=True):
        messages = violations.get(expense.id, [])
        assert item == {
            "expense_id": expense.id,
            "employee": expense.employee,
            "date": expense.date.isoformat(),
            "category": expense.category,
            "amount": str(expense.amount),
            "status": "FLAGGED" if messages else "PASS",
            "violations": messages,
        }
        flagged += item["status"] == "FLAGGED"
    assert payload["summary"] == {
        "total_expenses": len(payload["results"]),
        "passed": len(payload["results"]) - flagged,
        "flagged": flagged,
        "loader_errors": len(loaded.errors),
    }
    expected_errors = []
    for error in loaded.errors:
        record = asdict(error)
        record["reasons"] = list(error.reasons)
        expected_errors.append(record)
    assert payload["errors"] == expected_errors
    assert existing_export.read_bytes() == before


def test_cli_writes_output_without_replacing_the_expense_export(tmp_path):
    output = tmp_path / "policy_check_results.json"
    command = [
        sys.executable, "-m", "scripts.export_policy_results",
        "--expenses", "data/expenses/sample_expenses.csv",
        "--policy", "data/policy/policy.json",
        "--output", str(output),
    ]
    success = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert success.returncode == 0
    assert "policy_check_results.json" in success.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["summary"]["passed"] + payload["summary"]["flagged"] == payload["summary"]["total_expenses"]
    assert payload["summary"]["loader_errors"] == len(payload["errors"])
    protected = export_expenses(ROOT / "data/expenses/sample_expenses.csv", tmp_path / "sample_expenses.json")
    original = protected.read_bytes()
    refused = subprocess.run(
        command[:-1] + [str(protected), "--force"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert refused.returncode == 1
    assert "sample_expenses.json" in refused.stderr
    assert "Traceback" not in refused.stderr
    assert protected.read_bytes() == original


def test_export_summary_includes_new_violations_without_changing_inputs(tmp_path):
    source = ROOT / "data" / "expenses" / "sample_expenses.csv"
    policy_path = ROOT / "data" / "policy" / "policy.json"
    original_expenses = source.read_bytes()
    original_policy = policy_path.read_bytes()
    output = export_policy_results(source, policy_path, tmp_path / "policy_check_results.json")
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["summary"] == {
        "total_expenses": 72,
        "passed": 32,
        "flagged": 40,
        "loader_errors": 28,
    }
    results = {item["expense_id"]: item for item in payload["results"]}
    assert results["EXP-002"]["status"] == "PASS"
    assert results["EXP-002"]["violations"] == []
    assert results["EXP-013"]["status"] == "FLAGGED"
    assert results["EXP-013"]["violations"] == ["Category alcohol is restricted."]
    assert results["EXP-014"]["violations"] == [
        "Amount 75.00 exceeds the meals limit of 50.00 per expense.",
        "Receipt is missing for meals expense 75.00, which is above the 25.00 threshold.",
        "Submitted 31 days after the expense date, beyond the 30-day deadline.",
    ]
    assert results["EXP-062"]["violations"] == [
        "Category training is unknown.",
        "Category training requires review.",
    ]
    assert source.read_bytes() == original_expenses
    assert policy_path.read_bytes() == original_policy


def test_export_refuses_to_overwrite_an_input_file(tmp_path):
    source = tmp_path / "expenses.csv"
    policy_path = tmp_path / "policy.json"
    header = ",".join(FIELDS)
    source.write_text(
        header + "\nE-1,Alice,2026-10-05,meals,20.00,Lunch,true,2026-10-05,\n",
        encoding="utf-8",
    )
    policy_path.write_text((ROOT / "data" / "policy" / "policy.json").read_text(encoding="utf-8"), encoding="utf-8")
    original = source.read_bytes()
    with pytest.raises(ValueError, match="different files"):
        export_policy_results(source, policy_path, source, overwrite=True)
    with pytest.raises(ValueError, match="different files"):
        export_policy_results(source, policy_path, policy_path, overwrite=True)
    assert source.read_bytes() == original
    assert "version" in policy_path.read_text(encoding="utf-8")


def test_malformed_csv_and_json_follow_the_loader_contract(tmp_path):
    policy_path = ROOT / "data" / "policy" / "policy.json"
    output = tmp_path / "out.json"
    output.write_text("existing", encoding="utf-8")
    bad_headers = tmp_path / "bad.csv"
    bad_headers.write_text("id,amount\n", encoding="utf-8")
    with pytest.raises(ValueError, match="headers"):
        export_policy_results(bad_headers, policy_path, output, overwrite=True)
    assert output.read_text(encoding="utf-8") == "existing"
    assert bad_headers.read_text(encoding="utf-8") == "id,amount\n"

    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError):
        export_policy_results(
            ROOT / "data" / "expenses" / "sample_expenses.csv", bad_json, output, overwrite=True,
        )
    assert output.read_text(encoding="utf-8") == "existing"
    assert bad_json.read_text(encoding="utf-8") == "{"

    rows = tmp_path / "rows.csv"
    rows.write_text(
        ",".join(FIELDS) + "\n"
        "E-1,Alice,2026-10-05,meals,20.00,Lunch,true,2026-10-05,\n"
        "E-2,Alice,not-a-date,meals,20.00,Lunch,true,2026-10-05,\n",
        encoding="utf-8",
    )
    exported = export_policy_results(rows, policy_path, tmp_path / "rows.json")
    payload = json.loads(exported.read_text(encoding="utf-8"))
    assert payload["summary"] == {
        "total_expenses": 1,
        "passed": 1,
        "flagged": 0,
        "loader_errors": 1,
    }
    assert payload["results"][0]["expense_id"] == "E-1"
    assert payload["results"][0]["status"] == "PASS"
    assert payload["errors"][0]["expense_id"] == "E-2"
    assert payload["errors"][0]["reasons"][0].startswith("date:")
