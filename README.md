# Expense Policy Checker

A command-line project for checking employee expenses against company policy.
It loads stored expense claims, runs policy checks, and produces violation
reports grouped by employee or policy rule for finance review.

## Quick start

Requires Python 3.11+. Run from the repository root:

```sh
python3 -m scripts.check_expenses
```

The tool automatically reads the stored expense CSV and policy JSON, then shows:

```text
EXPENSE POLICY CHECKER

1. View report grouped by employee
2. View report grouped by policy rule
3. Exit

Enter your choice:
```

Enter `1` or `2` to display a report and return to the menu. Enter `3` to exit.
Invalid choices prompt again; Ctrl+C or end-of-input also exits. Both views use
the same claims and policy loaded at startup; restart after updating the files.
No file paths are requested, and viewing reports does not modify stored data.

### JSON export

To save policy results as JSON instead:

```sh
python3 -m scripts.export_policy_results --force
```

This checks `data/expenses/sample_expenses.csv` using `data/policy/policy.json`
and writes `data/out/policy_check_results.json`. `--force` replaces the existing
generated results file. The stored claims and policy are unchanged.

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

- `build_report(...)` creates an immutable report with summary counts and the
  unique flagged-claim total. It rejects duplicate input IDs and engine result
  IDs that do not correspond to an accepted claim.
- `group_report(report, group_by=...)` returns groups and
  subtotals. Group names are sorted; claims retain their input order.
- `render_report(report, group_by=...)` returns text ready for terminal display.
  Both grouping functions accept `"employee"` or `"rule"`; employee grouping is
  the default. Unsupported group choices raise `ValueError`.

**Employee grouping** shows each employee's flagged claims with IDs, dates,
categories, amounts, and all reasons. **Rule grouping** shows claims under each
rule they break, includes the employee name, and displays only that rule's
reasons. Grouping uses rule IDs rather than matching explanation text.

The report starts with accepted-claim, rejected-row, flagged-claim, and reason
counts, followed by the total flagged amount. Each employee or rule group has a
flagged-claim count and subtotal. Rejected rows appear in a separate section with
line numbers, available IDs, and all validation reasons; they are excluded from
policy checks and flagged totals.

Totals use `Decimal` and count the full amount of each flagged claim once, even
when it has several reasons. A claim can appear in multiple rule groups, so
those subtotals overlap and must not be added to obtain the overall total.
Amounts are assumed to use the policy currency; currency
conversion is outside this version.

Use menu choices `1` and `2` to view both groupings in one session. A report
with no flags says "No violations detected by the configured checks."

## Tests

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Report tests cover both groupings, every reason, exact totals, overlapping rule
groups, rejected rows, empty results, and integration with the committed sample.
Engine tests cover limit boundaries, receipt modes, configurable duplicates,
multiple violations, and compatibility between the two result interfaces.
CLI tests cover menu selection, repeated viewing, invalid choices, graceful
exit, file errors, and the complete command using the stored sample.

## Continuous integration

GitHub Actions runs pytest on Ubuntu with Python 3.11 for pull requests targeting
`main` and pushes to `main`. View results and failure logs in the PR checks or
the repository's **Actions** tab. The workflow is defined in
[tests.yml](.github/workflows/tests.yml).
