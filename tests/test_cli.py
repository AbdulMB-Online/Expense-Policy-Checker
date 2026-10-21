"""Exercise menu interaction, file failures, and the complete CLI command."""

from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from backend.loader.expense_loader import FIELDS
from backend.scripts import check_expenses
from backend.scripts.sample_data import generate_sample


ROOT = Path(__file__).resolve().parents[1]


def enter_choices(monkeypatch, choices):
    answers = iter(choices)
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))


@pytest.fixture
def stored_project(tmp_path, monkeypatch):
    generate_sample(tmp_path / "data" / "expenses" / "sample_expenses.csv")
    policy_path = tmp_path / "data" / "policy" / "policy.json"
    policy_path.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "data" / "policy" / "policy.json", policy_path)
    monkeypatch.setattr(check_expenses, "PROJECT_ROOT", tmp_path)
    return tmp_path


def test_exit_displays_menu_without_a_report(monkeypatch, capsys):
    enter_choices(monkeypatch, ["3"])
    assert check_expenses.main() == 0
    captured = capsys.readouterr()
    assert "1. View report grouped by employee" in captured.out
    assert "2. View report grouped by policy rule" in captured.out
    assert "3. Exit" in captured.out
    assert "EXPENSE POLICY REPORT" not in captured.out
    assert "Goodbye." in captured.out
    assert not captured.err


@pytest.mark.parametrize("choice, grouping, heading", [
    ("1", "employee", "EMPLOYEE: Anika Rao"),
    ("2", "rule", "RULE: Amount limit"),
])
def test_selected_report_is_displayed_then_menu_returns(monkeypatch, capsys, choice, grouping, heading):
    enter_choices(monkeypatch, [choice, "3"])
    assert check_expenses.main() == 0
    captured = capsys.readouterr()
    assert f"Grouped by: {grouping}" in captured.out
    assert heading in captured.out
    assert "Total flagged amount: USD 14887.09" in captured.out
    assert "REJECTED INPUT ROWS: 28" in captured.out
    assert captured.out.count("EXPENSE POLICY CHECKER") == 2
    assert not captured.err


def test_switching_reports_reuses_one_loaded_snapshot(monkeypatch, capsys):
    original_loader = check_expenses.load_expenses
    loads = []

    def record_load(path):
        loads.append(path)
        return original_loader(path)

    monkeypatch.setattr(check_expenses, "load_expenses", record_load)
    enter_choices(monkeypatch, ["1", "2", "1", "3"])
    assert check_expenses.main() == 0
    captured = capsys.readouterr()
    assert len(loads) == 1
    assert captured.out.count("Grouped by: employee") == 2
    assert captured.out.count("Grouped by: rule") == 1
    assert captured.out.count("EXPENSE POLICY CHECKER") == 4
    assert not captured.err


@pytest.mark.parametrize("invalid", ["", "0", "4", "employee", "1.0", "abc"])
def test_invalid_choice_reprompts_and_whitespace_is_accepted(monkeypatch, capsys, invalid):
    enter_choices(monkeypatch, [invalid, " 1 ", " 3 "])
    assert check_expenses.main() == 0
    captured = capsys.readouterr()
    assert captured.out.count("Invalid choice. Enter 1, 2, or 3.") == 1
    assert "Grouped by: employee" in captured.out
    assert captured.out.count("EXPENSE POLICY CHECKER") == 3
    assert not captured.err


@pytest.mark.parametrize("interruption", [EOFError, KeyboardInterrupt])
def test_end_of_input_or_ctrl_c_exits_cleanly(monkeypatch, capsys, interruption):
    def interrupt(prompt):
        raise interruption

    monkeypatch.setattr("builtins.input", interrupt)
    assert check_expenses.main() == 0
    captured = capsys.readouterr()
    assert "Goodbye." in captured.out
    assert "Traceback" not in captured.out + captured.err
    assert not captured.err


