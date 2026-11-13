"use client";
import { useEffect, useRef, useState } from "react";
import { useUi } from "@/app/providers";
import { api } from "@/lib/api";
import { hardReset } from "@/lib/kiosk";

export default function End() {
  const { t } = useUi();
  const [sent, setSent] = useState(false);
  const [comment, setComment] = useState("");
  const typing = useRef(false);

  useEffect(() => {
    const id = setTimeout(() => { if (!typing.current) hardReset(); }, 45_000); // auto reset; longer while the student writes a comment
    return () => clearTimeout(id);
  }, []);

  async function rate(n: number) {
    try { await api("/feedback", { method: "POST", json: { rating: n, comment: comment.trim() || null } }); } catch {}
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
            <label className="mx-auto mt-4 block max-w-md text-left text-sm font-medium">{t("comment_label")}
              <textarea value={comment} onChange={(ev) => { typing.current = true; setComment(ev.target.value.slice(0, 300)); }} rows={2} className="mt-1 w-full rounded-lg border border-slate-300 p-2" />
            </label>
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
