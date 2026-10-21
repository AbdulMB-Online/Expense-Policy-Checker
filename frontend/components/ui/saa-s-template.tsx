import React, { useEffect, useState } from "react";
import {
  ArrowDownToLine, ArrowRight, CheckCheck, ChevronDown, CircleAlert, CircleCheck, FileText, Loader2,
  Menu, RefreshCw, Search, ShieldCheck, Users, X, LayoutDashboard, ReceiptText, Upload, LogOut, Utensils, Plane, BedDouble, Car, ShoppingBag, Check,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ReportAssistant } from "@/components/report-assistant";
import { PolicyLibrary } from "@/components/policy-library";
import { ThemeToggle } from "@/components/theme-toggle";
import { SourceFiles } from "@/components/source-files";
import { SubmittedExpenses, UserExpenseView } from "@/components/user-expense-view";
import { ExpenseReview } from "@/components/expense-review";
import { categoryLabel, dateLabel, money, readReport, reportQuery, apiJson, type DemoUser, type Claim, type Grouping, type Report, type ReportGroup } from "@/lib/report";

const reviewerTabs = [
  { id: "overview", label: "Overview", icon: LayoutDashboard },
  { id: "reports", label: "Claims to review", icon: FileText },
  { id: "expenses", label: "All expenses", icon: ReceiptText },
  { id: "imports", label: "Import files", icon: Upload },
  { id: "issues", label: "Input issues", icon: CircleAlert },
];
const employeeTabs = [
  { id: "submit", label: "Submit expense", icon: Upload },
  { id: "expenses", label: "My expenses", icon: ReceiptText },
];

function initialsOf(name: string) {
  return name.split(" ").map((word) => word[0]).slice(0, 2).join("");
}

function Brand({ onHome }: { onHome: () => void }) {
  return <a href="#main-content" className="brand" aria-label="ExpenseCheck overview" onClick={onHome}>
    <span className="brand-mark"><CheckCheck size={18} strokeWidth={2.5} /></span>
    <span>expensecheck</span>
  </a>;
}

