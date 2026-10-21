import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Component from "@/components/ui/saa-s-template";
import { UserExpenseView } from "@/components/user-expense-view";
import { extractReceipt, type Claim, type Report } from "@/lib/report";
import { alice, fixture, demoReviewer } from "./fixture";

vi.mock("@/lib/report", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/report")>();
  return { ...actual, extractReceipt: vi.fn(), apiJson: (url: string, options?: RequestInit) => url === "/api/datasets" || url.includes("/history")
    ? Promise.resolve([]) : actual.apiJson(url, options) };
});

const employee = { id: "employee-test", name: "Test Employee", role: "employee" as const };

const saved: Claim = {
  ...alice, id: "USR-NEW", employee: "Test Employee", origin: "submission", receipt_attached: true,
  receipt: { name: "Lunch receipt.pdf", download_url: "/api/receipts/USR-NEW" },
  violations: [alice.violations[0]],
};

function updated(claim: Claim = saved): Report {
  return { ...fixture, claims: [...fixture.claims, claim], submissions: [claim], employees: [...fixture.employees, claim.employee],
    overview: { ...fixture.overview, accepted_count: 3, flagged_count: claim.status === "flagged" ? 3 : 2 },
    groups: { ...fixture.groups, employee: [...fixture.groups.employee, ...(claim.status === "flagged" ? [{ id: claim.employee, name: claim.employee, total_amount: claim.amount, claims: [claim] }] : [])] },
  };
}

function response(data: unknown) { return { ok: true, json: async () => data } as Response; }

beforeEach(() => {
  localStorage.clear();
  vi.mocked(extractReceipt).mockReset().mockRejectedValue(new Error("Autofill unavailable. Enter details manually."));
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(fixture)));
});
afterEach(() => { vi.unstubAllGlobals(); });

async function openForm(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByLabelText("Employee name");
  return screen.getByRole("form", { name: "Submit an expense" });
}

async function fillForm(user: ReturnType<typeof userEvent.setup>, amount = "75.00") {
  expect(screen.getByLabelText("Employee name")).toHaveValue("Test Employee");
  await user.type(screen.getByLabelText("Amount (USD)"), amount);
  await user.type(screen.getByLabelText("Description"), "Client lunch");
}

