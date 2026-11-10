"use client";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { dict, type Key } from "@/lib/i18n";
import type { Lang } from "@/lib/types";

export type TextSize = "normal" | "large";
interface Ui {
  lang: Lang; setLang: (l: Lang) => void;
  textSize: TextSize; setTextSize: (s: TextSize) => void;
  studentName: string | null; setStudentName: (n: string | null) => void;
  t: (k: Key) => string;
}
const UiContext = createContext<Ui | null>(null);

// sessionStorage can be blocked: every access is wrapped.
const read = (k: string) => { try { return sessionStorage.getItem(k); } catch { return null; } };
const write = (k: string, v: string | null) => { try { v === null ? sessionStorage.removeItem(k) : sessionStorage.setItem(k, v); } catch {} };

export function Providers({ children }: { children: React.ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");
  const [textSize, setTextSizeState] = useState<TextSize>("normal");
  const [studentName, setNameState] = useState<string | null>(null);

  useEffect(() => {
    setLangState(read("lang") === "hi" ? "hi" : "en");
    setTextSizeState(read("textSize") === "large" ? "large" : "normal");
    setNameState(read("studentName"));
  }, []);
  useEffect(() => {
    document.documentElement.classList.toggle("text-large", textSize === "large");
    document.documentElement.lang = lang;
  }, [textSize, lang]);

  const setLang = useCallback((l: Lang) => { setLangState(l); write("lang", l); }, []);
  const setTextSize = useCallback((s: TextSize) => { setTextSizeState(s); write("textSize", s); }, []);
  const setStudentName = useCallback((n: string | null) => { setNameState(n); write("studentName", n); }, []);
  const t = useCallback((k: Key) => dict[lang][k], [lang]);

  return <UiContext.Provider value={{ lang, setLang, textSize, setTextSize, studentName, setStudentName, t }}>{children}</UiContext.Provider>;
}

export function useUi(): Ui {
  const c = useContext(UiContext);
  if (!c) throw new Error("useUi outside Providers");
  return c;
}
