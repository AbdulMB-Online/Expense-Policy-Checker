import { useEffect, useRef, useState, type FormEvent } from "react";
import { Check, ChevronLeft, Loader2, Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { apiJson, categoryLabel, money, uploadReport, type CategoryPolicy, type Report } from "@/lib/report";

export interface PolicyConfig {
  name: string; version: string; currency: string;
  categories: Record<string, CategoryPolicy & { max_nights_per_stay?: number | null; review_required?: boolean }>;
  restricted_categories: string[]; unknown_category_action: "review_required";
  submission: { max_days_after_expense: number; inclusive: boolean };
  duplicates: { key_fields: string[]; require_different_ids: boolean; flag: "all_matches" | "later_matches"; classification: "suspected_duplicate" };
  reporting: { collect_all_violations: boolean; flagged_amount_counting: "once_per_expense" };
}
export interface SavedPolicy { id: string; config: PolicyConfig }

function policyFile(config: PolicyConfig) {
  return new File([JSON.stringify(config, null, 2)], `${config.name.replace(/[^a-zA-Z0-9_-]/g, "_")}.json`, { type: "application/json" });
}

export function PolicySummary({ name, version, currency, categories, activeRules, rules }: {
  name: string; version?: string; currency: string;
  categories: Record<string, CategoryPolicy & { review_required?: boolean }>;
  activeRules?: string[];
  rules?: { deadline: string; restricted: string; duplicates: string };
}) {
  return <div className="policy-sheet">
    <div className="policy-version"><span>{name}{version ? ` · Version ${version}` : ""}</span><span>{currency}</span></div>
    <div className="policy-categories">{Object.entries(categories).map(([category, settings]) => <div key={category}><strong>{categoryLabel(category)}</strong><span>{settings.max_amount === null ? "No amount limit" : `${money(settings.max_amount, currency)} / ${settings.limit_basis === "per_night" ? "night" : "claim"}`}<small>{settings.receipt.mode === "always" ? "Receipt required" : settings.receipt.mode === "above_threshold" ? `Receipt above ${money(settings.receipt.threshold!, currency)}` : "No receipt check"}{settings.review_required ? " · Manual review" : ""}</small></span></div>)}</div>
    {rules && <div className="policy-rule-summary"><p><strong>Submission deadline</strong>{rules.deadline}</p><p><strong>Restricted categories</strong>{rules.restricted}</p><p><strong>Duplicate checks</strong>{rules.duplicates}</p></div>}
    {!!activeRules?.length && <div className="active-checks"><span>Active checks</span>{activeRules.map((rule) => <Badge key={rule} variant="outline"><Check size={11} />{rule}</Badge>)}</div>}
  </div>;
}

export function PolicyLibrary({ report, onReport, onBusy }: {
  report: Report | null; onReport: (report: Report) => void; onBusy: (busy: boolean) => void;
}) {
  const [policies, setPolicies] = useState<SavedPolicy[]>([]);
  const [selected, setSelected] = useState("");
  const [draft, setDraft] = useState<PolicyConfig | null>(null);
  const [category, setCategory] = useState("");
  const [restricted, setRestricted] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [retry, setRetry] = useState(0);
  const picked = useRef(false);
  const policy = policies.find((item) => item.id === selected);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError("");
    apiJson<SavedPolicy[]>("/api/policies", { signal: controller.signal }).then((items) => {
      if (controller.signal.aborted) return;
      if (!Array.isArray(items)) throw new Error("Saved policies couldn't be loaded.");
      setPolicies(items);
      setLoading(false);
    }).catch((problem) => { if (!controller.signal.aborted) { setError(problem instanceof Error ? problem.message : "Saved policies couldn't be loaded."); setLoading(false); } });
    return () => controller.abort();
  }, [retry]);

  useEffect(() => {
    if (picked.current || !policies.length) return;
    setSelected(policies.find((item) => item.id === report?.policy.id)?.id ?? policies[0].id);
  }, [policies, report?.policy.id]);

  function create() {
    if (!policy) return;
    setDraft({ ...structuredClone(policy.config), name: "", version: "1.0" });
    setCategory(""); setRestricted(policy.config.restricted_categories.join(", ")); setError(""); setNotice("");
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    if (!Object.keys(draft.categories).length) { setError("Add at least one category before saving."); return; }
    setBusy(true); onBusy(true); setError("");
    try {
      const files = new FormData(); files.set("policy", policyFile({ ...draft, restricted_categories: [...new Set(restricted.split(",").map((value) => value.trim()).filter(Boolean))] }));
      const saved = await apiJson<SavedPolicy>("/api/policies", { method: "POST", body: files });
      setPolicies((items) => [saved, ...items.filter((item) => item.id !== saved.id)]);
      setSelected(saved.id); setDraft(null); setNotice("Policy saved. Choose Use policy to apply it.");
    } catch (problem) { setError(problem instanceof Error ? problem.message : "The policy could not be saved. Your changes have been kept."); }
    finally { setBusy(false); onBusy(false); }
  }

  async function apply() {
    if (!policy) return;
    setBusy(true); onBusy(true); setError("");
    try { onReport(await uploadReport(null, policyFile(policy.config), report?.dataset_id ?? null)); setNotice(`Now checking expenses with ${policy.config.name}.`); }
    catch (problem) { setError(problem instanceof Error ? problem.message : "The policy could not be applied. Your current report has been kept."); }
    finally { setBusy(false); onBusy(false); }
  }

  function updateCategory(name: string, patch: Partial<PolicyConfig["categories"][string]>) {
    setDraft((current) => current && ({ ...current, categories: { ...current.categories, [name]: { ...current.categories[name], ...patch } } }));
  }

  function addCategory() {
    if (!draft) return;
    const name = category.trim().toLowerCase().replace(/\s+/g, "_");
    if (!name) return;
    if (Object.hasOwn(draft.categories, name)) { setError("That category already exists. Choose a different name."); return; }
    updateCategory(name, { max_amount: null, limit_basis: "per_expense", receipt: { mode: "always" } });
    setCategory(""); setError("");
  }

  const title = draft ? "Create a policy" : policy?.config.name ?? report?.policy.name ?? "Policies";
  return <section className="policy-library" aria-label="Policies">
    <header className="workspace-page-heading"><h1>{title}</h1><p>{draft ? "Starts as a copy of the policy you had selected." : "Choose which policy checks the current expenses."}</p></header>
    {loading && <p role="status"><Loader2 size={15} className="spin" /> Loading policies…</p>}
    {error && <div className="error-banner" role="alert"><p>{error}</p>{!policies.length && <Button onClick={() => setRetry((value) => value + 1)}>Retry</Button>}</div>}
    {notice && <p className="policy-notice" role="status"><Check size={16} />{notice}</p>}
    {!draft && policy && <>
      <div className="policy-library-controls"><label>Saved policy<select value={selected} disabled={busy} onChange={(event) => { picked.current = true; setSelected(event.target.value); setNotice(""); }}>{policies.map((item) => <option value={item.id} key={item.id}>{item.config.name} · v{item.config.version}{item.id === report?.policy.id ? " (active)" : ""}</option>)}</select></label><Button variant="outline" onClick={create} disabled={busy}><Plus size={15} />New policy</Button></div>
      <PolicySummary name={policy.config.name} version={policy.config.version} currency={policy.config.currency} categories={policy.config.categories} activeRules={policy.id === report?.policy.id ? report?.policy.active_rules : undefined} rules={{ deadline: `${policy.config.submission.max_days_after_expense} days after the expense`, restricted: policy.config.restricted_categories.map(categoryLabel).join(", ") || "None", duplicates: policy.config.duplicates.key_fields.map(categoryLabel).join(", ") }} />
      {policy.config.currency !== report?.currency && <p className="review-guidance">This policy uses {policy.config.currency}. Amounts aren't converted, so its submissions are kept separately.</p>}
      <div className="policy-library-footer"><span>{policy.id === report?.policy.id ? "Currently active" : `${policies.length} saved ${policies.length === 1 ? "policy" : "policies"}`}</span><Button onClick={apply} disabled={busy || policy.id === report?.policy.id}>{busy ? <Loader2 size={15} className="spin" /> : <Check size={15} />}{busy ? "Checking expenses…" : "Use policy"}</Button></div>
    </>}
    {!draft && !policy && report && <PolicySummary name={report.policy.name} version={report.policy.version} currency={report.currency} categories={report.policy.categories} activeRules={report.policy.active_rules} />}
    {draft && <form className="policy-editor" onSubmit={save}><fieldset disabled={busy}>
      <button type="button" className="policy-back" onClick={() => { setDraft(null); setError(""); }}><ChevronLeft size={15} />Back to library</button>
      <div className="policy-form-grid"><label className="expense-wide">Policy name<input required maxLength={100} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder="e.g. Business travel" /></label><label>Version<input required maxLength={30} value={draft.version} onChange={(event) => setDraft({ ...draft, version: event.target.value })} /></label><label>Currency<input required pattern="[A-Z]{3}" maxLength={3} value={draft.currency} onChange={(event) => setDraft({ ...draft, currency: event.target.value.toUpperCase() })} /></label></div>
      <h3>Category rules</h3><p className="policy-editor-hint">Leave the amount blank for no limit. Add a category for each type of expense you allow.</p>
      {Object.entries(draft.categories).map(([name, settings]) => <section className="policy-category-editor" key={name}><div className="policy-category-heading"><h4>{categoryLabel(name)}</h4><button type="button" aria-label={`Remove ${categoryLabel(name)} category`} onClick={() => { const categories = { ...draft.categories }; delete categories[name]; setDraft({ ...draft, categories }); }}><Trash2 size={15} /></button></div><div className="policy-form-grid">
        <label>Amount limit<input aria-label={`${categoryLabel(name)} amount limit`} inputMode="decimal" pattern="[0-9]+([.][0-9]{1,2})?" value={settings.max_amount ?? ""} placeholder="No limit" onChange={(event) => updateCategory(name, { max_amount: event.target.value || null })} /></label>
        <label>Limit applies<select value={settings.limit_basis} onChange={(event) => updateCategory(name, { limit_basis: event.target.value, nights_required: event.target.value === "per_night" })}><option value="per_expense">Per expense</option><option value="per_night">Per night</option></select></label>
        <label>Receipt rule<select aria-label={`${categoryLabel(name)} receipt rule`} value={settings.receipt.mode} onChange={(event) => updateCategory(name, { receipt: event.target.value === "above_threshold" ? { mode: event.target.value, threshold: "25.00" } : { mode: event.target.value } })}><option value="always">Always required</option><option value="above_threshold">Above an amount</option><option value="unconfigured">No receipt check</option></select></label>
        {settings.receipt.mode === "above_threshold" && <label>Receipt threshold<input required inputMode="decimal" pattern="[0-9]+([.][0-9]{1,2})?" value={settings.receipt.threshold ?? ""} onChange={(event) => updateCategory(name, { receipt: { ...settings.receipt, threshold: event.target.value } })} /></label>}
        {settings.limit_basis === "per_night" && <label>Maximum nights<input type="number" min={1} step={1} value={settings.max_nights_per_stay ?? ""} placeholder="No limit" onChange={(event) => updateCategory(name, { max_nights_per_stay: event.target.value ? Number(event.target.value) : null })} /></label>}
      </div><label className="policy-checkbox"><input type="checkbox" checked={!!settings.review_required} onChange={(event) => updateCategory(name, { review_required: event.target.checked })} />Always flag for manual review</label></section>)}
      <div className="policy-add-category"><label>New category<input value={category} maxLength={100} onChange={(event) => setCategory(event.target.value)} placeholder="e.g. Training" /></label><Button variant="outline" type="button" onClick={addCategory} disabled={!category.trim()}><Plus size={15} />Add category</Button></div>
      <h3>Rules across all expenses</h3><div className="policy-form-grid"><label>Submission deadline (days)<input required type="number" min={0} step={1} value={draft.submission.max_days_after_expense} onChange={(event) => setDraft({ ...draft, submission: { ...draft.submission, max_days_after_expense: Number(event.target.value) } })} /></label><label>Restricted categories<input value={restricted} onChange={(event) => setRestricted(event.target.value)} placeholder="alcohol, personal" /></label></div>
      <label className="policy-checkbox"><input type="checkbox" checked={draft.submission.inclusive} onChange={(event) => setDraft({ ...draft, submission: { ...draft.submission, inclusive: event.target.checked } })} />Allow submissions on the deadline</label>
      <label>Duplicate handling<select value={draft.duplicates.flag} onChange={(event) => setDraft({ ...draft, duplicates: { ...draft.duplicates, flag: event.target.value as "all_matches" | "later_matches" } })}><option value="all_matches">Flag all matching claims</option><option value="later_matches">Flag later matching claims</option></select></label>
      <div className="duplicate-fields"><span>Match duplicates by</span>{["employee", "date", "category", "amount", "nights", "description"].map((field) => <label className="policy-checkbox" key={field}><input type="checkbox" checked={draft.duplicates.key_fields.includes(field)} onChange={(event) => setDraft({ ...draft, duplicates: { ...draft.duplicates, key_fields: event.target.checked ? [...draft.duplicates.key_fields, field] : draft.duplicates.key_fields.filter((value) => value !== field) } })} />{categoryLabel(field)}</label>)}</div>
      <div className="policy-library-footer"><Button variant="outline" type="button" onClick={() => setDraft(null)}>Cancel</Button><Button type="submit" disabled={!draft.duplicates.key_fields.length}>{busy && <Loader2 size={15} className="spin" />}{busy ? "Saving…" : "Save policy"}</Button></div>
    </fieldset></form>}
  </section>;
}
