from decimal import Decimal
from pathlib import Path
import subprocess
import sys

import pytest

from backend.loader.expense_loader import load_expenses
from backend.loader.policy_loader import load_policy
from backend.rules.engine import RulesEngine
from backend.scripts.generate_example_policy import generate_policy
from backend.scripts.sample_data import generate_sample, sample_rows


def test_default_sample_preserves_scenarios(tmp_path):
    result = load_expenses(generate_sample(tmp_path / "sample.csv"))
    assert len(sample_rows()) == 100
    assert len(result.expenses) == 72
    assert len(result.errors) == 28
    expenses = {expense.id: expense for expense in result.expenses}
    assert expenses["EXP-002"].amount == Decimal("50.00")
    assert expenses["EXP-003"].amount == Decimal("50.01")
    assert expenses["EXP-005"].amount == Decimal("75.00")
    assert not expenses["EXP-005"].receipt_attached
    first, second = expenses["EXP-006"], expenses["EXP-007"]
    assert (first.employee, first.date, first.category, first.amount) == (
        second.employee, second.date, second.category, second.amount)
    assert expenses["EXP-008"].amount == 0
    assert "," in expenses["EXP-010"].description
    assert expenses["EXP-004"].category == "transport"
    assert expenses["EXP-004"].amount == Decimal("40.00")
    assert not expenses["EXP-004"].receipt_attached
    assert first.category == "transport" and first.amount == Decimal("40.00")
    assert (expenses["EXP-011"].submission_date - expenses["EXP-011"].date).days == 30
    assert (expenses["EXP-012"].submission_date - expenses["EXP-012"].date).days == 31
    assert expenses["EXP-013"].category == "alcohol"
    combined = expenses["EXP-014"]
    assert combined.amount > 50 and not combined.receipt_attached
    assert (combined.submission_date - combined.date).days == 31
    assert expenses["EXP-015"].amount == Decimal("200") * expenses["EXP-015"].nights
    assert expenses["EXP-016"].amount > Decimal("200") * expenses["EXP-016"].nights
    assert expenses["EXP-017"].amount <= 25 and not expenses["EXP-017"].receipt_attached
    assert expenses["EXP-018"].category == "office_supplies" and expenses["EXP-018"].amount == 100
    assert expenses["EXP-019"].amount == Decimal("100.01")
    assert expenses["EXP-020"].amount == 75
    assert expenses["EXP-021"].amount == Decimal("75.01")
    assert expenses["EXP-022"].category == "other"
    assert {item.category for item in result.expenses} == {
        "meals", "hotel", "transport", "office_supplies", "other", "alcohol",
        "training", "equipment",
    }


def test_repeatable_generation_and_extra_rows(tmp_path):
    first = generate_sample(tmp_path / "one.csv", extra_clean=100, seed=7)
    second = generate_sample(tmp_path / "two.csv", extra_clean=100, seed=7)
    assert first.read_bytes() == second.read_bytes()
    result = load_expenses(first)
    assert len(result.expenses) == 172
    assert len(result.errors) == 28
    generated = [item for item in result.expenses if item.id.startswith("CLEAN-")]
    assert len(generated) == 100
    assert all(0 < item.amount <= 25 and item.receipt_attached for item in generated)
    assert all(0 <= (item.submission_date - item.date).days <= 30 for item in generated)
    assert {item.employee for item in generated} <= {"Anika Rao", "Karan Mehta", "Rohan Desai"}
    assert sample_rows(10, 7) != sample_rows(10, 8)


def test_sample_covers_requested_manual_policy_scenarios(tmp_path):
    loaded = load_expenses(generate_sample(tmp_path / "sample.csv"))
    expenses = {item.id: item for item in loaded.expenses}
    errors = {item.expense_id: item for item in loaded.errors}
    policy = load_policy(Path(__file__).resolve().parents[1] / "data/policy/policy.json")
    travel = load_policy(generate_policy(tmp_path / "business_travel.json"))

    for expense_id in ("EXP-013", "EXP-065"):
        assert expenses[expense_id].category in policy["restricted_categories"]
    assert expenses["EXP-062"].category not in policy["categories"]
    assert policy["unknown_category_action"] == "review_required"
    for settings in (policy, travel):
        assert expenses["EXP-063"].category not in settings["categories"]

    deadline = policy["submission"]["max_days_after_expense"]
    at_deadline = expenses["EXP-011"]
    assert (at_deadline.submission_date - at_deadline.date).days == deadline
    for expense_id in ("EXP-012", "EXP-014", "EXP-057", "EXP-061"):
        late = expenses[expense_id]
        assert (late.submission_date - late.date).days > deadline
    future = expenses["EXP-058"]
    assert future.date > future.submission_date

    assert policy["categories"]["hotel"]["nights_required"]
    assert expenses["EXP-047"].nights is None
    for expense_id in ("BAD-021", "BAD-022", "BAD-023", "BAD-024"):
        assert any(reason.startswith("nights:") for reason in errors[expense_id].reasons)

    maximum_nights = travel["categories"]["hotel"]["max_nights_per_stay"]
    assert expenses["EXP-044"].nights == maximum_nights
    assert expenses["EXP-048"].nights == maximum_nights + 1
    for expense_id in ("EXP-044", "EXP-048"):
        stay = expenses[expense_id]
        for settings in (policy, travel):
            assert stay.amount <= Decimal(settings["categories"]["hotel"]["max_amount"]) * stay.nights
        assert stay.receipt_attached
    for expense_id in ("EXP-022", "EXP-064"):
        assert policy["categories"][expenses[expense_id].category]["review_required"]


