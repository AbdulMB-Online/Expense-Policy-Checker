import { useEffect, useState, type FormEvent } from "react";
import { Button } from "@/components/ui/button";
import { apiJson, postJson, type Claim, type DemoUser, type Report, type ReviewEvent, type ReviewStatus } from "@/lib/report";

export function statusLabel(status: ReviewStatus) { return status.replaceAll("_", " "); }

export function ExpenseReview({ claim, report, user, onSaved }: { claim: Claim; report: Report; user: DemoUser; onSaved: (report: Report) => void }) {
  const [history, setHistory] = useState<ReviewEvent[]>([]);
  const [accounts, setAccounts] = useState<DemoUser[]>([]);
  const [owner, setOwner] = useState("");
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const query = report.dataset_id ? `?dataset=${encodeURIComponent(report.dataset_id)}` : "";
  const base = `/api/expenses/${encodeURIComponent(claim.id)}`;

  useEffect(() => {
    const controller = new AbortController();
    apiJson<ReviewEvent[]>(`${base}/history${query}`, { signal: controller.signal }).then(setHistory).catch((problem) => {
      if (!controller.signal.aborted) setError(problem.message);
    });
    if (user.role === "reviewer" && !claim.owner_id) apiJson<DemoUser[]>("/api/demo/accounts", { signal: controller.signal }).then(setAccounts).catch((problem) => {
      if (!controller.signal.aborted) setError(problem.message);
    });
    return () => controller.abort();
  }, [base, query, user.role, claim.owner_id, claim.review_status]);

  async function action(path: string, body: unknown) {
    setBusy(true);
    setError("");
    try { onSaved(await postJson<Report>(`${base}/${path}${query}`, body)); setComment(""); }
    catch (problem) { setError(problem instanceof Error ? problem.message : "Could not save the decision."); }
    finally { setBusy(false); }
  }

  return <section className="expense-review" aria-label="Expense review">
    <h3>Review status: <span>{statusLabel(claim.review_status)}</span></h3>
    {history.length > 0 && <ol className="review-history">{history.map((event) => <li key={event.revision}><strong>{statusLabel(event.decision)}</strong> · {event.reviewer} · Revision {event.revision}<p>{event.comment}</p></li>)}</ol>}
    {user.role === "reviewer" && !claim.owner_id && <div className="owner-mapping"><label>Employee account<select aria-label="Employee account" value={owner} onChange={(event) => setOwner(event.target.value)}><option value="">Choose an account</option>{accounts.map((account) => <option value={account.id} key={account.id}>{account.name}</option>)}</select></label><Button disabled={busy || !owner} onClick={() => { void action("owner", { user_id: owner }); }}>Assign employee</Button></div>}
    {user.role === "reviewer" && claim.review_status === "submitted" && claim.owner_id && claim.owner_id !== user.id && <>
      <label htmlFor="review-comment">Reviewer comment</label><textarea id="review-comment" maxLength={2000} rows={3} value={comment} onChange={(event) => setComment(event.target.value)} placeholder="Explain a rejection or requested changes" />
      <div className="review-actions">{([['approved', 'Approve expense'], ['rejected', 'Reject expense'], ['changes_requested', 'Request changes']] as const).map(([decision, label]) => <Button variant="outline" key={decision} disabled={busy || (decision !== "approved" && !comment.trim())} onClick={() => { void action("review", { run_id: report.run_id, revision_id: claim.revision_id, decision, comment }); }}>{label}</Button>)}</div>
    </>}
    {claim.owner_id === user.id && user.role === "reviewer" && <p>You cannot review your own expense.</p>}
    {claim.owner_id === user.id && claim.review_status === "changes_requested" && (claim.origin === "submission"
      ? <CorrectionForm claim={claim} report={report} onSaved={onSaved} />
      : <p>Ask a reviewer to import a corrected CSV for this expense.</p>)}
    {error && <p role="alert" className="field-error">{error}</p>}
  </section>;
}

function CorrectionForm({ claim, report, onSaved }: { claim: Claim; report: Report; onSaved: (report: Report) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const files = new FormData(event.currentTarget);
    const file = files.get("receipt");
    if (file instanceof File && !file.size) files.delete("receipt");
    if (report.dataset_id) files.set("dataset", report.dataset_id);
    files.set("revision", String(claim.revision));
    setBusy(true);
    setError("");
    try { onSaved(await apiJson<Report>(`/api/expenses/${encodeURIComponent(claim.id)}`, { method: "PUT", body: files })); }
    catch (problem) { setError(problem instanceof Error ? problem.message : "Could not resubmit expense."); }
    finally { setBusy(false); }
  }
  return <form className="correction-form" onSubmit={submit} aria-label="Correct expense"><fieldset disabled={busy}>
    <legend>Correct and resubmit</legend>
    <label>Expense date<input name="date" type="date" defaultValue={claim.date} required /></label>
    <label>Category<select name="category" defaultValue={claim.category}>{Object.keys(report.policy.categories).map((category) => <option key={category}>{category}</option>)}</select></label>
    <label>Amount<input name="amount" defaultValue={claim.amount} inputMode="decimal" required maxLength={64} /></label>
    <label>Number of nights (hotel)<input name="nights" type="number" min={1} defaultValue={claim.nights ?? ""} /></label>
    <label>Description<textarea name="description" defaultValue={claim.description} required maxLength={2000} /></label>
    <label>Replace receipt (optional)<input name="receipt" type="file" accept=".pdf,.png,.jpg,.jpeg" /></label>
    <p>Your current receipt is kept unless you attach a replacement.</p><Button type="submit">Resubmit expense</Button>
    {error && <p role="alert">{error}</p>}
  </fieldset></form>;
}
