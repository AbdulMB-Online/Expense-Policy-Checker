# Expense Policy Checker

A command-line project for checking employee expenses against company policy.
It loads stored expense claims, runs policy checks, and produces violation
reports grouped by employee or policy rule for finance review.

Team 4: Devang Borkar (sample data and loaders), Shreyaa Lakshmivaragan (policy
engine), and Abdul Malik (violation reporting; CLI, CI, and documentation work).

The current implementation includes loaders, sample generation, three policy
rules, JSON exports, and the reporting module. The interactive CLI menu is the
next component to be implemented.

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

`PASS` means no violation was detected by the three implemented checks. The
policy coverage limitations below still require human review.

To regenerate the sample CSV or export validated records without policy checks:

```sh
python3 -m scripts.sample_data --force
python3 -m scripts.export_json --force
```

These utilities replace the sample CSV and validated-record JSON respectively.
The default sample has 30 rows: 22 valid expenses and 8 rejected rows.

See the [loader guide](docs/loader.md) for usage, input contracts, validation
behavior, JSON output, and sample scenarios.

## Policy engine

Shreyaa implemented the engine in [rules/engine.py](rules/engine.py). It operates
on accepted `Expense` objects returned by the loader. Policy settings come from
the separate [JSON policy file](data/policy/policy.json), allowing finance to
change limits without editing Python code. Policy amounts remain decimal strings
in JSON and are converted to `Decimal` during evaluation.

Every rule inherits from the abstract `PolicyRule` class in
[rules/base.py](rules/base.py). Its `evaluate(expense, all_expenses)` method
returns an explanation when the expense breaks that rule, or `None` otherwise.

| Rule | Current behavior |
| --- | --- |
| `AmountLimitRule` | Checks category limits per expense, or `max_amount × nights` for hotel stays. An amount exactly at the limit passes; a null limit produces no amount flag. |
| `MissingReceiptRule` | Requires a receipt according to the category's `always`, `above_threshold`, or `unconfigured` setting. Exactly at a threshold passes. |
| `DuplicateRule` | Compares the configured business fields and flags suspected duplicates. Supports flagging all matches or only later matches in input order. |

The checked-in policy sets these limits and receipt requirements:

| Category | Amount limit | Receipt requirement |
| --- | --- | --- |
| `meals` | USD 50.00 per expense | Above USD 25.00 |
| `hotel` | USD 200.00 per night | Always |
| `transport` | USD 75.00 per expense | Above USD 25.00 |
| `office_supplies` | USD 100.00 per expense | Above USD 25.00 |
| `other` | No amount limit | Unconfigured |

The duplicate key is employee, date, category, amount, and nights. Both members
of a matching pair with different IDs are currently flagged. A repeated record
ID is instead a loader error, because accepted claims must have unique IDs.

The engine evaluates every rule for every accepted expense. A USD 75.00 meal
without a receipt receives both an amount-limit reason and a missing-receipt
reason. Clean expenses are omitted from the engine's result mapping.

Two result interfaces are available:

- `RulesEngine(policy).run_all(expenses)` returns
  `{expense_id: [reason strings]}`, used by the existing JSON exporter.
- `RulesEngine(policy).run_detailed(expenses)` returns
  `{expense_id: [PolicyViolation objects]}`. Abdul added this reporting interface
  to preserve each reason with its stable `rule_id` and readable `rule_name`.
  The original `run_all()` interface remains compatible.

To add a rule, subclass `PolicyRule`, implement `evaluate`, and register an
instance in `RulesEngine.rules`. Set `rule_id` and `rule_name` for readable,
stable report groups; otherwise both default to the rule's class name.

### Current policy coverage

The policy file also contains submission deadlines, restricted categories,
manual-review settings for `other` and unknown categories, and hotel-night
requirements. These settings are not yet enforced by the three implemented
rules. A nightly amount check is skipped when valid nights are unavailable.
The engine currently collects every reason regardless of the policy's
`reporting.collect_all_violations` setting. Flags are a first pass for reviewers;
unflagged claims still need review for the uncovered checks.

## Violation reporting

Abdul's [reporting module](reporting/violation_report.py) combines accepted
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
Amounts are assumed to use the policy currency (USD in the sample); currency
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

### Expected sample results

| Measure | Value |
| --- | --- |
| Accepted claims | 22 |
| Rejected rows | 8 |
| Flagged claims | 10 |
| Violation reasons | 12 |
| Total flagged amount | USD 917.03 |
| Alice Morgan subtotal | USD 837.03 across 8 claims |
| Jordan Lee subtotal | USD 80.00 across 2 claims |

Rule groups contain 6 amount-limit claims (USD 777.03), 4 missing-receipt claims
(USD 210.00), and 2 suspected duplicates (USD 80.00). The rule subtotals overlap
because `EXP-005` and `EXP-014` each break two implemented rules.

### Planned interactive CLI

The planned `python3 -m scripts.check_expenses` command will automatically load
the project files and offer a numbered menu: 1) employee report, 2) rule report,
3) exit. This command and menu are not implemented yet; use the API example
above for grouped text reports, or the quick-start command for JSON results.

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
