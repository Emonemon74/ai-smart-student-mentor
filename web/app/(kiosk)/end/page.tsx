"use client";
import { useEffect, useState } from "react";
import { useUi } from "@/app/providers";
import { api } from "@/lib/api";
import { hardReset } from "@/lib/kiosk";

export default function End() {
  const { t } = useUi();
  const [sent, setSent] = useState(false);

  useEffect(() => {
    const id = setTimeout(() => hardReset(), 15_000); // auto reset after 15 s
    return () => clearTimeout(id);
  }, []);

  async function rate(n: number) {
    try { await api("/feedback", { method: "POST", json: { rating: n } }); } catch {}
    setSent(true);
    setTimeout(() => hardReset(), 1200);
  }

  return (
    <section className="grid flex-1 place-items-center text-center">
      <div>
        <h1 className="text-3xl font-bold text-[#14284b]">{t("end_title")}</h1>
        {sent ? <p className="mt-6 text-xl">{t("thanks")}</p> : (
          <>
            <p className="mt-6 text-xl">{t("useful")}</p>
            <div className="mt-4 flex justify-center gap-3" role="group" aria-label={t("useful")}>
              {[1, 2, 3, 4, 5].map((n) => (
                <button key={n} onClick={() => rate(n)} className="min-h-16 min-w-16 rounded-xl border border-slate-300 bg-white text-2xl font-semibold">{n}</button>
              ))}
            </div>
            <button onClick={() => hardReset()} className="mt-8 min-h-12 rounded-xl border border-slate-300 bg-white px-6">{t("close")}</button>
          </>
        )}
      </div>
    </section>
  );
}
