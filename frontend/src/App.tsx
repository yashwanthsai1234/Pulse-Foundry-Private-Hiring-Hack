// Sources:
// - https://reactrouter.com/start/declarative/routing (Routes / Route / NavLink, declarative mode)
import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { api } from "./api/client";
import type { Settings, Summary } from "./api/types";
import { ApiError } from "./components/ApiError";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { RunProvider, useRun } from "./lib/RunContext";
import { useApi } from "./lib/useApi";
import Contracts from "./pages/Contracts";
import Credentials from "./pages/Credentials";
import Exports from "./pages/Exports";
import Ingest from "./pages/Ingest";
import Issues from "./pages/Issues";
import People from "./pages/People";
import Shifts from "./pages/Shifts";

const NAV = [["/ingest", "Ingest"], ["/issues", "Issues"], ["/people", "People"], ["/shifts", "Shifts"], ["/credentials", "Credentials"], ["/exports", "Exports"], ["/contracts", "Contracts"]];

function Header() {
  const { refresh } = useRun();
  const { data: summary, error } = useApi<Summary>("/api/summary");
  const { data: settings } = useApi<Settings>("/api/settings");
  const sev = summary?.issues_by_severity ?? {};
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-4 px-4 py-3">
        <h1 className="text-lg font-semibold">Harborview Source of Truth</h1>
        <span className="rounded bg-red-600 px-2 py-0.5 text-xs font-semibold text-white" data-testid="critical-count">CRITICAL {sev.CRITICAL ?? 0}</span>
        <span className="rounded bg-orange-500 px-2 py-0.5 text-xs font-semibold text-white" data-testid="high-count">HIGH {sev.HIGH ?? 0}</span>
        <label className="ml-auto text-sm text-slate-600">
          as-of{" "}
          <input type="date" className="rounded border border-slate-300 px-2 py-0.5" value={settings?.as_of ?? ""}
            onChange={async (e) => { if (e.target.value) { await api("/api/settings", "PUT", { as_of: e.target.value }).catch(() => {}); refresh(); } }} />
        </label>
      </div>
      <div className="mx-auto max-w-7xl px-4"><ApiError error={error && "Cannot reach the backend: " + error} /></div>
      <nav className="mx-auto flex max-w-7xl gap-1 px-4">
        {NAV.map(([to, label]) => (
          <NavLink key={to} to={to} className={({ isActive }) => `border-b-2 px-3 py-2 text-sm ${isActive ? "border-blue-600 font-medium text-blue-700" : "border-transparent text-slate-600 hover:text-slate-900"}`}>{label}</NavLink>
        ))}
      </nav>
    </header>
  );
}

export default function App() {
  return (
    <RunProvider>
      <Header />
      <main className="mx-auto max-w-7xl p-4">
        <ErrorBoundary>
        <Routes>
          <Route path="/" element={<Navigate to="/ingest" replace />} />
          <Route path="/ingest" element={<Ingest />} />
          <Route path="/issues" element={<Issues />} />
          <Route path="/people" element={<People />} />
          <Route path="/shifts" element={<Shifts />} />
          <Route path="/credentials" element={<Credentials />} />
          <Route path="/exports" element={<Exports />} />
          <Route path="/contracts" element={<Contracts />} />
          <Route path="*" element={<p className="text-slate-600">Page not found. <NavLink className="text-blue-700" to="/ingest">Go to Ingest</NavLink></p>} />
        </Routes>
        </ErrorBoundary>
      </main>
    </RunProvider>
  );
}
