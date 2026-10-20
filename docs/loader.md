# Loader guide

The `loader` package reads expense CSV files and policy JSON files, validates
their data, and returns values for the rules engine. It does not apply policy
to expenses. Runtime code uses only the Python standard library.

Run the commands below from the repository root.

```sh
python3 -m scripts.sample_data --output artifacts/sample_expenses.csv
python3 -m scripts.sample_data --output /tmp/expenses.csv --seed 42
```

Existing files are protected; use `--force` to overwrite. Identical arguments produce identical data.

```python
from loader.expense_loader import load_expenses

result = load_expenses("data/expenses/sample_expenses.csv")
for expense in result.expenses:
    print(expense.id, expense.amount)
for error in result.errors:
    print(error.line_number, error.expense_id, error.reasons)
```

## JSON export

Run from the repository root:

```sh
python3 -m scripts.export_json --input data/expenses/sample_expenses.csv --output artifacts/sample_expenses.json
```

The exporter calls `load_expenses` and writes an object with `expenses` (validated
records) and `errors` (rejected row IDs, line numbers, and reasons). The default
sample produces 72 expense records and 28 errors. Dates use ISO strings, amounts
use decimal strings to preserve precision, and receipts use JSON booleans.
Both paths above are defaults, so `python3 -m scripts.export_json` also works.
Use `--force` to replace an existing JSON file. The input CSV cannot be overwritten.
File-level input errors stop export without changing an existing output file.

## CSV contract

Required headers, in any order:

```csv
id,employee,date,category,amount,description,receipt_attached,submission_date,nights
EXP-001,Alice Morgan,2026-10-05,meals,20.00,Team lunch,true,2026-10-05,
```

- All headers are required. Field values are required and trimmed except for
  `nights`, which is optional for every category. IDs must be unique among accepted records.
- `date` is the date the expense was incurred; `submission_date` is the date it
  was submitted. Both are required real dates in `YYYY-MM-DD` format.
  Comparing these dates belongs to the rules engine.
- Any supplied `nights` value must be a positive integer. Whether a category
  requires nights is a policy decision, not a loader validation check.
- Amounts are nonnegative decimal numbers with at most two decimal places, parsed
  as `Decimal`. Zero is valid. Symbols, separators, exponents, NaN and infinity are rejected.
- Receipts are `true` or `false`, case insensitive, parsed as booleans.
- Employee, category and description are nonempty text. Category membership belongs to the policy engine.
- All amounts are assumed USD; conversion is outside this version.
- UTF-8 with optional BOM is supported; blank lines are skipped.

The loader returns `LoadResult.expenses` and `LoadResult.errors`. Each row error
includes its starting physical line, available ID, and all validation reasons.
Invalid rows are skipped while subsequent rows continue. Rejected rows do not
reserve IDs. Wrong field counts are row errors. Unreadable files, invalid UTF-8,
malformed CSV syntax, and missing/duplicate/unknown headers raise file-level exceptions.

Duplicate IDs are invalid records. Matching business details under different IDs
remain valid for the duplicate policy rule. Policy violations do not belong
in loader validation.

## Policy loading and responsibility

```python
from loader.policy_loader import load_policy

policy = load_policy("data/policy/policy.json")
# Select the alternative policy with the same loader:
travel_policy = load_policy("artifacts/business_travel.json")
```

`load_policy` reads the external JSON file and validates required keys, types,
decimal strings, rule setting formats, and supported configuration options.
It returns a dictionary preserving the JSON values; monetary limits remain
strings for exact conversion to `Decimal` by the rules engine. Missing files
raise `OSError`; malformed JSON or invalid configuration raises `ValueError`
with a reason. Duplicate JSON keys and unknown fields are rejected.

Both loaders perform data validation only. Neither applies policy to expenses.
Missing hotel nights, date comparisons, category limits, receipt requirements,
restricted categories and suspected duplicates belong to the rules
engine. The expense loader accepts structurally valid records even when they
may violate policy. Unique record IDs are an input constraint; business duplicate
detection is separate. The sample generator uses fixed scenarios rather than
reading or enforcing the policy file.

