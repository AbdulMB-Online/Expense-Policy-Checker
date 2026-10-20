import { useEffect, useState } from "react";
import Component from "@/components/ui/saa-s-template";
import { apiJson, postJson, type DemoUser } from "@/lib/report";
import { Button } from "@/components/ui/button";

export default function DemoSession() {
  const [user, setUser] = useState<DemoUser | null>(null);
  const [accounts, setAccounts] = useState<DemoUser[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");

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
    } catch (problem) { setError(problem instanceof Error ? problem.message : "Unable to sign out."); }
    finally { setBusy(false); }
  }

  if (user) return <>{error && <p role="alert" className="error-banner">{error}</p>}<Component key={user.id} user={user} onLogout={() => { void logout(); }} /></>;
  return <main className="demo-login"><div className="eyebrow">EXPENSE POLICY CHECKER</div><h1>Choose a demo account</h1><p>Employees submit and track their own expenses. Reviewers import files and decide on individual claims.</p>
    {error && <p role="alert">{error} <Button variant="outline" onClick={() => { void initialize(); }}>Retry</Button></p>}
    <div className="demo-accounts">{accounts.map((account) => <Button variant="outline" key={account.id} disabled={busy} onClick={() => { void login(account.id); }}><strong>{account.name}</strong><span>{account.role === "reviewer" ? "Reviewer" : "Employee"}</span></Button>)}</div>
    {busy && <p role="status">Loading…</p>}<p className="review-guidance">Local demo accounts do not require passwords.</p>
  </main>;
}
