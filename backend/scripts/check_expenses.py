"""View stored expense claims grouped by employee or policy rule."""

import csv
import sys
from pathlib import Path

from backend.loader.expense_loader import load_expenses
from backend.loader.policy_loader import load_policy
from backend.reporting.violation_report import (
    ViolationReport,
    build_report,
    render_report,
)
from backend.rules.engine import RulesEngine

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MENU = """
EXPENSE POLICY CHECKER

1. View report grouped by employee
2. View report grouped by policy rule
3. Exit
"""


def _load_report() -> ViolationReport:
    """Read project-relative files and prepare one consistent report snapshot."""
    expenses_path = PROJECT_ROOT / "data" / "expenses" / "sample_expenses.csv"
    policy_path = PROJECT_ROOT / "data" / "policy" / "policy.json"
    try:
        loaded = load_expenses(expenses_path)
    except (OSError, ValueError, csv.Error) as error:
        raise ValueError(f"Unable to load expense claims from {expenses_path}: {error}") from error
    try:
        policy = load_policy(policy_path)
    except (OSError, ValueError) as error:
        raise ValueError(f"Unable to load policy from {policy_path}: {error}") from error
    return build_report(
        loaded.expenses,
        RulesEngine(policy).run_detailed(loaded.expenses),
        currency=policy["currency"],
        errors=loaded.errors,
    )


def main() -> int:
    """Display the menu until exit, EOF, or interruption; return an exit code."""
    try:
        report = _load_report()
        while True:
            print(MENU)
            choice = input("Enter your choice: ").strip()
            if choice == "3":
                print("Goodbye.")
                return 0
            if choice in {"1", "2"}:
                grouping = "employee" if choice == "1" else "rule"
                print()
                print(render_report(report, group_by=grouping), end="")
            else:
                print("Invalid choice. Enter 1, 2, or 3.")
    except (EOFError, KeyboardInterrupt):
        print("\nGoodbye.")
        return 0
    except (OSError, ValueError, csv.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
