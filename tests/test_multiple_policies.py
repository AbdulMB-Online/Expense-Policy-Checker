"""Exercise policy selection through the loader, engine, and public CLI."""

import json
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from scripts.generate_example_policy import BUSINESS_TRAVEL_POLICY, generate_policy
from loader.expense_loader import load_expenses
from loader.policy_loader import load_policy
from rules.engine import RulesEngine


ROOT = Path(__file__).resolve().parents[1]
STANDARD = ROOT / "data/policy/policy.json"
@pytest.fixture
def travel_policy(tmp_path):
    return generate_policy(tmp_path / "business_travel.json")


def test_policies_produce_independent_results_for_the_same_expenses(travel_policy):
    expenses = load_expenses(ROOT / "data/expenses/sample_expenses.csv").expenses
    standard = RulesEngine(load_policy(STANDARD))
    travel = RulesEngine(load_policy(travel_policy))
    original = standard.run_all(expenses)
    alternative = travel.run_all(expenses)
    for expense_id in ("EXP-003", "EXP-016", "EXP-019", "EXP-021"):
        assert expense_id in original
        assert expense_id not in alternative
    assert "EXP-072" not in original
    assert alternative["EXP-072"] == ["Receipt is missing for transport expense 0.01."]
    assert alternative["EXP-006"] == original["EXP-006"]
    assert standard.run_all(expenses) == original


def test_travel_training_category_enforces_its_limit_and_receipt(travel_policy):
    expenses = load_expenses(ROOT / "data/expenses/sample_expenses.csv").expenses
    training = next(item for item in expenses if item.id == "EXP-062")
    engine = RulesEngine(load_policy(travel_policy))
    at_limit = replace(training, amount=Decimal("1500.00"))
    assert engine.run_all([at_limit]) == {}
    over_limit = replace(training, amount=Decimal("1500.01"), receipt_attached=False)
    violations = engine.run_detailed([over_limit])[training.id]
    assert {item.rule_id for item in violations} == {"amount_limit", "missing_receipt"}


def test_cli_selects_each_policy_and_keeps_separate_results(tmp_path, travel_policy):
    inputs = (STANDARD, travel_policy, ROOT / "data/expenses/sample_expenses.csv")
    originals = {path: path.read_bytes() for path in inputs}
    outputs = []
    for policy in (STANDARD, travel_policy):
        output = tmp_path / f"{policy.stem}_results.json"
        result = subprocess.run(
            [sys.executable, "-m", "scripts.export_policy_results",
             "--policy", str(policy), "--output", str(output)],
            cwd=ROOT, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        outputs.append(output)
    standard, travel = [json.loads(path.read_text()) for path in outputs]
    standard_results = {item["expense_id"]: item for item in standard["results"]}
    travel_results = {item["expense_id"]: item for item in travel["results"]}
    assert standard_results["EXP-003"]["status"] == "FLAGGED"
    assert travel_results["EXP-003"]["status"] == "PASS"
    assert standard_results["EXP-072"]["status"] == "PASS"
    assert travel_results["EXP-072"]["status"] == "FLAGGED"
    assert standard["errors"] == travel["errors"]
    assert standard["summary"]["total_expenses"] == travel["summary"]["total_expenses"] == 72
    assert {path: path.read_bytes() for path in inputs} == originals


def test_generated_policy_matches_settings_and_requires_force_to_overwrite(tmp_path):
    output = tmp_path / "nested" / "business_travel.json"
    command = [sys.executable, "-m", "scripts.generate_example_policy",
               "--output", str(output)]
    generated = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert generated.returncode == 0, generated.stderr
    assert json.loads(output.read_text()) == BUSINESS_TRAVEL_POLICY
    assert load_policy(output) == BUSINESS_TRAVEL_POLICY
    output.write_text("existing custom policy")
    protected = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    assert protected.returncode == 1
    assert output.read_text() == "existing custom policy"
    replaced = subprocess.run(command + ["--force"], cwd=ROOT, capture_output=True, text=True)
    assert replaced.returncode == 0, replaced.stderr
    assert json.loads(output.read_text()) == BUSINESS_TRAVEL_POLICY
