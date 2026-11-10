"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useUi } from "@/app/providers";
import { api } from "@/lib/api";
import { hardReset, kioskError } from "@/lib/kiosk";

const NOTICE_VERSION = "v1";

export default function Consent() {
  const { t, studentName } = useUi();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => { if (studentName === null && typeof window !== "undefined" && !sessionStorage.getItem("studentName")) router.replace("/"); }, [studentName, router]);

  async function accept() {
    setBusy(true);
    try {
      await api("/consent", { method: "POST", json: { notice_version: NOTICE_VERSION } });
      router.push("/profile");
    } catch (e) { kioskError(e, router.push); setErr(t("error_generic")); setBusy(false); }
  }

  const rows: [Parameters<typeof t>[0], Parameters<typeof t>[0]][] = [
    ["consent_what_h", "consent_what"], ["consent_why_h", "consent_why"], ["consent_ai_h", "consent_ai"],
    ["consent_who_h", "consent_who"], ["consent_long_h", "consent_long"], ["consent_cam_h", "consent_cam"],
  ];
  return (
    <section className="mx-auto w-full max-w-2xl flex-1 py-4">
      <h1 className="text-3xl font-bold text-[#14284b]">{t("consent_title")}</h1>
      <div className="mt-4 space-y-3 rounded-2xl bg-white p-5 shadow-sm">
        {rows.map(([h, b]) => (
          <div key={h}><h2 className="font-semibold text-[#14284b]">{t(h)}</h2><p className="text-slate-700">{t(b)}</p></div>
        ))}
      </div>
      {err && <p role="alert" className="mt-3 rounded-lg bg-red-50 px-4 py-3 text-red-800">{err}</p>}
      <div className="mt-5 flex gap-3">
        <button onClick={accept} disabled={busy} autoFocus className="min-h-14 rounded-xl bg-[#14284b] px-8 text-xl font-semibold text-white disabled:opacity-40">{t("accept")}</button>
        <button onClick={() => hardReset()} className="min-h-14 rounded-xl border border-slate-300 bg-white px-6 text-lg">{t("decline")}</button>
      </div>
    </section>
  );
}