const Navigation = React.memo(function Navigation({ issueCount, openPolicy, activeTab, onTabChange, user, onLogout }: {
  issueCount: number; openPolicy: () => void; activeTab: string; onTabChange: (tab: string) => void;
  user: DemoUser; onLogout: () => void;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  return <header className="site-header">
    <nav className="header-inner" aria-label="Main navigation">
      <Brand onHome={() => { onTabChange(user.role === "reviewer" ? "overview" : "submit"); setMobileOpen(false); }} />
      <div className={`navigation-links ${mobileOpen ? "is-open" : ""}`}>
        {(user.role === "reviewer" ? reviewerTabs : employeeTabs).map(({ id, label, icon: Icon }) => <button key={id} className={activeTab === id ? "nav-active" : ""} aria-current={activeTab === id ? "page" : undefined} onClick={() => { onTabChange(id); setMobileOpen(false); }}><Icon size={17} />{label}{id === "issues" && issueCount > 0 && <span className="nav-count">{issueCount}</span>}</button>)}
        <button className="nav-secondary" onClick={() => { openPolicy(); setMobileOpen(false); }}><ShieldCheck size={17} />Policy</button>
      </div>
      <div className="workspace-label">
        <span className="workspace-avatar" aria-hidden="true">{initialsOf(user.name)}</span>
        <span className="account-name"><span>{user.name}</span><small>{user.role === "reviewer" ? "Finance" : "Employee"}</small></span>
        <button className="icon-button" onClick={onLogout} aria-label="Switch account" title="Switch account"><LogOut size={16} /></button>
      </div>
      <button className="mobile-toggle icon-button" onClick={() => setMobileOpen(!mobileOpen)} aria-label={mobileOpen ? "Close menu" : "Open menu"} aria-expanded={mobileOpen}>
        {mobileOpen ? <X size={20} /> : <Menu size={20} />}
      </button>
    </nav>
  </header>;
});

function updatedAt(report: Report) {
  return new Date(report.generated_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function Hero({ report, busy, refresh, review }: { report: Report | null; busy: boolean; refresh: () => void; review: () => void }) {
  const overview = report?.overview;
  const percent = overview?.accepted_count ? Math.round(overview.flagged_count / overview.accepted_count * 100) : 0;
  const headline = !overview ? "Loading your report…"
    : overview.flagged_count ? `${overview.flagged_count} ${overview.flagged_count === 1 ? "claim needs" : "claims need"} a closer look`
    : "Nothing flagged right now";
  return <section className="hero" id="overview" aria-labelledby="overview-title">
    <h1 id="overview-title">{headline}</h1>
    <p className="hero-meta">{report && <span>Checked against {report.policy.name}, updated {updatedAt(report)}</span>}<Button variant="ghost" className="refresh-button" onClick={refresh} disabled={busy} aria-label="Refresh report"><RefreshCw size={14} className={busy ? "spin" : ""} />Refresh</Button></p>
    <div className="check-track" role="img" aria-label={`${percent}% of checked claims flagged`}><span style={{ width: `${percent}%` }} /></div>
    <div className="check-legend"><span><i />{overview?.flagged_count ?? "—"} flagged</span><span><i />{overview?.unflagged_count ?? "—"} clear</span></div>
    <Button className="summary-action" onClick={review}>Review flagged claims<ArrowRight size={16} /></Button>
  </section>;
}

function Metrics({ report }: { report: Report | null }) {
  const overview = report?.overview;
  const cards = [
    { label: "Claims checked", value: overview?.accepted_count ?? "—", tone: "neutral" },
    { label: "Policy flags", value: overview?.violation_count ?? "—", tone: "flag" },
    { label: "Flagged amount", value: report ? money(report.overview.total_flagged_amount, report.currency) : "—", tone: "neutral" },
    { label: "Input issues", value: overview?.rejected_count ?? "—", tone: "issue" },
  ];
  return <section className="metrics-grid" aria-label="Report summary">{cards.map(({ label, value, tone }) =>
    <div className={`metric-card metric-${tone}`} key={label}><div className="metric-value">{value}</div><div className="metric-heading">{label}</div></div>,
  )}</section>;
}

function CategoryIcon({ category }: { category: string }) {
  const Icon = /meal|food/i.test(category) ? Utensils : /hotel|lodg/i.test(category) ? BedDouble : /flight|air/i.test(category) ? Plane : /taxi|transport|mileage/i.test(category) ? Car : /office|suppl/i.test(category) ? ShoppingBag : ReceiptText;
  return <Icon size={17} strokeWidth={1.7} />;
}

function RuleBadge({ name, id }: { name: string; id: string }) {
  return <Badge variant="outline" className={`rule-badge rule-${id}`}>{name}</Badge>;
}

function ClaimGroup({ group, grouping, currency, onClaim }: { group: ReportGroup; grouping: Grouping; currency: string; onClaim: (claim: Claim) => void }) {
  const [collapsed, setCollapsed] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const claims = showAll ? group.claims : group.claims.slice(0, 4);
  return <section className="claim-group">
    <button className="group-heading" aria-expanded={!collapsed} onClick={() => setCollapsed(!collapsed)}>
      <span className={`group-avatar ${grouping === "rule" ? "rule-avatar" : ""}`}>{grouping === "employee" ? initialsOf(group.name) : <ShieldCheck size={16} />}</span>
      <span className="group-name">{group.name}<small>{group.claims.length} flagged {group.claims.length === 1 ? "claim" : "claims"}</small></span>
      <span className="group-amount">{money(group.total_amount, currency)}</span>
      <ChevronDown size={16} className={collapsed ? "is-collapsed" : ""} />
    </button>
    {!collapsed && <div className="claim-rows">
      {claims.map((claim) => <button className="claim-row" key={claim.id} onClick={() => onClaim(claim)} aria-label={`View expense ${claim.id}`}>
        <span className="claim-identity"><span className="claim-category-icon"><CategoryIcon category={claim.category} /></span><span><strong>{claim.description}</strong><small>{grouping === "rule" && <span>{claim.employee}</span>}<span>{categoryLabel(claim.category)}</span><span>{dateLabel(claim.date)}</span><span className="claim-id">{claim.id}</span></small></span></span>
        <span className="claim-badges">{claim.violations.map((violation, i) => <RuleBadge key={`${violation.rule_id}-${i}`} id={violation.rule_id} name={violation.rule_name} />)}</span>
        <span className="claim-amount">{money(claim.amount, currency)}</span>
      </button>)}
      {group.claims.length > 4 && <button className="show-more" onClick={() => setShowAll(!showAll)}>{showAll ? "Show fewer claims" : `Show ${group.claims.length - 4} more claims`}<ChevronDown size={14} className={showAll ? "rotate-180" : ""} /></button>}
    </div>}
  </section>;
}

function ClaimDetails({ claim, report, close, user, onSaved }: { claim: Claim | null; report: Report | null; close: () => void; user: DemoUser; onSaved: (report: Report) => void }) {
  // Rule-group rows include only that rule's reasons; the detail view always
  // retrieves the full claim so reviewers can inspect every reason together.
  const fullClaim = report?.claims.find((item) => item.id === claim?.id) ?? claim;
  return <Dialog open={!!claim} onOpenChange={(open) => { if (!open) close(); }}><DialogContent className="claim-dialog">
    <div className="receipt-stub">
      <DialogHeader><DialogTitle>{fullClaim?.id}</DialogTitle><DialogDescription>{fullClaim ? `${fullClaim.employee}, ${dateLabel(fullClaim.date)}` : ""}</DialogDescription></DialogHeader>
      {fullClaim && report && <div className="detail-amount"><span>{money(fullClaim.amount, report.currency)}</span><Badge className={`detail-status ${fullClaim.status}`} variant="outline">{fullClaim.status === "flagged" ? "Needs review" : "No flags"}</Badge></div>}
    </div>
    {fullClaim && report && <div className="receipt-body">
      <p className="detail-description">{fullClaim.description}</p>
      <dl className="detail-grid">
        <div><dt>Category</dt><dd>{categoryLabel(fullClaim.category)}</dd></div>
        <div><dt>Receipt</dt><dd>{fullClaim.receipt_attached ? "Attached" : "Missing"}</dd></div>
        {fullClaim.nights !== null && <div><dt>Nights</dt><dd>{fullClaim.nights}</dd></div>}
      </dl>
      {fullClaim.receipt && <a className="receipt-download" href={fullClaim.receipt.download_url} download><ArrowDownToLine size={15} /><span>Download receipt: {fullClaim.receipt.name}</span></a>}
      <div className="detail-reasons"><h3>{fullClaim.violations.length ? "Why it was flagged" : "No violations detected by active checks"}</h3>{fullClaim.violations.map((violation, index) => <div className="detail-reason" key={`${violation.rule_id}-${index}`}><CircleAlert size={16} /><div><strong>{violation.rule_name}</strong><p>{violation.reason}</p></div></div>)}</div>
      <ExpenseReview key={fullClaim.revision_id} claim={fullClaim} report={report} user={user} onSaved={onSaved} />
    </div>}
  </DialogContent></Dialog>;
}

function PolicyDetails({ open, close, report }: { open: boolean; close: () => void; report: Report | null }) {
  return <Dialog open={open} onOpenChange={(value) => { if (!value) close(); }}><DialogContent className="detail-dialog policy-dialog">
    <DialogHeader><DialogTitle>{report?.policy.name ?? "Expense policy"}</DialogTitle><DialogDescription>{report ? `Version ${report.policy.version}, amounts in ${report.currency}` : "No policy loaded yet."}</DialogDescription></DialogHeader>
    {report && <>
      <div className="policy-categories">{Object.entries(report.policy.categories).map(([name, settings]) => <div key={name}><strong>{categoryLabel(name)}</strong><span>{settings.max_amount === null ? "No limit" : `${money(settings.max_amount, report.currency)} / ${settings.limit_basis === "per_night" ? "night" : "claim"}`}<small>{settings.receipt.mode === "always" ? "Receipt always required" : settings.receipt.mode === "above_threshold" ? `Receipt above ${money(settings.receipt.threshold!, report.currency)}` : "No receipt rule"}</small></span></div>)}</div>
      <div className="active-checks"><span>Active checks</span>{report.policy.active_rules.map((rule) => <Badge key={rule} variant="outline"><Check size={11} />{rule}</Badge>)}</div>
    </>}
  </DialogContent></Dialog>;
}

export default function Component({ user, onLogout = () => {} }: { user: DemoUser; onLogout?: () => void }) {
  const [activeTab, setActiveTab] = useState(user.role === "reviewer" ? "overview" : "submit");
  const workspaceTabs = user.role === "reviewer" ? reviewerTabs : employeeTabs;
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
  const [libraryOpen, setLibraryOpen] = useState(false);
  const [policyOpen, setPolicyOpen] = useState(false);
  const [issuesOpen, setIssuesOpen] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");


  useEffect(() => {
    if (dataset) localStorage.setItem(`expense-dataset-${user.id}`, dataset);
    else localStorage.removeItem(`expense-dataset-${user.id}`);
    if (user.role === "reviewer") apiJson<typeof datasets>("/api/datasets").then(setDatasets).catch((problem) => setDatasetsError(problem.message));
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
  const filtered = !!(employee || debouncedSearch);
  const clearFilters = () => { setEmployee(""); setSearch(""); };
  return <div className="app-shell">
    <a className="skip-link" href="#main-content">Skip to content</a>
    <Navigation issueCount={report?.overview.rejected_count ?? 0} openPolicy={() => user.role === "reviewer" ? setLibraryOpen(true) : setPolicyOpen(true)} activeTab={activeTab} onTabChange={setActiveTab} user={user} onLogout={onLogout} />
    <main className="dashboard-container" id="main-content">
      <div className="workspace-controls">{user.role === "reviewer" && report && !pending && !error && <ReportAssistant report={report} employee={employee} search={debouncedSearch} onClaim={setSelectedClaim} />}<ThemeToggle /></div>
      {error && <div className="error-banner" role="alert"><CircleAlert size={18} /><div><strong>We couldn't load your report.</strong><p>{error}</p></div><Button variant="outline" onClick={refresh}>Try again</Button></div>}
      <Tabs className="workspace-tabs" value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="workspace-tab-list" aria-label="Workspace sections">{workspaceTabs.map(({ id, label }) => <TabsTrigger key={id} value={id}>{label}</TabsTrigger>)}</TabsList>
        {user.role === "employee" && <>
          <TabsContent value="submit" forceMount hidden={activeTab !== "submit"}><UserExpenseView key={dataset ?? "stored"} user={user} report={report} busy={pending || exporting || !!error} onBusy={setSubmitting} onSaved={changeSource} onClaim={setSelectedClaim} showSubmitted={false} /></TabsContent>
          <TabsContent value="expenses" forceMount hidden={activeTab !== "expenses"}><header className="workspace-page-heading"><h1>My expenses {report && <span className="heading-count">{report.claims.length}</span>}</h1></header>{report && <SubmittedExpenses report={report} onClaim={setSelectedClaim} />}</TabsContent>
        </>}
        {user.role === "reviewer" && <>
          <TabsContent value="overview" forceMount hidden={activeTab !== "overview"}>
            <Hero report={error ? null : report} busy={pending} refresh={refresh} review={() => setActiveTab("reports")} />
            <Metrics report={error ? null : report} />
          </TabsContent>
          <TabsContent value="reports" forceMount hidden={activeTab !== "reports"}>
            <section className="reports-section" id="reports" aria-busy={pending}>
              <header className="workspace-page-heading"><h1>Claims to review <span className="heading-count">{report?.overview.flagged_count ?? "—"}</span></h1></header>
              <Tabs className="report-workspace" value={grouping} onValueChange={(value) => setGrouping(value as Grouping)}>
                <div className="report-toolbar">
                  <TabsList className="grouping-tabs"><TabsTrigger value="employee"><Users size={14} />By employee</TabsTrigger><TabsTrigger value="rule"><ShieldCheck size={14} />By policy rule</TabsTrigger></TabsList>
                  <label className="search-field"><Search size={16} /><input aria-label="Search claims" disabled={uploading} value={search} maxLength={200} onChange={(event) => setSearch(event.target.value)} placeholder="Search claims" />{search && <button disabled={uploading} onClick={() => setSearch("")} aria-label="Clear search"><X size={14} /></button>}</label>
                  <label className="employee-filter"><select aria-label="Filter by employee" disabled={uploading} value={employee} onChange={(event) => setEmployee(event.target.value)}><option value="">All employees</option>{report?.employees.map((name) => <option value={name} key={name}>{name}</option>)}</select></label>
                  <Button variant="outline" className="export-button" disabled={!report || pending || !!error || exporting} onClick={download}>{exporting ? <Loader2 size={14} className="spin" /> : <ArrowDownToLine size={14} />}Export report</Button>
                </div>
                <div className="results-description" aria-live="polite">{pending ? <><Loader2 size={13} className="spin" />Updating…</> : report && !error && filtered ? <>Showing {report.summary.flagged_count} of {report.overview.flagged_count}<button className="clear-filters" onClick={clearFilters}>Clear filters</button></> : null}</div>
                {exportError && <p className="export-error" role="alert">{exportError}</p>}
                <TabsContent value={grouping}>
                  {loading && !report ? <div className="report-skeleton" role="status" aria-label="Loading report">{[0, 1, 2].map((i) => <div key={i} />)}</div>
                    : error ? <div className="empty-state"><CircleAlert size={26} /><h3>Report unavailable</h3><p>Check your connection and try again.</p></div>
                    : groups.length ? <div className={pending ? "groups-list is-updating" : "groups-list"}>{groups.map((group) => <ClaimGroup key={`${dataset}-${grouping}-${group.id}-${employee}-${debouncedSearch}`} group={group} grouping={grouping} currency={report!.currency} onClaim={setSelectedClaim} />)}</div>
                    : <div className="empty-state"><CircleCheck size={26} /><h3>{filtered ? "No matching flagged claims" : "No flags from the active checks"}</h3>{filtered && <><p>Try another employee or search term.</p><Button variant="outline" onClick={clearFilters}>Clear filters</Button></>}</div>}
                </TabsContent>
              </Tabs>
            </section>
          </TabsContent>
          <TabsContent value="expenses" forceMount hidden={activeTab !== "expenses"}><header className="workspace-page-heading"><h1>All expenses {report && <span className="heading-count">{report.claims.length}</span>}</h1></header>{report && <SubmittedExpenses report={report} all onClaim={setSelectedClaim} />}</TabsContent>
          <TabsContent value="imports" forceMount hidden={activeTab !== "imports"}><header className="workspace-page-heading"><h1>Import files</h1><p>Check a new expense file or policy, or reopen an earlier import.</p></header>
            <SourceFiles report={report} busy={loading || exporting || submitting} onReport={changeSource} onSamples={() => changeSource(null)} onBusy={setUploading}>
              <div className="source-saved-files"><label className="saved-datasets">Earlier imports<select aria-label="Saved datasets" disabled={pending} value={dataset ?? ""} onChange={(event) => { changeSource(null); setDataset(event.target.value || null); }}><option value="">Company sample</option>{datasets.map((item) => <option key={item.id} value={item.id}>{item.expenses} with {item.policy}</option>)}</select></label>{datasetsError && <p role="alert">Could not load earlier imports: {datasetsError}</p>}</div>
            </SourceFiles>
          </TabsContent>
          <TabsContent value="issues" forceMount hidden={activeTab !== "issues"}><header className="workspace-page-heading"><h1>Input issues</h1><p>Rows in the expense file that couldn't be checked.</p></header>
            <section id="input-issues" className="input-issues">
              <button className="issues-heading" onClick={() => setIssuesOpen(!issuesOpen)} aria-expanded={issuesOpen}><span><strong>{report?.errors.length ? "A few records need fixing" : "Input records"}</strong><Badge variant="outline">{report?.errors.length ?? 0}</Badge></span><span className="issues-toggle">{issuesOpen ? "Hide" : "Show"}<ChevronDown size={15} className={issuesOpen ? "rotate-180" : ""} /></span></button>
              {issuesOpen && <div className="issues-list">{report?.errors.length ? report.errors.map((issue) => <div className="issue-row" key={issue.line_number}><span className="issue-line">Line {issue.line_number}</span><strong>{issue.expense_id ?? "No ID"}</strong><span>{issue.reasons.join("; ")}</span></div>) : <div className="no-issues"><Check size={15} />Every row was read successfully.</div>}</div>}
            </section>
          </TabsContent>
        </>}
      </Tabs>
      {user.role === "reviewer" && <footer className="page-footer"><span>{report ? `${report.sources.expenses}, updated ${updatedAt(report)}` : "Connecting…"}</span><button onClick={() => setPolicyOpen(true)}>View active policy</button></footer>}
    </main>
    <ClaimDetails claim={selectedClaim} report={report} close={() => setSelectedClaim(null)} user={user} onSaved={(data) => { changeSource(data); setSelectedClaim(data.claims.find((item) => item.id === selectedClaim?.id) ?? null); }} />
    {user.role === "reviewer" && <PolicyLibrary open={libraryOpen} close={() => setLibraryOpen(false)} report={report} onReport={changeSource} onBusy={setUploading} />}
    <PolicyDetails open={policyOpen} report={report} close={() => setPolicyOpen(false)} />
  </div>;
}
