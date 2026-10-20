# Expense dashboard

React + TypeScript + Vite, with Tailwind CSS and shadcn/ui. The design adapts
the supplied SaaS template to expense review. Data comes from the existing Python
loaders, rules engine, and reporting module through a local FastAPI service.

## Run the dashboard

Requires Python 3.11+ and Node.js 24+. From the repository root:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-web.txt
npm --prefix frontend ci
npm --prefix frontend run build
.venv/bin/python -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. The Python server serves the built React app and
API together. Stop it with Ctrl+C. Build the frontend before starting this
server; rebuild after frontend edits.

Choose a demo account when the app opens. **Refresh report** reloads the inputs
and uses saved check results when the expense revisions, policy, and engine are unchanged.
The CLI remains available with `python3 -m backend.scripts.check_expenses`.

## Use the dashboard

- Choose an employee demo account to submit your own expenses. Your employee
  identity is fixed by the account. Enter a date, category, amount, and
  description. Hotel/per-night categories also require the number of nights.
  Attach a PDF, PNG, or JPEG receipt (up to 5 MiB), then click **Submit expense**.
- The active policy checks run before saving. Valid claims with violations are
  saved with every reason; invalid fields or unsupported receipts show errors
  and retain the draft. Submissions without receipts are allowed and flagged
  when the policy requires one. **Unflagged** still requires finance review.
- Choose Morgan Finance or Taylor Finance to open **Reviewer view**. Totals,
  grouping, filters, and exports include submitted claims. **All expenses** also
  includes unflagged imported claims. Open a claim to download its receipt and
  approve it, reject it, or request changes. Rejections and change requests need
  a comment. Reviewers cannot decide on their own expenses.
- Imported names matching a seeded employee are mapped to that account. For an
  unknown name, open the claim and choose **Employee account → Assign employee**
  before reviewing it. Account IDs control ownership after this initial mapping.
- Employees see only their own claims, totals, receipts, and review history.
  A form expense with requested changes can be corrected and resubmitted from
  its details. The previous revision, receipt, findings, and decision are retained.
  Correct imported expenses through a new CSV upload.
- Use **Saved datasets** to reopen uploaded inputs after a restart. The selected
  dataset is remembered per demo account in the browser. Use **Switch account**
  to move between employees and reviewers.
- Under **Report files**, choose an **Expense CSV**, a **Policy JSON**, or both,
  then click **Check selected files**. Filenames can differ from the samples;
  contents must follow the [loader formats](../docs/loader.md). Replacing one
  file keeps the other active file. Both active filenames are displayed.
- Invalid file formats show a reason and keep the active report. Bad CSV rows
  appear under **Input issues** while valid rows continue through policy checks.
- **Use sample files** returns to the stored inputs. Changing sources clears
  employee/search filters so they cannot hide claims from the new file.
- Switch between **By employee** and **By policy rule**.
- Search claim IDs, dates, employees, categories, or descriptions, or select an
  employee. Filtering preserves the full-file duplicate detection context.
- Click a claim to see its receipt status and every violation reason.
- Expand a group or show its remaining claims. Open **Input issues** for rejected
  rows and **Policy** for the current configuration.
- **Export report** downloads text using the selected grouping and current
  filters. Input errors in downloads apply to the complete source file.

Summary cards always describe the complete source. The report count and groups
reflect filters. Monetary amounts and totals come from Python as decimal strings;
the browser does not calculate financial totals. Unflagged claims still require
review for conditions outside the active checks.

Uploads do not overwrite repository samples. CSVs, policy JSON files, and
receipts are limited to 5 MiB each. PDF, PNG, and JPEG receipts are checked by
file signature and served as downloads; the app does not extract receipt text.

All durable application data lives in `artifacts/submissions.sqlite3`, ignored
by Git. This includes original file bytes as SQLite BLOBs, artifact metadata,
parsed inputs and rejected-row reasons, policy versions, expense ownership and
revisions, check runs, individual decisions, and exported text reports. Uploads
survive API restarts and are no longer evicted after 20 datasets. The CLI export
scripts still write their requested output files independently of the web database.

