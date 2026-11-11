"use client";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useUi } from "@/app/providers";
import { api } from "@/lib/api";
import { kioskError } from "@/lib/kiosk";
import type { ChatMessage, ChatReply } from "@/lib/types";
import { speak, stopSpeaking, useRecorder } from "@/lib/voice";

export default function Mentor() {
  const { t, lang } = useUi();
  const router = useRouter();
  const [msgs, setMsgs] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [muted, setMuted] = useState(false);
  const started = useRef(false);
  const bottom = useRef<HTMLDivElement>(null);
  const mutedRef = useRef(muted);
  useEffect(() => { mutedRef.current = muted; }, [muted]);

  const ask = useCallback(async (history: ChatMessage[]) => {
    setBusy(true); setErr("");
    try {
      const r = await api<ChatReply>("/mentor/chat", { method: "POST", json: { messages: history, lang } });
      setMsgs([...history, { role: "assistant", content: r.reply }]);
      if (!mutedRef.current) speak(r.reply, lang);
    } catch (e) {
      const code = kioskError(e, router.push);
      if (code === "ai_unavailable") setErr(t("ai_busy"));
      else if (code !== "no_session" && code !== "consent_required") setErr(t("error_generic"));
    }
    setBusy(false);
  }, [lang, router, t]);

  // Opening turn: the mentor speaks first. The ref guards React strict-mode double mounting.
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void ask([]);
    return () => stopSpeaking();
  }, [ask]);

  useEffect(() => { bottom.current?.scrollIntoView({ block: "end" }); }, [msgs, busy]);
  // Keyboard users: the message box has focus on arrival and again after each reply.
  useEffect(() => { if (!busy) inputRef.current?.focus(); }, [busy]);

  const onText = useCallback((text: string) => setInput((cur) => (cur ? cur + " " : "") + text), []);
  const rec = useRecorder(onText, lang);

  function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    void ask([...msgs, { role: "user", content: text }]);
  }
  function createPlan() {
    try { sessionStorage.setItem("mentorMessages", JSON.stringify(msgs)); } catch {}
    router.push("/roadmap/new");
  }

  const micMsg = rec.error === "mic_denied" || rec.error === "stt_unavailable" || rec.error ? t("stt_failed") : "";
  const canPlan = msgs.some((m) => m.role === "user");

  return (
    <section className="flex flex-1 flex-col">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-[#14284b]">{t("mentor_title")}</h1>
        <button onClick={() => { setMuted((m) => !m); stopSpeaking(); }} aria-pressed={muted} className="min-h-12 rounded-lg border border-slate-300 bg-white px-4 text-sm">{muted ? t("unmute") : t("mute")}</button>
      </div>
      <div className="mt-3 flex-1 space-y-3 overflow-y-auto rounded-2xl bg-white p-4 shadow-sm" style={{ maxHeight: "52vh", minHeight: "30vh" }} aria-live="polite">
        {msgs.map((m, i) => (
          <div key={i} className={`flex ${m.role === "user" ? "justify-end" : ""}`}>
            <div className={`max-w-[80%] rounded-2xl px-4 py-3 text-lg ${m.role === "user" ? "bg-[#14284b] text-white" : "bg-slate-100"}`}>{m.content}</div>
          </div>
        ))}
        {busy && <div className="text-slate-400">…</div>}
        <div ref={bottom} />
      </div>
      {(err || micMsg) && <p role="alert" className="mt-3 rounded-lg bg-amber-50 px-4 py-3 text-amber-900">{err || micMsg}</p>}
      <div className="mt-3 flex gap-2">
        <input ref={inputRef} autoFocus value={input} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => e.key === "Enter" && send()} placeholder={rec.busy ? t("transcribing") : rec.recording ? t("recording") : t("type_message")}
          aria-label={t("type_message")} className="min-h-14 flex-1 rounded-xl border border-slate-300 bg-white px-4 text-lg" />
        <button
          onPointerDown={(e) => { e.preventDefault(); void rec.start(); }} onPointerUp={rec.stop} onPointerLeave={() => rec.recording && rec.stop()}
          aria-label={t("hold_to_talk")} title={t("hold_to_talk")}
          className={`min-h-14 min-w-14 select-none rounded-xl border px-4 text-2xl touch-none ${rec.recording ? "border-red-500 bg-red-50" : "border-slate-300 bg-white"}`}>🎤</button>
        <button onClick={send} disabled={busy || !input.trim()} className="min-h-14 rounded-xl bg-[#14284b] px-8 text-xl font-semibold text-white disabled:opacity-40">{t("send")}</button>
      </div>
      <div className="mt-3">
        <button onClick={createPlan} disabled={!canPlan || busy} className="min-h-14 rounded-xl bg-emerald-700 px-8 text-xl font-semibold text-white disabled:opacity-40">{t("create_plan")}</button>
      </div>
    </section>
  );
}
