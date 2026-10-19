from decimal import Decimal
from pathlib import Path
import subprocess
import sys

import pytest

from loader.expense_loader import load_expenses
from scripts.sample_data import generate_sample, sample_rows


def test_default_sample_preserves_scenarios(tmp_path):
    result = load_expenses(generate_sample(tmp_path / "sample.csv"))
    assert len(sample_rows()) == 30
    assert len(result.expenses) == 22
    assert len(result.errors) == 8
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
    }


def test_repeatable_generation_and_extra_rows(tmp_path):
    first = generate_sample(tmp_path / "one.csv", extra_clean=100, seed=7)
    second = generate_sample(tmp_path / "two.csv", extra_clean=100, seed=7)
    assert first.read_bytes() == second.read_bytes()
    result = load_expenses(first)
    assert len(result.expenses) == 122
    assert len(result.errors) == 8
    generated = [item for item in result.expenses if item.id.startswith("CLEAN-")]
    assert len(generated) == 100
    assert all(0 < item.amount <= 25 and item.receipt_attached for item in generated)
    assert all(0 <= (item.submission_date - item.date).days <= 30 for item in generated)
    assert sample_rows(10, 7) != sample_rows(10, 8)


def test_protects_existing_files_and_creates_parents(tmp_path):
    path = generate_sample(tmp_path / "nested" / "sample.csv")
    original = path.read_bytes()
    with pytest.raises(FileExistsError):
        generate_sample(path, extra_clean=1)
    assert path.read_bytes() == original
    generate_sample(path, extra_clean=1, overwrite=True)
    assert len(load_expenses(path).expenses) == 23


def test_negative_count_does_not_create_file(tmp_path):
    path = tmp_path / "sample.csv"
    with pytest.raises(ValueError, match="nonnegative"):
        generate_sample(path, extra_clean=-1)
    assert not path.exists()


def test_cli(tmp_path):
    path = tmp_path / "sample.csv"
    command = [sys.executable, "-m", "scripts.sample_data", "--output", str(path)]
    success = subprocess.run(command, capture_output=True, text=True)
    assert success.returncode == 0
    assert "30 expense rows" in success.stdout
    protected = subprocess.run(command, capture_output=True, text=True)
    assert protected.returncode == 1
    assert "Error:" in protected.stderr
    assert subprocess.run(command + ["--force"], capture_output=True).returncode == 0


def test_committed_sample_matches_generator(tmp_path):
    generated = generate_sample(tmp_path / "sample.csv")
    committed = Path(__file__).resolve().parents[1] / "data" / "expenses" / "sample_expenses.csv"
    assert generated.read_bytes() == committed.read_bytes()
