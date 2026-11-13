"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useUi } from "@/app/providers";
import { ConceptCheck } from "@/components/ConceptCheck";
import { ReportView } from "@/components/ReportView";
import { api } from "@/lib/api";
import { kioskError } from "@/lib/kiosk";
import type { NextStep, Profile, Report, RoadmapView } from "@/lib/types";

type Step = "checkin" | "check" | "report";

/** Review check-in (RB 4, 9, 18): optional confidence and plan-fit, a concept check on the weakest bank topic of the plan,
 *  then the report and a choice of next step. */
export default function Review() {
  const { t } = useUi();
  const { id } = useParams<{ id: string }>();
  const rid = Number(id);
  const router = useRouter();
  const [step, setStep] = useState<Step>("checkin");
  const [confidence, setConfidence] = useState<number | null>(null);
  const [fit, setFit] = useState<number | null>(null);
  const [topic, setTopic] = useState<string | null>(null);
  const [rm, setRm] = useState<RoadmapView | null>(null);
  const [report, setReport] = useState<Report | null>(null);
  const [err, setErr] = useState("");

  // The weakest catalogue topic of the plan's tasks (via their resources) that has bank questions.
  useEffect(() => {
    (async () => {
      try {
        const [plan, profile] = await Promise.all([api<RoadmapView>(`/roadmaps/${rid}`), api<Profile>("/me/profile")]);
        setRm(plan);
        const subj = profile.subjects.find((s) => s.code === plan.subject_code);
        const planTopics = [...new Set(plan.tasks.map((x) => plan.resources[x.resource_id]?.topic).filter(Boolean))] as string[];
        const banked = (subj?.levels ?? []).filter((l) => l.has_check && planTopics.includes(l.topic));   // levels are weakest first
        setTopic(banked[0]?.topic ?? null);
      } catch (e) { const c = kioskError(e, router.push); if (c !== "no_session" && c !== "consent_required") setErr(t("error_generic")); }
    })();
  }, [rid, router, t]);

  async function finish() {
    try {
      await api(`/roadmaps/${rid}/review`, { method: "POST", json: { confidence, plan_fit: fit } });
      setReport(await api<Report>(`/roadmaps/${rid}/report`));
      setStep("report");
    } catch (e) { kioskError(e, router.push); setErr(t("error_generic")); }
  }
  function afterCheckin() { if (topic) setStep("check"); else void finish(); }

  async function goNext(s: NextStep) {
    if (!report) return;
    if (s.code === "revise") router.push(`/roadmap/new?goal=${report.goal}&subject=${report.subject_code}`);
    else if (s.code === "prerequisite") router.push(`/roadmap/new?goal=${report.goal}&subject=${report.subject_code}`);
    else if (s.code === "check") router.push("/check");
    else if (s.code === "mentor") { try { await api("/requests", { method: "POST", json: { category: "academic", subject_code: report.subject_code } }); } catch (e) { kioskError(e, router.push); } }
  }

  if (err) return <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-red-800">{err}</p>;
  if (!rm) return <p className="text-slate-500">{t("loading")}</p>;
  const pill = (on: boolean) => `min-h-12 rounded-xl border px-5 text-base ${on ? "border-[#14284b] bg-[#14284b] text-white" : "border-slate-300 bg-white"}`;

  if (step === "check" && topic) {
    return <ConceptCheck subject={rm.subject_code} topic={topic} purpose="review" roadmapId={rid} push={router.push} onDone={() => void finish()} />;
  }
  if (step === "report" && report) {
    return (
      <section className="space-y-4 pb-8">
        <h1 className="text-3xl font-bold text-[#14284b]">{t("report_title")}</h1>
        <ReportView r={report} />
        <div className="print:hidden">
          <h2 className="font-semibold">{t("choose_next")}</h2>
          <div className="mt-2 flex flex-wrap gap-3">
            {report.next_steps.map((s, i) => <button key={i} onClick={() => goNext(s)} className="min-h-12 rounded-lg bg-[#14284b] px-5 text-white">{t(`ns_${s.code}` as "ns_check")}</button>)}
            <button onClick={() => router.push("/mentor")} className="min-h-12 rounded-lg border border-slate-300 bg-white px-5">{t("talk_mentor")}</button>
            <Link href="/profile" className="min-h-12 rounded-lg border border-slate-300 bg-white px-5 py-3">{t("back")}</Link>
          </div>
        </div>
      </section>
    );
  }
  return (
    <section className="mx-auto w-full max-w-2xl space-y-6 pb-8">
      <div>
        <h1 className="text-3xl font-bold text-[#14284b]">{t("review_title")}</h1>
        <p className="text-slate-600">{rm.goal_name} · {rm.subject_name} · {t("optional_note")}</p>
      </div>
      <div>
        <h2 className="font-semibold">{t("confidence_q")}</h2>
        <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label={t("confidence_q")}>
          {[t("not_confident"), t("somewhat"), t("confident")].map((label, i) => <button key={label} onClick={() => setConfidence(confidence === i + 1 ? null : i + 1)} aria-pressed={confidence === i + 1} className={pill(confidence === i + 1)}>{label}</button>)}
        </div>
      </div>
      <div>
        <h2 className="font-semibold">{t("plan_fit_q")}</h2>
        <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label={t("plan_fit_q")}>
          {[1, 2, 3, 4, 5].map((n) => <button key={n} onClick={() => setFit(fit === n ? null : n)} aria-pressed={fit === n} className={pill(fit === n)}>{n}</button>)}
        </div>
      </div>
      {topic && <p className="text-sm text-slate-600">{t("then_check")} <b>{topic}</b>.</p>}
      <button onClick={afterCheckin} className="min-h-14 rounded-xl bg-[#14284b] px-8 text-xl font-semibold text-white">{t("continue_")}</button>
    </section>
  );
}
