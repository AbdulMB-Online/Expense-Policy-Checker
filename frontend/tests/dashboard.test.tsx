import { render, screen, within, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import Component from "@/components/ui/saa-s-template";
import { money } from "@/lib/report";
import { alice, fixture, demoReviewer } from "./fixture";

vi.mock("@/lib/report", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/report")>();
  return { ...actual, apiJson: (url: string, options?: RequestInit) => url === "/api/datasets" || url.includes("/history")
    ? Promise.resolve([]) : actual.apiJson(url, options) };
});

function response(data: unknown = fixture) { return { ok: true, json: async () => data }; }

beforeEach(() => { localStorage.clear(); vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response())); });
afterEach(() => { vi.unstubAllGlobals(); });

describe("dashboard", () => {
  it("loads real API data and shows employee groups", async () => {
    render(<Component user={demoReviewer} />);
    await userEvent.click(screen.getByRole("tab", { name: "Claims to review" }));
    expect(await screen.findByRole("button", { name: /Alice Morgan/ })).toBeInTheDocument();
    expect(screen.getByText("Claims checked")).toBeInTheDocument();
    expect(screen.getByText("Claims checked")).not.toBeVisible();
    expect(screen.queryByRole("form", { name: "Submit an expense" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "User view" })).not.toBeInTheDocument();
    expect(screen.getAllByText("$115.00").length).toBeGreaterThan(0);
    expect(fetch).toHaveBeenCalledWith("/api/report?", expect.objectContaining({ signal: expect.any(AbortSignal) }));
  });

  it("switches to rules and shows every reason in the claim dialog", async () => {
    const user = userEvent.setup();
    render(<Component user={demoReviewer} />);
    await userEvent.click(screen.getByRole("tab", { name: "Claims to review" }));
    await screen.findByRole("button", { name: /Alice Morgan/ });
    await user.click(screen.getByRole("tab", { name: "By policy rule" }));
    await user.click(screen.getAllByRole("button", { name: "View expense EXP-005" })[0]);
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(alice.violations[0].reason)).toBeInTheDocument();
    expect(within(dialog).getByText(alice.violations[1].reason)).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("requests employee and debounced search filters", async () => {
    const user = userEvent.setup();
    render(<Component user={demoReviewer} />);
    await userEvent.click(screen.getByRole("tab", { name: "Claims to review" }));
    await screen.findByRole("button", { name: /Alice Morgan/ });
    await user.selectOptions(screen.getByLabelText("Filter by employee"), "Alice Morgan");
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("employee=Alice+Morgan"), expect.anything()));
    await user.type(screen.getByLabelText("Search claims"), "EXP-005");
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("search=EXP-005"), expect.anything()));
  });

  it("expands rejected rows and policy details", async () => {
    const user = userEvent.setup();
    render(<Component user={demoReviewer} />);
    await userEvent.click(screen.getByRole("tab", { name: "Claims to review" }));
    await screen.findByRole("button", { name: /Alice Morgan/ });
    await user.click(screen.getByRole("tab", { name: "Input issues" }));
    expect(screen.getByRole("button", { name: /A few records need fixing/ })).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("employee: required field is empty")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "View active policy" }));
    expect(screen.getByRole("heading", { name: "Expense policy" })).toBeInTheDocument();
    expect(screen.getByText("$50.00 / claim")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows API errors and retries successfully", async () => {
    vi.mocked(fetch).mockRejectedValueOnce(new Error("API offline"));
    const user = userEvent.setup();
    render(<Component user={demoReviewer} />);
    await userEvent.click(screen.getByRole("tab", { name: "Claims to review" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("API offline");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("button", { name: /Alice Morgan/ })).toBeInTheDocument();
  });

  it("shows an empty search result without inventing claims", async () => {
    vi.mocked(fetch).mockResolvedValue(response({ ...fixture, summary: { ...fixture.summary, flagged_count: 0 }, groups: { employee: [], rule: [] } }) as Response);
    render(<Component user={demoReviewer} />);
    await userEvent.click(screen.getByRole("tab", { name: "Claims to review" }));
    expect(await screen.findByText("No flags from the active checks")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "View expense EXP-005" })).not.toBeInTheDocument();
  });

  it("exports a report as a real download", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("URL", class extends URL {
      static createObjectURL = vi.fn(() => "blob:report");
      static revokeObjectURL = vi.fn();
    });
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    vi.mocked(fetch).mockImplementation(async (input) => String(input).includes("/download")
      ? { ok: true, blob: async () => new Blob(["Expense report"]) } as Response
      : response() as Response);
    render(<Component user={demoReviewer} />);
    await userEvent.click(screen.getByRole("tab", { name: "Claims to review" }));
    await screen.findByRole("button", { name: /Alice Morgan/ });
    await user.click(screen.getByRole("button", { name: "Export report" }));
    await waitFor(() => expect(clicked).toHaveBeenCalled());
    expect(fetch).toHaveBeenCalledWith("/api/report/download?group_by=employee");
  });

  it("collapses groups and restores the claim rows", async () => {
    const user = userEvent.setup();
    render(<Component user={demoReviewer} />);
    await userEvent.click(screen.getByRole("tab", { name: "Claims to review" }));
    const group = await screen.findByRole("button", { name: /Alice Morgan/ });
    await user.click(group);
    expect(group).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: "View expense EXP-005" })).not.toBeInTheDocument();
    await user.click(group);
    expect(screen.getByRole("button", { name: "View expense EXP-005" })).toBeInTheDocument();
  });

  it("opens the responsive navigation and closes it after a destination", async () => {
    const user = userEvent.setup();
    render(<Component user={demoReviewer} />);
    await userEvent.click(screen.getByRole("tab", { name: "Claims to review" }));
    await screen.findByRole("button", { name: /Alice Morgan/ });
    await user.click(screen.getByRole("button", { name: "Open menu" }));
    expect(screen.getByRole("button", { name: "Close menu" })).toHaveAttribute("aria-expanded", "true");
    await user.click(screen.getByRole("button", { name: "Import files" }));
    expect(screen.getByRole("button", { name: "Open menu" })).toHaveAttribute("aria-expanded", "false");
  });

  it("shows all remaining claims in a longer group", async () => {
    const user = userEvent.setup();
    const claims = Array.from({ length: 6 }, (_, index) => ({ ...alice, id: `LONG-${index}` }));
    vi.mocked(fetch).mockResolvedValue(response({
      ...fixture,
      groups: { ...fixture.groups, employee: [{ id: "Alice Morgan", name: "Alice Morgan", total_amount: "450.00", claims }] },
      claims,
    }) as Response);
    render(<Component user={demoReviewer} />);
    await userEvent.click(screen.getByRole("tab", { name: "Claims to review" }));
    await screen.findByRole("button", { name: /Alice Morgan/ });
    expect(screen.queryByRole("button", { name: "View expense LONG-5" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Show 2 more claims" }));
    expect(screen.getByRole("button", { name: "View expense LONG-5" })).toBeInTheDocument();
  });

  it("uploads custom names and keeps that source for filters, refresh, export, and sample reset", async () => {
    const user = userEvent.setup();
    const uploaded = { ...fixture, dataset_id: "review-token", sources: { expenses: "October claims.csv", policy: "Finance rules 2026.json" } };
    vi.stubGlobal("URL", class extends URL {
      static createObjectURL = vi.fn(() => "blob:report");
      static revokeObjectURL = vi.fn();
    });
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    vi.mocked(fetch).mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/download")) return { ok: true, blob: async () => new Blob(["Uploaded report"]) } as Response;
      return response(url.includes("/upload") || url.includes("dataset=review-token") ? uploaded : fixture) as Response;
    });
    render(<Component user={demoReviewer} />);
    await userEvent.click(screen.getByRole("tab", { name: "Claims to review" }));
    await screen.findByRole("button", { name: /Alice Morgan/ });
    await user.click(screen.getByRole("tab", { name: "Import files" }));
    expect(screen.getByRole("button", { name: "Check selected files" })).toBeDisabled();
    await user.upload(screen.getByLabelText(/Expense CSV/), new File(["claims"], "October claims.csv", { type: "text/csv" }));
    await user.upload(screen.getByLabelText(/Policy JSON/), new File(["{}"], "Finance rules 2026.json", { type: "application/json" }));
    await user.click(screen.getByRole("button", { name: "Check selected files" }));
    expect(await screen.findByText("Uploaded files active")).toBeInTheDocument();
    expect(screen.getByText("Active: Finance rules 2026.json")).toBeInTheDocument();
    const posted = vi.mocked(fetch).mock.calls.find(([input]) => input === "/api/report/upload")!;
    const files = posted[1]?.body as FormData;
    expect((files.get("expenses") as File).name).toBe("October claims.csv");
    expect((files.get("policy") as File).name).toBe("Finance rules 2026.json");
    await user.click(screen.getByRole("tab", { name: "Overview" }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Refresh report/ })).toBeEnabled());
    await user.click(screen.getByRole("tab", { name: "Claims to review" }));
    await user.selectOptions(screen.getByLabelText("Filter by employee"), "Alice Morgan");
    await user.type(screen.getByLabelText("Search claims"), "EXP-005");
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/report?employee=Alice+Morgan&search=EXP-005&dataset=review-token", expect.anything()));
    await user.click(screen.getByRole("tab", { name: "Overview" }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Refresh report/ })).toBeEnabled());
    const calls = vi.mocked(fetch).mock.calls.length;
    await user.click(screen.getByRole("button", { name: /Refresh report/ }));
    await waitFor(() => expect(vi.mocked(fetch).mock.calls.length).toBeGreaterThan(calls));
    await user.click(screen.getByRole("tab", { name: "Claims to review" }));
    await user.click(screen.getByRole("tab", { name: "By policy rule" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Export report" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Export report" }));
    expect(fetch).toHaveBeenCalledWith("/api/report/download?employee=Alice+Morgan&search=EXP-005&dataset=review-token&group_by=rule");
    await user.click(screen.getByRole("tab", { name: "Import files" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Use sample files" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Use sample files" }));
    expect(await screen.findByText("Stored sample files")).toBeInTheDocument();
    expect(screen.getByLabelText("Search claims")).toHaveValue("");
    expect(screen.getByLabelText("Filter by employee")).toHaveValue("");
    expect(vi.mocked(fetch).mock.calls.at(-1)?.[0]).toBe("/api/report?");
  });

  it("can replace only the policy and then sends its active context with another upload", async () => {
    const user = userEvent.setup();
    const uploaded = { ...fixture, dataset_id: "policy-context", sources: { ...fixture.sources, policy: "New limits.json" } };
    vi.mocked(fetch).mockImplementation(async (input) => response(String(input).includes("/upload") || String(input).includes("dataset=") ? uploaded : fixture) as Response);
    render(<Component user={demoReviewer} />);
    await userEvent.click(screen.getByRole("tab", { name: "Claims to review" }));
    await screen.findByRole("button", { name: /Alice Morgan/ });
    await user.click(screen.getByRole("tab", { name: "Import files" }));
    await user.upload(screen.getByLabelText(/Policy JSON/), new File(["{}"], "New limits.json", { type: "application/json" }));
    await user.click(screen.getByRole("button", { name: "Check selected files" }));
    await screen.findByText("Uploaded files active");
    const posted = vi.mocked(fetch).mock.calls.find(([input]) => input === "/api/report/upload")!;
    expect((posted[1]?.body as FormData).has("expenses")).toBe(false);
    await waitFor(() => expect(screen.getByLabelText(/Expense CSV/)).toBeEnabled());
    await user.upload(screen.getByLabelText(/Expense CSV/), new File(["data"], "Replacement.csv", { type: "text/csv" }));
    await user.click(screen.getByRole("button", { name: "Check selected files" }));
    const posts = vi.mocked(fetch).mock.calls.filter(([input]) => input === "/api/report/upload");
    expect((posts[1][1]?.body as FormData).get("dataset")).toBe("policy-context");
    expect((posts[1][1]?.body as FormData).has("policy")).toBe(false);
  });

  it("keeps the report and selected files when upload validation fails", async () => {
    const user = userEvent.setup();
    vi.mocked(fetch).mockImplementation(async (input) => String(input).includes("/upload")
      ? { ok: false, json: async () => ({ detail: "Bad.json: missing categories" }) } as Response : response() as Response);
    render(<Component user={demoReviewer} />);
    await userEvent.click(screen.getByRole("tab", { name: "Claims to review" }));
    await screen.findByRole("button", { name: /Alice Morgan/ });
    await user.click(screen.getByRole("tab", { name: "Import files" }));
    await user.upload(screen.getByLabelText(/Policy JSON/), new File(["{}"], "Bad.json", { type: "application/json" }));
    await user.click(screen.getByRole("button", { name: "Check selected files" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Bad.json: missing categories");
    expect(screen.queryByRole("button", { name: /Alice Morgan/ })).not.toBeInTheDocument();
    expect(screen.getByText("Stored sample files")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check selected files" })).toBeEnabled();
    expect((screen.getByLabelText(/Policy JSON/) as HTMLInputElement).files?.[0].name).toBe("Bad.json");
  });
});

it("formats large monetary strings without losing cents", () => {
  expect(money("999999999999999999999999999999.99", "USD")).toBe("$999,999,999,999,999,999,999,999,999,999.99");
  expect(money("0.10", "EUR")).toBe("€0.10");
});

it("separates workspace panels and keeps sidebar, summary action, and keyboard tabs in sync", async () => {
  const user = userEvent.setup();
  render(<Component user={demoReviewer} />);
  await screen.findByText("Claims checked");
  expect(screen.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
  expect(screen.queryByRole("button", { name: "Export report" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Check selected files" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /Review flagged claims/ }));
  expect(screen.getByRole("tab", { name: "Claims to review" })).toHaveAttribute("aria-selected", "true");
  expect(screen.getByRole("button", { name: "Claims to review" })).toHaveAttribute("aria-current", "page");
  await user.selectOptions(screen.getByLabelText("Filter by employee"), "Alice Morgan");
  await user.click(screen.getByRole("button", { name: "Import files" }));
  const file = new File(["claims"], "Draft.csv", { type: "text/csv" });
  await user.upload(screen.getByLabelText(/Expense CSV/), file);
  screen.getByRole("tab", { name: "Import files" }).focus();
  await user.keyboard("{ArrowRight}");
  expect(screen.getByRole("tab", { name: "Input issues" })).toHaveAttribute("aria-selected", "true");
  expect(screen.queryByRole("button", { name: "Check selected files" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("tab", { name: "Import files" }));
  expect((screen.getByLabelText(/Expense CSV/) as HTMLInputElement).files?.[0].name).toBe("Draft.csv");
  await user.click(screen.getByRole("tab", { name: "Claims to review" }));
  expect(screen.getByLabelText("Filter by employee")).toHaveValue("Alice Morgan");
});
