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
.venv/bin/python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. The Python server serves the built React app and
API together. Stop it with Ctrl+C. Build the frontend before starting this
server; rebuild after frontend edits.

The stored CSV and policy are loaded automatically. **Refresh report** reloads
stored files, or reruns checks on the active uploaded files.
The CLI remains available with `python3 -m scripts.check_expenses`.

## Use the dashboard

- Open **User view** to enter an employee name, date, category, amount, and
  description. Hotel/per-night categories also require the number of nights.
  Attach a PDF, PNG, or JPEG receipt (up to 5 MiB), then click **Submit expense**.
- The active policy checks run before saving. Valid claims with violations are
  saved with every reason; invalid fields or unsupported receipts show errors
  and retain the draft. Submissions without receipts are allowed and flagged
  when the policy requires one. **Unflagged** still requires finance review.
- Open **Reviewer view** or **View reviewer report** after submission. Totals,
  grouping, filters, and exports include submitted claims. **Submitted expenses**
  in both views also shows clean claims; open a claim to download its receipt.
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

Uploads do not overwrite the repository's samples. Files are limited to 5 MiB
each and parsed into temporary, separate review snapshots. The local API keeps
the latest 20 snapshots in memory until it restarts. Refresh, filtering, and
export use the active snapshot; reloading the browser starts with sample files.
Upload again if a snapshot is no longer available. Use the documented single
API process; snapshots are not shared between multiple server workers.

Form submissions and their receipt bytes are stored together in
`artifacts/submissions.sqlite3`, which is ignored by Git. They survive API
restarts and do not modify the source CSV. Default CSV submissions belong to the
stored workspace. Uploaded CSV workspaces are identified by file contents;
upload the same CSV again after a restart to recover their submissions. Changing
only policy limits rechecks those claims; changing currency keeps them separate
to avoid relabeling amounts. Retrying a submission does not create a second
claim. Receipt contents are checked by file signature and served as downloads;
the app does not extract receipt text. User/reviewer views share this local
workspace and do not implement accounts or access roles.

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
component takes no props; internal components receive typed API data. Radix
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
.venv/bin/python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
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
