"""Generate repeatable clean records, policy examples, and invalid rows."""

import argparse
import csv
import random
from pathlib import Path

from loader.expense_loader import FIELDS

DEFAULT_SAMPLE_SIZE = 30


def sample_rows(extra_clean: int = 0, seed: int = 42) -> list[dict[str, str]]:
    """Return scenarios for the five policy rules plus malformed input rows."""
    if extra_clean < 0:
        raise ValueError("extra_clean must be nonnegative")
    rows = []

    def add(id, amount="20.00", receipt="true", **changes):
        row = dict(zip(FIELDS, (id, "Alice Morgan", "2026-10-05", "meals", amount, "Team lunch", receipt, "2026-10-05", "")))
        row.update(changes)
        rows.append(row)

    add("EXP-001")
    add("EXP-002", "50.00")
    add("EXP-003", "50.01")
    add("EXP-004", "40.00", "false", category="transport", description="Taxi to client office")
    add("EXP-005", "75.00", "false")
    add("EXP-006", "40.00", employee="Jordan Lee", category="transport", description="Taxi to airport")
    add("EXP-007", "40.00", employee="Jordan Lee", category="transport", description="Taxi to airport")
    add("EXP-008", "0.00", "false", description="Complimentary meal")
    add("EXP-009", "25.00", "false")
    add("EXP-010", "12.34", description="Lunch, client meeting")
    add("BAD-001", employee="")
    add("BAD-002", "-5.00")
    add("BAD-003", date="2026-02-30")
    add("BAD-004", "not-a-number")
    add("BAD-005", description="")
    add("BAD-006", receipt="maybe")
    add("", description="Missing ID")
    add("EXP-001", description="Repeated record ID")
    add("EXP-011", date="2026-09-05", description="Meal submitted exactly 30 days later")
    add("EXP-012", date="2026-09-04", description="Meal submitted 31 days later")
    add("EXP-013", "15.00", category="alcohol", description="Restricted alcohol expense")
    add("EXP-014", "75.00", "false", date="2026-09-04", description="Late over-limit meal without receipt")
    add("EXP-015", "400.00", category="hotel", nights="2", description="Hotel at $200 per night for two nights")
    add("EXP-016", "402.00", category="hotel", nights="2", description="Hotel above $200 per night for two nights")
    add("EXP-017", "20.00", "false", category="hotel", nights="1", description="Hotel without required receipt even below $25")
    add("EXP-018", "100.00", category="office_supplies", description="Office supplies exactly at limit")
    add("EXP-019", "100.01", category="office_supplies", description="Office supplies above limit")
    add("EXP-020", "75.00", category="transport", description="Train fare exactly at limit")
    add("EXP-021", "75.01", category="transport", description="Train fare above limit")
    add("EXP-022", "500.00", "false", category="other", description="Other expense requires policy review")
    rng = random.Random(seed)
    for index in range(DEFAULT_SAMPLE_SIZE - len(rows) + extra_clean):
        cents = rng.randint(1, 2500)
        add(f"CLEAN-{index + 1:05d}", f"{cents // 100}.{cents % 100:02d}",
            employee=rng.choice(("Alice Morgan", "Jordan Lee", "Sam Patel")),
            date=f"2026-10-{rng.randint(1, 28):02d}", submission_date="2026-10-28",
            description=f"Generated meal {index + 1}")
    return rows


def generate_sample(path: str | Path, *, extra_clean: int = 0, seed: int = 42,
                    overwrite: bool = False) -> Path:
    """Protect existing files unless overwrite is explicitly requested."""
    rows = sample_rows(extra_clean, seed)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w" if overwrite else "x", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/expenses/sample_expenses.csv"))
    parser.add_argument("--extra-clean", type=int, default=0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--force", action="store_true", help="Overwrite existing output")
    args = parser.parse_args()
    try:
        path = generate_sample(args.output, extra_clean=args.extra_clean, seed=args.seed, overwrite=args.force)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")
    print(f"Wrote {DEFAULT_SAMPLE_SIZE + args.extra_clean} expense rows to {path}")


if __name__ == "__main__":
    main()