## Sample scenarios

The default sample has exactly 100 data rows (excluding the header): 72 valid
expenses and 28 invalid rows. It includes examples for five policy scenarios:
category amount limits, required receipts, suspected duplicates, submission
deadlines, and restricted categories. The external
[JSON policy](../data/policy/policy.json) defines meals at $50 per expense,
hotel at $200 per night, transport at $75 per expense, and office supplies at $100
per expense. Hotel receipts are always required; the other three categories
require receipts above $25. Submission is allowed within 30 days inclusive,
alcohol is restricted, and `other` or unknown categories require review. The
30-day deadline and alcohol restriction are project-chosen examples of the
overview's rules; category limits and receipts follow the category screenshot. These
are sample policy values; the loader does not enforce policy rules. The rules
engine currently implements amount limits, receipt requirements, and suspected
duplicates. Submission deadlines, restricted categories, and manual-review
settings are not yet enforced. See the
[violation reporting guide](../README.md#violation-reporting) for
grouped report usage.

- `EXP-001`: clean meal; `EXP-002`: exactly $50; `EXP-003`: $50.01.
- `EXP-004`: $40 taxi under `transport` without receipt; `EXP-005`: $75 meal without receipt
  (two potential violations).
- `EXP-006` / `EXP-007`: identical $40 taxi expenses with receipts and matching
  employee/date/category/amount, under different IDs.
- `EXP-008`: zero; `EXP-009`: exactly $25 without receipt; `EXP-010`: comma in description.
- `EXP-011`: incurred September 5 and submitted October 5, exactly 30 days later.
- `EXP-012`: incurred September 4 and submitted October 5, 31 days later.
- `EXP-013`: $15 alcohol expense with a receipt, illustrating a restricted category.
- `EXP-014`: $75 meal without a receipt, incurred September 4 and submitted
  October 5, illustrating amount, receipt, and submission deadline violations.
- `EXP-015` / `EXP-016`: hotel stays of two nights at $400 and $402, respectively,
  illustrating the $200 nightly boundary and an over-limit total.
- `EXP-017`: $20 hotel stay for one night without its always-required receipt.
- `EXP-018` / `EXP-019`: office supplies at $100 and $100.01.
- `EXP-020` / `EXP-021`: transport at $75 and $75.01.
- `EXP-022`: $500 under `other` without a receipt, requiring manual review.
- Invalid cases: missing employee, negative amount, impossible date, nonnumeric amount,
  missing description, invalid receipt value, missing ID, and repeated ID.

- `EXP-023`–`EXP-040`: meals, transport, and office supplies below/at/above
  the receipt threshold and category limit, including combined violations.
- `EXP-041`–`EXP-048`: single-night, multi-night, and long hotel stays,
  one-cent nightly overages, a complimentary stay without receipt, and missing nights.
- `EXP-049`–`EXP-055`: three matching dinners with multiple violations and
  near matches differing in employee, date, amount, or category.
- `EXP-056`–`EXP-061`: 29-day and very late submissions, submission before
  the expense, leap day, and month/year boundaries.
- `EXP-062`–`EXP-065`: unknown categories, zero-value `other`, and alcohol.
- `EXP-066`–`EXP-069`: Unicode, whitespace trimming, mixed-case receipt
  booleans, CSV commas/quotes/newlines, and accepted decimal formats.
- `EXP-070`–`EXP-072`: hotel near matches differing only in nights and a one-cent fare.
- `BAD-007`–`BAD-026`: missing fields, excessive precision, exponent notation,
  NaN/infinity, currency symbols, thousands separators, invalid dates and nights,
  and rows with multiple validation errors.

These cases span 12 employees. Date ordering, missing hotel nights, and category
review cases demonstrate gaps requiring manual review in the current engine;
a `PASS` for these cases only reflects the implemented checks.

All default records are fixed scenarios. `--extra-clean N` optionally adds N
generated valid meals of $0.01–$25 with receipts beyond the default 100. Their
business details can coincide; duplicate-policy classification remains the
rules engine's job.

## Tests

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```
