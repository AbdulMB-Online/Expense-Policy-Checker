import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from loader.expense_loader import load_expenses
from loader.policy_loader import load_policy
from rules.engine import RulesEngine
from scripts.export_policy_results import export_policy_results
from scripts.export_json import export_json


ROOT = Path(__file__).resolve().parents[1]


def test_exports_engine_results_summary_and_loader_errors(tmp_path):
    source = ROOT / "data" / "expenses" / "sample_expenses.csv"
    policy_path = ROOT / "data" / "policy" / "policy.json"
    existing_export = export_json(source, tmp_path / "sample_expenses.json")
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
    protected = export_json(ROOT / "data/expenses/sample_expenses.csv", tmp_path / "sample_expenses.json")
    original = protected.read_bytes()
    refused = subprocess.run(
        command[:-1] + [str(protected), "--force"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert refused.returncode == 1
    assert "sample_expenses.json" in refused.stderr
    assert "Traceback" not in refused.stderr
    assert protected.read_bytes() == original
