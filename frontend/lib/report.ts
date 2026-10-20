export type Grouping = "employee" | "rule";
export interface Violation { rule_id: string; rule_name: string; reason: string }
export interface Claim {
  id: string; employee: string; date: string; category: string; amount: string;
  description: string; receipt_attached: boolean; status: "flagged" | "unflagged";
  violations: Violation[];
  submission_date: string; nights: number | null; origin: "file" | "submission";
  receipt: { name: string; download_url: string } | null;
}
export interface ReportGroup { id: string; name: string; total_amount: string; claims: Claim[] }
export interface Summary {
  accepted_count: number; unflagged_count: number; flagged_count: number;
  violation_count: number; rejected_count: number; total_flagged_amount: string;
}
export interface CategoryPolicy {
  max_amount: string | null; limit_basis: string;
  receipt: { mode: string; threshold?: string };
  nights_required?: boolean;
}
export interface Report {
  generated_at: string; currency: string;
  dataset_id: string | null;
  sources: { expenses: string; policy: string };
  period: { start: string; end: string } | null;
  overview: Summary; summary: Summary; employees: string[]; claims: Claim[];
  submissions: Claim[];
  groups: Record<Grouping, ReportGroup[]>;
  errors: { line_number: number; expense_id: string | null; reasons: string[] }[];
  policy: { name: string; version: string; categories: Record<string, CategoryPolicy>; active_rules: string[] };
}

/** Format API decimal strings without converting monetary values to floats. */
export function money(amount: string, currency: string) {
  const [whole, fraction = "00"] = amount.split(".");
  const integer = new Intl.NumberFormat("en-US").format(BigInt(whole));
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).formatToParts(0)
    .map((part) => part.type === "integer" ? integer : part.type === "fraction" ? fraction.padEnd(2, "0") : part.value)
    .join("");
}

export function dateLabel(date: string) {
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" })
    .format(new Date(`${date}T00:00:00Z`));
}

export function categoryLabel(category: string) {
  return category.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function reportQuery(employee: string, search: string, dataset?: string | null) {
  const query = new URLSearchParams();
  if (employee) query.set("employee", employee);
  if (search.trim()) query.set("search", search.trim());
  if (dataset) query.set("dataset", dataset);
  return query;
}

async function parseReport(response: Response): Promise<Report> {
  if (!response.ok) {
    const problem = await response.json().catch(() => ({}));
    throw new Error(typeof problem.detail === "string" ? problem.detail : "The report could not be loaded. Please try again.");
  }
  return response.json();
}

export async function readReport(employee: string, search: string, signal?: AbortSignal, dataset?: string | null): Promise<Report> {
  return parseReport(await fetch(`/api/report?${reportQuery(employee, search, dataset)}`, { signal }));
}

export async function uploadReport(expenses: File | null, policy: File | null, dataset: string | null): Promise<Report> {
  const files = new FormData();
  if (expenses) files.append("expenses", expenses);
  if (policy) files.append("policy", policy);
  if (dataset) files.append("dataset", dataset);
  return parseReport(await fetch("/api/report/upload", { method: "POST", body: files }));
}

export class ExpenseSubmissionError extends Error {
  constructor(message: string, public fields: Record<string, string> = {}, public status?: number) { super(message); }
}

export async function submitExpense(files: FormData): Promise<{ claim: Claim; report: Report }> {
  const response = await fetch("/api/expenses", { method: "POST", body: files });
  if (!response.ok) {
    const problem = await response.json().catch(() => ({}));
    if (typeof problem.detail === "string") throw new ExpenseSubmissionError(problem.detail, {}, response.status);
    if (Array.isArray(problem.detail)) {
      const fields = Object.fromEntries(problem.detail.map((issue: { loc: string[]; msg: string }) => [issue.loc.at(-1), issue.msg]));
      throw new ExpenseSubmissionError("Please correct the highlighted expense details.", fields, response.status);
    }
    throw new ExpenseSubmissionError(problem.detail?.message ?? "The expense could not be submitted. Please retry.", problem.detail?.fields, response.status);
  }
  return response.json();
}
