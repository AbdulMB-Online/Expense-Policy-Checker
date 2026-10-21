# Expense dashboard

React + TypeScript + Vite, with Tailwind CSS and shadcn/ui. The interface uses a
finance workspace with dark and light themes, sidebar navigation, grouped claim review, and
responsive employee submission forms. Data comes from the existing Python
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

Search your name, select your account tile, and click **Sign in**. Accounts come from the
SQLite `users` table; the server returns the stored role and the dashboard opens
the matching workspace. Demo accounts do not require a password. There is no
role selector or reviewer/employee view switch inside the dashboard.

Reviewers have separate **Overview**, **Claims to review**, **All expenses**,
**Import files**, and **Input issues** tabs. Employees use **Submit expense**
and **My expenses**. The sidebar switches the same views; drafts, selected files,
and review filters stay intact while switching tabs.

Dark mode is the default. The header theme control switches between dark and
light and remembers the preference in the browser. **Refresh report** reloads the inputs
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
- Sign in as Morgan Finance or Taylor Finance to open **Expense review**. Totals,
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
- Reviewers can use **Previously imported files** under **Report files** to reopen
  uploaded inputs after a restart. The selected import is remembered per account
  in the browser. Import controls are not shown on the employee submission page. Use **Switch account**
  to move between employees and reviewers.
- Reviewers can open **Policy** in the sidebar or click the active policy above
  the report. The library includes the default policy, uploaded policies, and
  policies created with **New policy**. Choose a starting policy, set its name,
  currency, category limits, receipt requirements, restricted categories,
  submission deadline, and duplicate checks, then click **Save policy**.
- Select a saved policy and click **Use policy** to recheck the current expense
  dataset. Saving a policy alone does not change the active report. Policies are
  stored in SQLite and survive restarts. A different currency uses a separate
  submission workspace; existing amounts are not converted. Employees can view
  their current policy but cannot create or apply policies.
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

## Report assistant

From the repository root, install the web dependencies and copy the key template:

```bash
.venv/bin/python -m pip install -r requirements-web.txt
cp .env.example .env
```

For Azure AI Foundry, fill in the local `.env` (do not overwrite an existing file
with keys):

```dotenv
LLM_PROVIDER=azure_foundry
LLM_API=chat_completions
AZURE_OPENAI_API_KEY=your-key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=your-deployment-name
```

Use your resource's endpoint and the deployment **name** shown in Foundry. The
endpoint may also be `https://your-resource.services.ai.azure.com`, and an
`/openai/v1/` suffix is accepted. Use `LLM_API=chat_completions` when your deployment example uses
`client.chat.completions.create` (such as the supplied grok-4.7 example). This
uses `/openai/v1/chat/completions` and Bearer key authentication, matching that
example. Use `LLM_API=responses` for Responses-compatible deployments; that mode
uses `/openai/v1/responses` with Azure api-key authentication. Neither v1 route
requires an API version. Supply the resource base URL, not a project URL or a
URL ending in chat/completions. See [Microsoft's endpoint guide](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/endpoints).

For direct OpenAI instead, set `LLM_PROVIDER=openai`, `OPENAI_API_KEY`, and
optionally `OPENAI_MODEL` (default `gpt-5.5`). Server environment variables take
precedence over `.env`. Restart the API server after changing configuration:

```bash
.venv/bin/python -m uvicorn backend.api.app:app --host 127.0.0.1 --port 8000
```

Build the frontend with `npm run build` from `frontend/`, or run the Vite dev
server as described above. In Reviewer view, choose **Ask about this report**.
Ask about priorities, individual claim IDs, policy rules, employee/category
comparisons, or monthly patterns. Follow-up questions retain the conversation.
Choose **Entire report** or **Current filters**, and use the claim buttons below
answers to inspect supporting records. **Stop** cancels waiting; **New chat**
clears the conversation. Closing the dialog, refreshing/changing the report,
or changing filters/scope starts a new conversation. Chats are not persisted.

The key stays on the server; `.env` is ignored by Git. Without a key, reporting
and submissions work normally and chat displays setup instructions. Questions,
chat history, and the selected report's claim details and policy are sent to
the configured AI provider when you send a question. Receipt files and download links are excluded.
Responses-mode requests use `store=false` in the
[Responses API](https://developers.openai.com/api/reference/resources/responses/methods/create).
AI answers need reviewer verification and cannot approve or edit expenses.

Limits: 4,000 characters per question, 10 answers per chat, 90-second provider
request timeout, and 300 KB of report context. Larger reports require narrowing
the employee/search filters and choosing Current filters. Records are never
silently omitted. Global summary/input errors are labeled separately from
filtered claims. Amounts and employee/category/month totals are calculated in
Python with decimal arithmetic before sending context. No live AI request is
needed for automated tests; the provider boundary is mocked.
