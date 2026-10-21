# Expense Policy Checker

A command-line project for checking employee expenses against company policy.
It loads stored expense claims, runs policy checks, and produces violation
reports grouped by employee or policy rule for finance review.

## Browser dashboard

A React dashboard supports custom CSV/policy JSON uploads, employee/rule views,
filters, claim details, rejected records, and report downloads. Its employee workspace
accepts expense submissions and receipt attachments, checks the policy, and adds
saved claims to the dashboard report. Demo employee and reviewer accounts have
separate access, with individual approvals and review history. See the
[dashboard setup guide](frontend/README.md) to install and run it locally.

Sign-in loads registered accounts from the SQLite `users` table and routes each
account by its saved role. Reviewers can create and select policies in a durable
policy library. The interface supports persistent dark and light themes.

## Backend structure

All Python application code lives in `backend/`. Run commands from the repository
root using the `backend.` package prefix:

```sh
python3 -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8000
python3 -m backend.scripts.check_expenses
```

- `backend/api/`: application factory, request schemas, authentication
  dependencies, error responses, and route groups.
- `backend/services/`: report evaluation and exports, input validation,
  submissions, reviews, and source snapshots. Services do not import FastAPI.
- `backend/database/`: SQLite repositories, schema, transactions, and lossless
  record serialization.
- `backend/loader/`, `backend/rules/`, and `backend/reporting/`: parsing, policy
  checks, and report rendering shared by the web application and CLI.
- `backend/scripts/`: CLI entry points and artifact-generation commands.

Each application instance composes its own services and repositories.
Routes handle HTTP inputs and responses; services coordinate workflows;
repositories own SQL and transaction boundaries. Full-input validation remains
inside submission transactions, and report filtering happens after policy checks.
The frontend, `data/`, `artifacts/`, and Python tests retain their existing locations.

After installing `requirements-dev.txt`, run the backend checks with:

```sh
python3 -m pytest -q
python3 -m ruff check backend
python3 -m ruff format --check backend
```

## Local database and attachments

