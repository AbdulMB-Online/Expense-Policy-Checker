import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import DemoSession from "@/components/demo-session";
import Component from "@/components/ui/saa-s-template";
import { ExpenseReview } from "@/components/expense-review";
import { alice, fixture, demoReviewer } from "./fixture";

function response(data: unknown, status = 200) { return { ok: status === 200, status, json: async () => data } as Response; }
const employee = { id: "employee-alice", name: "Alice Morgan", role: "employee" as const };

beforeEach(() => { localStorage.clear(); });
afterEach(() => { vi.unstubAllGlobals(); });

it("starts with demo sign-in and keeps employee identity fixed without reviewer controls", async () => {
  const user = userEvent.setup();
  const ownReport = { ...fixture, current_user: employee, claims: [alice], employees: [employee.name], errors: [] };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/session") return response({ detail: "Choose an account" }, 401);
    if (url === "/api/demo/accounts") return response([employee, demoReviewer]);
    if (url === "/api/demo/login") return response(employee);
    if (url === "/api/demo/logout") return response(null);
    if (url === "/api/datasets") return response([]);
    return response(ownReport);
  }));
  render(<DemoSession />);
  await user.click(await screen.findByRole("button", { name: /Alice Morgan.*Employee/ }));
  const identity = await screen.findByLabelText("Employee name");
  expect(identity).toHaveValue("Alice Morgan");
  expect(identity).toHaveAttribute("readonly");
  expect(screen.queryByRole("link", { name: "Reviewer view" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Check selected files" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Switch account" }));
  expect(await screen.findByRole("heading", { name: "Choose a demo account" })).toBeInTheDocument();
});

it("submits individual decisions against the displayed revision and run and shows history", async () => {
  const user = userEvent.setup();
  const onSaved = vi.fn();
  const reviewed = { ...fixture, claims: [{ ...alice, review_status: "approved" }] };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => String(input).includes("/history")
    ? response([{ revision: 1, decision: "changes_requested", comment: "Attach a receipt", reviewer: "Taylor Finance", created_at: "2026-10-20", run_id: "previous" }])
    : response(reviewed)));
  render(<ExpenseReview claim={alice} report={fixture} user={demoReviewer} onSaved={onSaved} />);
  expect(await screen.findByText("Attach a receipt")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Reject expense" })).toBeDisabled();
  await user.type(screen.getByLabelText("Reviewer comment"), "Verified receipt");
  await user.click(screen.getByRole("button", { name: "Approve expense" }));
  await waitFor(() => expect(onSaved).toHaveBeenCalledWith(reviewed));
  expect(fetch).toHaveBeenCalledWith("/api/expenses/EXP-005/review", expect.objectContaining({ method: "POST",
    body: JSON.stringify({ run_id: fixture.run_id, revision_id: alice.revision_id, decision: "approved", comment: "Verified receipt" }) }));
});

it("lets reviewers assign unmatched expenses and keeps stale-review errors visible", async () => {
  const user = userEvent.setup();
  const onSaved = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    if (String(input).includes("/history")) return response([]);
    if (String(input).includes("/accounts")) return response([employee]);
    return response({ detail: "This expense changed. Refresh before reviewing it." }, 409);
  }));
  render(<ExpenseReview claim={{ ...alice, owner_id: null }} report={fixture} user={demoReviewer} onSaved={onSaved} />);
  expect(screen.queryByRole("button", { name: "Approve expense" })).not.toBeInTheDocument();
  await user.selectOptions(await screen.findByLabelText("Employee account"), employee.id);
  await user.click(screen.getByRole("button", { name: "Assign employee" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("This expense changed");
  expect(onSaved).not.toHaveBeenCalled();
});

it("restores a saved dataset and exposes unflagged imported claims for review", async () => {
  const user = userEvent.setup();
  const claim = { ...alice, id: "CLEAN-1", status: "unflagged", violations: [] };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/datasets") return response([{ id: "saved-october", expenses: "October.csv", policy: "Rules.json" }]);
    if (url.includes("/history")) return response([]);
    return response(url.includes("dataset=saved-october") ? { ...fixture, dataset_id: "saved-october", claims: [claim] } : fixture);
  }));
  render(<Component user={demoReviewer} />);
  await screen.findByRole("button", { name: /Alice Morgan.*flagged/ });
  await user.selectOptions(screen.getByLabelText("Saved datasets"), "saved-october");
  await user.click(await screen.findByRole("button", { name: "View review expense CLEAN-1" }));
  expect(within(screen.getByRole("dialog")).getByRole("button", { name: "Approve expense" })).toBeInTheDocument();
  expect(localStorage.getItem(`expense-dataset-${demoReviewer.id}`)).toBe("saved-october");
});

it("resubmits a corrected expense with its revision and an optional replacement receipt", async () => {
  const user = userEvent.setup();
  const onSaved = vi.fn();
  const claim = { ...alice, origin: "submission" as const, review_status: "changes_requested" as const };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => String(input).includes("/history") ? response([]) : response(fixture)));
  render(<ExpenseReview claim={claim} report={fixture} user={employee} onSaved={onSaved} />);
  const form = screen.getByRole("form", { name: "Correct expense" });
  await user.clear(within(form).getByLabelText("Description"));
  await user.type(within(form).getByLabelText("Description"), "Corrected client lunch");
  await user.click(within(form).getByRole("button", { name: "Resubmit expense" }));
  await waitFor(() => expect(onSaved).toHaveBeenCalledWith(fixture));
  const posted = vi.mocked(fetch).mock.calls.find(([, init]) => init?.method === "PUT")![1]?.body as FormData;
  expect(posted.get("revision")).toBe("1");
  expect(posted.get("description")).toBe("Corrected client lunch");
  expect(posted.has("receipt")).toBe(false);
});
