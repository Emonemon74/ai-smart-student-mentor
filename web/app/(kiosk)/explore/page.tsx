"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useUi } from "@/app/providers";
import { api } from "@/lib/api";
import { kioskError } from "@/lib/kiosk";
import type { Contact, Goal, Resource } from "@/lib/types";

const LEVELS = ["all", "foundation", "beginner", "intermediate", "advanced"] as const;

/** General guidance (and a handy page in personal mode): goal pathways, approved resources and support contacts. */
export default function Explore() {
  const { t, lang, mode } = useUi();
  const router = useRouter();
  const [goals, setGoals] = useState<Goal[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [goal, setGoal] = useState<Goal | null>(null);
  const [subject, setSubject] = useState("");
  const [resources, setResources] = useState<Resource[]>([]);
  const [level, setLevel] = useState<(typeof LEVELS)[number]>("all");
  const [res, setRes] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const [g, c] = await Promise.all([api<Goal[]>("/goals"), api<Contact[]>("/support/contacts")]);
        setGoals(g); setContacts(c);
      } catch (e) { kioskError(e, router.push); setErr(t("error_generic")); }
    })();
  }, [router, t]);

  async function loadResources(g: Goal, code: string) {
    setSubject(code); setRes(true);
    try { setResources(await api<Resource[]>(`/resources?subject_code=${code}&goal=${g.code}&lang=${lang}`)); } catch (e) { kioskError(e, router.push); setResources([]); }
  }

  const shown = resources.filter((r) => level === "all" || r.level === level);
  const chip = (on: boolean) => `min-h-12 rounded-full border px-4 text-sm ${on ? "border-[#14284b] bg-[#14284b] text-white" : "border-slate-300 bg-white"}`;
  return (
    <section className="space-y-5 pb-8">
      <div>
        <h1 className="text-3xl font-bold text-[#14284b]">{t("explore_title")}</h1>
        <p className="text-slate-600">{t("explore_sub")}</p>
      </div>
      {err && <p role="alert" className="rounded-lg bg-red-50 px-4 py-3 text-red-800">{err}</p>}

      <div className="grid gap-3 md:grid-cols-2">
        {goals.map((g) => (
          <article key={g.code} className={`rounded-2xl border-2 bg-white p-4 shadow-sm ${goal?.code === g.code ? "border-[#14284b]" : "border-transparent"}`}>
            <h2 className="font-semibold">{lang === "hi" ? g.name_hi : g.name}</h2>
            <p className="mt-1 text-sm"><b>{t("components")}:</b> {g.components}</p>
            <p className="text-sm"><b>{t("indicators")}:</b> {g.indicators}</p>
            <button onClick={() => { setGoal(g); setSubject(""); setResources([]); setRes(false); }} className="mt-3 min-h-12 rounded-lg border border-slate-300 px-4 text-sm">{t("resources_h")}</button>
          </article>
        ))}
      </div>

      {goal && (
        <div className="rounded-2xl bg-white p-4 shadow-sm">
          <h2 className="font-semibold">{lang === "hi" ? goal.name_hi : goal.name} · {t("pick_subject")}</h2>
          {goal.subjects.length === 0 ? <p className="mt-2 text-sm text-slate-600">{t("no_goal_subjects")}</p> : (
            <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label={t("pick_subject")}>
              {goal.subjects.map((s) => <button key={s.code} onClick={() => loadResources(goal, s.code)} aria-pressed={subject === s.code} className={chip(subject === s.code)}>{s.name}</button>)}
            </div>
          )}
          {res && (
            <>
              <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label={t("level")}>
                {LEVELS.map((l) => <button key={l} onClick={() => setLevel(l)} aria-pressed={level === l} className={chip(level === l)}>{l === "all" ? t("all") : t(`level_${l}` as const)}</button>)}
              </div>
              {shown.length === 0 ? <p className="mt-3 text-sm text-slate-600">{t("no_resources")}</p> : (
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full text-left text-sm">
                    <thead className="text-slate-500"><tr><th className="py-1 font-normal">{t("resource")}</th><th className="font-normal">{t("format")}</th><th className="font-normal">{t("level")}</th><th className="font-normal">{t("language_col")}</th><th className="font-normal">{t("minutes")}</th><th className="font-normal">{t("source")}</th></tr></thead>
                    <tbody>
                      {shown.map((r) => (
                        <tr key={r.id} className="border-t">
                          <td className="py-1.5"><a href={r.url} target="_blank" rel="noreferrer" className="underline">{r.title}</a> <span className="text-slate-400">· {r.topic}</span></td>
                          <td>{t(`fmt_${r.kind}` as "fmt_video")}</td><td>{t(`level_${r.level}` as const)}</td><td>{t(`lang_${r.lang}` as "lang_en")}</td><td>{r.minutes}</td><td className="text-slate-500">{r.source}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      )}

      <div className="rounded-2xl bg-white p-4 shadow-sm">
        <h2 className="font-semibold">{t("contacts_h")}</h2>
        <ul className="mt-2 space-y-1 text-sm">
          {contacts.map((c) => <li key={c.name}><b>{lang === "hi" && c.name_hi ? c.name_hi : c.name}</b> · {c.how} · {c.hours}</li>)}
        </ul>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Link href="/mentor" className="inline-block min-h-14 rounded-xl bg-[#14284b] px-8 py-4 text-xl font-semibold text-white">{t("talk_mentor")}</Link>
        {mode === "general" ? <p className="text-sm text-slate-600">{t("create_plan_hint")}</p> : <Link href="/profile" className="min-h-12 rounded-lg border border-slate-300 bg-white px-5 py-3">{t("back")}</Link>}
      </div>
    </section>
  );
}