describe("expense submission", () => {
  it("fills a receipt-first draft, allows edits, and submits only on explicit review", async () => {
    const user = userEvent.setup();
    vi.mocked(extractReceipt).mockResolvedValue({ merchant: "Joe's Cafe", title: "Lunch at Joe's Cafe", description: "Sandwich and coffee.", date: "2026-10-21", amount: "20.28", currency: "USD", category: "meals", nights: null, warnings: [], model: "grok-4.7" });
    vi.mocked(fetch).mockResolvedValue(response({ claim: saved, report: updated() }));
    render(<UserExpenseView user={employee} report={fixture} busy={false} onBusy={vi.fn()} onSaved={vi.fn()} onClaim={vi.fn()} />);
    const receipt = new File(["image"], "receipt.png", { type: "image/png" });
    await user.upload(screen.getByLabelText(/Receipt \(optional\)/), receipt);
    expect(await screen.findByText(/Receipt read/)).toBeInTheDocument();
    expect(extractReceipt).toHaveBeenCalledWith(receipt, fixture.dataset_id, expect.any(AbortSignal));
    expect(screen.getByLabelText("Description")).toHaveValue("Lunch at Joe's Cafe\nSandwich and coffee.");
    expect(screen.getByLabelText("Amount (USD)")).toHaveValue("20.28");
    expect(screen.getByLabelText("Expense date")).toHaveValue("2026-10-21");
    expect(screen.getByLabelText("Employee name")).toHaveValue("Test Employee");
    expect(fetch).not.toHaveBeenCalled();
    await user.clear(screen.getByLabelText("Description"));
    await user.type(screen.getByLabelText("Description"), "Reviewed lunch receipt");
    await user.click(screen.getByRole("button", { name: "Submit expense" }));
    await screen.findByRole("heading", { name: "Expense submitted" });
    const posted = vi.mocked(fetch).mock.calls[0][1]?.body as FormData;
    expect(posted.get("description")).toBe("Reviewed lunch receipt");
    expect((posted.get("receipt") as File).name).toBe("receipt.png");
  });

  it("keeps manual entries and offers a retry after extraction fails", async () => {
    const user = userEvent.setup();
    render(<UserExpenseView user={employee} report={fixture} busy={false} onBusy={vi.fn()} onSaved={vi.fn()} onClaim={vi.fn()} />);
    await fillForm(user);
    await user.upload(screen.getByLabelText(/Receipt \(optional\)/), new File(["image"], "receipt.png", { type: "image/png" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Autofill unavailable");
    expect(screen.getByLabelText("Description")).toHaveValue("Client lunch");
    expect(screen.getByLabelText("Amount (USD)")).toHaveValue("75.00");
    vi.mocked(extractReceipt).mockResolvedValue({ merchant: "Cafe", title: "Cafe lunch", description: "Coffee", date: "2026-10-20", amount: "9.00", currency: "USD", category: "meals", nights: null, warnings: ["Check the date."], model: "grok-4.7" });
    await user.click(screen.getByRole("button", { name: "Retry autofill" }));
    expect(await screen.findByText("Check the date.")).toBeInTheDocument();
    expect(screen.getByLabelText("Description")).toHaveValue("Client lunch");
    expect(screen.getByLabelText("Amount (USD)")).toHaveValue("75.00");
  });

  it("ignores stale extraction after replacement, removal, and cancellation", async () => {
    const user = userEvent.setup();
    const pending: { resolve: (value: Awaited<ReturnType<typeof extractReceipt>>) => void; signal: AbortSignal }[] = [];
    vi.mocked(extractReceipt).mockImplementation((_file, _dataset, signal) => new Promise((resolve) => pending.push({ resolve, signal })));
    render(<UserExpenseView user={employee} report={fixture} busy={false} onBusy={vi.fn()} onSaved={vi.fn()} onClaim={vi.fn()} />);
    const input = screen.getByLabelText(/Receipt \(optional\)/);
    await user.upload(input, new File(["first"], "first.png", { type: "image/png" }));
    expect(screen.getByRole("button", { name: "Submit expense" })).toBeDisabled();
    expect(screen.getByLabelText("Amount (USD)")).toBeDisabled();
    await user.upload(input, new File(["second"], "second.png", { type: "image/png" }));
    expect(pending[0].signal.aborted).toBe(true);
    await user.click(screen.getByRole("button", { name: "Remove receipt" }));
    expect(pending[1].signal.aborted).toBe(true);
    await act(async () => { for (const item of pending) item.resolve({ merchant: "Old", title: "Stale", description: "Stale", date: null, amount: "99.00", currency: "USD", category: "meals", nights: null, warnings: [], model: "grok-4.7" }); });
    expect(screen.getByLabelText("Description")).toHaveValue("");
    expect(screen.getByLabelText("Amount (USD)")).toHaveValue("");
    expect(screen.queryByText(/Receipt read/)).not.toBeInTheDocument();
    await user.upload(input, new File(["third"], "third.png", { type: "image/png" }));
    await user.click(screen.getByRole("button", { name: "Cancel autofill" }));
    expect(pending[2].signal.aborted).toBe(true);
    expect(screen.getByLabelText("Amount (USD)")).not.toBeDisabled();
    expect((input as HTMLInputElement).files?.[0].name).toBe("third.png");
  });

  it("leaves unknown values blank and requests review instead of keeping default date and category", async () => {
    const user = userEvent.setup();
    vi.mocked(extractReceipt).mockResolvedValue({ merchant: null, title: null, description: null, date: null, amount: null, currency: "EUR", category: null, nights: null, warnings: ["Currency differs from USD. Enter the amount manually."], model: "grok-4.7" });
    render(<UserExpenseView user={employee} report={fixture} busy={false} onBusy={vi.fn()} onSaved={vi.fn()} onClaim={vi.fn()} />);
    await user.upload(screen.getByLabelText(/Receipt \(optional\)/), new File(["image"], "receipt.png", { type: "image/png" }));
    expect(await screen.findByText(/Currency differs/)).toBeInTheDocument();
    expect(screen.getByLabelText("Expense date")).toHaveValue("");
    expect(screen.getByLabelText("Category")).toHaveValue("");
    expect(screen.getByLabelText("Amount (USD)")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Submit expense" })).toBeDisabled();
  });

  it("cancels extraction when the active dataset changes and ignores its late result", async () => {
    const user = userEvent.setup();
    let resolve!: (value: Awaited<ReturnType<typeof extractReceipt>>) => void;
    vi.mocked(extractReceipt).mockImplementation(() => new Promise((done) => { resolve = done; }));
    const props = { user: employee, busy: false, onBusy: vi.fn(), onSaved: vi.fn(), onClaim: vi.fn() };
    const view = render(<UserExpenseView {...props} report={fixture} />);
    await user.upload(screen.getByLabelText(/Receipt \(optional\)/), new File(["image"], "receipt.png", { type: "image/png" }));
    const signal = vi.mocked(extractReceipt).mock.calls[0][2];
    view.rerender(<UserExpenseView {...props} report={{ ...fixture, dataset_id: "new-dataset" }} />);
    expect(signal.aborted).toBe(true);
    expect(screen.getByLabelText("Amount (USD)")).not.toBeDisabled();
    await act(async () => { resolve({ merchant: null, title: "Old receipt", description: null, date: null, amount: "99.00", currency: "USD", category: "meals", nights: null, warnings: [], model: "grok-4.7" }); });
    expect(screen.getByLabelText("Amount (USD)")).toHaveValue("");
  });

  it("submits details and receipt, shows policy reasons, and updates the reviewer report", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockImplementation(async (input) => String(input) === "/api/expenses"
      ? response({ claim: saved, report: updated() }) : response(fixture));
    render(<Component user={employee} />);
    const form = await openForm(user);
    await fillForm(user);
    const receipt = new File(["%PDF-1.4 receipt"], "Lunch receipt.pdf", { type: "application/pdf" });
    await user.upload(screen.getByLabelText(/Receipt \(optional\)/), receipt);
    await user.click(within(form).getByRole("button", { name: "Submit expense" }));
    expect(await screen.findByRole("heading", { name: "Expense submitted" })).toHaveFocus();
    const confirmation = screen.getByRole("status");
    expect(confirmation).toHaveTextContent("Saved with policy flags for review.");
    expect(confirmation).toHaveTextContent(alice.violations[0].reason);
    const posted = vi.mocked(fetch).mock.calls.find(([input]) => input === "/api/expenses")![1]?.body as FormData;
    expect(posted.get("employee")).toBe("Test Employee");
    expect(posted.get("amount")).toBe("75.00");
    expect(posted.get("category")).toBe("meals");
    expect(posted.get("date")).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    expect(posted.get("request_id")).toMatch(/^[\da-f-]{36}$/);
    expect((posted.get("receipt") as File).name).toBe(receipt.name);
    expect(posted.has("receipt_attached")).toBe(false);
    expect(screen.getByLabelText("Amount (USD)")).toHaveValue("");
    cleanup();
    vi.mocked(fetch).mockResolvedValue(response(updated()));
    render(<Component user={demoReviewer} />);
    await user.click(screen.getByRole("tab", { name: "All expenses" }));
    await screen.findByRole("button", { name: "View review expense USR-NEW" });
    await user.click(screen.getByRole("tab", { name: "Claims to review" }));
    expect(screen.getByRole("button", { name: /Test Employee.*flagged/ })).toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "All expenses" }));
    await user.click(screen.getByRole("button", { name: "View review expense USR-NEW" }));
    expect(within(screen.getByRole("dialog")).getByRole("link", { name: /Download receipt: Lunch receipt.pdf/ })).toHaveAttribute("href", "/api/receipts/USR-NEW");
  });

  it("allows a missing receipt, displays every flag, and submits without a fake attachment field", async () => {
    const user = userEvent.setup();
    const missing = { ...saved, receipt: null, receipt_attached: false, violations: alice.violations };
    vi.mocked(fetch).mockImplementation(async (input) => String(input) === "/api/expenses"
      ? response({ claim: missing, report: updated(missing) }) : response(fixture));
    render(<Component user={employee} />);
    const form = await openForm(user);
    await fillForm(user);
    await user.click(within(form).getByRole("button", { name: "Submit expense" }));
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent(alice.violations[0].reason);
    expect(status).toHaveTextContent(alice.violations[1].reason);
    const posted = vi.mocked(fetch).mock.calls.find(([input]) => input === "/api/expenses")![1]?.body as FormData;
    expect(posted.has("receipt")).toBe(false);
  });

  it("keeps unflagged submissions visible in both views without calling them approved", async () => {
    const user = userEvent.setup();
    const clean = { ...saved, amount: "20.00", status: "unflagged" as const, violations: [] };
    vi.mocked(fetch).mockImplementation(async (input) => String(input) === "/api/expenses"
      ? response({ claim: clean, report: updated(clean) }) : response(fixture));
    render(<Component user={employee} />);
    const form = await openForm(user);
    await fillForm(user, "20.00");
    await user.click(within(form).getByRole("button", { name: "Submit expense" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Final review is still required.");
    await user.click(screen.getByRole("tab", { name: "My expenses" }));
    expect(screen.getByRole("button", { name: "View submitted expense USR-NEW" })).toHaveTextContent("No flags");
    cleanup();
    vi.mocked(fetch).mockResolvedValue(response(updated(clean)));
    render(<Component user={demoReviewer} />);
    await user.click(screen.getByRole("tab", { name: "All expenses" }));
    await screen.findByRole("button", { name: "View review expense USR-NEW" });
    expect(screen.getByRole("button", { name: "View review expense USR-NEW" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "View review expense USR-NEW" }));
    expect(within(screen.getByRole("dialog")).getByRole("heading", { name: "No violations detected by active checks" })).toBeInTheDocument();
  });

  it("retains draft and attachment on server errors and reuses the request key for a retry", async () => {
    const user = userEvent.setup();
    let posts = 0;
    vi.mocked(fetch).mockImplementation(async (input) => {
      if (String(input) !== "/api/expenses") return response(fixture);
      posts += 1;
      return posts === 1 ? { ok: false, json: async () => ({ detail: "Storage unavailable. Please retry." }) } as Response : response({ claim: saved, report: updated() });
    });
    render(<Component user={employee} />);
    const form = await openForm(user);
    await fillForm(user);
    await user.upload(screen.getByLabelText(/Receipt \(optional\)/), new File(["%PDF-"], "Lunch receipt.pdf", { type: "application/pdf" }));
    await user.click(within(form).getByRole("button", { name: "Submit expense" }));
    expect(await screen.findByText(/Storage unavailable/)).toBeInTheDocument();
    expect(screen.getByLabelText("Description")).toHaveValue("Client lunch");
    expect((screen.getByLabelText(/Receipt \(optional\)/) as HTMLInputElement).files?.[0].name).toBe("Lunch receipt.pdf");
    await user.click(within(form).getByRole("button", { name: "Submit expense" }));
    await screen.findByRole("heading", { name: "Expense submitted" });
    const requests = vi.mocked(fetch).mock.calls.filter(([input]) => input === "/api/expenses");
    expect((requests[0][1]?.body as FormData).get("request_id")).toBe((requests[1][1]?.body as FormData).get("request_id"));
  });

  it("shows field-specific validation and keeps the entered values", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockImplementation(async (input) => String(input) === "/api/expenses"
      ? { ok: false, json: async () => ({ detail: { message: "Correct the amount.", fields: { amount: "Expected a nonnegative decimal." } } }) } as Response : response(fixture));
    render(<Component user={employee} />);
    const form = await openForm(user);
    await fillForm(user);
    await user.click(within(form).getByRole("button", { name: "Submit expense" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Correct the amount.");
    expect(screen.getByLabelText("Amount (USD)")).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByLabelText("Amount (USD)")).toHaveAccessibleDescription("Expected a nonnegative decimal.");
    expect(screen.getByLabelText("Amount (USD)")).toHaveFocus();
    expect(screen.getByLabelText("Amount (USD)")).toHaveValue("75.00");
  });

  it("requires hotel nights and submits them with the active dataset", async () => {
    const user = userEvent.setup();
    const custom: Report = { ...fixture, dataset_id: "custom-source", policy: { ...fixture.policy, categories: { ...fixture.policy.categories, hotel: { max_amount: "200.00", limit_basis: "per_night", nights_required: true, receipt: { mode: "always" } } } } };
    const onSaved = vi.fn();
    vi.mocked(fetch).mockResolvedValue(response({ claim: saved, report: custom }));
    render(<UserExpenseView user={employee} report={custom} busy={false} onBusy={vi.fn()} onSaved={onSaved} onClaim={vi.fn()} />);
    await waitFor(() => expect(screen.getByLabelText("Category")).toHaveValue("meals"));
    await fillForm(user, "400.00");
    await user.selectOptions(screen.getByLabelText("Category"), "hotel");
    const nights = screen.getByLabelText("Number of nights");
    expect(nights).toBeRequired();
    await user.click(screen.getByRole("button", { name: "Submit expense" }));
    expect(fetch).not.toHaveBeenCalled();
    await user.type(nights, "2");
    await user.click(screen.getByRole("button", { name: "Submit expense" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(custom));
    const files = vi.mocked(fetch).mock.calls[0][1]?.body as FormData;
    expect(files.get("nights")).toBe("2");
    expect(files.get("dataset")).toBe("custom-source");
  });

  it("prevents repeated clicks while saving and retains the employee draft", async () => {
    const user = userEvent.setup();
    let finish!: (value: Response) => void;
    vi.mocked(fetch).mockImplementation(async (input) => String(input) === "/api/expenses" ? new Promise<Response>((resolve) => { finish = resolve; }) : response(fixture));
    render(<Component user={employee} />);
    const form = await openForm(user);
    await fillForm(user);
    expect(screen.queryByRole("link", { name: "Expense review" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("Description")).toHaveValue("Client lunch");
    await user.click(within(form).getByRole("button", { name: "Submit expense" }));
    expect(within(form).getByRole("button", { name: "Submitting…" })).toBeDisabled();
    expect(screen.getByLabelText("Employee name")).toBeDisabled();
    await user.click(within(form).getByRole("button", { name: "Submitting…" }));
    expect(vi.mocked(fetch).mock.calls.filter(([input]) => input === "/api/expenses")).toHaveLength(1);
    await act(async () => { finish(response({ claim: saved, report: updated() })); });
    expect(await screen.findByRole("heading", { name: "Expense submitted" })).toBeInTheDocument();
  });

  it("can remove a receipt and rejects oversized files before posting", async () => {
    const user = userEvent.setup();
    render(<Component user={employee} />);
    const form = await openForm(user);
    await fillForm(user);
    const input = screen.getByLabelText(/Receipt \(optional\)/);
    await user.upload(input, new File(["%PDF-"], "Receipt.pdf", { type: "application/pdf" }));
    await user.click(screen.getByRole("button", { name: "Remove receipt" }));
    expect((input as HTMLInputElement).files).toHaveLength(0);
    await user.upload(input, new File([new Uint8Array(5 * 1024 * 1024 + 1)], "Large.pdf", { type: "application/pdf" }));
    await user.click(within(form).getByRole("button", { name: "Submit expense" }));
    expect(screen.getByText("Receipt must be 5 MiB or smaller.")).toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.some(([url]) => url === "/api/expenses")).toBe(false);
  });

  it("native required fields prevent an empty submission", async () => {
    const user = userEvent.setup();
    render(<Component user={employee} />);
    const form = await openForm(user);
    await user.click(within(form).getByRole("button", { name: "Submit expense" }));
    expect(vi.mocked(fetch).mock.calls.some(([url]) => url === "/api/expenses")).toBe(false);
    fireEvent.change(screen.getByLabelText("Expense date"), { target: { value: "2026-10-10" } });
    expect(screen.getByLabelText("Expense date")).toHaveValue("2026-10-10");
  });

  it("offers a new draft after a request key conflict", async () => {
    const user = userEvent.setup();
    let posts = 0;
    vi.mocked(fetch).mockImplementation(async (input) => {
      if (String(input) !== "/api/expenses") return response(fixture);
      posts += 1;
      return posts === 1 ? { ok: false, status: 409, json: async () => ({ detail: "This submission was already saved with different details. Start a new expense." }) } as Response : response({ claim: saved, report: updated() });
    });
    render(<Component user={employee} />);
    const form = await openForm(user);
    await fillForm(user);
    await user.click(within(form).getByRole("button", { name: "Submit expense" }));
    await user.click(await screen.findByRole("button", { name: "Start a new expense" }));
    expect(screen.getByLabelText("Employee name")).toHaveValue("Test Employee");
    expect(screen.getByLabelText("Description")).toHaveValue("");
    await user.type(screen.getByLabelText("Amount (USD)"), "75.00");
    await user.type(screen.getByLabelText("Description"), "New client lunch");
    await user.click(within(form).getByRole("button", { name: "Submit expense" }));
    await screen.findByRole("heading", { name: "Expense submitted" });
    const requests = vi.mocked(fetch).mock.calls.filter(([input]) => input === "/api/expenses");
    expect((requests[0][1]?.body as FormData).get("request_id")).not.toBe((requests[1][1]?.body as FormData).get("request_id"));
  });
});

it("keeps an employee draft and receipt when switching to expense history", async () => {
  const user = userEvent.setup();
  render(<Component user={employee} />);
  await openForm(user);
  await fillForm(user);
  await user.upload(screen.getByLabelText(/Receipt \(optional\)/), new File(["%PDF-"], "Draft receipt.pdf", { type: "application/pdf" }));
  await user.click(screen.getByRole("tab", { name: "My expenses" }));
  expect(screen.queryByRole("form", { name: "Submit an expense" })).not.toBeInTheDocument();
  expect(screen.getByRole("region", { name: "Submitted expenses" })).toBeVisible();
  await user.click(screen.getByRole("tab", { name: "Submit expense" }));
  expect(screen.getByLabelText("Description")).toHaveValue("Client lunch");
  expect(screen.getByLabelText("Amount (USD)")).toHaveValue("75.00");
  expect((screen.getByLabelText(/Receipt \(optional\)/) as HTMLInputElement).files?.[0].name).toBe("Draft receipt.pdf");
});
