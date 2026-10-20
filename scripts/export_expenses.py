"""Load and validate expense CSV records, then export records and errors as JSON."""

import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path

from loader.expense_loader import load_expenses


def export_expenses(source: str | Path, output: str | Path, *, overwrite: bool = False) -> Path:
    """Export validated records and row errors; preserve exact decimal values."""
    source, output = Path(source), Path(output)
    if source.resolve() == output.resolve() or (output.exists() and source.samefile(output)):
        raise ValueError("Input and output must be different files")
    result = load_expenses(source)
    records = []
    for expense in result.expenses:
        record = asdict(expense)
        record["date"] = expense.date.isoformat()
        record["submission_date"] = expense.submission_date.isoformat()
        record["amount"] = str(expense.amount)
        records.append(record)
    payload = {
        "expenses": records,
        "errors": [asdict(error) for error in result.errors],
    }
    serialized = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w" if overwrite else "x", encoding="utf-8") as target:
        target.write(serialized)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/expenses/sample_expenses.csv"))
    parser.add_argument("--output", type=Path, default=Path("artifacts/sample_expenses.json"))
    parser.add_argument("--force", action="store_true", help="Overwrite existing output")
    args = parser.parse_args()
    try:
        output = export_expenses(args.input, args.output, overwrite=args.force)
    except (OSError, ValueError, UnicodeError, csv.Error) as error:
        parser.exit(1, f"Error: {error}\n")
    print(f"Exported expenses and validation errors to {output}")


if __name__ == "__main__":
    main()
