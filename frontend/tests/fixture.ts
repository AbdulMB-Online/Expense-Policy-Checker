import type { Claim, Report } from "@/lib/report";

export const alice: Claim = {
  id: "EXP-005", employee: "Alice Morgan", date: "2026-10-05", category: "meals",
  amount: "75.00", description: "Client lunch", receipt_attached: false, status: "flagged",
  submission_date: "2026-10-05", nights: null, origin: "file", receipt: null,
  violations: [
    { rule_id: "amount_limit", rule_name: "Amount limit", reason: "Amount 75.00 exceeds the meal limit of 50.00." },
    { rule_id: "missing_receipt", rule_name: "Missing receipt", reason: "A receipt is required for this 75.00 meal." },
  ],
};
const jordan: Claim = {
  id: "EXP-004", employee: "Jordan Lee", date: "2026-10-05", category: "transport",
  amount: "40.00", description: "Taxi to client", receipt_attached: false, status: "flagged",
  submission_date: "2026-10-05", nights: null, origin: "file", receipt: null,
  violations: [{ rule_id: "missing_receipt", rule_name: "Missing receipt", reason: "A receipt is required for this taxi." }],
};

export const fixture: Report = {
  generated_at: "2026-10-20T14:00:00Z", currency: "USD",
  dataset_id: null,
  sources: { expenses: "sample_expenses.csv", policy: "policy.json" },
  period: { start: "2026-10-05", end: "2026-10-05" },
  overview: { accepted_count: 2, unflagged_count: 0, flagged_count: 2, violation_count: 3, rejected_count: 1, total_flagged_amount: "115.00" },
  summary: { accepted_count: 2, unflagged_count: 0, flagged_count: 2, violation_count: 3, rejected_count: 1, total_flagged_amount: "115.00" },
  employees: ["Alice Morgan", "Jordan Lee"], claims: [alice, jordan],
  submissions: [],
  groups: {
    employee: [
      { id: "Alice Morgan", name: "Alice Morgan", total_amount: "75.00", claims: [alice] },
      { id: "Jordan Lee", name: "Jordan Lee", total_amount: "40.00", claims: [jordan] },
    ],
    rule: [
      { id: "amount_limit", name: "Amount limit", total_amount: "75.00", claims: [{ ...alice, violations: [alice.violations[0]] }] },
      { id: "missing_receipt", name: "Missing receipt", total_amount: "115.00", claims: [{ ...alice, violations: [alice.violations[1]] }, jordan] },
    ],
  },
  errors: [{ line_number: 12, expense_id: "BAD-001", reasons: ["employee: required field is empty"] }],
  policy: { name: "Expense policy", version: "1.0", categories: { meals: { max_amount: "50.00", limit_basis: "per_expense", receipt: { mode: "above_threshold", threshold: "25.00" } } }, active_rules: ["Amount limit", "Missing receipt"] },
};
