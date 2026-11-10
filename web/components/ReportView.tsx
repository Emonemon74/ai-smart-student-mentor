"use client";
import { useUi } from "@/app/providers";
import { dayRange, longDate } from "@/lib/dates";
import type { Report } from "@/lib/types";

/** Two visually separate blocks (LLD C12 /report): verified results from assessments, and the student's own reported activity. */
export function ReportView({ r }: { r: Report }) {
  const { t, lang } = useUi();
  const sr = r.self_reported;
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">{r.subject_name} · v{r.version} · {longDate(r.start_on, lang)} – {longDate(r.review_on, lang)} · {r.programme}</p>

      <section className="rounded-2xl border-2 border-blue-200 bg-white p-4 shadow-sm">
        <h2 className="font-semibold text-blue-900">{t("verified")}</h2>
        <p className="text-xs text-slate-500">{t("verified_note")}</p>
        {r.has_review_data && r.baseline_subject_pct !== null && r.review_subject_pct !== null && (
          <p className="mt-2 text-lg">{r.baseline_subject_pct}% → <b>{r.review_subject_pct}%</b></p>
        )}
        <table className="mt-2 w-full text-sm">
          <thead><tr className="text-left text-slate-500"><th className="py-1 font-normal">&nbsp;</th><th className="font-normal">{t("before")}</th><th className="font-normal">{t("after")}</th><th className="text-right font-normal">{t("change")}</th></tr></thead>
          <tbody>
            {r.verified.map((v) => (
              <tr key={`${v.topic}-${v.kind}`} className="border-t">
                <td className="py-1.5">{v.topic} <span className="text-slate-400">({v.kind})</span></td>
                <td>{v.baseline_pct}%</td>
                <td>{v.review_pct === null ? <span className="text-slate-500">{v.note}</span> : `${v.review_pct}%`}</td>
                <td className={`text-right font-medium ${v.delta === null ? "" : v.delta >= 0 ? "text-emerald-700" : "text-red-700"}`}>{v.delta === null ? "" : `${v.delta >= 0 ? "+" : ""}${v.delta}`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="rounded-2xl border-2 border-dashed border-slate-300 bg-white p-4 shadow-sm">
        <h2 className="font-semibold">{t("self_reported")}</h2>
        <p className="text-xs text-slate-500">{t("self_note")}</p>
        <p className="mt-2">{t("done")} {sr.done} · {t("partial")} {sr.partial} · {t("pending")} {sr.pending} <span className="text-slate-500">/ {sr.total}</span></p>
        {sr.overdue.length > 0 && (
          <ul className="mt-2 text-sm text-red-800">
            {sr.overdue.map((o) => <li key={o.id}>{t("overdue")}: {o.topic} · {dayRange(r.start_on, o.day_from, o.day_to, lang)}</li>)}
          </ul>
        )}
      </section>

      {r.remaining_flags.length > 0 && (
        <section className="rounded-2xl bg-white p-4 shadow-sm">
          <h2 className="font-semibold">{t("remaining_gaps")}</h2>
          <ul className="mt-1 list-disc pl-5 text-sm">{r.remaining_flags.map((f, i) => <li key={i}>{f.reason}</li>)}</ul>
        </section>
      )}
      <p className="text-xs text-slate-500">{r.caveat}</p>
    </div>
  );
}
