"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useUi } from "@/app/providers";
import { api } from "@/lib/api";
import { addDays, todayIso } from "@/lib/dates";
import { kioskError, recentMessages } from "@/lib/kiosk";
import type { ChatMessage, DraftView, Profile, RoadmapIn, RoadmapView } from "@/lib/types";

export default function NewRoadmap() {
  const { t, lang } = useUi();
  const router = useRouter();
  const [profile, setProfile] = useState<Profile | null>(null);
  const [subject, setSubject] = useState("");
  const [days, setDays] = useState(14);
  const [minutes, setMinutes] = useState(60);
  const [review, setReview] = useState(addDays(todayIso(), 14));
  const [draft, setDraft] = useState<DraftView | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const p = await api<Profile>("/me/profile");
        setProfile(p);
        const wanted = new URLSearchParams(window.location.search).get("subject");
        setSubject(p.subjects.find((s) => s.code === wanted)?.code ?? p.subjects[0]?.code ?? ""); // flagged subjects sort first
      } catch (e) { kioskError(e, router.push); setErr(t("error_generic")); }
    })();
  }, [router, t]);

  function changeDays(n: number) {
    setDays(n);
    if (review < addDays(todayIso(), n)) setReview(addDays(todayIso(), n));
  }
  function mentorMessages(): ChatMessage[] {
    try { return JSON.parse(sessionStorage.getItem("mentorMessages") ?? "[]"); } catch { return []; }
  }

  async function generate() {
    setBusy(true); setErr(""); setDraft(null);
    try {
      setDraft(await api<DraftView>("/roadmaps/draft", { method: "POST", json: { subject_code: subject, days, daily_minutes: minutes, review_on: review, lang, messages: recentMessages(mentorMessages()) } }));
    } catch (e) {
      const code = kioskError(e, router.push);
      setErr(code === "ai_unavailable" ? t("ai_busy") : t("error_generic"));
    }
    setBusy(false);
  }
  async function save() {
    if (!draft) return;
    setBusy(true); setErr("");
    try {
      const saved = await api<RoadmapView>("/roadmaps", { method: "POST", json: draft.roadmap });
      router.push(`/roadmap/${saved.id}`);
    } catch (e) { kioskError(e, router.push); setErr(t("error_generic")); setBusy(false); }
  }
  const edit = (i: number, activity: string) => setDraft((d) => d && { ...d, roadmap: { ...d.roadmap, tasks: d.roadmap.tasks.map((x, k) => (k === i ? { ...x, activity } : x)) } as RoadmapIn });
  const remove = (i: number) => setDraft((d) => d && { ...d, roadmap: { ...d.roadmap, tasks: d.roadmap.tasks.filter((_, k) => k !== i) } as RoadmapIn });

  const field = "mt-1 min-h-14 w-full rounded-xl border border-slate-300 bg-white px-4 text-lg";
  return (
    <section className="pb-8">
      <h1 className="text-3xl font-bold text-[#14284b]">{t("plan_new_title")}</h1>
      {profile && (
        <div className="mt-4 grid gap-3 md:grid-cols-4">
          <label className="text-sm font-medium">{t("subject")}
            <select value={subject} onChange={(e) => setSubject(e.target.value)} className={field}>{profile.subjects.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}</select>
          </label>
          <label className="text-sm font-medium">{t("days")}
            <input type="number" min={7} max={30} value={days} onChange={(e) => changeDays(Math.max(7, Math.min(30, Number(e.target.value) || 7)))} className={field} />
          </label>
          <label className="text-sm font-medium">{t("minutes_per_day")}
            <input type="number" min={15} max={240} step={5} value={minutes} onChange={(e) => setMinutes(Math.max(15, Math.min(240, Number(e.target.value) || 15)))} className={field} />
          </label>
          <label className="text-sm font-medium">{t("review_date")}
            <input type="date" min={addDays(todayIso(), days)} value={review} onChange={(e) => setReview(e.target.value)} className={field} />
          </label>
        </div>
      )}
      <button onClick={generate} disabled={busy || !subject} className="mt-4 min-h-14 rounded-xl bg-[#14284b] px-8 text-xl font-semibold text-white disabled:opacity-40">{draft ? t("regenerate") : t("generate")}</button>
      {busy && !draft && <p className="mt-3 text-slate-600" role="status">{t("generating")}</p>}
      {err && <p role="alert" className="mt-3 rounded-lg bg-amber-50 px-4 py-3 text-amber-900">{err}</p>}

      {draft && (
        <div className="mt-6">
          <p className="text-slate-700">{draft.roadmap.summary}</p>
          <div className="mt-3 space-y-3">
            {draft.roadmap.tasks.map((task, i) => {
              const res = draft.resources[task.resource_id];
              return (
                <article key={i} className={`rounded-2xl border-2 bg-white p-4 shadow-sm ${task.kind === "checkpoint" ? "border-emerald-300" : "border-transparent"}`}>
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-semibold">{task.day_from === task.day_to ? task.day_from : `${task.day_from}–${task.day_to}`} · {task.topic}{task.kind === "checkpoint" && <span className="ml-2 rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800">{t("checkpoint")}</span>}</div>
                    <button onClick={() => remove(i)} className="min-h-12 rounded-lg border border-slate-300 px-3 text-sm">{t("remove")}</button>
                  </div>
                  <textarea value={task.activity} onChange={(e) => edit(i, e.target.value.slice(0, 300))} rows={2} aria-label={task.topic} className="mt-2 w-full rounded-lg border border-slate-300 p-2" />
                  <p className="mt-1 text-sm text-slate-600"><b>{t("why")}:</b> {task.reason} · <b>{t("effort")}:</b> {task.minutes} min · <b>{t("check")}:</b> {task.check}</p>
                  {res && <p className="text-sm"><b>{t("resource")}:</b> <a href={res.url} target="_blank" rel="noreferrer" className="underline">{res.title}</a></p>}
                </article>
              );
            })}
          </div>
          <button onClick={save} disabled={busy || draft.roadmap.tasks.length === 0} className="mt-5 min-h-14 rounded-xl bg-emerald-700 px-8 text-xl font-semibold text-white disabled:opacity-40">{t("save_plan")}</button>
        </div>
      )}
    </section>
  );
}
