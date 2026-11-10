"use client";
import { useCallback, useEffect, useState } from "react";
import { useUi } from "@/app/providers";
import { ReportView } from "@/components/ReportView";
import { api, ApiError } from "@/lib/api";
import { daysUntil, dayRange, shortDate, todayIso } from "@/lib/dates";
import type { Report, RoadmapView, TaskStatus } from "@/lib/types";

export default function Phone() {
  const { t, lang, setLang } = useUi();
  const [rm, setRm] = useState<RoadmapView | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [tab, setTab] = useState<"plan" | "progress">("plan");
  const [expired, setExpired] = useState(false);

  const fail = useCallback((e: unknown) => { if (e instanceof ApiError && e.status === 401) setExpired(true); }, []);
  const loadReport = useCallback(() => api<Report>("/phone/report").then(setReport).catch(fail), [fail]);

  useEffect(() => { api<RoadmapView>("/phone/roadmap").then(setRm).catch(fail); }, [fail]);
  useEffect(() => { if (tab === "progress") void loadReport(); }, [tab, loadReport]);

  async function setStatus(id: number, status: TaskStatus) {
    const prev = rm;
    setRm((r) => r && { ...r, tasks: r.tasks.map((x) => (x.id === id ? { ...x, status } : x)) }); // optimistic
    try { await api(`/phone/tasks/${id}`, { method: "PATCH", json: { status } }); } catch (e) { setRm(prev); fail(e); }
  }

  if (expired) return <main className="mx-auto max-w-md p-6"><p role="alert" className="rounded-lg bg-amber-50 px-4 py-3 text-amber-900">{t("link_expired")}</p></main>;
  if (!rm) return <main className="mx-auto max-w-md p-6 text-slate-500">{t("loading")}</main>;

  const left = daysUntil(rm.review_on);
  const states: TaskStatus[] = ["pending", "partial", "done"];
  return (
    <main className="mx-auto max-w-md p-4 pb-10">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h1 className="text-xl font-bold text-[#14284b]">{rm.subject_name}</h1>
          <p className="text-sm text-slate-600">{t("review_date")}: {shortDate(rm.review_on, lang)} · {left} {t("days_left")}</p>
        </div>
        <button onClick={() => setLang(lang === "en" ? "hi" : "en")} className="min-h-10 rounded-lg border border-slate-300 bg-white px-3 text-sm print:hidden">{lang === "en" ? "हिन्दी" : "English"}</button>
      </div>
      <p className="mt-2 text-sm text-slate-700">{rm.summary}</p>

      <div className="mt-4 flex gap-2 print:hidden" role="tablist">
        {(["plan", "progress"] as const).map((k) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)} className={`min-h-11 rounded-full px-5 text-sm ${tab === k ? "bg-[#14284b] text-white" : "border border-slate-300 bg-white"}`}>{k === "plan" ? t("phone_plan") : t("phone_progress")}</button>
        ))}
        <button onClick={() => window.print()} className="ml-auto min-h-11 rounded-full border border-slate-300 bg-white px-4 text-sm">PDF</button>
      </div>

      {tab === "plan" && (
        <div className="mt-4 space-y-3">
          {rm.tasks.map((task) => {
            const overdue = task.status !== "done" && task.due_on < todayIso();
            const res = rm.resources[task.resource_id];
            return (
              <article key={task.id} className="rounded-2xl bg-white p-4 shadow-sm">
                <div className="flex items-center justify-between gap-2 text-xs text-slate-500">
                  <span>{dayRange(rm.start_on, task.day_from, task.day_to, lang)}</span>
                  <span className={overdue ? "rounded-full bg-red-100 px-2 py-0.5 font-medium text-red-700" : ""}>{overdue ? `${t("overdue")} · ` : ""}due {shortDate(task.due_on, lang)}</span>
                </div>
                <div className="mt-1 font-semibold">{task.topic}{task.kind === "checkpoint" && <span className="ml-2 rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-normal text-emerald-800">{t("checkpoint")}</span>}</div>
                <p className="mt-1 text-sm">{task.activity}</p>
                <p className="mt-1 text-xs text-slate-500">{t("why")}: {task.reason}</p>
                <p className="text-xs text-slate-500">{t("check")}: {task.check}</p>
                {res && <p className="mt-1 text-sm"><a href={res.url} target="_blank" rel="noreferrer" className="underline">{res.title}</a></p>}
                <div className="mt-3 flex gap-2 print:hidden" role="group" aria-label={task.topic}>
                  {states.map((s) => (
                    <button key={s} onClick={() => setStatus(task.id, s)} aria-pressed={task.status === s}
                      className={`min-h-11 flex-1 rounded-lg border text-sm ${task.status === s ? "border-[#14284b] bg-[#14284b] text-white" : "border-slate-300"}`}>{t(s)}</button>
                  ))}
                </div>
              </article>
            );
          })}
        </div>
      )}
      {tab === "progress" && <div className="mt-4">{report ? <ReportView r={report} /> : <p className="text-slate-500">{t("loading")}</p>}</div>}
      <p className="mt-6 text-xs text-slate-500">{t("phone_footer")}</p>
    </main>
  );
}
