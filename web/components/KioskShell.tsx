"use client";
import { usePathname, useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useUi } from "@/app/providers";
import { api } from "@/lib/api";
import { hardReset } from "@/lib/kiosk";

const WARN_AFTER_MS = 100_000; // warning at 100 s idle
const WARN_SECONDS = 20;       // then 20 s countdown = 2 min total
const HEALTH_MS = 30_000;

export function KioskShell({ children }: { children: React.ReactNode }) {
  const { t, lang, setLang, textSize, setTextSize, studentName } = useUi();
  const router = useRouter();
  const pathname = usePathname();
  const [warn, setWarn] = useState<number | null>(null);
  const [down, setDown] = useState(false);
  const [humanMsg, setHumanMsg] = useState(false);
  const idle = useRef<ReturnType<typeof setTimeout> | null>(null);
  const loggedIn = !!studentName;

  // Back-forward cache guard: a restored page must never show the previous student's data.
  useEffect(() => {
    const onShow = (e: PageTransitionEvent) => { if (e.persisted) location.reload(); };
    window.addEventListener("pageshow", onShow);
    return () => window.removeEventListener("pageshow", onShow);
  }, []);

  // Idle timer (only while signed in).
  const arm = useCallback(() => {
    if (idle.current) clearTimeout(idle.current);
    setWarn(null);
    idle.current = setTimeout(() => setWarn(WARN_SECONDS), WARN_AFTER_MS);
  }, []);
  useEffect(() => {
    if (!loggedIn) return;
    arm();
    const onActivity = () => { if (warn === null) arm(); };
    window.addEventListener("pointerdown", onActivity);
    window.addEventListener("keydown", onActivity);
    return () => {
      window.removeEventListener("pointerdown", onActivity);
      window.removeEventListener("keydown", onActivity);
      if (idle.current) clearTimeout(idle.current);
    };
  }, [loggedIn, arm, warn]);
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

  async function humanMentor() {
    try { await api("/requests", { method: "POST", json: { kind: "referral" } }); } catch {}
    setHumanMsg(true);
  }

  const showHeader = loggedIn && pathname !== "/" && pathname !== "/login";

  return (
    <div className="mx-auto flex min-h-screen max-w-5xl flex-col p-4 md:p-6">
      {showHeader && (
        <header className="mb-4 flex flex-wrap items-center justify-between gap-2 print:hidden">
          <div className="font-semibold text-[#14284b]">{studentName}</div>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <button onClick={() => setLang(lang === "en" ? "hi" : "en")} className="min-h-12 rounded-lg border border-slate-300 bg-white px-4">{lang === "en" ? "हिन्दी" : "English"}</button>
            <button onClick={() => setTextSize(textSize === "normal" ? "large" : "normal")} aria-label={t("text_size")} className="min-h-12 rounded-lg border border-slate-300 bg-white px-4">{textSize === "normal" ? t("large") : t("normal")}</button>
            <button onClick={humanMentor} className="min-h-12 rounded-lg border border-blue-300 bg-blue-50 px-4 text-blue-900">{t("human_mentor")}</button>
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
      {humanMsg && (
        <Modal>
          <p>{t("human_mentor_msg")}</p>
          <button autoFocus onClick={() => setHumanMsg(false)} className="mt-4 min-h-12 rounded-lg bg-[#14284b] px-6 text-white">{t("close")}</button>
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
