import { useEffect, useState } from "react";
import Component from "@/components/ui/saa-s-template";
import { apiJson, postJson, type DemoUser } from "@/lib/report";
import { Check, CheckCheck, Search, ArrowRight, Loader2, X } from "lucide-react";
import { ThemeToggle } from "@/components/theme-toggle";
import { Button } from "@/components/ui/button";
import "@/styles/sign-in.css";

export default function DemoSession() {
  const [user, setUser] = useState<DemoUser | null>(null);
  const [accounts, setAccounts] = useState<DemoUser[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [accountId, setAccountId] = useState("");
  const [search, setSearch] = useState("");

  async function initialize() {
    setBusy(true);
    setError("");
    try {
      const response = await fetch("/api/session");
      if (response.ok) setUser(await response.json());
      else if (response.status !== 401) throw new Error("The demo session could not be loaded.");
      setAccounts(await apiJson<DemoUser[]>("/api/demo/accounts"));
    } catch (problem) { setError(problem instanceof Error ? problem.message : "Unable to load accounts."); }
    finally { setBusy(false); }
  }

  useEffect(() => { void initialize(); }, []);

  async function login(id: string) {
    setBusy(true);
    setError("");
    try { setUser(await postJson<DemoUser>("/api/demo/login", { user_id: id })); }
    catch (problem) { setError(problem instanceof Error ? problem.message : "Unable to sign in."); }
    finally { setBusy(false); }
  }

  async function logout() {
    setBusy(true);
    try {
      const response = await fetch("/api/demo/logout", { method: "POST" });
      if (!response.ok) throw new Error("Could not switch accounts. Please retry.");
      setUser(null);
      setAccountId("");
      setSearch("");
    } catch (problem) { setError(problem instanceof Error ? problem.message : "Unable to sign out."); }
    finally { setBusy(false); }
  }

  if (user) return <>{error && <p role="alert" className="error-banner">{error}</p>}<Component key={user.id} user={user} onLogout={() => { void logout(); }} /></>;
  const selected = accounts.find((account) => account.id === accountId);
  const query = search.trim().toLocaleLowerCase();
  const matches = accounts.filter((account) => account.name.toLocaleLowerCase().includes(query));

  return <main className="sign-in-screen">
    <header className="sign-in-top"><a href="#sign-in" className="brand"><span className="brand-mark"><CheckCheck size={18} strokeWidth={2.5} /></span><span>expensecheck</span></a><ThemeToggle /></header>
    <section className="sign-in-card" id="sign-in" aria-labelledby="sign-in-title">
      <div className="sign-in-heading"><h1 id="sign-in-title">Welcome back.</h1><p>Choose your account to continue.</p></div>
      <form onSubmit={(event) => { event.preventDefault(); if (accountId && !busy) void login(accountId); }}>
        <div className="account-directory-heading"><h2>Your team</h2><span>{accounts.length ? `${accounts.length} accounts` : ""}</span></div>
        <div className="account-search"><Search size={18} aria-hidden="true" /><input aria-label="Find your account" autoComplete="off" placeholder="Search your name" value={search} onChange={(event) => setSearch(event.target.value)} disabled={busy} />{search && <button type="button" onClick={() => setSearch("")} aria-label="Clear account search"><X size={16} /></button>}</div>
        <fieldset className="account-directory" disabled={busy}><legend className="sr-only">Choose your account</legend>
          {matches.map((account) => {
            const color = [...account.id].reduce((sum, char) => sum + char.charCodeAt(0), 0) % 4;
            return <label className={`person-tile ${accountId === account.id ? "person-selected" : ""}`} key={account.id}>
              <input className="person-radio" type="radio" name="account" value={account.id} checked={accountId === account.id} onChange={() => { setAccountId(account.id); setError(""); }} aria-label={account.name} />
              <span className={`person-avatar person-color-${color}`} aria-hidden="true">{account.name.split(" ").map((word) => word[0]).slice(0, 2).join("")}</span>
              <span className="person-name"><strong>{account.name}</strong><small>{account.role === "reviewer" ? "Finance" : "Team member"}</small></span>
              <span className="person-check" aria-hidden="true">{accountId === account.id && <Check size={12} strokeWidth={3} />}</span>
            </label>;
          })}
          {!matches.length && <div className="account-directory-empty" role="status">{busy ? <><Loader2 size={20} className="spin" /><span>Loading your team…</span></> : <><Search size={22} /><strong>{query ? "No accounts found" : "No accounts available"}</strong><span>{query ? "Try a different name." : "Reload the account list to try again."}</span>{query ? <button type="button" onClick={() => setSearch("")}>Clear search</button> : <button type="button" onClick={() => { void initialize(); }}>Reload accounts</button>}</>}</div>}
        </fieldset>
        {error && <div className="sign-in-error" role="alert"><p>{error}</p>{!accounts.length && <button type="button" onClick={() => { void initialize(); }}>Try again</button>}</div>}
        <div className="sign-in-action"><div className="sign-in-selection" aria-live="polite">{selected ? <span>Continue as <strong>{selected.name}</strong></span> : <span>No account selected</span>}</div><Button type="submit" disabled={busy || !accountId}>{busy && accountId ? <><Loader2 size={16} className="spin" />Signing in…</> : <>Sign in<ArrowRight size={17} /></>}</Button></div>
      </form>
    </section>
  </main>;
}