The web app uses Python's built-in `sqlite3`; no database server or object-storage
service is required. Everything is stored in `artifacts/submissions.sqlite3`.
The database is initialized on first use, with 12 employee demo accounts matching
the sample data and two finance reviewer accounts. Start the dashboard using the
[local setup instructions](frontend/README.md#run-the-dashboard).

Original expense CSVs, policy JSON files, receipt attachments, and downloaded web
reports are stored directly in the `artifacts.contents` BLOB column. Metadata
includes the filename, media type, byte size, SHA-256 checksum, uploader, and UTC
creation time. Receipt uploads accept PDF, PNG, or JPEG files up to 5 MiB. File
bytes are fetched only by download operations, not artifact list queries. Keeping
these small local-demo attachments in SQLite makes a database backup include
both the records and their files.

The database layer is split into:

- `backend/database/core.py` and `schema.py`: connections, foreign keys,
  transactions, versioned schema, demo accounts, and legacy database migration.
- `backend/database/submissions.py`: atomic form-expense and receipt saves, plus retry
  deduplication scoped to the submitting account.
- `backend/database/workspace.py`: composition of the focused `sessions.py`,
  `datasets.py`, `checks.py`, `reviews.py`, and `artifacts.py` repositories.

`datasets` links original artifacts and parsed CSV input, including rejected rows.
`policy_versions` preserves validated policy JSON by content hash. `expenses`
indexes workspace, owner, origin, and source expense ID; `expense_revisions`
retains immutable validated records and receipt links. Amounts remain exact
**decimal strings** in JSON records and are evaluated using Python `Decimal`;
SQLite floating-point arithmetic is not used for financial totals.
`check_runs` and `check_results` pin each evaluation to its policy, engine source
hash, full ordered revision set, and validation errors. Reads reuse those findings.
`review_events` records the reviewer, decision, comment, revision, and run. A
revision can receive one decision; corrections create a new revision rather than
rewriting the old decision. Transactions reject competing or stale decisions.

`PRAGMA user_version` tracks the schema version. Version 1 migrates the original
`submissions` table into expenses, revisions, and BLOB artifacts in one
transaction. Existing receipts and exact amounts are retained; the legacy table
is kept for recovery but is no longer used. Previously uploaded in-memory datasets
from an older server need one re-upload because their original bytes were not saved.

All report and receipt endpoints require demo sign-in. Useful API endpoints are:

- `GET /api/demo/accounts`, `POST /api/demo/login` with `{"user_id":"employee-anika"}`,
  `GET /api/session`, and `POST /api/demo/logout`.
- `GET /api/datasets`: saved inputs available to the active account.
- `GET /api/artifacts` and `GET /api/artifacts/{id}`: reviewer metadata/downloads.
- `GET /api/check-runs/{id}`: reviewer access to original policy, input revisions,
  validation errors, and findings from a historical run.
- `POST /api/expenses/{id}/owner`: reviewer mapping for an unmatched import.
- `POST /api/expenses/{id}/review`: individual decision with `run_id`,
  `revision_id`, `decision`, and `comment`.
- `GET /api/expenses/{id}/history`: decision history for the owner or reviewers.
- `PUT /api/expenses/{id}`: owner correction after requested changes, including
  the expected `revision` and optionally a replacement receipt.

Expense endpoints accept `?dataset=...` for an uploaded workspace; form endpoints
accept `dataset` as a form field. The active workspace always determines currency.
Interactive request schemas are available at `/docs` while the API is running.

For a consistent backup, use SQLite's backup command (choose a new destination):

```sh
sqlite3 artifacts/submissions.sqlite3 ".backup artifacts/expense-backup.sqlite3"
```

The backup includes attachment bytes, historical inputs, and review records.
Restore with the application stopped by placing the backup at the original
`artifacts/submissions.sqlite3` location. Database files stay outside Git.

## Quick start

Requires Python 3.11+. Run from the repository root:

```sh
python3 -m backend.scripts.check_expenses
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
python3 -m backend.scripts.export_policy_results --force
```

This checks `data/expenses/sample_expenses.csv` using `data/policy/policy.json`
and writes `data/out/policy_check_results.json`. `--force` replaces the existing
generated results file. The stored claims and policy are unchanged.

## Generate artifacts

All file generation lives in `backend/scripts/`.

```sh
# artifacts/sample_expenses.csv (reproducible copy of the sample)
python3 -m backend.scripts.sample_data --force

# artifacts/sample_expenses.json (validated records and loader errors)
python3 -m backend.scripts.export_expenses --force

# artifacts/policy_check_results.json (summary, results, and loader errors)
python3 -m backend.scripts.export_policy_results --force

# artifacts/business_travel.json (alternative policy)
python3 -m backend.scripts.generate_example_policy --force

# artifacts/business_travel_results.json
python3 -m backend.scripts.export_policy_results \
  --policy artifacts/business_travel.json \
  --output artifacts/business_travel_results.json --force
```

`--force` replaces existing output; omit it to protect existing files.
Use `--output PATH` for another destination. To check a generated or custom CSV,
pass `--expenses PATH` to `export_policy_results` or `--input PATH` to `export_expenses`.

The sample contains exactly 100 rows across 12 fictional employees. It covers
amounts, receipts, duplicates, restricted and unknown categories, late submissions,
future expense dates relative to submission, missing or invalid hotel nights,
maximum stay length, and categories requiring review. The business travel example
policy caps hotel stays at seven nights: `EXP-044` is at the cap and `EXP-048`
exceeds it. The standard policy leaves stay length uncapped. See the
[sample scenarios](docs/loader.md#sample-scenarios) for IDs and validation details.

## Policies and reports


Results include every detected violation and a `PASS` or `FLAGGED` status.
Checks cover amounts, receipts, duplicates, submission deadlines, future dates,
category restrictions and review requirements, hotel nights, and stay lengths.
Flags still require finance review. Invalid supplied
night counts are rejected by the loader before policy evaluation.

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
`main` and pushes to `main`. A separate Node.js 24 job tests the React dashboard
and type-checks/builds the frontend. View results and failure logs in the PR checks or
the repository's **Actions** tab. The workflow is defined in
[tests.yml](.github/workflows/tests.yml).
