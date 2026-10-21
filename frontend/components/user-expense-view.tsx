import { useEffect, useId, useRef, useState, type ChangeEvent, type FormEvent } from "react";
import { ArrowRight, CircleAlert, CircleCheck, FileText, Loader2, ShieldCheck, Upload, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { categoryLabel, dateLabel, ExpenseSubmissionError, extractReceipt, money, submitExpense, type Claim, type Report, type DemoUser } from "@/lib/report";
import { statusLabel } from "@/components/expense-review";

function today() {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

export function SubmittedExpenses({ report, onClaim, all = false }: { report: Report; onClaim: (claim: Claim) => void; all?: boolean }) {
  const [showAll, setShowAll] = useState(false);
  const claims = [...(all || report.current_user?.role === "employee" ? report.claims : report.submissions)].reverse();
  return <section className="submitted-expenses" aria-label="Submitted expenses">
    {claims.length ? <div className="submitted-list">{(showAll ? claims : claims.slice(0, 5)).map((claim) => <button className="submitted-row" key={claim.id} onClick={() => onClaim(claim)} aria-label={`View ${all ? "review" : "submitted"} expense ${claim.id}`}>
      <span className="claim-category-icon"><FileText size={17} /></span>
      <span className="submitted-identity"><strong>{claim.description}</strong><small>{all && <span>{claim.employee}</span>}<span>{categoryLabel(claim.category)}</span><span>{dateLabel(claim.date)}</span>{!claim.receipt && !claim.receipt_attached && <span>No receipt</span>}</small></span>
      <span className="submission-tags">{claim.review_status && claim.review_status !== "submitted" && <span className={`review-chip ${claim.review_status}`}>{statusLabel(claim.review_status)}</span>}<span className={`submission-status ${claim.status}`}>{claim.status === "flagged" ? `${claim.violations.length} ${claim.violations.length === 1 ? "flag" : "flags"}` : "No flags"}</span></span>
      <strong className="submitted-amount">{money(claim.amount, report.currency)}</strong>
    </button>)}{claims.length > 5 && <button className="show-more" onClick={() => setShowAll(!showAll)}>{showAll ? "Show recent submissions" : "Show all submissions"}</button>}</div> : <p className="submission-empty"><FileText size={18} />Expenses you submit will show up here.</p>}
  </section>;
}

export function UserExpenseView({ report, busy, onBusy, onSaved, onClaim, user, showSubmitted = true }: {
  showSubmitted?: boolean;
  report: Report | null; busy: boolean; onBusy: (busy: boolean) => void;
  onSaved: (report: Report) => void; onClaim: (claim: Claim) => void;
  user: DemoUser;
}) {
  const prefix = useId();
  const [draft, setDraft] = useState({ employee: user.role === "employee" ? user.name : "", date: today(), category: "", amount: "", description: "", nights: "" });
  const [receipt, setReceipt] = useState<File | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [extractionError, setExtractionError] = useState("");
  const [extractionNotes, setExtractionNotes] = useState<string[] | null>(null);
  const extraction = useRef<AbortController | null>(null);
  const editedFields = useRef(new Set<string>());
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
    if (report && extractionNotes === null && !report.policy.categories[draft.category]) {
      setDraft((previous) => ({ ...previous, category: Object.keys(report.policy.categories)[0] ?? "", nights: "" }));
    }
  }, [report, draft.category, extractionNotes]);

  useEffect(() => { if (confirmation) resultHeading.current?.focus(); }, [confirmation]);

  useEffect(() => {
    setExtracting(false);
    setExtractionError("");
    setExtractionNotes(null);
    return () => {
      extraction.current?.abort();
      extraction.current = null;
    };
  }, [report?.dataset_id]);

  function cancelExtraction() {
    extraction.current?.abort();
    extraction.current = null;
    setExtracting(false);
    setExtractionError("");
    setExtractionNotes(null);
  }

  async function autofill(file: File) {
    cancelExtraction();
    if (!report) return;
    if (file.size > 5 * 1024 * 1024) {
      setFields((previous) => ({ ...previous, receipt: "Receipt must be 5 MiB or smaller." }));
      return;
    }
    const controller = new AbortController();
    extraction.current = controller;
    setExtracting(true);
    setConfirmation(null);
    try {
      const result = await extractReceipt(file, report.dataset_id, controller.signal);
      if (controller.signal.aborted) return;
      const description = [result.title, result.description].filter(Boolean).join("\n");
      const suggestions = {
        date: result.date ?? "", amount: result.amount ?? "", description,
        category: result.category && report.policy.categories[result.category] ? result.category : "",
        nights: result.nights == null ? "" : String(result.nights),
      };
      setDraft((previous) => {
        const next = { ...previous };
        for (const name of Object.keys(suggestions) as (keyof typeof suggestions)[]) {
          if (!editedFields.current.has(name)) next[name] = suggestions[name];
        }
        return next;
      });
      setFields((previous) => Object.fromEntries(Object.entries(previous).filter(([name]) => editedFields.current.has(name))));
      setExtractionNotes(result.warnings);
    } catch (problem) {
      if (!controller.signal.aborted) setExtractionError(problem instanceof Error ? problem.message : "Receipt autofill failed. Enter the details manually.");
    } finally {
      if (extraction.current === controller) {
        extraction.current = null;
        setExtracting(false);
      }
    }
  }

  useEffect(() => {
    if (sending || busy || !errorFocus.current) return;
    const control = form.current?.elements.namedItem(errorFocus.current);
    if (control instanceof HTMLElement) control.focus();
    errorFocus.current = null;
  }, [sending, busy, fields]);

  function startNewExpense() {
    cancelExtraction();
    editedFields.current.clear();
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
    editedFields.current.add(name);
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
    if (!report || sending || busy || extracting) return;
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
      cancelExtraction();
      editedFields.current.clear();
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
    <header className="submission-heading"><h1>Submit an expense</h1><p>Drop in a receipt to fill the form, or type the details yourself.</p></header>
    {!report ? <div className="submission-empty" role="status">Loading your expense policy…</div> : <>
      {confirmation && <div className={`submission-result ${confirmation.status}`} role="status"><CircleCheck size={22} /><div><h2 tabIndex={-1} ref={resultHeading}>Expense submitted</h2><p>{confirmation.id}, {money(confirmation.amount, report.currency)}. {confirmation.status === "flagged" ? "Saved with policy flags for review." : "No policy flags. Final review is still required."}</p>{confirmation.violations.length > 0 && <ul>{confirmation.violations.map((violation, index) => <li key={`${violation.rule_id}-${index}`}><strong>{violation.rule_name}:</strong> {violation.reason}</li>)}</ul>}</div></div>}
      <div className="submission-layout">
        <form ref={form} className="expense-form" aria-label="Submit an expense" onSubmit={submit}>
          <fieldset disabled={sending || busy}>
            <div className="receipt-autofill">
              <div className={`receipt-drop${receipt ? " has-file" : ""}${extracting ? " is-reading" : ""}`}>
                <input ref={fileInput} className="receipt-input" id={`${prefix}-receipt`} name="receipt" type="file" accept=".pdf,.png,.jpg,.jpeg,application/pdf,image/png,image/jpeg" aria-invalid={!!fields.receipt} aria-describedby={fields.receipt ? `${prefix}-receipt-error` : undefined} onChange={(event) => {
                  const file = event.target.files?.[0] ?? null;
                  setReceipt(file);
                  setFields((previous) => ({ ...previous, receipt: "" }));
                  if (file) void autofill(file); else cancelExtraction();
                }} />
                <span className="receipt-drop-icon" aria-hidden="true">{extracting ? <Loader2 size={20} className="spin" /> : receipt ? <FileText size={20} /> : <Upload size={20} />}</span>
                <span className="receipt-drop-copy"><label htmlFor={`${prefix}-receipt`}>Receipt <span>(optional)</span></label><small>{receipt ? receipt.name : "Drop a PDF or image here, or click to browse. Up to 5 MB."}</small></span>
              </div>
              {receipt && <div className="receipt-actions">
                {extracting && <p role="status">Reading receipt…</p>}
                {extracting ? <Button type="button" variant="ghost" onClick={cancelExtraction}>Cancel autofill</Button> : <Button type="button" variant="ghost" onClick={() => void autofill(receipt)}>Retry autofill</Button>}
                <button className="remove-receipt" type="button" onClick={() => { cancelExtraction(); setReceipt(null); if (fileInput.current) fileInput.current.value = ""; }}><X size={14} />Remove receipt</button>
              </div>}
              {extractionError && <p className="receipt-message is-error" role="alert">{extractionError}</p>}
              {extractionNotes && <div role="status" className="receipt-message receipt-suggestions"><p>Receipt read. Check the details below.</p>{extractionNotes.length > 0 && <ul>{extractionNotes.map((note, index) => <li key={index}>{note}</li>)}</ul>}</div>}
              {fieldError("receipt")}
            </div>
            <fieldset disabled={extracting}>
            <div className="expense-fields">
              <div className="expense-field"><label htmlFor={`${prefix}-employee`}>Employee name</label><input {...fieldProps("employee")} readOnly={user.role === "employee"} list={`${prefix}-employees`} autoComplete="name" required maxLength={200} placeholder="Enter your full name" />{fieldError("employee")}</div>
              <datalist id={`${prefix}-employees`}>{report.employees.map((name) => <option value={name} key={name} />)}</datalist>
              <div className="expense-field"><label htmlFor={`${prefix}-date`}>Expense date</label><input {...fieldProps("date")} type="date" required />{fieldError("date")}</div>
              <div className="expense-field"><label htmlFor={`${prefix}-category`}>Category</label><select {...fieldProps("category")} required><option value="">Choose a category</option>{Object.keys(report.policy.categories).map((category) => <option value={category} key={category}>{categoryLabel(category)}</option>)}</select>{fieldError("category")}</div>
              <div className="expense-field"><label htmlFor={`${prefix}-amount`}>Amount ({report.currency})</label><input {...fieldProps("amount")} inputMode="decimal" pattern="[0-9]+([.][0-9]{1,2})?" required maxLength={64} placeholder="0.00" />{fieldError("amount")}</div>
              {needsNights && <div className="expense-field"><label htmlFor={`${prefix}-nights`}>Number of nights</label><input {...fieldProps("nights")} type="number" min="1" step="1" required />{fieldError("nights")}</div>}
              <div className="expense-field expense-wide"><label htmlFor={`${prefix}-description`}>Description</label><textarea {...fieldProps("description")} rows={3} required maxLength={2000} placeholder="What was this expense for?" />{fieldError("description")}</div>
            </div>
            </fieldset>
            {error && <div className="submission-error" role="alert"><CircleAlert size={17} /><div><p>{error}</p>{conflict && <Button type="button" variant="outline" onClick={startNewExpense}>Start a new expense</Button>}</div></div>}
            <div className="expense-submit"><Button type="submit" className="gradient-button" disabled={!draft.category || extracting}>{sending ? <Loader2 size={15} className="spin" /> : <ArrowRight size={15} />}{sending ? "Submitting…" : "Submit expense"}</Button></div>
          </fieldset>
        </form>
        <aside className="submission-policy" aria-label="Submission policy">
          <span className="submission-policy-label"><ShieldCheck size={15} />{report.policy.name}</span>
          <h2>{draft.category ? categoryLabel(draft.category) : "Choose a category"}</h2>
          <dl>
            <div><dt>Limit</dt><dd>{settings?.max_amount == null ? "No limit" : `${money(settings.max_amount, report.currency)} per ${settings.limit_basis === "per_night" ? "night" : "expense"}`}</dd></div>
            <div><dt>Receipt</dt><dd>{settings?.receipt.mode === "always" ? "Always required" : settings?.receipt.mode === "above_threshold" ? `Required above ${money(settings.receipt.threshold!, report.currency)}` : "Not checked"}</dd></div>
          </dl>
        </aside>
      </div>
      {showSubmitted && <SubmittedExpenses report={report} onClaim={onClaim} />}
    </>}
  </section>;
}
