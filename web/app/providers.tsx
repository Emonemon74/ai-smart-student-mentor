"use client";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { dict, type Key } from "@/lib/i18n";
import type { Lang, Mode } from "@/lib/types";

export type TextSize = "normal" | "large";
interface Ui {
  lang: Lang; setLang: (l: Lang) => void;
  textSize: TextSize; setTextSize: (s: TextSize) => void;
  studentName: string | null; setStudentName: (n: string | null) => void;
  mode: Mode | null; setMode: (m: Mode | null) => void;
  ready: boolean;   // saved language, text size, name and mode have been read from sessionStorage
  t: (k: Key) => string;
}
const UiContext = createContext<Ui | null>(null);

// sessionStorage can be blocked: every access is wrapped.
const read = (k: string) => { try { return sessionStorage.getItem(k); } catch { return null; } };
const write = (k: string, v: string | null) => { try { if (v === null) sessionStorage.removeItem(k); else sessionStorage.setItem(k, v); } catch {} };

export function Providers({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");
  const [textSize, setTextSizeState] = useState<TextSize>("normal");
  const [studentName, setNameState] = useState<string | null>(null);
  const [mode, setModeState] = useState<Mode | null>(null);
  const [ready, setReady] = useState(false);

  // Hydrate from sessionStorage after mount (the server render has no storage, so reading during render would mismatch).
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    setLangState(read("lang") === "hi" ? "hi" : "en");
    setTextSizeState(read("textSize") === "large" ? "large" : "normal");
    setNameState(read("studentName"));
    const m = read("mode");
    setModeState(m === "personal" || m === "general" ? m : null);
    setReady(true);
  }, []);
  /* eslint-enable react-hooks/set-state-in-effect */
  useEffect(() => {
    document.documentElement.classList.toggle("text-large", textSize === "large");
    document.documentElement.lang = lang;
  }, [textSize, lang]);

  const setLang = useCallback((l: Lang) => { setLangState(l); write("lang", l); }, []);
  const setTextSize = useCallback((s: TextSize) => { setTextSizeState(s); write("textSize", s); }, []);
  // The server is the authority on consent; the UI only uses the mode to choose screens.
  const setMode = useCallback((m: Mode | null) => { setModeState(m); write("mode", m); }, []);
  const setStudentName = useCallback((n: string | null) => { setNameState(n); write("studentName", n); }, []);
  const t = useCallback((k: Key) => dict[lang][k], [lang]);

  return <UiContext.Provider value={{ lang, setLang, textSize, setTextSize, studentName, setStudentName, mode, setMode, ready, t }}>{children}</UiContext.Provider>;
}

export function useUi(): Ui {
  const c = useContext(UiContext);
  if (!c) throw new Error("useUi outside Providers");
  return c;
}
