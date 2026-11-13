"use client";
// C13: hold-to-talk recording (browser MediaRecorder -> /api/stt) and spoken replies (speechSynthesis).
import { useCallback, useRef, useState } from "react";

type L = "en" | "hi";
const MAX_MS = 30_000;

// Browsers load their voice list lazily: on the first call getVoices() can be empty until "voiceschanged" fires
// (LLD_next F6). Wait for it, for at most one second, then pick.
function voicesReady(synth: SpeechSynthesis): Promise<SpeechSynthesisVoice[]> {
  const now = synth.getVoices();
  if (now.length) return Promise.resolve(now);
  return new Promise((resolve) => {
    const done = () => { synth.removeEventListener("voiceschanged", done); clearTimeout(timer); resolve(synth.getVoices()); };
    const timer = setTimeout(done, 1000);
    synth.addEventListener("voiceschanged", done);
  });
}

export function speak(text: string, lang: L): void {
  if (typeof window === "undefined" || !("speechSynthesis" in window)) return;
  const synth = window.speechSynthesis;
  synth.cancel();
  const tag = lang === "hi" ? "hi-IN" : "en-IN";
  void voicesReady(synth).then((voices) => {
    const voice = voices.find((v) => v.lang.toLowerCase().startsWith(lang));
    if (lang === "hi" && !voice) return; // no Hindi voice installed: stay silent, captions remain
    const u = new SpeechSynthesisUtterance(text);
    u.lang = tag;
    if (voice) u.voice = voice;
    synth.speak(u);
  });
}

export function stopSpeaking(): void {
  try { window.speechSynthesis?.cancel(); } catch {}
}

export function useRecorder(onText: (t: string) => void, lang: L) {
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const rec = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const chunks = useRef<Blob[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const wanted = useRef(false); // false if the finger was released before the mic opened

  const release = () => { stream.current?.getTracks().forEach((t) => t.stop()); stream.current = null; }; // mic indicator off

  const stop = useCallback(() => {
    wanted.current = false;
    if (timer.current) clearTimeout(timer.current);
    if (rec.current && rec.current.state !== "inactive") rec.current.stop();
    else release();
    rec.current = null;
    setRecording(false);
  }, []);

  const start = useCallback(async () => {
    setError(null);
    stopSpeaking(); // starting a recording cancels speech
    wanted.current = true;
    try {
      const s = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (!wanted.current) { s.getTracks().forEach((t) => t.stop()); return; }
      stream.current = s;
      const mime = typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : undefined;
      const r = new MediaRecorder(s, mime ? { mimeType: mime } : undefined);
      chunks.current = [];
      r.ondataavailable = (e) => { if (e.data.size) chunks.current.push(e.data); };
      r.onstop = async () => {
        release();
        const blob = new Blob(chunks.current, { type: r.mimeType || "audio/webm" });
        if (blob.size < 800) { setBusy(false); return; } // too short to be speech
        setBusy(true);
        try {
          const fd = new FormData();
          fd.append("file", blob, "speech.webm");
          fd.append("lang", lang);
          const res = await fetch("/api/stt", { method: "POST", body: fd, credentials: "same-origin" });
          if (!res.ok) {
            let code = "error";
            try { code = (await res.json()).detail ?? code; } catch {}
            setError(code);
          } else {
            const { text } = await res.json();
            if (text) onText(text);
          }
        } catch { setError("stt_unavailable"); }
        setBusy(false);
      };
      rec.current = r;
      r.start();
      setRecording(true);
      timer.current = setTimeout(() => stop(), MAX_MS); // hard stop at 30 s
    } catch {
      release();
      setError("mic_denied");
    }
  }, [lang, onText, stop]);


  return { recording, busy, error, start, stop };
}
