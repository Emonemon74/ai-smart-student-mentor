"use client";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useUi } from "@/app/providers";
import { SupportPanel } from "@/components/SupportPanel";
import { api } from "@/lib/api";
import { hardReset } from "@/lib/kiosk";
import type { Contact, RequestOut } from "@/lib/types";

const WARN_AFTER_MS = 100_000; // warning at 100 s idle
const WARN_SECONDS = 20;       // then 20 s countdown = 2 min total
const HEALTH_MS = 30_000;

export function KioskShell({ children }: { children: React.ReactNode }) {
  const { t, lang, setLang, textSize, setTextSize, studentName, mode } = useUi();
  const router = useRouter();
  const pathname = usePathname();
  const [warn, setWarn] = useState<number | null>(null);
  const [down, setDown] = useState(false);
  const [chooser, setChooser] = useState(false);
  const [panel, setPanel] = useState<{ contacts: Contact[]; wellbeing: boolean; academic: boolean } | null>(null);
  const [deskMsg, setDeskMsg] = useState(false);
  const idle = useRef<ReturnType<typeof setTimeout> | null>(null);
  const loggedIn = !!studentName;

  // Back-forward cache guard: a restored page must never show the previous student's data.
  useEffect(() => {
    const onShow = (e: PageTransitionEvent) => { if (e.persisted) location.reload(); };
    window.addEventListener("pageshow", onShow);
    return () => window.removeEventListener("pageshow", onShow);
  }, []);

  // Idle timer (only while signed in).
  const startTimer = useCallback(() => {
    if (idle.current) clearTimeout(idle.current);
    idle.current = setTimeout(() => setWarn(WARN_SECONDS), WARN_AFTER_MS);
  }, []);
  const arm = useCallback(() => { setWarn(null); startTimer(); }, [startTimer]);
  useEffect(() => {
    if (!loggedIn) return;
    startTimer();
    const onActivity = () => { if (warn === null) arm(); };
    window.addEventListener("pointerdown", onActivity);
    window.addEventListener("keydown", onActivity);
    return () => {
      window.removeEventListener("pointerdown", onActivity);
      window.removeEventListener("keydown", onActivity);
      if (idle.current) clearTimeout(idle.current);
    };
  }, [loggedIn, arm, startTimer, warn]);
  useEffect(() => {
    if (warn === null) return;
    if (warn <= 0) { hardReset(); return; }
    const id = setTimeout(() => setWarn((w) => (w === null ? null : w - 1)), 1000);
    return () => clearTimeout(id);
  }, [warn]);

  // Health poll: offline help screen when the API or DB is down.
  useEffect(() => {
    let alive = true;
    const check = async () => {
      try {
        const h = await api<{ db: boolean }>("/healthz");
        if (alive) setDown(!h.db);
      } catch { if (alive) setDown(true); }
    };
    check();
    const id = setInterval(check, HEALTH_MS);
    return () => { alive = false; clearInterval(id); };
  }, []);

  // "Talk to a human": choose an academic mentor or a private counsellor. Both show the team's contacts straight away.
  async function academic() {
    setChooser(false);
    try {
      const r = await api<RequestOut>("/requests", { method: "POST", json: { category: "academic" } });
      setPanel({ contacts: r.contacts, wellbeing: false, academic: true });
    } catch { setDeskMsg(true); } // e.g. before consent: be honest and point to the desk instead of claiming it was sent
  }
  async function counsellor() {
    setChooser(false);
    try {
      setPanel({ contacts: await api<Contact[]>("/support/contacts"), wellbeing: true, academic: false });
    } catch { setDeskMsg(true); }
  }

  const showHeader = loggedIn && pathname !== "/" && pathname !== "/login";

  return (
    <div className="mx-auto flex min-h-screen max-w-5xl flex-col p-4 md:p-6">
      {showHeader && (
        <header className="mb-4 flex flex-wrap items-center justify-between gap-2 print:hidden">
          <div className="flex items-center gap-2 font-semibold text-[#14284b]">{studentName}{mode === "general" && <span className="rounded-full bg-blue-100 px-3 py-1 text-xs font-medium text-blue-900">{t("general_chip")}</span>}</div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <button onClick={() => setLang(lang === "en" ? "hi" : "en")} className="min-h-12 rounded-lg border border-slate-300 bg-white px-4">{lang === "en" ? "हिन्दी" : "English"}</button>
            <button onClick={() => setTextSize(textSize === "normal" ? "large" : "normal")} aria-label={t("text_size")} className="min-h-12 rounded-lg border border-slate-300 bg-white px-4">{textSize === "normal" ? t("large") : t("normal")}</button>
            <button onClick={() => setChooser(true)} className="min-h-12 rounded-lg border border-blue-300 bg-blue-50 px-4 text-blue-900">{t("human_mentor")}</button>
            <button onClick={() => router.push("/end")} className="min-h-12 rounded-lg bg-[#14284b] px-4 text-white">{t("end_session")}</button>
          </div>
        </header>
      )}
      <main className="flex flex-1 flex-col">{children}</main>

      {warn !== null && (
        <Modal>
          <h2 className="text-xl font-bold">{t("idle_title")}</h2>
          <p className="mt-2">{t("idle_body")} {warn} {t("seconds")}</p>
          <button autoFocus onClick={arm} className="mt-4 min-h-12 rounded-lg bg-[#14284b] px-6 text-white">{t("stay")}</button>
        </Modal>
      )}
      {chooser && (
        <Modal>
          <p className="font-semibold">{t("human_choose")}</p>
          <div className="mt-4 flex flex-col gap-3">
            <button autoFocus onClick={academic} className="min-h-12 rounded-lg bg-[#14284b] px-6 text-white">{t("academic_mentor")}</button>
            <button onClick={counsellor} className="min-h-12 rounded-lg border border-blue-300 bg-blue-50 px-6 text-blue-900">{t("counsellor_private")}</button>
            <button onClick={() => setChooser(false)} className="min-h-12 rounded-lg border border-slate-300 px-6">{t("cancel")}</button>
          </div>
        </Modal>
      )}
      {panel && (
        <div role="dialog" aria-modal="true" className="fixed inset-0 z-40 grid place-items-center overflow-y-auto bg-black/40 p-4 print:hidden">
          <div className="w-full max-w-lg">
            {panel.academic && <p role="status" className="mb-2 rounded-lg bg-white px-3 py-2 text-emerald-800">{t("academic_sent")}</p>}
            <SupportPanel contacts={panel.contacts} canRequest={panel.wellbeing} onClose={() => setPanel(null)} />
          </div>
        </div>
      )}
      {deskMsg && (
        <Modal>
          <p>{t("human_mentor_desk")}</p>
          <button autoFocus onClick={() => setDeskMsg(false)} className="mt-4 min-h-12 rounded-lg bg-[#14284b] px-6 text-white">{t("close")}</button>
        </Modal>
      )}
      {down && (
        <div role="alert" className="fixed inset-0 z-50 grid place-items-center bg-white p-8 text-center text-2xl font-semibold text-[#14284b]">
          {t("unavailable")}
        </div>
      )}
    </div>
  );
}

function Modal({ children }: { children: React.ReactNode }) {
  return (
    <div role="dialog" aria-modal="true" className="fixed inset-0 z-40 grid place-items-center bg-black/40 p-4 print:hidden">
      <div className="max-w-md rounded-2xl bg-white p-6 text-center shadow-xl">{children}</div>
    </div>
  );
}
