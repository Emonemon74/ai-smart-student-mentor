"use client";
import { useCallback, useState } from "react";
import { api, ApiError } from "@/lib/api";

interface SubjectRow { code: string; name: string; students: number | null; flagged: number | null; avg_pct: number | null; active_plans: number | null; suppressed: boolean }
interface Summary {
  subjects: SubjectRow[];
  metrics: { login_success_rate_7d: number | null; draft_success_rate_7d: number | null; feedback_avg: number | null; feedback_n: number; plans_with_progress: number | null };
  requests: { id: number; roll_no: string; kind: string; subject_code: string | null; note: string | null; created_at: string }[];
  last_import: { baseline: string | null; review: string | null };
  health: { db: boolean; llm: { last_ok: string | null; last_error: string | null } };
  recent_audit: { at: string; actor: string; action: string }[];
}

const pct = (v: number | null) => (v === null ? "-" : `${Math.round(v * 100)}%`);
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }) : "never");

export default function Admin() {
  const [password, setPassword] = useState("");
  const [data, setData] = useState<Summary | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setData(await api<Summary>("/admin/summary")); setErr(""); }
    catch (e) { setData(null); setErr(e instanceof ApiError && e.status === 401 ? "Please sign in." : "Could not load the dashboard."); }
  }, []);

  async function login() {
    setBusy(true); setErr("");
    try { await api("/admin/login", { method: "POST", json: { password } }); setPassword(""); await load(); }
    catch (e) { setErr(e instanceof ApiError && e.code === "bad_credentials" ? "Wrong password." : "Could not sign in."); }
    setBusy(false);
  }
  async function close(id: number) {
    try { await api(`/admin/requests/${id}/close`, { method: "POST" }); await load(); } catch { setErr("Could not close the request."); }
  }

  if (!data) {
    return (
      <main className="mx-auto max-w-sm p-6">
        <h1 className="text-2xl font-bold text-[#14284b]">Staff dashboard</h1>
        <p className="mt-1 text-sm text-slate-600">Anonymous totals and requests only. No individual marks are shown.</p>
        <label className="mt-6 block text-sm font-medium">Password
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} onKeyDown={(e) => e.key === "Enter" && password && login()} autoFocus autoComplete="current-password" className="mt-1 min-h-12 w-full rounded-lg border border-slate-300 bg-white px-3" />
        </label>
        {err && <p role="alert" className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-red-800">{err}</p>}
        <button onClick={login} disabled={busy || !password} className="mt-4 min-h-12 w-full rounded-lg bg-[#14284b] text-white disabled:opacity-40">Sign in</button>
      </main>
    );
  }

  const m = data.metrics;
  const tiles: [string, string][] = [
    ["Login success (7 days)", pct(m.login_success_rate_7d)], ["Plan generation success (7 days)", pct(m.draft_success_rate_7d)],
    ["Usefulness rating", m.feedback_avg === null ? "-" : `${m.feedback_avg} / 5 (n=${m.feedback_n})`], ["Plans with progress", pct(m.plans_with_progress)],
  ];
  return (
    <main className="mx-auto max-w-5xl space-y-6 p-4 md:p-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-bold text-[#14284b]">Staff dashboard</h1>
        <button onClick={load} className="min-h-11 rounded-lg border border-slate-300 bg-white px-4">Refresh</button>
      </div>
      {err && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-red-800">{err}</p>}

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {tiles.map(([label, v]) => <div key={label} className="rounded-xl bg-white p-4 shadow-sm"><div className="text-2xl font-bold">{v}</div><div className="text-xs text-slate-500">{label}</div></div>)}
      </section>

      <section className="rounded-xl bg-white p-4 shadow-sm">
        <h2 className="font-semibold">Subjects</h2>
        <div className="overflow-x-auto"><table className="mt-2 w-full text-left text-sm">
          <thead className="text-slate-500"><tr><th className="py-1 font-normal">Subject</th><th className="font-normal">Students</th><th className="font-normal">Average</th><th className="font-normal">Flagged</th><th className="font-normal">Active plans</th></tr></thead>
          <tbody>{data.subjects.map((s) => s.suppressed
            ? <tr key={s.code} className="border-t text-slate-500"><td className="py-1.5">{s.name}</td><td colSpan={4}>Hidden: fewer than 5 students (privacy)</td></tr>
            : <tr key={s.code} className="border-t"><td className="py-1.5">{s.name} <span className="text-slate-400">({s.code})</span></td><td>{s.students}</td><td>{s.avg_pct}%</td><td>{s.flagged}</td><td>{s.active_plans}</td></tr>)}
          </tbody></table></div>
      </section>

      <section className="rounded-xl bg-white p-4 shadow-sm">
        <h2 className="font-semibold">Intervention queue <span className="font-normal text-slate-500">({data.requests.length} open)</span></h2>
        {data.requests.length === 0 ? <p className="mt-1 text-sm text-slate-500">No open requests.</p> : (
          <ul className="mt-2 divide-y text-sm">
            {data.requests.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 py-2">
                <span><b>{r.roll_no}</b> · {r.kind}{r.subject_code && ` · ${r.subject_code}`}{r.note && <span className="text-slate-600"> · “{r.note}”</span>} <span className="text-slate-400">{when(r.created_at)}</span></span>
                <button onClick={() => close(r.id)} className="min-h-10 rounded-lg border border-slate-300 px-3">Close</button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="grid gap-4 md:grid-cols-2">
        <div className="rounded-xl bg-white p-4 text-sm shadow-sm">
          <h2 className="font-semibold">Health</h2>
          <p className="mt-1">Database: <b className={data.health.db ? "text-emerald-700" : "text-red-700"}>{data.health.db ? "OK" : "down"}</b></p>
          <p>AI last success: {when(data.health.llm.last_ok)}</p>
          <p>AI last error: {data.health.llm.last_error ?? "none"}</p>
          <h2 className="mt-3 font-semibold">Data imports</h2>
          <p>Baseline: {when(data.last_import.baseline)}</p>
          <p>Review: {when(data.last_import.review)}</p>
        </div>
        <div className="rounded-xl bg-white p-4 shadow-sm">
          <h2 className="font-semibold">Recent activity</h2>
          <ul className="mt-1 max-h-64 overflow-y-auto font-mono text-xs">{data.recent_audit.map((a, i) => <li key={i}>{new Date(a.at).toLocaleTimeString("en-IN")} · {a.actor} · {a.action}</li>)}</ul>
        </div>
      </section>
    </main>
  );
}
