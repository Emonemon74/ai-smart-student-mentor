"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { QRCodeSVG } from "qrcode.react";
import { useCallback, useEffect, useState } from "react";
import { useUi } from "@/app/providers";
import { api } from "@/lib/api";
import { dayRange, longDate, shortDate } from "@/lib/dates";
import { kioskError } from "@/lib/kiosk";
import type { RoadmapView, ShareOut } from "@/lib/types";

export default function RoadmapPage() {
  const { t, lang } = useUi();
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [rm, setRm] = useState<RoadmapView | null>(null);
  const [share, setShare] = useState<ShareOut | null>(null);
  const [left, setLeft] = useState(0);
  const [err, setErr] = useState("");

  useEffect(() => {
    (async () => {
      try { setRm(await api<RoadmapView>(`/roadmaps/${id}`)); } catch (e) { kioskError(e, router.push); setErr(t("error_generic")); }
    })();
  }, [id, router, t]);

  const newCode = useCallback(async () => {
    try { setShare(await api<ShareOut>(`/roadmaps/${id}/share`, { method: "POST" })); } catch (e) { kioskError(e, router.push); setErr(t("error_generic")); }
  }, [id, router, t]);

  // Countdown to the QR expiry.
  useEffect(() => {
    if (!share) return;
    const tick = () => setLeft(Math.max(0, Math.round((new Date(share.expires_at).getTime() - Date.now()) / 1000)));
    tick();
    const i = setInterval(tick, 1000);
    return () => clearInterval(i);
  }, [share]);

  if (err) return <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-red-800">{err}</p>;
  if (!rm) return <p className="text-slate-500">{t("loading")}</p>;

  return (
    <section className="space-y-4 pb-8">
      <div>
        <h1 className="text-3xl font-bold text-[#14284b]">{t("plan_title")}: {rm.subject_name}</h1>
        <p className="text-sm font-medium text-slate-700">{t("goal_label")}: {rm.goal_name}{rm.target_date && ` · ${t("target_date")} ${longDate(rm.target_date, lang)}`}</p>
        <p className="text-sm text-slate-600">v{rm.version} · {rm.days} · {rm.daily_minutes} min · {t("review_date")} {longDate(rm.review_on, lang)}</p>
        <p className="mt-2 text-slate-700">{rm.summary}</p>
        {Object.values(rm.levels).filter((l) => l.level).length > 0 && (
          <p className="mt-2 text-sm text-slate-600"><b>{t("levels_h")}:</b> {Object.values(rm.levels).filter((l) => l.level).map((l) => `${l.topic} ${t(`level_${l.level!}` as const)} (${l.source === "check" ? t("src_check") : l.source === "student" ? t("src_student") : t("src_records")})`).join("; ")} · {t("provisional")}</p>
        )}
      </div>
      <div className="space-y-3">
        {rm.tasks.map((task) => {
          const res = rm.resources[task.resource_id];
          return (
            <article key={task.id} className={`rounded-2xl border-2 bg-white p-4 shadow-sm ${task.kind === "checkpoint" ? "border-emerald-300" : "border-transparent"}`}>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="font-semibold">{dayRange(rm.start_on, task.day_from, task.day_to, lang)} · {task.topic}</div>
                {task.kind === "checkpoint" && <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs text-emerald-800">{t("checkpoint")}</span>}
              </div>
              <p className="mt-1">{task.activity}</p>
              <p className="mt-1 text-sm text-slate-600"><b>{t("why")}:</b> {task.reason} · <b>{t("effort")}:</b> {task.minutes} min · <b>{t("check")}:</b> {task.check} · <b>due</b> {shortDate(task.due_on, lang)}</p>
              {res && <p className="text-sm"><b>{t("resource")}:</b> <a href={res.url} target="_blank" rel="noreferrer" className="underline">{res.title}</a> <span className="text-slate-500">· {res.source}</span></p>}
            </article>
          );
        })}
      </div>

      <div className="rounded-2xl bg-white p-5 shadow-sm print:hidden">
        {!share ? (
          <button onClick={newCode} className="min-h-14 rounded-xl bg-[#14284b] px-8 text-xl font-semibold text-white">{t("send_phone")}</button>
        ) : (
          <div className="flex flex-wrap items-center gap-6">
            <div className="rounded-xl border border-slate-200 bg-white p-3" aria-label="QR code"><QRCodeSVG value={share.url} size={200} /></div>
            <div>
              <p className="text-lg">{t("scan_note")}</p>
              <p className="mt-1 text-2xl font-semibold">{t("expires_in")} {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}</p>
              <button onClick={newCode} className="mt-3 min-h-12 rounded-lg border border-slate-300 px-4">{t("new_code")}</button>
            </div>
          </div>
        )}
      </div>
      <div className="flex flex-wrap gap-3 print:hidden">
        <button onClick={() => window.print()} className="min-h-12 rounded-lg border border-slate-300 bg-white px-5">{t("print")}</button>
        <Link href={`/report/${rm.id}`} className="min-h-12 rounded-lg border border-slate-300 bg-white px-5 py-3">{t("report")}</Link>
        <Link href="/profile" className="min-h-12 rounded-lg border border-slate-300 bg-white px-5 py-3">{t("back")}</Link>
      </div>
    </section>
  );
}