Uploaded CSV workspaces are identified by file contents. Reusing the same CSV
keeps submitted claims. Changing only policy limits produces another saved
check run; changing currency keeps amounts in a separate workspace. Duplicate
checks evaluate the full workspace before permissions and screen filters are
applied. Employee duplicate explanations omit other employees' claim IDs.
Automated flags and human review decisions are separate fields.

Demo sign-in uses a one-day, HTTP-only, SameSite cookie backed by a hashed
session token in SQLite. The local demo deliberately permits account selection
without passwords; run it on `127.0.0.1` as shown above.

See the [database documentation](../README.md#local-database-and-attachments)
for schema, migration, attachment APIs, and backup details.

## Frontend development

Run the Python API in one terminal using the command above. In another:

```sh
npm --prefix frontend run dev
```

Open **http://127.0.0.1:5173**. Vite proxies `/api` to port 8000 and refreshes the
page after React/CSS edits. There is no separate CORS configuration to maintain.

## Component and style paths

| Path | Purpose |
| --- | --- |
| `components/ui/saa-s-template.tsx` | Adapted dashboard, navigation, summaries, report groups, and dialogs |
| `demo.tsx` | Renders the supplied demo import pattern |
| `components/ui/` | shadcn button, badge, dialog, and tab primitives |
| `components/source-files.tsx` | Optional CSV/JSON selection, upload validation feedback, active filenames, sample reset |
| `components/user-expense-view.tsx` | Expense form, receipt selection, policy guidance, result reasons, and submitted-claim list |
| `styles/globals.css` | Tailwind imports, dark theme tokens, dashboard layout, responsive styles |
| `lib/report.ts` | API types, fetching, query parameters, date/currency formatting |
| `lib/utils.ts` | Shared class-name merging |

Paths in this table are relative to `frontend/`. The `@` alias points to that
directory, so `@/components/ui` resolves to `frontend/components/ui`, not to a
second folder at the Python repository root. `components.json` configures this
location for shadcn. Keeping primitives here makes registry/demo imports and
future CLI additions resolve consistently.

React hooks manage the employee, search, grouping, dialog, refresh, and loading
state. There is no required global state/context provider. The top-level
dashboard component receives the signed-in demo user and account-switch callback;
internal components receive typed API data. Radix
primitives manage accessible tabs/dialog focus and keyboard interactions.

## Recreating the frontend setup

This repository is already configured. For a new empty project, the equivalent
setup starts with:

```sh
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install tailwindcss @tailwindcss/vite
npx shadcn@latest init
npx shadcn@latest add button badge dialog tabs
```

Register `@tailwindcss/vite` in the Vite plugins and import `tailwindcss` in the
shared CSS. Configure matching `@/*` paths in TypeScript and Vite and the UI/style
paths in `components.json`. In this app, generated primitives use the local
`@/lib/utils` helper. Do not recreate the app or rerun initialization over the
configured files. See the official [shadcn Vite guide](https://ui.shadcn.com/docs/installation/vite)
and [Tailwind Vite guide](https://tailwindcss.com/docs/installation/using-vite).

## Tests and build

From the repository root:

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
npm --prefix frontend test
npm --prefix frontend run build
```

API integration tests use real loaders/rules against isolated sample files.
React tests cover data display, grouping, filters, dialogs, error recovery,
uploads, and downloads. API upload tests verify custom names and policy limits,
retained duplicate context, separate snapshots, rejected formats, and size
limits. GitHub Actions runs Python tests plus frontend tests and build.
Submission integration tests also check real policy results, persistence after
restart, receipt downloads, validation/rollback, duplicate context, retries,
concurrent requests, and custom file/currency isolation. React tests cover form
entry, attachments, result reasons, reviewer updates, clean claims, field errors,
required hotel nights, and retry/loading behavior.

## Assets and responsive behavior

Lucide React supplies the icons. `public/favicon.svg` is a local vector mark.
The decorative office image is stored locally in `public/office.jpg` from
[Unsplash](https://images.unsplash.com/photo-1497366754035-f200968a6e72).
Fonts use Google Fonts with system fallbacks. The interface becomes a single
column on phones, uses a collapsible navigation menu, stacks claim information,
and honors reduced-motion preferences.
