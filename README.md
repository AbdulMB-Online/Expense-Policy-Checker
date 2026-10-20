# Expense Policy Checker

A command-line project for checking employee expenses against company policy.
It loads stored expense claims, runs policy checks, and produces violation
reports grouped by employee or policy rule for finance review.

## Quick start

Requires Python 3.11+. Run from the repository root:

```sh
python3 -m scripts.export_policy_results --force
```

This checks the existing claims in `data/expenses/sample_expenses.csv` using
`data/policy/policy.json` and writes `data/out/policy_check_results.json`.
`--force` replaces the existing generated results file. No input paths or
interactive responses are required. The stored claims and policy are unchanged.

The JSON output contains:

- `summary`: accepted, passed, flagged, and rejected-row counts.
- `results`: one entry per accepted expense, including amount, `PASS` or
  `FLAGGED` status, and every violation reason.
- `errors`: rejected input rows, available IDs, line numbers, and reasons.

`PASS` means no violation was detected by the implemented amount, receipt, and
duplicate checks. Other policy settings, including submission deadlines and
restricted categories, still require manual review.

To regenerate the sample CSV or export validated records without policy checks:

```sh
python3 -m scripts.sample_data --force
python3 -m scripts.export_json --force
```

These utilities replace the sample CSV and validated-record JSON respectively.
The default sample has 30 rows: 22 valid expenses and 8 rejected rows.

See the [loader guide](docs/loader.md) for usage, input contracts, validation
behavior, JSON output, and sample scenarios.

## Violation reporting

The [reporting module](reporting/violation_report.py) combines accepted
expenses with detailed engine results and optional loader errors. It separates
report construction from grouping and text formatting:

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

### Display both report views now

The report API is available now. From the repository root, run this Python
example to display both views using the stored files:

```python
from loader.expense_loader import load_expenses
from loader.policy_loader import load_policy
from reporting.violation_report import build_report, render_report
from rules.engine import RulesEngine

loaded = load_expenses("data/expenses/sample_expenses.csv")
policy = load_policy("data/policy/policy.json")
detailed = RulesEngine(policy).run_detailed(loaded.expenses)
report = build_report(
    loaded.expenses,
    detailed,
    currency=policy["currency"],
    errors=loaded.errors,
)

print(render_report(report, group_by="employee"), end="")
print(render_report(report, group_by="rule"), end="")
```

The reporting functions return data or text; the caller displays the text with
`print`. They do not modify expense or policy files. A report with no flags says
"No violations detected by the configured checks."

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