def test_expanded_scenarios_cover_boundaries_duplicates_and_validation(tmp_path):
    loaded = load_expenses(generate_sample(tmp_path / "sample.csv"))
    policy = load_policy(Path(__file__).resolve().parents[1] / "data/policy/policy.json")
    violations = RulesEngine(policy).run_detailed(loaded.expenses)
    rules = {key: {item.rule_id for item in values} for key, values in violations.items()}
    for start in (23, 29, 35):
        assert f"EXP-{start:03d}" not in rules
        assert f"EXP-{start + 1:03d}" not in rules
        assert rules[f"EXP-{start + 2:03d}"] == {"missing_receipt"}
        assert f"EXP-{start + 3:03d}" not in rules
        assert rules[f"EXP-{start + 4:03d}"] == {"missing_receipt"}
        assert rules[f"EXP-{start + 5:03d}"] == {"amount_limit", "missing_receipt"}
    for number in (49, 50, 51):
        assert rules[f"EXP-{number:03d}"] == {
            "amount_limit", "missing_receipt", "suspected_duplicate",
        }
    for number in (52, 53, 54, 55):
        assert "suspected_duplicate" not in rules[f"EXP-{number:03d}"]
    assert "EXP-070" not in rules and "EXP-071" not in rules
    expenses = {item.id: item for item in loaded.expenses}
    assert len({item.employee for item in loaded.expenses}) == 12
    assert expenses["EXP-066"].employee == "Chloë D’Souza"
    assert expenses["EXP-066"].receipt_attached
    assert expenses["EXP-067"].description == 'Client lunch, "working session"'
    assert expenses["EXP-068"].description == "Parking\nreceipt details"
    assert expenses["EXP-059"].date.isoformat() == "2024-02-29"
    errors = {item.expense_id: item for item in loaded.errors}
    assert len(errors["BAD-025"].reasons) == 3
    assert len(errors["BAD-026"].reasons) == 3
    assert errors["BAD-026"].line_number == 102  # Quoted newline occupies a physical line.


def test_protects_existing_files_and_creates_parents(tmp_path):
    path = generate_sample(tmp_path / "nested" / "sample.csv")
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        generate_sample(path, extra_clean=1)
    assert path.read_bytes() == original
    generate_sample(path, extra_clean=1, overwrite=True)
    assert len(load_expenses(path).expenses) == 73


def test_negative_count_does_not_create_file(tmp_path):
    path = tmp_path / "sample.csv"
    with pytest.raises(ValueError, match="nonnegative"):
        generate_sample(path, extra_clean=-1)
    assert not path.exists()


def test_cli(tmp_path):
    path = tmp_path / "sample.csv"
    command = [sys.executable, "-m", "backend.scripts.sample_data", "--output", str(path)]
    success = subprocess.run(command, capture_output=True, text=True)
    assert success.returncode == 0
    assert "100 expense rows" in success.stdout
    protected = subprocess.run(command, capture_output=True, text=True)
    assert protected.returncode == 1
    assert "Error:" in protected.stderr
    assert subprocess.run(command + ["--force"], capture_output=True).returncode == 0


def test_committed_sample_matches_generator(tmp_path):
    generated = generate_sample(tmp_path / "sample.csv")
    committed = Path(__file__).resolve().parents[1] / "data" / "expenses" / "sample_expenses.csv"
    assert generated.read_bytes() == committed.read_bytes()


def test_committed_sample_rejects_exact_rows_with_all_validation_reasons():
    source = Path(__file__).resolve().parents[1] / "data/expenses/sample_expenses.csv"
    loaded = load_expenses(source)
    amount = "amount: expected a nonnegative decimal with at most two decimal places"
    expense_date = "date: expected a real date in YYYY-MM-DD format"
    submission_date = "submission_date: expected a real date in YYYY-MM-DD format"
    receipt = "receipt_attached: expected true or false"
    nights = "nights: expected a positive integer"
    assert [(error.line_number, error.expense_id, error.reasons) for error in loaded.errors] == [
        (12, "BAD-001", ("employee: required field is empty",)),
        (13, "BAD-002", (amount,)),
        (14, "BAD-003", (expense_date,)),
        (15, "BAD-004", (amount,)),
        (16, "BAD-005", ("description: required field is empty",)),
        (17, "BAD-006", (receipt,)),
        (18, None, ("id: required field is empty",)),
        (19, "EXP-001", ("id: duplicates a previously accepted record",)),
        (83, "BAD-007", ("category: required field is empty",)),
        (84, "BAD-008", ("amount: required field is empty",)),
        (85, "BAD-009", ("receipt_attached: required field is empty",)),
        (86, "BAD-010", ("date: required field is empty",)),
        (87, "BAD-011", ("submission_date: required field is empty",)),
        (88, "BAD-012", (amount,)),
        (89, "BAD-013", (amount,)),
        (90, "BAD-014", (amount,)),
        (91, "BAD-015", (amount,)),
        (92, "BAD-016", (amount,)),
        (93, "BAD-017", (amount,)),
        (94, "BAD-018", (expense_date,)),
        (95, "BAD-019", (expense_date,)),
        (96, "BAD-020", (submission_date,)),
        (97, "BAD-021", (nights,)),
        (98, "BAD-022", (nights,)),
        (99, "BAD-023", (nights,)),
        (100, "BAD-024", (nights,)),
        (101, "BAD-025", ("employee: required field is empty", amount, receipt)),
        (102, "BAD-026", ("description: required field is empty", expense_date, submission_date)),
    ]
    assert [expense.id for expense in loaded.expenses] == [
        f"EXP-{number:03d}" for number in range(1, 73)
    ]
