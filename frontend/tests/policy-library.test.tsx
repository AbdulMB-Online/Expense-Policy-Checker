import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { PolicyLibrary, type PolicyConfig } from "@/components/policy-library";
import { ThemeToggle } from "@/components/theme-toggle";
import { fixture } from "./fixture";

const config: PolicyConfig = {
  name: "Office policy", version: "1.0", currency: "USD", categories: fixture.policy.categories,
  restricted_categories: ["alcohol"], unknown_category_action: "review_required",
  submission: { max_days_after_expense: 30, inclusive: true },
  duplicates: { key_fields: ["employee", "date", "amount"], require_different_ids: true, flag: "all_matches", classification: "suspected_duplicate" },
  reporting: { collect_all_violations: true, flagged_amount_counting: "once_per_expense" },
};
const saved = { id: "office", config };
const travel = { id: "travel", config: { ...config, name: "Travel policy" } };
function response(data: unknown) { return { ok: true, json: async () => data } as Response; }
beforeEach(() => { vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response([saved, travel]))); });
afterEach(() => { vi.unstubAllGlobals(); document.documentElement.classList.remove("dark"); localStorage.clear(); });

it("selects a saved policy and applies it to the current expense dataset", async () => {
  const user = userEvent.setup(); const onReport = vi.fn(); const close = vi.fn();
  vi.mocked(fetch).mockImplementation(async (input) => String(input) === "/api/report/upload" ? response(fixture) : response([saved, travel]));
  render(<PolicyLibrary open close={close} report={{ ...fixture, dataset_id: "custom-data", policy: { ...fixture.policy, id: saved.id } }} onReport={onReport} onBusy={vi.fn()} />);
  await screen.findByLabelText("Saved policy");
  expect(screen.getByRole("button", { name: "Use policy" })).toBeDisabled();
  await user.selectOptions(screen.getByLabelText("Saved policy"), travel.id);
  await user.click(screen.getByRole("button", { name: "Use policy" }));
  await waitFor(() => expect(onReport).toHaveBeenCalledWith(fixture));
  const body = vi.mocked(fetch).mock.calls.find(([url]) => url === "/api/report/upload")![1]!.body as FormData;
  expect(body.get("dataset")).toBe("custom-data");
  expect(body.has("expenses")).toBe(false);
  expect((body.get("policy") as File).name).toBe("Travel_policy.json");
  expect(close).toHaveBeenCalled();
});

it("creates category rules, saves them in the library, and leaves application explicit", async () => {
  const user = userEvent.setup(); const onReport = vi.fn(); let posted: PolicyConfig | undefined;
  vi.mocked(fetch).mockImplementation(async (input, options) => {
    if (options?.method === "POST") {
      const file = (options.body as FormData).get("policy") as File;
      const content = await new Promise<string>((resolve) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.readAsText(file); });
      posted = JSON.parse(content);
      return response({ id: "new-policy", config: posted });
    }
    return response([saved]);
  });
  render(<PolicyLibrary open close={vi.fn()} report={fixture} onReport={onReport} onBusy={vi.fn()} />);
  await user.click(await screen.findByRole("button", { name: "New policy" }));
  await user.type(screen.getByLabelText("Policy name"), "Team travel");
  await user.clear(screen.getByLabelText("Meals amount limit"));
  await user.type(screen.getByLabelText("Meals amount limit"), "80.00");
  await user.type(screen.getByLabelText("New category"), "Training");
  await user.click(screen.getByRole("button", { name: "Add category" }));
  await user.type(screen.getByLabelText("Training amount limit"), "500.00");
  await user.clear(screen.getByLabelText("Restricted categories"));
  await user.type(screen.getByLabelText("Restricted categories"), "alcohol, personal");
  await user.click(screen.getByRole("button", { name: "Save policy" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Policy saved");
  expect(posted?.categories.meals.max_amount).toBe("80.00");
  expect(posted?.categories.training.max_amount).toBe("500.00");
  expect(posted?.restricted_categories).toEqual(["alcohol", "personal"]);
  expect(screen.getByLabelText("Saved policy")).toHaveValue("new-policy");
  expect(onReport).not.toHaveBeenCalled();
});

it("keeps a policy draft after server validation fails", async () => {
  const user = userEvent.setup();
  vi.mocked(fetch).mockImplementation(async (_, options) => options?.method === "POST"
    ? { ok: false, json: async () => ({ detail: "Invalid policy category" }) } as Response : response([saved]));
  render(<PolicyLibrary open close={vi.fn()} report={fixture} onReport={vi.fn()} onBusy={vi.fn()} />);
  await user.click(await screen.findByRole("button", { name: "New policy" }));
  await user.type(screen.getByLabelText("Policy name"), "My draft");
  await user.click(screen.getByRole("button", { name: "Save policy" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Invalid policy category");
  expect(screen.getByLabelText("Policy name")).toHaveValue("My draft");
});

it("remembers a theme change when moving between sign-in and the workspace", async () => {
  document.documentElement.classList.add("dark");
  const user = userEvent.setup();
  const first = render(<ThemeToggle />);
  await user.click(screen.getByRole("button", { name: "Switch to light mode" }));
  expect(document.documentElement).not.toHaveClass("dark");
  expect(localStorage.getItem("expense-theme")).toBe("light");
  first.unmount(); render(<ThemeToggle />);
  await user.click(screen.getByRole("button", { name: "Switch to dark mode" }));
  expect(document.documentElement).toHaveClass("dark");
  expect(localStorage.getItem("expense-theme")).toBe("dark");
});
