"use client";
import { useCallback, useEffect, useState } from "react";
import { useUi } from "@/app/providers";
import { api, ApiError } from "@/lib/api";
import { kioskError } from "@/lib/kiosk";
import type { DiagnosticOut, DiagnosticResult } from "@/lib/types";

/** One question per screen, four large option buttons (keys 1-4), Skip, progress. No timer is shown. */
export function ConceptCheck({ subject, topic, purpose = "level", roadmapId, onDone, push }: {
  subject: string; topic: string; purpose?: "level" | "review"; roadmapId?: number; onDone: (r: DiagnosticResult) => void; push: (p: string) => void;
}) {
  const { t } = useUi();
  const [d, setD] = useState<DiagnosticOut | null>(null);
  const [i, setI] = useState(0);
  const [answers, setAnswers] = useState<(number | null)[]>([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<DiagnosticResult | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const out = await api<DiagnosticOut>("/diagnostics", { method: "POST", json: { subject_code: subject, topic, purpose, roadmap_id: roadmapId ?? null } });
        if (alive) setD(out);
      } catch (e) {
        const c = kioskError(e, push);
        if (alive && c !== "no_session" && c !== "consent_required") setErr(c === "not_found" || c === "not_enough_questions" ? t("no_check_bank") : t("error_generic"));
      }
    })();
    return () => { alive = false; };
  }, [subject, topic, purpose, roadmapId, push, t]);

  const submit = useCallback(async (all: (number | null)[]) => {
    if (!d) return;
    setBusy(true);
    try {
      const r = await api<DiagnosticResult>(`/diagnostics/${d.id}/submit`, { method: "POST", json: { answers: all } });
      setRes(r);
    } catch (e) {
      const code = kioskError(e, push);
      setErr(e instanceof ApiError && e.code === "check_expired" ? t("check_expired") : code === "no_session" || code === "consent_required" ? "" : t("error_generic"));
    }
    setBusy(false);
  }, [d, push, t]);

  const pick = useCallback((choice: number | null) => {
    if (!d || busy) return;
    const next = [...answers, choice];
    setAnswers(next);
    if (i + 1 >= d.questions.length) void submit(next); else setI(i + 1);
  }, [answers, busy, d, i, submit]);

  // Keyboard: 1-4 answer, S skips.
  useEffect(() => {
    if (!d || res) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key >= "1" && e.key <= "4") pick(Number(e.key) - 1);
      else if (e.key.toLowerCase() === "s") pick(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [d, res, pick]);

  if (err) return <p role="alert" className="rounded-lg bg-amber-50 px-4 py-3 text-amber-900">{err}</p>;
  if (res) return <CheckResult r={res} onContinue={() => onDone(res)} />;
  if (!d) return <p className="text-slate-500">{t("loading")}</p>;

  const q = d.questions[i];
  return (
    <div className="mx-auto w-full max-w-2xl">
      <p className="text-sm text-slate-600" aria-live="polite">{t("question_of")} {i + 1} {t("of")} {d.questions.length} · {topic}</p>
      <div className="mt-1 flex gap-1" aria-hidden>{d.questions.map((_, k) => <span key={k} className={`h-2 flex-1 rounded-full ${k <= i ? "bg-[#14284b]" : "bg-slate-200"}`} />)}</div>
      <h2 className="mt-4 text-2xl font-semibold text-[#14284b]">{q.stem}</h2>
      <div className="mt-4 grid gap-3">
        {q.options.map((o, k) => (
          <button key={k} onClick={() => pick(k)} disabled={busy} className="min-h-16 rounded-xl border-2 border-slate-300 bg-white px-5 py-3 text-left text-lg hover:border-[#14284b] disabled:opacity-50">
            <span className="mr-3 font-bold text-[#14284b]">{k + 1}</span>{o}
          </button>
        ))}
      </div>
      <button onClick={() => pick(null)} disabled={busy} className="mt-4 min-h-12 rounded-lg border border-slate-300 bg-white px-6">{t("skip")} (S)</button>
    </div>
  );
}

export function CheckResult({ r, onContinue }: { r: DiagnosticResult; onContinue: () => void }) {
  const { t } = useUi();
  return (
    <div className="mx-auto w-full max-w-2xl space-y-4">
      <h2 className="text-2xl font-bold text-[#14284b]">{t("result_title")}: {r.topic}</h2>
      <div className="rounded-2xl bg-white p-4 shadow-sm">
        <p className="text-lg">{t("score")}: <b>{r.correct} / {r.total}</b></p>
        <p className="text-lg">{t("your_level")}: <b>{t(`level_${r.level}` as const)}</b> <span className="text-sm text-slate-500">({t("provisional")}, {t("src_check")})</span></p>
        <p className="mt-2 text-sm text-slate-600">{t("check_note")}</p>
      </div>
      <ol className="space-y-3">
        {r.items.map((it, k) => (
          <li key={it.id} className={`rounded-xl border-2 bg-white p-3 text-sm ${it.correct ? "border-emerald-300" : "border-amber-300"}`}>
            <p className="font-medium">{k + 1}. {it.correct ? "✓" : "✗"} {it.chosen === null ? `(${t("skip")})` : `${t("your_choice")}: ${it.chosen + 1}`} · {t("correct_answer")}: {it.answer + 1}</p>
            <p className="mt-1 text-slate-700">{it.explanation}</p>
          </li>
        ))}
      </ol>
      <button autoFocus onClick={onContinue} className="min-h-14 rounded-xl bg-[#14284b] px-8 text-xl font-semibold text-white">{t("continue_")}</button>
    </div>
  );
}
