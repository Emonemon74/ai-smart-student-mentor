"use client";
import { useUi } from "@/app/providers";
import { dayRange, longDate } from "@/lib/dates";
import { indicatorLabel, indicatorValue, limitationText, nextStepText } from "@/lib/report-i18n";
import type { Indicator, Report } from "@/lib/types";

const BADGE: Record<Indicator["source"], string> = {
  verified: "bg-blue-100 text-blue-900", kiosk_check: "bg-violet-100 text-violet-900", self_reported: "bg-slate-200 text-slate-800",
};

/** Three evidence kinds, never mixed: verified marks (blue), kiosk concept checks (violet), the student's own activity (dashed grey).
 *  Section order follows LLD_next C12 ReportView. Used on the kiosk and on the phone. */
export function ReportView({ r }: { r: Report }) {
  const { t, lang } = useUi();
  const sr = r.self_reported;
  const srcLabel = (s: Indicator["source"]) => (s === "verified" ? t("src_verified") : s === "kiosk_check" ? t("src_kiosk") : t("src_self"));
  const d = (iso: string | null) => (iso ? longDate(iso.slice(0, 10), lang) : "-");   // review_imported_at is a full timestamp
  return (
    <div className="space-y-4">
      <p className="text-sm text-slate-600">
        {r.roll_no} · {r.programme} · {t("semester")} {r.semester} · {r.subject_name} · v{r.version} · {t("goal_label")}: {r.goal_name}
        {" · "}{longDate(r.start_on, lang)} – {longDate(r.review_on, lang)}{r.target_date && ` · ${t("target_date")} ${longDate(r.target_date, lang)}`}
      </p>

      <section className="rounded-2xl border-2 border-blue-200 bg-white p-4 shadow-sm">
        <h2 className="font-semibold text-blue-900">{t("verified")}</h2>
        <p className="text-xs text-slate-500">{t("verified_note")}</p>
        {r.has_review_data && r.baseline_subject_pct !== null && r.review_subject_pct !== null && (
          <p className="mt-2 text-lg">{r.baseline_subject_pct}% → <b>{r.review_subject_pct}%</b></p>
        )}
        {r.verified.length > 0 && (
          <table className="mt-2 w-full text-sm">
            <thead><tr className="text-left text-slate-500"><th className="py-1 font-normal">&nbsp;</th><th className="pr-3 font-normal">{t("before")}</th><th className="pr-3 font-normal">{t("after")}</th><th className="text-right font-normal">{t("change")}</th></tr></thead>
            <tbody>
              {r.verified.map((v) => (
                <tr key={`${v.topic}-${v.kind}`} className="border-t">
                  <td className="py-1.5">{v.topic} <span className="text-slate-400">({v.kind})</span></td>
                  <td className="pr-3">{v.baseline_pct}%</td>
                  <td className="pr-3">{v.review_pct === null ? <span className="text-slate-500">{v.note}</span> : `${v.review_pct}%`}</td>
                  <td className={`text-right font-medium ${v.delta === null ? "" : v.delta >= 0 ? "text-emerald-700" : "text-red-700"}`}>{v.delta === null ? "" : `${v.delta >= 0 ? "+" : ""}${v.delta}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {r.checks.length > 0 && (
        <section className="rounded-2xl border-2 border-violet-200 bg-white p-4 shadow-sm">
          <h2 className="font-semibold text-violet-900">{t("kiosk_checks_h")}</h2>
          <p className="text-xs text-slate-500">{t("kiosk_checks_note")}</p>
          <table className="mt-2 w-full text-sm">
            <thead><tr className="text-left text-slate-500"><th className="py-1 font-normal">&nbsp;</th><th className="font-normal">{t("before")}</th><th className="font-normal">{t("after")}</th></tr></thead>
            <tbody>
              {r.checks.map((c) => (
                <tr key={c.topic} className="border-t align-top">
                  <td className="py-1.5">{c.topic}</td>
                  <td>{c.before_level ? `${t(`level_${c.before_level}` as const)} · ${c.before_score}` : "-"}</td>
                  <td>{c.after_level ? `${t(`level_${c.after_level}` as const)} · ${c.after_score}` : <span className="text-slate-500">{c.note}</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section className="rounded-2xl border-2 border-dashed border-slate-300 bg-white p-4 shadow-sm">
        <h2 className="font-semibold">{t("self_reported")}</h2>
        <p className="text-xs text-slate-500">{t("self_note")}</p>
        <p className="mt-2">{t("done")} {sr.done} · {t("partial")} {sr.partial} · {t("pending")} {sr.pending} <span className="text-slate-500">/ {sr.total}</span></p>
        {r.confidence_review !== null && <p className="text-sm text-slate-600">{t("confidence_label")}: {[t("not_confident"), t("somewhat"), t("confident")][r.confidence_review - 1]}</p>}
        {sr.overdue.length > 0 && (
          <ul className="mt-2 text-sm text-red-800">
            {sr.overdue.map((o) => <li key={o.id}>{t("overdue")}: {o.topic} · {dayRange(r.start_on, o.day_from, o.day_to, lang)}</li>)}
          </ul>
        )}
      </section>

      {r.indicators.length > 0 && (
        <section className="rounded-2xl bg-white p-4 shadow-sm">
          <h2 className="font-semibold">{t("indicators_h")}</h2>
          <ul className="mt-2 space-y-1 text-sm">
            {r.indicators.map((i) => (
              <li key={i.code} className="flex flex-wrap items-center justify-between gap-2">
                <span>{indicatorLabel(i.code, i.label, t)}: <b>{indicatorValue(i.value, t)}</b></span>
                <span className={`rounded-full px-2 py-0.5 text-xs ${BADGE[i.source]}`}>{srcLabel(i.source)}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {r.remaining_flags.length > 0 && (
        <section className="rounded-2xl bg-white p-4 shadow-sm">
          <h2 className="font-semibold">{t("remaining_gaps")}</h2>
          <ul className="mt-1 list-disc pl-5 text-sm">{r.remaining_flags.map((f, i) => <li key={i}>{f.reason}</li>)}</ul>
        </section>
      )}

      {r.next_steps.length > 0 && (
        <section className="rounded-2xl border-2 border-emerald-200 bg-white p-4 shadow-sm">
          <h2 className="font-semibold text-emerald-900">{t("next_steps_h")}</h2>
          <ul className="mt-1 space-y-1 text-sm">
            {r.next_steps.map((s, i) => <li key={i}><b>{t(`ns_${s.code}` as "ns_check")}:</b> {nextStepText(s.text, t)}</li>)}
          </ul>
        </section>
      )}
      {r.academic_referral !== "none" && <p className="text-sm text-slate-600">{t("referral_status")}: {r.academic_referral === "open" ? t("ref_open") : t("ref_closed")}</p>}

      <section className="rounded-2xl bg-white p-4 text-xs text-slate-600 shadow-sm">
        <h2 className="text-sm font-semibold text-slate-800">{t("limitations_h")}</h2>
        <ul className="mt-1 list-disc space-y-0.5 pl-5">{r.limitations.map((l, i) => <li key={i}>{limitationText(l, t, lang, (iso) => longDate(iso, lang))}</li>)}</ul>
        <p className="mt-2">{r.caveat}</p>
        <p className="mt-1 text-slate-500">{t("data_timestamps")} {d(r.baseline_as_of)}{r.review_imported_at ? ` · ${t("review_data")} ${d(r.review_imported_at)}` : ""}</p>
      </section>
    </div>
  );
}
