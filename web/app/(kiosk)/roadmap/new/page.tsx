"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useUi } from "@/app/providers";
import { api } from "@/lib/api";
import { addDays, todayIso } from "@/lib/dates";
import { kioskError, recentMessages } from "@/lib/kiosk";
import type { ChatMessage, DraftView, Goal, GoalCode, Level, Profile, Resource, RoadmapIn, RoadmapListItem, RoadmapView } from "@/lib/types";

const LEVELS: Level[] = ["foundation", "beginner", "intermediate", "advanced"];

function NewRoadmapInner() {
  const { t, lang } = useUi();
  const router = useRouter();
  const sp = useSearchParams();
  const [goals, setGoals] = useState<Goal[]>([]);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [plans, setPlans] = useState<RoadmapListItem[]>([]);
  const [goal, setGoal] = useState<GoalCode>("semester");
  const [subject, setSubject] = useState("");
  const [days, setDays] = useState(14);
  const [minutes, setMinutes] = useState(60);
  const [review, setReview] = useState(addDays(todayIso(), 14));
  const [target, setTarget] = useState("");
  const [overrides, setOverrides] = useState<Record<string, Level | "">>({});
  const [trackTopics, setTrackTopics] = useState<string[]>([]);
  const [draft, setDraft] = useState<DraftView | null>(null);
  const [fallback, setFallback] = useState<Resource[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const [g, p, pl] = await Promise.all([api<Goal[]>("/goals"), api<Profile>("/me/profile"), api<RoadmapListItem[]>("/roadmaps")]);
        setGoals(g); setProfile(p); setPlans(pl);
        const wantedGoal = (sp.get("goal") as GoalCode | null) ?? (p.backlogs.some((b) => b.status === "pending") ? "backlog" : "semester");
        const goalDef = g.find((x) => x.code === wantedGoal) ?? g[0];
        setGoal(goalDef.code);
        const wanted = sp.get("subject");
        setSubject(goalDef.subjects.find((s) => s.code === wanted)?.code ?? goalDef.subjects[0]?.code ?? "");
      } catch (e) { const c = kioskError(e, router.push); if (c !== "no_session" && c !== "consent_required") setErr(t("error_generic")); }
    })();
  }, [router, t, sp]);

  const goalDef = goals.find((g) => g.code === goal);
  const subjectDef = goalDef?.subjects.find((s) => s.code === subject);
  const summary = profile?.subjects.find((s) => s.code === subject);
  const alreadyMinutes = useMemo(() => plans.filter((p) => p.status === "active" && !(p.goal === goal && p.subject_code === subject)).reduce((a, p) => a + p.daily_minutes, 0), [plans, goal, subject]);

  // Tracks have no marks: the student self-estimates per catalogue topic. The list loads when the subject is a track.
  useEffect(() => {
    if (!subject || subjectDef?.kind !== "track") return;
    let alive = true;
    (async () => {
      let topics: string[] = [];
      try { topics = [...new Set((await api<Resource[]>(`/resources?subject_code=${subject}&goal=${goal}&lang=${lang}`)).map((r) => r.topic))]; } catch {}
      if (alive) setTrackTopics(topics);
    })();
    return () => { alive = false; };
  }, [subject, subjectDef?.kind, goal, lang]);

  // Changing goal or subject starts a fresh draft.
  function resetDraft() { setOverrides({}); setDraft(null); setFallback(null); setTrackTopics([]); }
  function changeSubject(code: string) { resetDraft(); setSubject(code); }

  function pickGoal(code: GoalCode) {
    resetDraft();
    setGoal(code);
    const g = goals.find((x) => x.code === code);
    setSubject(g?.subjects[0]?.code ?? "");
  }
  function changeDays(n: number) {
    setDays(n);
    if (review < addDays(todayIso(), n)) setReview(addDays(todayIso(), n));
  }
  function mentorMessages(): ChatMessage[] {
    try { return JSON.parse(sessionStorage.getItem("mentorMessages") ?? "[]"); } catch { return []; }
  }
  const cleanOverrides = () => Object.fromEntries(Object.entries(overrides).filter(([, v]) => v)) as Record<string, Level>;

  async function generate() {
    setBusy(true); setErr(""); setDraft(null); setFallback(null);
    try {
      setDraft(await api<DraftView>("/roadmaps/draft", { method: "POST", json: {
        goal, subject_code: subject, days, daily_minutes: minutes, review_on: review, target_date: goalDef?.needs_target_date && target ? target : null,
        level_overrides: cleanOverrides(), lang, messages: recentMessages(mentorMessages()) } }));
    } catch (e) {
      const code = kioskError(e, router.push);
      if (code === "ai_unavailable") {
        setErr(t("ai_busy_resources"));   // RB 17: the student still gets level-matched approved resources and the human option
        try { setFallback(await api<Resource[]>(`/resources?subject_code=${subject}&goal=${goal}&lang=${lang}&max_minutes=${minutes}`)); } catch {}
      } else setErr(code === "over_daily_capacity" ? `${t("over_capacity")} (${t("already_planned")} ${alreadyMinutes} ${t("min_per_day")})` : t("error_generic"));
    }
    setBusy(false);
  }
  async function save() {
    if (!draft) return;
    setBusy(true); setErr("");
    try {
      const saved = await api<RoadmapView>("/roadmaps", { method: "POST", json: draft.roadmap });
      router.push(`/roadmap/${saved.id}`);
    } catch (e) {
      const code = kioskError(e, router.push);
      setErr(code === "over_daily_capacity" ? t("over_capacity") : t("error_generic")); setBusy(false);
    }
  }
  const edit = (i: number, activity: string) => setDraft((d) => d && { ...d, roadmap: { ...d.roadmap, tasks: d.roadmap.tasks.map((x, k) => (k === i ? { ...x, activity } : x)) } as RoadmapIn });
  const remove = (i: number) => setDraft((d) => d && { ...d, roadmap: { ...d.roadmap, tasks: d.roadmap.tasks.filter((_, k) => k !== i) } as RoadmapIn });

  const levelRows = subjectDef?.kind === "track"
    ? trackTopics.map((topic) => ({ topic, label: "", def: "" as Level | "" }))
    : (summary?.levels ?? []).filter((l) => l.level !== null).slice(0, 5).map((l) => ({ topic: l.topic, label: `${l.level ? t(`level_${l.level}` as const) : ""} · ${l.source === "check" ? t("src_check") : l.source === "student" ? t("src_student") : t("src_records")}`, def: (l.level ?? "") as Level | "" }));

  const field = "mt-1 min-h-14 w-full rounded-xl border border-slate-300 bg-white px-4 text-lg";
  return (
    <section className="pb-8">
      <h1 className="text-3xl font-bold text-[#14284b]">{t("plan_new_title")}</h1>
      <div className="mt-4" role="group" aria-label={t("goal")}>
        <div className="text-sm font-medium">{t("goal")}</div>
        <div className="mt-1 flex flex-wrap gap-2">
          {goals.map((g) => (
            <button key={g.code} onClick={() => pickGoal(g.code)} aria-pressed={goal === g.code}
              className={`min-h-12 rounded-xl border px-4 text-base ${goal === g.code ? "border-[#14284b] bg-[#14284b] text-white" : "border-slate-300 bg-white"}`}>{lang === "hi" ? g.name_hi : g.name}</button>
          ))}
        </div>
        {goalDef && <p className="mt-1 text-sm text-slate-600">{goalDef.components}</p>}
      </div>

      {goalDef && goalDef.subjects.length === 0 ? <p className="mt-4 text-slate-600">{t("no_goal_subjects")}</p> : (
        <div className="mt-4 grid gap-3 md:grid-cols-5">
          <label className="text-sm font-medium md:col-span-1">{t("subject")}
            <select value={subject} onChange={(e) => changeSubject(e.target.value)} className={field}>{goalDef?.subjects.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}</select>
          </label>
          <label className="text-sm font-medium">{t("days")}
            <input type="number" min={7} max={30} value={days} onChange={(e) => changeDays(Math.max(7, Math.min(30, Number(e.target.value) || 7)))} className={field} />
          </label>
          <label className="text-sm font-medium">{t("minutes_per_day")}
            <input type="number" min={15} max={240} step={5} value={minutes} onChange={(e) => setMinutes(Math.max(15, Math.min(240, Number(e.target.value) || 15)))} className={field} />
            {alreadyMinutes > 0 && <span className="mt-1 block text-xs font-normal text-slate-500">{t("already_planned")} {alreadyMinutes} {t("min_per_day")}</span>}
          </label>
          <label className="text-sm font-medium">{t("review_date")}
            <input type="date" min={addDays(todayIso(), days)} value={review} onChange={(e) => setReview(e.target.value)} className={field} />
          </label>
          {goalDef?.needs_target_date && (
            <label className="text-sm font-medium">{t("target_date")}
              <input type="date" min={todayIso()} value={target} onChange={(e) => setTarget(e.target.value)} className={field} />
            </label>
          )}
        </div>
      )}

      {levelRows.length > 0 && (
        <div className="mt-4 rounded-2xl bg-white p-4 shadow-sm">
          <h2 className="font-semibold">{t("plan_levels_h")}</h2>
          <p className="text-xs text-slate-500">{t("level_source_hint")} ({t("provisional")})</p>
          <ul className="mt-2 space-y-2">
            {levelRows.map((r) => (
              <li key={r.topic} className="flex flex-wrap items-center justify-between gap-2 text-sm">
                <span>{r.topic} <span className="text-slate-500">{r.label}</span></span>
                <span className="flex items-center gap-2">
                  <select aria-label={r.topic} value={overrides[r.topic] ?? ""} onChange={(e) => setOverrides((o) => ({ ...o, [r.topic]: e.target.value as Level | "" }))} className="min-h-12 rounded-lg border border-slate-300 bg-white px-3">
                    <option value="">{r.def ? t(`level_${r.def}` as const) : t("not_sure")}</option>
                    {LEVELS.map((l) => <option key={l} value={l}>{t(`level_${l}` as const)}</option>)}
                  </select>
                  {subjectDef?.kind !== "track" && summary?.levels.find((l) => l.topic === r.topic)?.has_check && (
                    <Link href={`/check?subject=${subject}&topic=${encodeURIComponent(r.topic)}&next=/roadmap/new?goal=${goal}%26subject=${subject}`} className="min-h-12 rounded-lg border border-slate-300 px-3 py-3 text-xs">{t("check_my_level")}</Link>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <button onClick={generate} disabled={busy || !subject} className="mt-4 min-h-14 rounded-xl bg-[#14284b] px-8 text-xl font-semibold text-white disabled:opacity-40">{draft ? t("regenerate") : t("generate")}</button>
      {busy && !draft && <p className="mt-3 text-slate-600" role="status">{t("generating")}</p>}
      {err && <p role="alert" className="mt-3 rounded-lg bg-amber-50 px-4 py-3 text-amber-900">{err}</p>}
      {fallback && (
        <div className="mt-3 rounded-2xl bg-white p-4 shadow-sm">
          <ul className="space-y-1 text-sm">
            {fallback.slice(0, 8).map((r) => <li key={r.id}><a href={r.url} target="_blank" rel="noreferrer" className="underline">{r.title}</a> <span className="text-slate-500">· {r.topic} · {t(`level_${r.level}` as const)} · {r.minutes} {t("minutes")} · {r.source}</span></li>)}
          </ul>
        </div>
      )}

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
                  {res && <p className="text-sm"><b>{t("resource")}:</b> <a href={res.url} target="_blank" rel="noreferrer" className="underline">{res.title}</a> <span className="text-slate-500">· {t(`level_${res.level}` as const)} · {res.minutes} {t("minutes")} · {res.source}</span></p>}
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

export default function NewRoadmap() {
  return <Suspense fallback={null}><NewRoadmapInner /></Suspense>;
}
