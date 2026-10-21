import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { ReportAssistant } from "@/components/report-assistant";
import { fixture } from "./fixture";

const response = (data: unknown, ok = true) => ({ ok, json: async () => data });
afterEach(() => vi.unstubAllGlobals());
function setup(available = true) {
  const fetcher = vi.fn().mockImplementation((url: string) => Promise.resolve(response(url.includes("status") ? { available, message: "Add OPENAI_API_KEY and restart the server." } : url.includes("/chat") ? { answer: "Review [EXP-005].", references: ["EXP-005"] } : fixture)));
  vi.stubGlobal("fetch", fetcher);
  const onClaim = vi.fn();
  const view = render(<ReportAssistant report={fixture} employee="Alice Morgan" search="" onClaim={onClaim} />);
  return { fetcher, onClaim, user: userEvent.setup(), ...view };
}
it("shows setup instructions and disables sending without a key", async () => {
  const { user } = setup(false);
  await user.click(screen.getByText("Ask about this report"));
  expect(await screen.findByText(/Add OPENAI_API_KEY/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Send question" })).toBeDisabled();
});
it("sends questions, follows up, and opens referenced claims", async () => {
  const { user, fetcher, onClaim } = setup();
  await user.click(screen.getByText("Ask about this report"));
  await screen.findByText(/Questions and report data/);
  await user.type(screen.getByLabelText("Your question"), "Why flagged?");
  await user.click(screen.getByText("Send question"));
  await screen.findByText("Review [EXP-005].");
  await waitFor(() => expect(screen.getByLabelText("Your question")).toBeEnabled());
  await user.type(screen.getByLabelText("Your question"), "What next?");
  await user.click(screen.getByText("Send question"));
  await waitFor(() => expect(screen.getAllByText("Review [EXP-005].")).toHaveLength(2));
  const calls = fetcher.mock.calls.filter(([url]) => url === "/api/assistant/chat");
  expect(JSON.parse(calls[1][1].body).messages).toHaveLength(3);
  await user.click(screen.getAllByText("View EXP-005")[0]);
  expect(onClaim).toHaveBeenCalledWith(expect.objectContaining({ id: "EXP-005" }));
});
it("passes current filters and resets conversation on scope changes", async () => {
  const { user, fetcher } = setup();
  await user.click(screen.getByText("Ask about this report"));
  await user.selectOptions(screen.getByLabelText("Chat report scope"), "filtered");
  await screen.findByText(/Questions and report data/);
  await user.click(screen.getByText("What should I review first, and why?"));
  await screen.findByText("Review [EXP-005].");
  const call = fetcher.mock.calls.find(([url]) => url === "/api/assistant/chat")!;
  expect(JSON.parse(call[1].body).employee).toBe("Alice Morgan");
  await user.selectOptions(screen.getByLabelText("Chat report scope"), "all");
  expect(screen.queryByText("Review [EXP-005].")).not.toBeInTheDocument();
});
it("retains failed question for retry without adding fabricated answers", async () => {
  const { user, fetcher } = setup();
  await user.click(screen.getByText("Ask about this report"));
  await screen.findByText(/Questions and report data/);
  fetcher.mockResolvedValueOnce(response({ detail: "Usage limit reached" }, false));
  await user.type(screen.getByLabelText("Your question"), "Compare employees");
  await user.click(screen.getByText("Send question"));
  expect(await screen.findByRole("alert")).toHaveTextContent("Usage limit reached");
  expect(screen.getByLabelText("Your question")).toHaveValue("Compare employees");
});
it("stops a pending request and ignores a late answer", async () => {
  const { user, fetcher } = setup();
  await user.click(screen.getByText("Ask about this report"));
  await screen.findByText(/Questions and report data/);
  let resolve!: (value: unknown) => void;
  fetcher.mockReturnValueOnce(new Promise(r => { resolve = r; }));
  await user.type(screen.getByLabelText("Your question"), "Explain");
  await user.click(screen.getByText("Send question"));
  await user.click(screen.getByText("Stop"));
  resolve(response({ answer: "Late answer", references: [] }));
  await waitFor(() => expect(screen.getByText("Send question")).toBeEnabled());
  expect(screen.queryByText("Late answer")).not.toBeInTheDocument();
});
