"""Evaluate loaded expenses against policy and export the results as JSON."""

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path

from loader.expense_loader import load_expenses
from loader.policy_loader import load_policy
from rules.engine import RulesEngine


def export_policy_results(
    expenses_path: str | Path,
    policy_path: str | Path,
    output: str | Path,
    *,
    overwrite: bool = False,
) -> Path:
    """Write one result per accepted expense, plus loader errors and a summary."""
    expenses_path, policy_path, output = Path(expenses_path), Path(policy_path), Path(output)
    if _same_path(output, expenses_path) or _same_path(output, policy_path):
        raise ValueError("Input and output must be different files")
    if output.name == "sample_expenses.json":
        raise ValueError("Refusing to write sample_expenses.json")
    loaded = load_expenses(expenses_path)
    policy = load_policy(policy_path)
    violations = RulesEngine(policy).run_all(loaded.expenses)
    results = []
    for expense in loaded.expenses:
        messages = list(violations.get(expense.id, []))
        results.append({
            "expense_id": expense.id,
            "employee": expense.employee,
            "date": expense.date.isoformat(),
            "category": expense.category,
            "amount": str(expense.amount),
            "status": "FLAGGED" if messages else "PASS",
            "violations": messages,
        })
    flagged = sum(item["status"] == "FLAGGED" for item in results)
    payload = {
        "summary": {
            "total_expenses": len(results),
            "passed": len(results) - flagged,
            "flagged": flagged,
            "loader_errors": len(loaded.errors),
        },
        "results": results,
        "errors": [asdict(error) for error in loaded.errors],
    }
    serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w" if overwrite else "x", encoding="utf-8") as target:
        target.write(serialized)
    return output


def _same_path(output: Path, other: Path) -> bool:
    if output.resolve() == other.resolve():
        return True
    return output.exists() and other.exists() and output.samefile(other)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expenses", type=Path, default=Path("data/expenses/sample_expenses.csv"))
    parser.add_argument("--policy", type=Path, default=Path("data/policy/policy.json"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/policy_check_results.json"))
    parser.add_argument("--force", action="store_true", help="Overwrite existing output")
    args = parser.parse_args()
    try:
        output = export_policy_results(args.expenses, args.policy, args.output, overwrite=args.force)
    except (OSError, ValueError, UnicodeError, csv.Error) as error:
        parser.exit(1, f"Error: {error}\n")
    print(f"Exported policy check results to {output}")


if __name__ == "__main__":
    main()
