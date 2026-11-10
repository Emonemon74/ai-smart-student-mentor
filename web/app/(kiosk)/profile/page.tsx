"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useUi } from "@/app/providers";
import { api } from "@/lib/api";
import { kioskError } from "@/lib/kiosk";
import type { Profile, RoadmapListItem, SubjectSummary } from "@/lib/types";

const d = (iso: string | null) => (iso ? iso.slice(0, 10) : "-");

export default function ProfilePage() {
  const { t } = useUi();
  const router = useRouter();
  const [p, setP] = useState<Profile | null>(null);
  const [plans, setPlans] = useState<RoadmapListItem[]>([]);
  const [err, setErr] = useState("");
  const [reporting, setReporting] = useState<SubjectSummary | null>(null);
  const [note, setNote] = useState("");
  const [sentMsg, setSentMsg] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);

  const loadPlans = useCallback(async () => {
    try { setPlans(await api<RoadmapListItem[]>("/roadmaps")); } catch { setPlans([]); }
  }, []);

  useEffect(() => {
    (async () => {
      try { setP(await api<Profile>("/me/profile")); } catch (e) { const c = kioskError(e, router.push); if (c !== "no_session" && c !== "consent_required") setErr(t("error_generic")); }
      loadPlans();
    })();
  }, [router, t, loadPlans]);

  async function sendCorrection() {
    if (!reporting) return;
    try {
      await api("/requests", { method: "POST", json: { kind: "correction", subject_code: reporting.code, note: note.trim() || null } });
      setSentMsg(t("error_sent")); setReporting(null); setNote("");
    } catch (e) { kioskError(e, router.push); }
  }
  async function deletePlans() {
    try { await api("/me/plans", { method: "DELETE" }); setConfirmDelete(false); loadPlans(); } catch (e) { kioskError(e, router.push); }
  }

  if (err) return <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-red-800">{err}</p>;
  if (!p) return <p className="text-slate-500">{t("loading")}</p>;

  return (
    <section className="space-y-5 pb-8">
      <div>
        <h1 className="text-3xl font-bold text-[#14284b]">{t("profile_title")}</h1>
        <p className="text-sm text-slate-600">
          {p.student.programme} · {t("semester")} {p.student.semester}
          {" · "}{t("records_as_of")} {d(p.as_of)}, {t("imported")} {d(p.imported_at)}
          {p.overall_pct !== null && ` · ${t("overall")} ${p.overall_pct}%`}
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {p.subjects.map((s) => (
          <article key={s.code} className={`rounded-2xl border-2 bg-white p-4 shadow-sm ${s.flags.length ? "border-amber-300" : "border-transparent"}`}>
            <div className="flex items-baseline justify-between gap-2">
              <h2 className="font-semibold">{s.name}</h2>
              <div className="text-2xl font-bold">{s.pct ?? "-"}<span className="text-sm font-normal text-slate-500">%</span></div>
            </div>
            <p className="text-sm text-slate-500">{s.n_assessments} {t("assessments")} · {t("attendance")} {s.attendance_pct ?? "-"}%</p>
            {s.flags.length === 0 ? <p className="mt-2 text-sm text-emerald-700">{t("no_issues")}</p> : (
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-slate-800">
                {s.flags.map((f, i) => <li key={i}>{f.reason}{typeof f.values.n === "number" && <span className="text-slate-500"> (n={f.values.n})</span>}</li>)}
              </ul>
            )}
            <button onClick={() => { setReporting(s); setSentMsg(""); }} className="mt-3 min-h-12 rounded-lg border border-slate-300 px-3 text-sm">{t("report_error")}</button>
          </article>
        ))}
      </div>
      {sentMsg && <p role="status" className="rounded-lg bg-emerald-50 px-4 py-3 text-emerald-800">{sentMsg}</p>}

      {p.upcoming.length > 0 && (
        <div className="rounded-2xl bg-white p-4 shadow-sm">
          <h2 className="font-semibold">{t("upcoming")}</h2>
          <ul className="mt-2 text-sm">{p.upcoming.map((u, i) => <li key={i}>{d(u.on)} · {u.subject_code} · {u.kind}</li>)}</ul>
        </div>
      )}

      <div className="rounded-2xl bg-white p-4 shadow-sm">
        <h2 className="font-semibold">{t("skill_coverage")}</h2>
        <p className="text-xs text-slate-500">{t("indicator_note")}</p>
        <ul className="mt-2 space-y-1 text-sm">
          {p.roles.map((r) => <li key={r.role} className="flex justify-between"><span>{r.role}</span><span>{r.pct ?? "-"}%{r.weakest_subject && <span className="text-slate-500"> ({r.weakest_subject})</span>}</span></li>)}
        </ul>
      </div>

      <div className="rounded-2xl bg-white p-4 shadow-sm">
        <h2 className="font-semibold">{t("your_plans")}</h2>
        {plans.length === 0 ? <p className="mt-1 text-sm text-slate-500">-</p> : (
          <ul className="mt-2 space-y-2">
            {plans.map((pl) => (
              <li key={pl.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span>{pl.subject_name} v{pl.version} · {d(pl.review_on)} · {pl.done}/{pl.total}</span>
                <span className="flex gap-2">
                  <Link href={`/roadmap/${pl.id}`} className="min-h-12 rounded-lg border border-slate-300 px-3 py-3">{t("open")}</Link>
                  <Link href={`/report/${pl.id}`} className="min-h-12 rounded-lg border border-slate-300 px-3 py-3">{t("report")}</Link>
                </span>
              </li>
            ))}
          </ul>
        )}
        {plans.length > 0 && <button onClick={() => setConfirmDelete(true)} className="mt-3 min-h-12 rounded-lg border border-red-300 px-3 text-sm text-red-800">{t("delete_plans")}</button>}
      </div>

      <Link href="/mentor" className="inline-block min-h-14 rounded-xl bg-[#14284b] px-8 py-4 text-xl font-semibold text-white">{t("talk_mentor")}</Link>

      {reporting && (
        <div role="dialog" aria-modal="true" className="fixed inset-0 z-40 grid place-items-center bg-black/40 p-4">
          <div className="w-full max-w-md rounded-2xl bg-white p-5">
            <h2 className="font-semibold">{t("report_error")}: {reporting.name}</h2>
            <textarea value={note} onChange={(e) => setNote(e.target.value.slice(0, 300))} rows={3} className="mt-3 w-full rounded-lg border border-slate-300 p-3" />
            <div className="mt-3 flex gap-2">
              <button onClick={sendCorrection} className="min-h-12 rounded-lg bg-[#14284b] px-5 text-white">{t("send")}</button>
              <button onClick={() => setReporting(null)} className="min-h-12 rounded-lg border border-slate-300 px-5">{t("cancel")}</button>
            </div>
          </div>
        </div>
      )}
      {confirmDelete && (
        <div role="dialog" aria-modal="true" className="fixed inset-0 z-40 grid place-items-center bg-black/40 p-4">
          <div className="max-w-md rounded-2xl bg-white p-5 text-center">
            <p>{t("confirm_delete")}</p>
            <div className="mt-4 flex justify-center gap-2">
              <button onClick={deletePlans} className="min-h-12 rounded-lg bg-red-700 px-5 text-white">{t("confirm")}</button>
              <button onClick={() => setConfirmDelete(false)} autoFocus className="min-h-12 rounded-lg border border-slate-300 px-5">{t("cancel")}</button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