@pytest.mark.parametrize("relative_path, content, explanation", [
    ("data/expenses/sample_expenses.csv", None, "expense claims"),
    ("data/expenses/sample_expenses.csv", b"bad headers\n", "expense claims"),
    ("data/expenses/sample_expenses.csv", b"\xff", "expense claims"),
    ("data/expenses/sample_expenses.csv", (",".join(FIELDS) + '\n"unterminated').encode(), "expense claims"),
    ("data/policy/policy.json", None, "policy"),
    ("data/policy/policy.json", b'{"version":', "policy"),
    ("data/policy/policy.json", b"{}", "policy"),
    ("data/policy/policy.json", b"\xff", "policy"),
])
def test_file_errors_are_readable_and_return_failure(stored_project, capsys, relative_path, content, explanation):
    path = stored_project / relative_path
    if content is None:
        path.unlink()
    else:
        path.write_bytes(content)
    assert check_expenses.main() == 1
    captured = capsys.readouterr()
    assert f"Error: Unable to load {explanation}" in captured.err
    assert str(path) in captured.err
    assert "Traceback" not in captured.err
    assert "EXPENSE POLICY CHECKER" not in captured.out


def test_header_only_claims_file_displays_empty_reports(stored_project, monkeypatch, capsys):
    path = stored_project / "data" / "expenses" / "sample_expenses.csv"
    path.write_text(",".join(FIELDS) + "\n", encoding="utf-8")
    enter_choices(monkeypatch, ["1", "2", "3"])
    assert check_expenses.main() == 0
    captured = capsys.readouterr()
    assert captured.out.count("No violations detected by the configured checks.") == 2
    assert captured.out.count("Accepted claims: 0") == 2
    assert captured.out.count("Total flagged amount: USD 0.00") == 2
    assert not captured.err


def test_project_files_do_not_depend_on_working_directory(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    enter_choices(monkeypatch, ["1", "3"])
    assert check_expenses.main() == 0
    captured = capsys.readouterr()
    assert "EXPENSE POLICY REPORT" in captured.out
    assert "Grouped by: employee" in captured.out
    assert "Flagged claims: 40" in captured.out
    assert "EMPLOYEE: Anika Rao" in captured.out
    assert "Total flagged amount: USD 14887.09" in captured.out
    assert "date: expected a real date in YYYY-MM-DD format" in captured.out
    assert not captured.err


def test_complete_command_displays_both_reports_without_changing_data():
    protected = [
        ROOT / "data" / "expenses" / "sample_expenses.csv",
        ROOT / "data" / "policy" / "policy.json",
        ROOT / "data" / "out" / "sample_expenses.json",
        ROOT / "data" / "out" / "policy_check_results.json",
    ]
    original = {path: path.read_bytes() if path.exists() else None for path in protected}
    result = subprocess.run(
        [sys.executable, "-m", "backend.scripts.check_expenses"],
        input="1\n2\n3\n", text=True, capture_output=True, cwd=ROOT, timeout=10,
    )
    assert result.returncode == 0
    assert not result.stderr
    assert result.stdout.count("Enter your choice:") == 3
    assert result.stdout.count("Grouped by: employee") == 1
    assert result.stdout.count("Grouped by: rule") == 1
    assert result.stdout.count("Total flagged amount: USD 14887.09") == 2
    assert result.stdout.count("Flagged claims: 40") == 2
    assert result.stdout.count("REJECTED INPUT ROWS: 28") == 2
    assert "EMPLOYEE: Karan Mehta" in result.stdout
    assert "RULE: Suspected duplicate" in result.stdout
    assert "RULE: Submission deadline" in result.stdout
    assert "date: expected a real date in YYYY-MM-DD format" in result.stdout
    assert result.stdout.endswith("Goodbye.\n")
    assert {path: path.read_bytes() if path.exists() else None for path in protected} == original


def test_complete_command_handles_closed_input():
    result = subprocess.run(
        [sys.executable, "-m", "backend.scripts.check_expenses"],
        input="", text=True, capture_output=True, cwd=ROOT, timeout=10,
    )
    assert result.returncode == 0
    assert not result.stderr
    assert result.stdout.endswith("Goodbye.\n")
