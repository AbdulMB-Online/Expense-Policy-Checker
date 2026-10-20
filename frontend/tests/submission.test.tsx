import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Component from "@/components/ui/saa-s-template";
import { UserExpenseView } from "@/components/user-expense-view";
import type { Claim, Report } from "@/lib/report";
import { alice, fixture, demoReviewer } from "./fixture";

vi.mock("@/lib/report", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/report")>();
  return { ...actual, apiJson: (url: string, options?: RequestInit) => url === "/api/datasets" || url.includes("/history")
    ? Promise.resolve([]) : actual.apiJson(url, options) };
});

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

beforeEach(() => { localStorage.clear(); vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(fixture))); });
afterEach(() => { vi.unstubAllGlobals(); });

async function openForm(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByRole("button", { name: /Alice Morgan/ });
  await user.click(screen.getByRole("button", { name: "User view" }));
  return screen.getByRole("form", { name: "Submit an expense" });
}

async function fillForm(user: ReturnType<typeof userEvent.setup>, amount = "75.00") {
  await user.type(screen.getByLabelText("Employee name"), "Test Employee");
  await user.type(screen.getByLabelText("Amount (USD)"), amount);
  await user.type(screen.getByLabelText("Description"), "Client lunch");
}

describe("expense submission", () => {
  it("submits details and receipt, shows policy reasons, and updates the reviewer report", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockImplementation(async (input) => String(input) === "/api/expenses"
      ? response({ claim: saved, report: updated() }) : response(fixture));
    render(<Component user={demoReviewer} />);
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
    await user.click(screen.getByRole("button", { name: "View reviewer report" }));
    expect(screen.getByRole("button", { name: /Test Employee.*flagged/ })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "View review expense USR-NEW" }));
    expect(within(screen.getByRole("dialog")).getByRole("link", { name: /Download receipt: Lunch receipt.pdf/ })).toHaveAttribute("href", "/api/receipts/USR-NEW");
  });

  it("allows a missing receipt, displays every flag, and submits without a fake attachment field", async () => {
    const user = userEvent.setup();
    const missing = { ...saved, receipt: null, receipt_attached: false, violations: alice.violations };
    vi.mocked(fetch).mockImplementation(async (input) => String(input) === "/api/expenses"
      ? response({ claim: missing, report: updated(missing) }) : response(fixture));
    render(<Component user={demoReviewer} />);
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
    render(<Component user={demoReviewer} />);
    const form = await openForm(user);
    await fillForm(user, "20.00");
    await user.click(within(form).getByRole("button", { name: "Submit expense" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Final review is still required.");
    expect(screen.getByRole("button", { name: "View submitted expense USR-NEW" })).toHaveTextContent("Unflagged by active checks");
    await user.click(screen.getByRole("button", { name: "View reviewer report" }));
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
    render(<Component user={demoReviewer} />);
    const form = await openForm(user);
    await fillForm(user);
    await user.upload(screen.getByLabelText(/Receipt \(optional\)/), new File(["%PDF-"], "Lunch receipt.pdf", { type: "application/pdf" }));
    await user.click(within(form).getByRole("button", { name: "Submit expense" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Storage unavailable");
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
    render(<Component user={demoReviewer} />);
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
    render(<UserExpenseView user={demoReviewer} report={custom} busy={false} onBusy={vi.fn()} onSaved={onSaved} onReview={vi.fn()} onClaim={vi.fn()} />);
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

  it("prevents repeated clicks while saving and retains the draft when changing views", async () => {
    const user = userEvent.setup();
    let finish!: (value: Response) => void;
    vi.mocked(fetch).mockImplementation(async (input) => String(input) === "/api/expenses" ? new Promise<Response>((resolve) => { finish = resolve; }) : response(fixture));
    render(<Component user={demoReviewer} />);
    const form = await openForm(user);
    await fillForm(user);
    await user.click(screen.getByRole("link", { name: "Reviewer view" }));
    await user.click(screen.getByRole("button", { name: "User view" }));
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
    render(<Component user={demoReviewer} />);
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
    render(<Component user={demoReviewer} />);
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
    render(<Component user={demoReviewer} />);
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
