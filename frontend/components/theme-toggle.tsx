import { useState } from "react";
import { Moon, Sun } from "lucide-react";

export function ThemeToggle() {
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));

  function toggle() {
    const next = !dark;
    document.documentElement.classList.toggle("dark", next);
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", next ? "#0f1311" : "#f3f5f2");
    try { localStorage.setItem("expense-theme", next ? "dark" : "light"); } catch { /* The toggle still works when browser storage is unavailable. */ }
    setDark(next);
  }

  return <button type="button" className="theme-toggle" onClick={toggle} aria-label={`Switch to ${dark ? "light" : "dark"} mode`} title={`Switch to ${dark ? "light" : "dark"} mode`}>
    {dark ? <Sun size={17} /> : <Moon size={17} />}<span>{dark ? "Light mode" : "Dark mode"}</span>
  </button>;
}
