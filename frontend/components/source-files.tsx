import { useRef, useState, type ReactNode, type FormEvent } from "react";
import { FileJson, FileSpreadsheet, Loader2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { uploadReport, type Report } from "@/lib/report";

export function SourceFiles({ report, busy, onReport, onSamples, onBusy, children }: {
  children?: ReactNode;
  report: Report | null; busy: boolean; onReport: (report: Report) => void;
  onSamples: () => void; onBusy: (busy: boolean) => void;
}) {
  const [expenses, setExpenses] = useState<File | null>(null);
  const [policy, setPolicy] = useState<File | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState("");
  const form = useRef<HTMLFormElement>(null);

  function clearFiles() {
    form.current?.reset();
    setExpenses(null);
    setPolicy(null);
    setError("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!expenses && !policy) return;
    setSending(true);
    onBusy(true);
    setError("");
    try {
      const result = await uploadReport(expenses, policy, report?.dataset_id ?? null);
      onReport(result);
      clearFiles();
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : "The files could not be checked. Please retry.");
    } finally {
      setSending(false);
      onBusy(false);
    }
  }

  return <section id="source-files" className="source-panel" aria-labelledby="source-title">
    <div className="source-heading"><h2 id="source-title">Files in use</h2><span className="source-mode">{report?.dataset_id ? "Uploaded files active" : "Stored sample files"}</span></div>
    {children}
    <form ref={form} onSubmit={submit}>
      <div className="source-inputs">
        <label className={`source-field${expenses ? " has-file" : ""}`}><input type="file" accept=".csv,text/csv" disabled={busy || sending} onChange={(event) => setExpenses(event.target.files?.[0] ?? null)} /><span className="source-field-icon"><FileSpreadsheet size={18} /></span><span className="source-field-copy"><strong>Expense CSV</strong><small>{expenses ? `Ready: ${expenses.name}` : "Drop a file or click to replace"}</small><small className="source-active" title={report?.sources.expenses}>Active: {report?.sources.expenses ?? "Stored expense CSV"}</small></span></label>
        <label className={`source-field${policy ? " has-file" : ""}`}><input type="file" accept=".json,application/json" disabled={busy || sending} onChange={(event) => setPolicy(event.target.files?.[0] ?? null)} /><span className="source-field-icon"><FileJson size={18} /></span><span className="source-field-copy"><strong>Policy JSON</strong><small>{policy ? `Ready: ${policy.name}` : "Drop a file or click to replace"}</small><small className="source-active" title={report?.sources.policy}>Active: {report?.sources.policy ?? "Stored policy JSON"}</small></span></label>
      </div>
      <div className="source-actions"><span>Up to 5 MB each</span><div>{report?.dataset_id && <Button type="button" variant="ghost" disabled={busy || sending} onClick={() => { clearFiles(); onSamples(); }}>Use sample files</Button>}<Button type="submit" disabled={busy || sending || (!expenses && !policy)}>{sending ? <Loader2 size={14} className="spin" /> : <Upload size={14} />}{sending ? "Checking files…" : "Check selected files"}</Button></div></div>
      {error && <p role="alert" className="source-error">{error}</p>}
    </form>
  </section>;
}
