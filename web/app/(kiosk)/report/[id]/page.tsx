"use client";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useUi } from "@/app/providers";
import { ReportView } from "@/components/ReportView";
import { api } from "@/lib/api";
import { kioskError } from "@/lib/kiosk";
import type { Report } from "@/lib/types";

export default function ReportPage() {
  const { t } = useUi();
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [r, setR] = useState<Report | null>(null);
  const [err, setErr] = useState("");
  const [asked, setAsked] = useState(false);

  useEffect(() => {
    (async () => {
      try { setR(await api<Report>(`/roadmaps/${id}/report`)); } catch (e) { kioskError(e, router.push); setErr(t("error_generic")); }
    })();
  }, [id, router, t]);

  async function human() {
    try { await api("/requests", { method: "POST", json: { kind: "referral", subject_code: r?.subject_code } }); setAsked(true); } catch (e) { kioskError(e, router.push); }
  }

  if (err) return <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-red-800">{err}</p>;
  if (!r) return <p className="text-slate-500">{t("loading")}</p>;
  return (
    <section className="space-y-4 pb-8">
      <h1 className="text-3xl font-bold text-[#14284b]">{t("report_title")}</h1>
      <ReportView r={r} />
      <div className="flex flex-wrap gap-3 print:hidden">
        <Link href={`/roadmap/new?subject=${r.subject_code}`} className="min-h-12 rounded-lg bg-[#14284b] px-5 py-3 text-white">{t("new_plan")}</Link>
        {r.remaining_flags.length > 0 && <button onClick={human} disabled={asked} className="min-h-12 rounded-lg border border-blue-300 bg-blue-50 px-5 text-blue-900 disabled:opacity-60">{asked ? t("human_mentor_msg") : t("human_mentor")}</button>}
        <button onClick={() => window.print()} className="min-h-12 rounded-lg border border-slate-300 bg-white px-5">{t("print")}</button>
        <Link href="/profile" className="min-h-12 rounded-lg border border-slate-300 bg-white px-5 py-3">{t("back")}</Link>
      </div>
    </section>
  );
}
