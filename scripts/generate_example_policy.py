"""Generate the example business travel policy in artifacts/."""

import argparse
import json
from pathlib import Path


BUSINESS_TRAVEL_POLICY = {'version': '1.0',
 'name': 'Business travel expense policy',
 'currency': 'USD',
 'categories': {'meals': {'max_amount': '75.00',
                          'limit_basis': 'per_expense',
                          'receipt': {'mode': 'above_threshold', 'threshold': '25.00'}},
                'hotel': {'max_amount': '300.00',
                          'limit_basis': 'per_night',
                          'receipt': {'mode': 'always'},
                          'nights_required': True,
                          'max_nights_per_stay': None},
                'transport': {'max_amount': '100.00',
                              'limit_basis': 'per_expense',
                              'receipt': {'mode': 'always'}},
                'office_supplies': {'max_amount': '150.00',
                                    'limit_basis': 'per_expense',
                                    'receipt': {'mode': 'above_threshold', 'threshold': '25.00'}},
                'training': {'max_amount': '1500.00',
                             'limit_basis': 'per_expense',
                             'receipt': {'mode': 'always'}},
                'other': {'max_amount': None,
                          'limit_basis': 'per_expense',
                          'receipt': {'mode': 'unconfigured'},
                          'review_required': True}},
 'restricted_categories': ['alcohol'],
 'unknown_category_action': 'review_required',
 'submission': {'max_days_after_expense': 30, 'inclusive': True},
 'duplicates': {'key_fields': ['employee', 'date', 'category', 'amount', 'nights'],
                'require_different_ids': True,
                'flag': 'all_matches',
                'classification': 'suspected_duplicate'},
 'reporting': {'collect_all_violations': True, 'flagged_amount_counting': 'once_per_expense'}}


def generate_policy(output: str | Path, *, overwrite: bool = False) -> Path:
    """Write the repeatable example policy, protecting existing files by default."""
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w" if overwrite else "x", encoding="utf-8") as target:
        target.write(json.dumps(BUSINESS_TRAVEL_POLICY, indent=2, ensure_ascii=False) + "\n")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/business_travel.json"))
    parser.add_argument("--force", action="store_true", help="Overwrite existing output")
    args = parser.parse_args()
    try:
        path = generate_policy(args.output, overwrite=args.force)
    except OSError as error:
        parser.exit(1, f"Error: {error}\n")
    print(f"Wrote business travel policy to {path}")


if __name__ == "__main__":
    main()
