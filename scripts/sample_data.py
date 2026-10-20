"""Generate repeatable clean records, policy examples, and invalid rows."""

import argparse
import csv
import random
from pathlib import Path

from loader.expense_loader import FIELDS

DEFAULT_SAMPLE_SIZE = 100


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

    next_id = 23

    def scenario(amount="20.00", receipt="true", **changes):
        nonlocal next_id
        add(f"EXP-{next_id:03d}", amount, receipt, **changes)
        next_id += 1

    # Each boundary matrix has its own employee to avoid incidental duplicates.
    employees = ("Sam Patel", "María García", "Chen Wei")
    for category, limit, employee in zip(
        ("meals", "transport", "office_supplies"), (5000, 7500, 10000), employees
    ):
        for cents, receipt, label in (
            (2499, "false", "Below receipt threshold"),
            (2500, "false", "At receipt threshold"),
            (2501, "false", "Above receipt threshold"),
            (limit - 1, "true", "One cent below category limit"),
            (limit, "false", "At category limit without receipt"),
            (limit + 1, "false", "Above category limit without receipt"),
        ):
            scenario(f"{cents // 100}.{cents % 100:02d}", receipt,
                employee=employee, category=category, description=f"{label}: {category}")

    for amount, receipt, nights, label in (
        ("199.99", "true", "1", "Single night below limit"),
        ("200.00", "true", "1", "Single night at limit"),
        ("200.01", "false", "1", "Single night above limit without receipt"),
        ("600.00", "true", "3", "Three nights at limit"),
        ("600.01", "true", "3", "Three nights one cent over limit"),
        ("0.00", "false", "1", "Complimentary hotel without receipt"),
        ("300.00", "true", "", "Hotel with missing nights requires review"),
        ("2000.00", "true", "10", "Long stay at nightly limit"),
    ):
        scenario(amount, receipt, employee="Priya Shah", category="hotel", nights=nights,
                 description=label)

    # A three-way duplicate that also breaks amount and receipt rules.
    for label in ("Original", "Resubmission", "Third submission"):
        scenario("60.00", "false", employee="Omar Hassan", description=f"{label}: client dinner")
    for changes in (
        {"employee": "Nora Williams"}, {"date": "2026-10-04"},
        {"amount": "59.99"}, {"category": "transport"},
    ):
        values = dict(amount="60.00", receipt="false", employee="Omar Hassan",
                      description="Near duplicate with one business field changed")
        values.update(changes)
        scenario(**values)

    for incurred, submitted, label in (
        ("2026-09-06", "2026-10-05", "Submitted after 29 days"),
        ("2026-08-01", "2026-10-05", "Very late submission"),
        ("2026-10-06", "2026-10-05", "Submission before expense requires review"),
        ("2024-02-29", "2024-03-30", "Leap day with 30-day submission"),
        ("2025-12-31", "2026-01-30", "Year boundary with 30-day submission"),
        ("2026-01-31", "2026-03-03", "Month boundary with 31-day submission"),
    ):
        scenario(employee="Fatima Ali", date=incurred, submission_date=submitted, description=label)
    for category, amount, receipt in (
        ("training", "1250.00", "true"), ("equipment", "9999.99", "false"),
        ("other", "0.00", "true"), ("alcohol", "80.00", "false"),
    ):
        scenario(amount, receipt, employee="Lucas Silva", category=category,
                 description=f"Category requiring manual review: {category}")
    scenario("12.50", " TRUE ", employee="  Zoë O’Connor  ", description="  Café lunch  ")
    scenario("18.5", "FALSE", employee="Zoë O’Connor", description='Client lunch, "working session"')
    scenario("0009.50", employee="Zoë O’Connor", description="Parking\nreceipt details")
    scenario("7", employee="Zoë O’Connor", description="Whole-dollar breakfast")
    # Nights is part of the duplicate key, even for otherwise identical stays.
    scenario("180.00", employee="Avery Kim", category="hotel", nights="1", description="One-night stay")
    scenario("180.00", employee="Avery Kim", category="hotel", nights="2", description="Two-night stay")
    scenario("0.01", "false", employee="Avery Kim", category="transport", description="Minimum positive fare")

    invalid_cases = (
        {"category": ""}, {"amount": ""}, {"receipt_attached": ""},
        {"date": ""}, {"submission_date": ""},
        {"amount": "1.001"}, {"amount": "1e2"}, {"amount": "NaN"},
        {"amount": "Infinity"}, {"amount": "$12.00"}, {"amount": "1,000.00"},
        {"date": "2026-02-29"}, {"date": "10/05/2026"},
        {"submission_date": "2026-13-01"},
        {"category": "hotel", "nights": "0"},
        {"category": "hotel", "nights": "-1"},
        {"category": "hotel", "nights": "1.5"},
        {"category": "hotel", "nights": "two"},
        {"employee": "   ", "amount": "-0.01", "receipt_attached": "yes"},
        {"description": "   ", "date": "2026-04-31", "submission_date": "invalid"},
    )
    for index, changes in enumerate(invalid_cases, start=7):
        row = {"description": "Invalid input validation example", **changes}
        add(f"BAD-{index:03d}", **row)

    rng = random.Random(seed)
    for index in range(extra_clean):
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
    parser.add_argument("--output", type=Path, default=Path("artifacts/sample_expenses.csv"))
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
