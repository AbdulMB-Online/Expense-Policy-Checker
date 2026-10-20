# Expense Policy Checker

A command-line project for checking employee expenses against company policy.
It loads stored expense claims, runs policy checks, and produces violation
reports grouped by employee or policy rule for finance review.

## Quick start

Requires Python 3.11+. Run from the repository root:

```sh
python3 -m scripts.export_policy_results --force
```

Uses the example `data/expenses/sample_expenses.csv` and
`data/policy/policy.json`; writes `artifacts/policy_check_results.json`.
The sample has 100 rows: 72 accepted expenses and 28 rejected rows.

## Generate artifacts

All file generation lives in `scripts/`.

```sh
# artifacts/sample_expenses.csv (reproducible copy of the sample)
python3 -m scripts.sample_data --force

# artifacts/sample_expenses.json (validated records and loader errors)
python3 -m scripts.export_json --force

# artifacts/policy_check_results.json (summary, results, and loader errors)
python3 -m scripts.export_policy_results --force

# artifacts/business_travel.json (alternative policy)
python3 -m scripts.generate_example_policy --force

# artifacts/business_travel_results.json
python3 -m scripts.export_policy_results \
  --policy artifacts/business_travel.json \
  --output artifacts/business_travel_results.json --force
```

`--force` replaces existing output; omit it to protect existing files.
Use `--output PATH` for another destination. To check a generated or custom CSV,
pass `--expenses PATH` to `export_policy_results` or `--input PATH` to `export_json`.

## Policies and reports


Results include every detected violation and a `PASS` or `FLAGGED` status.
Checks cover amounts, receipts, and suspected duplicates. Submission deadlines,
restricted categories, and manual-review settings still require manual review.

The [reporting module](reporting/violation_report.py) provides `build_report`,
`group_report`, and `render_report`, grouped by `employee` (default) or `rule`.
Totals count each flagged claim once; rule-group subtotals can overlap.
See the [loader guide](docs/loader.md) for input formats and sample scenarios.

## Tests

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Tests generate temporary artifacts; no generation step is required beforehand.
