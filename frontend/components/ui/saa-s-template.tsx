import React, { useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine, ArrowRight, ArrowUpRight, Check, CheckCheck, ChevronDown,
  CircleAlert, CircleCheck, FileCheck2, FileText, Info, Layers3, Loader2,
  Menu, RefreshCw, Search, ShieldCheck, Users, X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { SourceFiles } from "@/components/source-files";
import { SubmittedExpenses, UserExpenseView } from "@/components/user-expense-view";
import { ExpenseReview } from "@/components/expense-review";
import { categoryLabel, dateLabel, money, readReport, reportQuery, apiJson, type DemoUser, type Claim, type Grouping, type Report, type ReportGroup } from "@/lib/report";

// Adapted from the supplied SaaS template: fixed dark navigation, gradient hero,
// soft light effects, responsive menu, and a white gradient primary action.
function Brand({ onHome }: { onHome: () => void }) {
  return <a href="#overview" className="brand" aria-label="ExpenseCheck overview" onClick={onHome}>
    <span className="brand-mark"><CheckCheck size={21} strokeWidth={2.2} /></span>
    <span>Expense<span className="brand-light">Check</span><span className="brand-dot">.</span></span>
  </a>;
}

const Navigation = React.memo(function Navigation({ issueCount, openPolicy, openIssues, view, onView, user, onLogout }: {
  issueCount: number; openPolicy: () => void; openIssues: () => void;
  view: "review" | "submit"; onView: (view: "review" | "submit") => void;
  user: DemoUser; onLogout: () => void;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  return <header className="site-header">
    <nav className="header-inner" aria-label="Main navigation">
      <Brand onHome={() => onView(user.role === "reviewer" ? "review" : "submit")} />
      <div className={`navigation-links ${mobileOpen ? "is-open" : ""}`}>
        {user.role === "reviewer" && <a href="#overview" className={view === "review" ? "nav-active" : ""} onClick={() => { onView("review"); setMobileOpen(false); }}>Reviewer view</a>}
        <button className={view === "submit" ? "nav-active" : ""} aria-pressed={view === "submit"} onClick={() => { onView("submit"); setMobileOpen(false); }}>User view</button>
        {user.role === "reviewer" && <a href="#reports" onClick={() => { onView("review"); setMobileOpen(false); }}>Reports</a>}
        <button onClick={() => { openPolicy(); setMobileOpen(false); }}>Policy <ArrowUpRight size={12} /></button>
        {user.role === "reviewer" && <button onClick={() => { openIssues(); setMobileOpen(false); }}>Input issues <span className="nav-count">{issueCount}</span></button>}
      </div>
      <div className="workspace-label"><span className="status-dot" /><span className="account-name">{user.name}</span><button onClick={onLogout}>Switch account</button></div>
      <button className="mobile-toggle" onClick={() => setMobileOpen(!mobileOpen)} aria-label={mobileOpen ? "Close menu" : "Open menu"} aria-expanded={mobileOpen}>
        {mobileOpen ? <X size={22} /> : <Menu size={22} />}
      </button>
    </nav>
  </header>;
});

function Hero({ report, busy, refresh, review }: { report: Report | null; busy: boolean; refresh: () => void; review: () => void }) {
  const overview = report?.overview;
  const percent = overview?.accepted_count ? Math.round(overview.flagged_count / overview.accepted_count * 100) : 0;
  return <section className="hero" id="overview">
    <div className="hero-glow" aria-hidden="true" />
    <div className="hero-copy">
      <div className="eyebrow"><span className="eyebrow-dot" />A LITTLE AUTOMATION. A LOT MORE CLARITY.</div>
      <h1>A clearer view<br />of every expense<span>.</span></h1>
      <p>Your policy. Every claim. One place to see<br className="desktop-break" /> what needs a closer look.</p>
      <div className="hero-actions">
        <Button className="gradient-button" onClick={review}>Review flagged claims <ArrowRight size={15} /></Button>
        <Button variant="ghost" className="refresh-button" onClick={refresh} disabled={busy}><RefreshCw size={14} className={busy ? "spin" : ""} /> Refresh report</Button>
      </div>
      <div className="hero-footnote"><ShieldCheck size={14} /><span>Powered by your policy. Reviewed by you.</span></div>
    </div>
    <div className="snapshot-card">
      <img src="/office.jpg" className="snapshot-photo" alt="" aria-hidden="true" />
      <div className="snapshot-shade" />
      <div className="snapshot-top"><span><Layers3 size={14} /> REVIEW SNAPSHOT</span><span className="snapshot-live"><span className="status-dot" />{report ? "Up to date" : "Connecting"}</span></div>
      <div className="snapshot-middle"><span className="snapshot-icon"><FileCheck2 size={22} /></span><h2>A faster first pass.<br /><span>A more focused review.</span></h2></div>
      <div className="snapshot-bottom">
        <div className="snapshot-stats"><span><strong>{overview?.accepted_count ?? "—"}</strong> claims checked</span><span><strong>{overview?.flagged_count ?? "—"}</strong> need review</span></div>
        <div className="snapshot-progress" role="img" aria-label={`${percent}% of accepted claims flagged`}><span style={{ width: `${percent}%` }} /></div>
        <div className="snapshot-legend"><span><i className="legend-purple" />Flagged</span><span><i className="legend-neutral" />Unflagged by active checks</span></div>
      </div>
    </div>
  </section>;
}

function Metrics({ report }: { report: Report | null }) {
  const overview = report?.overview;
  const cards = [
    { label: "Claims checked", value: overview?.accepted_count ?? "—", detail: overview ? `${overview.unflagged_count} unflagged by active checks` : "Reading expense records", icon: FileText, color: "neutral" },
    { label: "Need a closer look", value: overview?.flagged_count ?? "—", detail: overview ? `${overview.violation_count} policy flags to review` : "Checking your policy", icon: CircleAlert, color: "purple" },
    { label: "Total flagged amount", value: report ? money(report.overview.total_flagged_amount, report.currency) : "—", detail: "Each claim counted once", icon: Layers3, color: "neutral" },
    { label: "Input issues", value: overview?.rejected_count ?? "—", detail: "Rows to correct before review", icon: FileCheck2, color: "amber" },
  ];
  return <section className="metrics-grid" aria-label="Complete source summary">{cards.map(({ label, value, detail, icon: Icon, color }) =>
    <div className={`metric-card metric-${color}`} key={label}><div className="metric-heading"><span>{label}</span><Icon size={15} /></div><div className="metric-value">{value}</div><div className="metric-detail">{detail}</div></div>,
  )}</section>;
}

function RuleBadge({ name, id }: { name: string; id: string }) {
  return <Badge variant="outline" className={`rule-badge rule-${id}`}>{name}</Badge>;
}

function ClaimGroup({ group, grouping, currency, onClaim }: { group: ReportGroup; grouping: Grouping; currency: string; onClaim: (claim: Claim) => void }) {
  const [collapsed, setCollapsed] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const claims = showAll ? group.claims : group.claims.slice(0, 4);
  const initials = group.name.split(" ").map((word) => word[0]).slice(0, 2).join("");
  return <section className="claim-group">
    <button className="group-heading" aria-expanded={!collapsed} onClick={() => setCollapsed(!collapsed)}>
      <span className={`group-avatar ${grouping === "rule" ? "rule-avatar" : ""}`}>{grouping === "employee" ? initials : <ShieldCheck size={17} />}</span>
      <span className="group-name">{group.name}<small>{group.claims.length} flagged {group.claims.length === 1 ? "claim" : "claims"}</small></span>
      <span className="group-amount">{money(group.total_amount, currency)}<small>flagged amount</small></span>
      <ChevronDown size={15} className={collapsed ? "is-collapsed" : ""} />
    </button>
    {!collapsed && <>
      <div className="claim-columns"><span>CLAIM DETAILS</span><span>POLICY FLAGS</span><span>AMOUNT</span></div>
      {claims.map((claim) => <button className="claim-row" key={claim.id} onClick={() => onClaim(claim)} aria-label={`View expense ${claim.id}`}>
        <span className="claim-identity"><span className="claim-category-icon"><FileText size={15} /></span><span><strong>{categoryLabel(claim.category)}<span className="claim-id">{claim.id}</span></strong><small>{grouping === "rule" ? `${claim.employee} · ` : ""}{dateLabel(claim.date)} · {claim.description}</small></span></span>
        <span className="claim-badges">{claim.violations.map((violation, i) => <RuleBadge key={`${violation.rule_id}-${i}`} id={violation.rule_id} name={violation.rule_name} />)}</span>
        <span className="claim-amount">{money(claim.amount, currency)}<ArrowUpRight size={13} /></span>
      </button>)}
      {group.claims.length > 4 && <button className="show-more" onClick={() => setShowAll(!showAll)}>{showAll ? "Show fewer claims" : `Show ${group.claims.length - 4} more claims`}<ChevronDown size={13} className={showAll ? "rotate-180" : ""} /></button>}
    </>}
  </section>;
}

function ClaimDetails({ claim, report, close, user, onSaved }: { claim: Claim | null; report: Report | null; close: () => void; user: DemoUser; onSaved: (report: Report) => void }) {
  // Rule-group rows include only that rule's reasons; the detail view always
  // retrieves the full claim so reviewers can inspect every reason together.
  const fullClaim = report?.claims.find((item) => item.id === claim?.id) ?? claim;
  return <Dialog open={!!claim} onOpenChange={(open) => { if (!open) close(); }}><DialogContent className="detail-dialog">
    <DialogHeader><div className="dialog-eyebrow"><FileText size={15} /> CLAIM DETAILS</div><DialogTitle>{fullClaim?.id}</DialogTitle><DialogDescription>Review the claim, supporting receipt, and policy check results.</DialogDescription></DialogHeader>
    {fullClaim && report && <>
      <div className="detail-amount">{money(fullClaim.amount, report.currency)}<Badge className="detail-status" variant="outline">{fullClaim.status === "flagged" ? "Needs review" : "Unflagged by active checks"}</Badge></div>
      <dl className="detail-grid"><div><dt>Employee</dt><dd>{fullClaim.employee}</dd></div><div><dt>Expense date</dt><dd>{fullClaim.date}</dd></div><div><dt>Category</dt><dd>{categoryLabel(fullClaim.category)}</dd></div><div><dt>Receipt attached</dt><dd>{fullClaim.receipt_attached ? "Yes" : "No"}</dd></div></dl>
      <div className="detail-description"><span>Description</span><p>{fullClaim.description}</p></div>
      {fullClaim.nights !== null && <p className="detail-description">Number of nights: {fullClaim.nights}</p>}
      {fullClaim.receipt && <a className="receipt-download" href={fullClaim.receipt.download_url} download><ArrowDownToLine size={16} /><span>Download receipt: {fullClaim.receipt.name}</span></a>}
      <div className="detail-reasons"><h3>{fullClaim.violations.length ? "Why this claim needs attention" : "No violations detected by active checks"}</h3>{fullClaim.violations.map((violation, index) => <div className="detail-reason" key={`${violation.rule_id}-${index}`}><CircleAlert size={16} /><div><strong>{violation.rule_name}</strong><p>{violation.reason}</p></div></div>)}</div>
      <p className="review-guidance"><Info size={14} />Verify the supporting information before deciding how to handle this claim.</p>
      <ExpenseReview key={fullClaim.revision_id} claim={fullClaim} report={report} user={user} onSaved={onSaved} />
    </>}
  </DialogContent></Dialog>;
}

function PolicyDetails({ open, close, report }: { open: boolean; close: () => void; report: Report | null }) {
  return <Dialog open={open} onOpenChange={(value) => { if (!value) close(); }}><DialogContent className="detail-dialog policy-dialog">
    <DialogHeader><div className="dialog-eyebrow"><ShieldCheck size={15} /> YOUR ACTIVE POLICY</div><DialogTitle>{report?.policy.name ?? "Expense policy"}</DialogTitle><DialogDescription>Current limits are read from the active policy file.</DialogDescription></DialogHeader>
    {report ? <><div className="policy-version"><span>Version {report.policy.version}</span><span>{report.currency}</span></div>
      <div className="policy-categories">{Object.entries(report.policy.categories).map(([name, settings]) => <div key={name}><strong>{categoryLabel(name)}</strong><span>{settings.max_amount === null ? "No configured limit" : `${money(settings.max_amount, report.currency)} / ${settings.limit_basis === "per_night" ? "night" : "claim"}`}<small>{settings.receipt.mode === "always" ? "Receipt always required" : settings.receipt.mode === "above_threshold" ? `Receipt above ${money(settings.receipt.threshold!, report.currency)}` : "Receipt rule unconfigured"}</small></span></div>)}</div>
      <div className="active-checks"><span>Active checks</span>{report.policy.active_rules.map((rule) => <Badge key={rule} variant="outline"><Check size={11} />{rule}</Badge>)}</div>
      <p className="review-guidance"><Info size={14} />Automated checks are a first pass. Verify supporting information before approving a claim.</p></> : <p>Load a report to view its policy.</p>}
  </DialogContent></Dialog>;
}

export default function Component({ user, onLogout = () => {} }: { user: DemoUser; onLogout?: () => void }) {
  const [view, setView] = useState<"review" | "submit">(user.role === "reviewer" ? "review" : "submit");
  const [report, setReport] = useState<Report | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [grouping, setGrouping] = useState<Grouping>("employee");
  const [employee, setEmployee] = useState("");
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [refreshCount, setRefreshCount] = useState(0);
  const [dataset, setDataset] = useState<string | null>(() => localStorage.getItem(`expense-dataset-${user.id}`));
  const [datasets, setDatasets] = useState<{ id: string; expenses: string; policy: string }[]>([]);
  const [datasetsError, setDatasetsError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [selectedClaim, setSelectedClaim] = useState<Claim | null>(null);
  const [policyOpen, setPolicyOpen] = useState(false);
  const [issuesOpen, setIssuesOpen] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");
  const issuesRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (dataset) localStorage.setItem(`expense-dataset-${user.id}`, dataset);
    else localStorage.removeItem(`expense-dataset-${user.id}`);
    apiJson<typeof datasets>("/api/datasets").then(setDatasets).catch((problem) => setDatasetsError(problem.message));
  }, [dataset, user.id, user.role]);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 250);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    readReport(employee, debouncedSearch, controller.signal, dataset).then((data) => {
      if (controller.signal.aborted) return;
      setReport(data);
      setSelectedClaim(null);
      setLoading(false);
    }).catch((problem: Error) => {
      if (controller.signal.aborted) return;
      setError(problem.message);
      setLoading(false);
    });
    return () => controller.abort();
  }, [employee, debouncedSearch, refreshCount, dataset]);

  function changeSource(data: Report | null) {
    setDataset(data?.dataset_id ?? null);
    setEmployee("");
    setSearch("");
    setDebouncedSearch("");
    setSelectedClaim(null);
    setExportError("");
    setError("");
    setReport(data);
  }

  const refresh = () => setRefreshCount((value) => value + 1);
  const openIssues = () => {
    setView("review");
    setIssuesOpen(true);
    setTimeout(() => issuesRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
  };
  async function download() {
    setExporting(true);
    setExportError("");
    try {
      const query = reportQuery(employee, debouncedSearch, dataset);
      query.set("group_by", grouping);
      const response = await fetch(`/api/report/download?${query}`);
      if (!response.ok) throw new Error("The report could not be exported. Please retry.");
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `expense-report-${grouping}.txt`;
      anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (problem) {
      setExportError(problem instanceof Error ? problem.message : "Export failed.");
    } finally { setExporting(false); }
  }

  const groups = report?.groups[grouping] ?? [];
  const pending = loading || uploading || submitting || search !== debouncedSearch;
  return <div className="app-shell">
    <Navigation issueCount={report?.overview.rejected_count ?? 0} openPolicy={() => setPolicyOpen(true)} openIssues={openIssues} view={view} onView={setView} user={user} onLogout={onLogout} />
    <main className="dashboard-container">
      <label className="saved-datasets">Saved datasets<select aria-label="Saved datasets" disabled={pending} value={dataset ?? ""} onChange={(event) => { changeSource(null); setDataset(event.target.value || null); }}><option value="">Company sample</option>{datasets.map((item) => <option key={item.id} value={item.id}>{item.expenses} · {item.policy}</option>)}</select></label>
      {datasetsError && <p role="alert">Could not load saved datasets: {datasetsError}</p>}
      {error && <div className="error-banner" role="alert"><CircleAlert size={18} /><div><strong>We couldn't load your report.</strong><p>{error}</p></div><Button variant="outline" onClick={refresh}>Try again</Button></div>}
      <div hidden={view !== "submit"}><UserExpenseView key={dataset ?? "stored"} user={user} report={report} busy={pending || exporting || !!error} onBusy={setSubmitting} onSaved={changeSource} onClaim={setSelectedClaim} onReview={() => { setView("review"); setTimeout(() => document.getElementById("reports")?.scrollIntoView({ behavior: "smooth" }), 0); }} /></div>
      {user.role === "reviewer" && <div hidden={view !== "review"}>
      <Hero report={error ? null : report} busy={pending} refresh={refresh} review={() => document.getElementById("reports")?.scrollIntoView({ behavior: "smooth" })} />
      <SourceFiles report={report} busy={loading || exporting || submitting} onReport={changeSource} onSamples={() => changeSource(null)} onBusy={setUploading} />
      <Metrics report={error ? null : report} />
      <section className="reports-section" id="reports" aria-busy={pending}>
        <div className="section-heading"><div><div className="section-eyebrow">THE EXCEPTIONS, IN FOCUS</div><h2>Claims to review <span className="heading-count">{report?.overview.flagged_count ?? "—"}</span></h2><p>A little context makes the next decision clearer.</p></div>
          <Button variant="outline" className="export-button" disabled={!report || pending || !!error || exporting} onClick={download}>{exporting ? <Loader2 size={14} className="spin" /> : <ArrowDownToLine size={14} />}Export report</Button>
        </div>
        <Tabs className="report-workspace" value={grouping} onValueChange={(value) => setGrouping(value as Grouping)}>
          <div className="report-toolbar"><TabsList className="grouping-tabs"><TabsTrigger value="employee"><Users size={14} />By employee</TabsTrigger><TabsTrigger value="rule"><ShieldCheck size={14} />By policy rule</TabsTrigger></TabsList><span className="report-currency">{report?.currency ?? "—"}<span className="status-dot" />Live report</span></div>
          <div className="filter-bar"><label className="search-field"><Search size={16} /><input aria-label="Search claims" disabled={uploading} value={search} maxLength={200} onChange={(event) => setSearch(event.target.value)} placeholder="Search claims, categories, or descriptions…" />{search && <button disabled={uploading} onClick={() => setSearch("")} aria-label="Clear search"><X size={14} /></button>}</label><label className="employee-filter"><Users size={14} /><select aria-label="Filter by employee" disabled={uploading} value={employee} onChange={(event) => setEmployee(event.target.value)}><option value="">All employees</option>{report?.employees.map((name) => <option value={name} key={name}>{name}</option>)}</select><ChevronDown size={13} /></label></div>
          <div className="results-description"><span>{pending ? <><Loader2 size={12} className="spin" />Updating report…</> : report && !error ? <>Showing <strong>{report.summary.flagged_count}</strong> of {report.overview.flagged_count} flagged claims{(employee || debouncedSearch) && <button className="clear-filters" onClick={() => { setEmployee(""); setSearch(""); }}>Clear filters</button>}</> : "Your report will appear here"}</span><span>{grouping === "rule" ? "Claims can appear under multiple rules" : "Full claim amounts · no double counting"}</span></div>
          {exportError && <p className="export-error" role="alert">{exportError}</p>}
          <TabsContent value={grouping}>
          {loading && !report ? <div className="report-skeleton" role="status" aria-label="Loading report">{[0, 1, 2].map((i) => <div key={i} />)}</div> : error ? <div className="empty-state"><CircleAlert size={28} /><h3>Report unavailable</h3><p>Check your data connection and try again.</p></div> : groups.length ? <div className={pending ? "groups-list is-updating" : "groups-list"}>{groups.map((group) => <ClaimGroup key={`${dataset}-${grouping}-${group.id}-${employee}-${debouncedSearch}`} group={group} grouping={grouping} currency={report!.currency} onClaim={setSelectedClaim} />)}</div> : <div className="empty-state"><CircleCheck size={29} /><h3>{employee || debouncedSearch ? "No matching flagged claims" : "No flags from the active checks"}</h3><p>{employee || debouncedSearch ? "Try another employee or search term." : "Continue your manual review for other policy conditions."}</p>{(employee || debouncedSearch) && <Button variant="outline" onClick={() => { setEmployee(""); setSearch(""); }}>Clear filters</Button>}</div>}
          </TabsContent>
          <div className="workspace-footer"><ShieldCheck size={13} /><span>Automated checks are a first pass. Final decisions stay with your finance team.</span><span className="footer-reasons">{report?.overview.violation_count ?? "—"} total reasons</span></div>
        </Tabs>
      </section>
      {!!report?.claims.length && <SubmittedExpenses report={report} all onClaim={setSelectedClaim} />}
      <section ref={issuesRef} id="input-issues" className="input-issues">
        <button className="issues-heading" onClick={() => setIssuesOpen(!issuesOpen)} aria-expanded={issuesOpen}><span className="issues-icon"><CircleAlert size={19} /></span><span><strong>{report?.errors.length ? "A few records need fixing" : "Input records"} <Badge variant="outline">{report?.errors.length ?? 0}</Badge></strong><small>Rejected rows across the source file. Correct these before policy review.</small></span><span className="issues-toggle">{issuesOpen ? "Hide details" : "View details"}<ChevronDown size={15} className={issuesOpen ? "rotate-180" : ""} /></span></button>
        {issuesOpen && <div className="issues-list">{report?.errors.length ? report.errors.map((issue) => <div className="issue-row" key={issue.line_number}><span className="issue-line">Line {issue.line_number}</span><strong>{issue.expense_id ?? "ID unavailable"}</strong><span>{issue.reasons.join(" · ")}</span></div>) : <div className="no-issues"><Check size={15} />No rejected records in the source file.</div>}</div>}
      </section>
      <footer className="page-footer"><span><ShieldCheck size={13} />Expense Policy Checker</span><span>{report ? <>{report.sources.expenses}<span className="footer-dot">·</span>Updated {new Date(report.generated_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</> : "Connecting to your expense records"}</span><button onClick={() => setPolicyOpen(true)}>View active policy<ArrowUpRight size={12} /></button></footer>
      </div>}
    </main>
    <ClaimDetails claim={selectedClaim} report={report} close={() => setSelectedClaim(null)} user={user} onSaved={(data) => { changeSource(data); setSelectedClaim(data.claims.find((item) => item.id === selectedClaim?.id) ?? null); }} />
    <PolicyDetails open={policyOpen} report={report} close={() => setPolicyOpen(false)} />
  </div>;
}
