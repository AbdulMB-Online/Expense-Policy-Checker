import { useEffect, useId, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { ArrowRight, CircleAlert, CircleCheck, FileText, Loader2, ShieldCheck, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { categoryLabel, dateLabel, ExpenseSubmissionError, money, submitExpense, type Claim, type Report, type DemoUser } from "@/lib/report";
import { statusLabel } from "@/components/expense-review";

function today() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

export function SubmittedExpenses({ report, onClaim, all = false }: { report: Report; onClaim: (claim: Claim) => void; all?: boolean }) {
  const [showAll, setShowAll] = useState(false);
  const claims = [...(all || report.current_user?.role === "employee" ? report.claims : report.submissions)].reverse();
  return <section className="submitted-expenses" aria-label="Submitted expenses">
    <div className="section-heading"><div><h2>{all ? "All expenses" : "Submitted expenses"} <span className="heading-count">{claims.length}</span></h2><p>Every claim, including those with no active policy flags.</p></div></div>
    {claims.length ? <div className="submitted-list">{(showAll ? claims : claims.slice(0, 5)).map((claim) => <button className="submitted-row" key={claim.id} onClick={() => onClaim(claim)} aria-label={`View ${all ? "review" : "submitted"} expense ${claim.id}`}>
      <span className="claim-category-icon"><FileText size={17} /></span><span className="submitted-identity"><strong>{claim.employee} · {categoryLabel(claim.category)}</strong><small>{dateLabel(claim.date)} · {claim.description}</small><small>{claim.id}{claim.receipt ? ` · Receipt: ${claim.receipt.name}` : " · No receipt"}</small></span>
      <span className={`submission-status ${claim.status}`}>{claim.review_status && <span>{statusLabel(claim.review_status)} · </span>}{claim.status === "flagged" ? `${claim.violations.length} policy ${claim.violations.length === 1 ? "flag" : "flags"}` : "Unflagged by active checks"}</span><strong>{money(claim.amount, report.currency)}</strong><ArrowRight size={15} />
    </button>)}{claims.length > 5 && <Button variant="ghost" onClick={() => setShowAll(!showAll)}>{showAll ? "Show recent submissions" : "Show all submissions"}</Button>}</div> : <p className="submission-empty"><FileText size={18} />Your submitted expenses will appear here.</p>}
  </section>;
}

export function UserExpenseView({ report, busy, onBusy, onSaved, onReview, onClaim, user }: {
  report: Report | null; busy: boolean; onBusy: (busy: boolean) => void;
  onSaved: (report: Report) => void; onReview: () => void; onClaim: (claim: Claim) => void;
  user: DemoUser;
}) {
  const prefix = useId();
  const [draft, setDraft] = useState({ employee: user.role === "employee" ? user.name : "", date: today(), category: "", amount: "", description: "", nights: "" });
  const [receipt, setReceipt] = useState<File | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [confirmation, setConfirmation] = useState<Claim | null>(null);
  const requestId = useRef(crypto.randomUUID());
  const fileInput = useRef<HTMLInputElement>(null);
  const form = useRef<HTMLFormElement>(null);
  const resultHeading = useRef<HTMLHeadingElement>(null);
  const errorFocus = useRef<string | null>(null);
  const settings = report?.policy.categories[draft.category];
  const needsNights = settings?.nights_required || settings?.limit_basis === "per_night";

  useEffect(() => {
    if (report && !report.policy.categories[draft.category]) {
      setDraft((previous) => ({ ...previous, category: Object.keys(report.policy.categories)[0] ?? "", nights: "" }));
    }
  }, [report, draft.category]);

  useEffect(() => { if (confirmation) resultHeading.current?.focus(); }, [confirmation]);

  useEffect(() => {
    if (sending || busy || !errorFocus.current) return;
    const control = form.current?.elements.namedItem(errorFocus.current);
    if (control instanceof HTMLElement) control.focus();
    errorFocus.current = null;
  }, [sending, busy, fields]);

  function startNewExpense() {
    requestId.current = crypto.randomUUID();
    setDraft((previous) => ({ ...previous, date: today(), amount: "", description: "", nights: "" }));
    setReceipt(null);
    if (fileInput.current) fileInput.current.value = "";
    setError("");
    setFields({});
    setConflict(false);
    setConfirmation(null);
  }

  function change(name: keyof typeof draft, value: string) {
    setDraft((previous) => ({ ...previous, [name]: value, ...(name === "category" ? { nights: "" } : {}) }));
    setFields((previous) => ({ ...previous, [name]: "" }));
  }

  function fieldProps(name: keyof typeof draft) {
    return { id: `${prefix}-${name}`, name, value: draft[name], "aria-invalid": !!fields[name], "aria-describedby": fields[name] ? `${prefix}-${name}-error` : undefined, onChange: (event: ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => change(name, event.target.value) };
  }

  function fieldError(name: string) {
    return fields[name] ? <small className="field-error" id={`${prefix}-${name}-error`}>{fields[name]}</small> : null;
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!report || sending || busy) return;
    setError("");
    setConflict(false);
    setFields({});
    if (receipt && receipt.size > 5 * 1024 * 1024) {
      setFields({ receipt: "Receipt must be 5 MiB or smaller." });
      fileInput.current?.focus();
      return;
    }
    setSending(true);
    onBusy(true);
    try {
      const files = new FormData(event.currentTarget);
      files.delete("receipt");
      if (receipt) files.append("receipt", receipt);
      files.set("request_id", requestId.current);
      if (report.dataset_id) files.set("dataset", report.dataset_id);
      const result = await submitExpense(files);
      onSaved(result.report);
      setConfirmation(result.claim);
      setDraft((previous) => ({ ...previous, amount: "", description: "", nights: "" }));
      setReceipt(null);
      if (fileInput.current) fileInput.current.value = "";
      requestId.current = crypto.randomUUID();
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "The expense could not be submitted. Please retry.");
      if (problem instanceof ExpenseSubmissionError) {
        setFields(problem.fields);
        errorFocus.current = Object.keys(problem.fields)[0] ?? null;
        setConflict(problem.status === 409);
      }
    } finally { setSending(false); onBusy(false); }
  }

  return <section className="user-expense-view" id="submit-expense" aria-label="User expense submission">
    <header className="submission-heading"><div className="eyebrow"><span className="eyebrow-dot" />YOUR EXPENSES, READY FOR REVIEW</div><h1>Submit an expense<span>.</span></h1><p>Add the details and a receipt. We’ll check the active policy and add your claim to the report.</p></header>
    {!report ? <div className="submission-empty" role="status">Loading the active expense policy…</div> : <>
      {confirmation && <div className={`submission-result ${confirmation.status}`} role="status"><CircleCheck size={23} /><div><h2 tabIndex={-1} ref={resultHeading}>Expense submitted</h2><p>{confirmation.id} · {money(confirmation.amount, report.currency)} · {confirmation.status === "flagged" ? "Saved with policy flags for review." : "No violations detected by active checks. Final review is still required."}</p>{confirmation.violations.length > 0 && <ul>{confirmation.violations.map((violation, index) => <li key={`${violation.rule_id}-${index}`}><strong>{violation.rule_name}:</strong> {violation.reason}</li>)}</ul>}{user.role === "reviewer" && <Button variant="ghost" onClick={onReview}>View reviewer report <ArrowRight size={14} /></Button>}</div></div>}
      <div className="submission-layout">
        <form ref={form} className="expense-form" aria-label="Submit an expense" onSubmit={submit}>
          <div className="expense-form-heading"><FileText size={20} /><div><h2>Expense details</h2><p>All fields are required unless marked optional.</p></div></div>
          <fieldset disabled={sending || busy}>
            <div className="expense-fields">
              <div className="expense-field"><label htmlFor={`${prefix}-employee`}>Employee name</label><input {...fieldProps("employee")} readOnly={user.role === "employee"} list={`${prefix}-employees`} autoComplete="name" required maxLength={200} placeholder="Enter your full name" />{fieldError("employee")}</div>
              <datalist id={`${prefix}-employees`}>{report.employees.map((name) => <option value={name} key={name} />)}</datalist>
              <div className="expense-field"><label htmlFor={`${prefix}-date`}>Expense date</label><input {...fieldProps("date")} type="date" required />{fieldError("date")}</div>
              <div className="expense-field"><label htmlFor={`${prefix}-category`}>Category</label><select {...fieldProps("category")} required>{Object.keys(report.policy.categories).map((category) => <option value={category} key={category}>{categoryLabel(category)}</option>)}</select>{fieldError("category")}</div>
              <div className="expense-field"><label htmlFor={`${prefix}-amount`}>Amount ({report.currency})</label><input {...fieldProps("amount")} inputMode="decimal" pattern="[0-9]+([.][0-9]{1,2})?" required maxLength={64} placeholder="0.00" />{fieldError("amount")}</div>
              {needsNights && <div className="expense-field"><label htmlFor={`${prefix}-nights`}>Number of nights</label><input {...fieldProps("nights")} type="number" min="1" step="1" required />{fieldError("nights")}</div>}
              <div className="expense-field expense-wide"><label htmlFor={`${prefix}-description`}>Description</label><textarea {...fieldProps("description")} rows={3} required maxLength={2000} placeholder="What was this expense for?" />{fieldError("description")}</div>
            </div>
            <div className="receipt-field"><label htmlFor={`${prefix}-receipt`}><Upload size={17} />Receipt <span>(optional)</span></label><p>Attach a PDF, PNG, or JPEG up to 5 MiB. Missing required receipts will be flagged.</p><input ref={fileInput} id={`${prefix}-receipt`} name="receipt" type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" aria-invalid={!!fields.receipt} aria-describedby={fields.receipt ? `${prefix}-receipt-error` : undefined} onChange={(event) => { setReceipt(event.target.files?.[0] ?? null); setFields((previous) => ({ ...previous, receipt: "" })); }} />{receipt && <button className="remove-receipt" type="button" onClick={() => { setReceipt(null); if (fileInput.current) fileInput.current.value = ""; }}><X size={13} />Remove receipt</button>}{fieldError("receipt")}</div>
            {error && <div className="submission-error" role="alert"><CircleAlert size={17} /><div><p>{error} Your entered details have been kept.</p>{conflict && <Button type="button" variant="outline" onClick={startNewExpense}>Start a new expense</Button>}</div></div>}
            <div className="expense-submit"><span>Policy flags are saved for finance review.</span><Button type="submit" className="gradient-button" disabled={!draft.category}>{sending ? <Loader2 size={15} className="spin" /> : <ArrowRight size={15} />}{sending ? "Submitting…" : "Submit expense"}</Button></div>
          </fieldset>
        </form>
        <aside className="submission-policy" aria-label="Submission policy"><div className="dialog-eyebrow"><ShieldCheck size={17} />ACTIVE POLICY</div><h2>{report.policy.name}</h2><p>Version {report.policy.version} · {report.currency}</p><div className="submission-policy-category"><strong>{categoryLabel(draft.category)}</strong><span>{settings?.max_amount == null ? "No configured amount limit" : `${money(settings.max_amount, report.currency)} per ${settings.limit_basis === "per_night" ? "night" : "expense"}`}</span><span>{settings?.receipt.mode === "always" ? "Receipt always required" : settings?.receipt.mode === "above_threshold" ? `Receipt required above ${money(settings.receipt.threshold!, report.currency)}` : "Receipt rule unconfigured"}</span></div><ol><li>Enter the claim details.</li><li>Attach the supporting receipt.</li><li>Submit to check the policy and save.</li></ol><p className="submission-policy-note">The configured policy checks run on submit. Finance makes the final decision.</p></aside>
      </div>
      <SubmittedExpenses report={report} onClaim={onClaim} />
    </>}
  </section>;
}
