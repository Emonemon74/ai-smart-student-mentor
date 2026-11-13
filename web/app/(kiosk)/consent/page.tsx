"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useUi } from "@/app/providers";
import { api } from "@/lib/api";
import { hardReset, kioskError } from "@/lib/kiosk";
import type { Mode } from "@/lib/types";

const NOTICE_VERSION = "v2";

export default function Consent() {
  const { t, studentName, setMode } = useUi();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => { if (studentName === null && typeof window !== "undefined" && !sessionStorage.getItem("studentName")) router.replace("/"); }, [studentName, router]);

  // Two scopes: personal (use my records) or general (guidance without records). Both are explicit choices.
  async function choose(scope: Mode) {
    setBusy(true);
    try {
      await api("/consent", { method: "POST", json: { notice_version: NOTICE_VERSION, scope } });
      setMode(scope);
      router.push(scope === "personal" ? "/profile" : "/explore");
    } catch (e) { kioskError(e, router.push); setErr(t("error_generic")); setBusy(false); }
  }

  const rows: [Parameters<typeof t>[0], Parameters<typeof t>[0]][] = [
    ["consent_what_h", "consent_what2"], ["consent_why_h", "consent_why2"], ["consent_save_h", "consent_save"], ["consent_ai_h", "consent_ai2"],
    ["consent_who_h", "consent_who2"], ["consent_long_h", "consent_long2"], ["consent_choice_h", "consent_choice"],
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
      <div className="mt-5 flex flex-wrap gap-3">
        <button onClick={() => choose("personal")} disabled={busy} autoFocus className="min-h-14 rounded-xl bg-[#14284b] px-8 text-xl font-semibold text-white disabled:opacity-40">{t("use_records")}</button>
        <button onClick={() => choose("general")} disabled={busy} className="min-h-14 rounded-xl border border-[#14284b] bg-white px-6 text-lg text-[#14284b] disabled:opacity-40">{t("no_records")}</button>
        <button onClick={() => hardReset()} className="min-h-14 rounded-xl border border-slate-300 bg-white px-6 text-lg">{t("exit")}</button>
      </div>
    </section>
  );
}
