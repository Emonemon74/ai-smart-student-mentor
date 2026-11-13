"use client";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { useUi } from "@/app/providers";
import { ConceptCheck } from "@/components/ConceptCheck";
import { api } from "@/lib/api";
import { kioskError } from "@/lib/kiosk";
import type { Profile } from "@/lib/types";

/** Only same-site paths: "next" must start with "/" and not "//" (no open redirect). */
const safeNext = (n: string | null) => (n && n.startsWith("/") && !n.startsWith("//") ? n : "/profile");

function CheckInner() {
  const { t } = useUi();
  const router = useRouter();
  const sp = useSearchParams();
  const [p, setP] = useState<Profile | null>(null);
  const [subject, setSubject] = useState(sp.get("subject") ?? "");
  const [topic, setTopic] = useState(sp.get("topic") ?? "");
  const [started, setStarted] = useState(!!(sp.get("subject") && sp.get("topic")));
  const next = safeNext(sp.get("next"));

  useEffect(() => {
    (async () => { try { setP(await api<Profile>("/me/profile")); } catch (e) { kioskError(e, router.push); } })();
  }, [router]);

  // Subjects and topics that have questions, weakest first (levels are sorted weakest first by the API).
  const options = (p?.subjects ?? []).filter((s) => s.levels.some((l) => l.has_check));
  const topics = options.find((s) => s.code === subject)?.levels.filter((l) => l.has_check) ?? [];

  if (started && subject && topic) {
    return <ConceptCheck subject={subject} topic={topic} push={router.push} onDone={() => router.push(next)} />;
  }
  const field = "mt-1 min-h-14 w-full rounded-xl border border-slate-300 bg-white px-4 text-lg";
  return (
    <section className="mx-auto w-full max-w-md space-y-4">
      <h1 className="text-3xl font-bold text-[#14284b]">{t("check_title")}</h1>
      <p className="text-slate-600">{t("check_intro")}</p>
      {!p ? <p className="text-slate-500">{t("loading")}</p> : options.length === 0 ? <p>{t("no_check_bank")}</p> : (
        <>
          <label className="block text-sm font-medium">{t("check_choose_subject")}
            <select value={subject} onChange={(e) => { setSubject(e.target.value); setTopic(""); }} className={field}>
              <option value="">-</option>{options.map((s) => <option key={s.code} value={s.code}>{s.name}</option>)}
            </select>
          </label>
          <label className="block text-sm font-medium">{t("check_choose_topic")}
            <select value={topic} onChange={(e) => setTopic(e.target.value)} className={field} disabled={!subject}>
              <option value="">-</option>{topics.map((l) => <option key={l.topic} value={l.topic}>{l.topic}</option>)}
            </select>
          </label>
          <button onClick={() => setStarted(true)} disabled={!subject || !topic} className="min-h-14 rounded-xl bg-[#14284b] px-8 text-xl font-semibold text-white disabled:opacity-40">{t("start_check")}</button>
        </>
      )}
    </section>
  );
}

export default function CheckPage() {
  return <Suspense fallback={null}><CheckInner /></Suspense>;
}
