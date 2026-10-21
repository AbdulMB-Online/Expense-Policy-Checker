import { useEffect, useRef, useState } from "react";
import { MessageCircle, Send, Loader2, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import type { Claim, Report } from "@/lib/report";

type Message = { role: "user" | "assistant"; content: string; references?: string[] };
type Status = { available: boolean; message: string; provider?: string };
const prompts = ["What should I review first, and why?", "Compare flagged spending by employee.", "Explain duplicate claims and what evidence to check.", "What patterns appear across categories and months?"];

export function ReportAssistant({ report, employee, search, onClaim }: { report: Report; employee: string; search: string; onClaim: (claim: Claim) => void }) {
  const [open, setOpen] = useState(false);
  const [scope, setScope] = useState("all");
  return <>
    <Button className="assistant-launch" variant="outline" onClick={() => setOpen(true)}><MessageCircle size={16} />Ask about this report</Button>
    <Dialog open={open} onOpenChange={setOpen}><DialogContent className="assistant-dialog">
      <DialogHeader><DialogTitle>Ask about this report</DialogTitle><DialogDescription>Get help spotting patterns and deciding what to review first.</DialogDescription></DialogHeader>
      <label className="assistant-scope">Looking at<select aria-label="Chat report scope" value={scope} onChange={e => setScope(e.target.value)}><option value="all">Entire report</option><option value="filtered">Current filters</option></select></label>
      <Chat key={`${report.dataset_id}-${scope}-${employee}-${search}-${report.generated_at}`} report={report} employee={scope === "filtered" ? employee : ""} search={scope === "filtered" ? search : ""} onClaim={claim => { setOpen(false); onClaim(claim); }} />
    </DialogContent></Dialog>
  </>;
}

function Chat({ report, employee, search, onClaim }: { report: Report; employee: string; search: string; onClaim: (claim: Claim) => void }) {
  const [status, setStatus] = useState<Status | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [question, setQuestion] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [references, setReferences] = useState<Claim[]>(report.claims);
  const controller = useRef<AbortController | null>(null);
  const end = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    const abort = new AbortController();
    fetch("/api/assistant/status", { signal: abort.signal }).then(async response => {
      if (!response.ok) throw new Error();
      const data: Status = await response.json();
      if (!abort.signal.aborted) setStatus(data);
    }).catch(() => { if (!abort.signal.aborted) setStatus({ available: false, message: "Assistant unavailable. Close and reopen chat to retry." }); });
    return () => { abort.abort(); controller.current?.abort(); };
  }, []);
  useEffect(() => { end.current?.scrollIntoView({ block: "nearest" }); }, [messages, busy]);
  async function send(text = question) {
    if (!text.trim() || busy || !status?.available) return;
    const next: Message[] = [...messages, { role: "user", content: text.trim() }];
    const abort = new AbortController(); controller.current = abort;
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/assistant/chat", { method: "POST", headers: { "Content-Type": "application/json" }, signal: abort.signal, body: JSON.stringify({ dataset: report.dataset_id, employee: employee || null, search, messages: next.map(({ role, content }) => ({ role, content })) }) });
      const data = await response.json();
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Please shorten your question or start a new chat.");
      if (abort.signal.aborted) return;
      setMessages([...next, { role: "assistant", content: data.answer, references: data.references }]);
      setQuestion("");
      setReferences(previous => [...previous, ...(data.reference_claims ?? [])]);
    } catch (problem) {
      if (!abort.signal.aborted) { setError(problem instanceof Error ? problem.message : "Unable to answer. Try again."); setQuestion(text); }
    } finally { if (!abort.signal.aborted) { setBusy(false); input.current?.focus(); } }
  }
  function stop() { controller.current?.abort(); setBusy(false); setError("Request stopped. You can send your question again."); }
  const limit = messages.length >= 20;
  return <>
    <p className="assistant-context">{report.sources.expenses}, {employee || "all employees"}{search ? `, matching “${search}”` : ""}</p>
    {!status ? <p className="assistant-note" role="status">Connecting…</p> : !status.available ? <p className="assistant-notice" role="status">{status.message}</p> : <p className="assistant-note">Questions and report data are sent to {status.provider ?? "your AI provider"}. Receipts stay here.</p>}
    <div className="assistant-messages" role="log" aria-label="Report conversation" aria-live="polite">
      {!messages.length && <div className="assistant-welcome"><MessageCircle size={25} /><h3>What would you like to understand?</h3><p>Ask your own question or start with one below.</p><div className="assistant-prompts">{prompts.map(prompt => <button key={prompt} disabled={!status?.available || busy} onClick={() => { setQuestion(prompt); void send(prompt); }}>{prompt}</button>)}</div></div>}
      {messages.map((message, i) => <article className={`assistant-message ${message.role}`} key={i}><strong>{message.role === "user" ? "You" : "Report assistant"}</strong><p>{message.content}</p>{!!message.references?.length && <div className="assistant-citations">{message.references.map(id => { const claim = references.find(c => c.id === id); return <button key={id} disabled={!claim} onClick={() => claim && onClaim(claim)}>View {id}</button>; })}</div>}</article>)}
      {busy && <p className="assistant-thinking" role="status"><Loader2 size={14} className="spin" />Reading the report…</p>}
      <div ref={end} />
    </div>
    {error && <p role="alert" className="assistant-error">{error}</p>}
    {limit && <p role="status">Start a new chat to continue after 10 answers.</p>}
    <form className="assistant-composer" onSubmit={e => { e.preventDefault(); void send(); }}><label htmlFor="report-question">Your question</label><textarea ref={input} id="report-question" maxLength={4000} rows={3} value={question} disabled={!status?.available || busy || limit} onChange={e => setQuestion(e.target.value)} placeholder="Why was a claim flagged? Where should I focus?" /><div><Button type="button" variant="ghost" disabled={busy || !messages.length} onClick={() => { setMessages([]); setError(""); setQuestion(""); }}><RotateCcw size={14} />New chat</Button>{busy ? <Button type="button" variant="outline" onClick={stop}>Stop</Button> : <Button type="submit" disabled={!status?.available || !question.trim() || limit}><Send size={14} />Send question</Button>}</div></form>
  </>;
}
