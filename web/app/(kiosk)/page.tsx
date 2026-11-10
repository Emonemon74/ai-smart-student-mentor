"use client";
import Link from "next/link";
import { useUi } from "@/app/providers";

export default function Welcome() {
  const { t, lang, setLang, textSize, setTextSize } = useUi();
  const pill = (active: boolean) => `min-h-12 rounded-xl border px-6 text-lg ${active ? "border-[#14284b] bg-[#14284b] text-white" : "border-slate-300 bg-white"}`;
  return (
    <section className="grid flex-1 place-items-center text-center">
      <div className="max-w-xl">
        <div className="mx-auto mb-4 grid h-14 w-14 place-items-center rounded-xl bg-[#14284b] text-2xl font-bold text-white">T</div>
        <h1 className="text-4xl font-bold leading-tight text-[#14284b]">{t("welcome_title")}</h1>
        <p className="mt-3 text-lg text-slate-600">{t("welcome_sub")}</p>
        <div className="mt-6 flex justify-center gap-3" role="group" aria-label={t("language")}>
          <button onClick={() => setLang("en")} className={pill(lang === "en")}>English</button>
          <button onClick={() => setLang("hi")} className={pill(lang === "hi")}>हिन्दी</button>
        </div>
        <div className="mt-3 flex justify-center gap-3" role="group" aria-label={t("text_size")}>
          <button onClick={() => setTextSize("normal")} className={pill(textSize === "normal")}>{t("normal")}</button>
          <button onClick={() => setTextSize("large")} className={pill(textSize === "large")}>{t("large")}</button>
        </div>
        <Link href="/login" className="mt-8 inline-block min-h-14 rounded-2xl bg-[#14284b] px-12 py-4 text-2xl font-semibold text-white shadow">{t("start")}</Link>
        <p className="mt-4 flex items-center justify-center gap-2 text-sm text-slate-500"><span className="h-2 w-2 rounded-full bg-emerald-500" />{t("no_camera")}</p>
      </div>
    </section>
  );
}
