"use client";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { useUi } from "@/app/providers";
import { api, ApiError } from "@/lib/api";
import type { StudentInfo } from "@/lib/types";

export default function Login() {
  const { t, setStudentName } = useUi();
  const router = useRouter();
  const [roll, setRoll] = useState("");
  const [pin, setPin] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const pinRef = useRef<HTMLInputElement>(null);

  const add = (d: string) => setPin((p) => (p.length < 6 ? p + d : p));
  async function submit() {
    setErr(""); setBusy(true);
    try {
      const s = await api<StudentInfo>("/auth/login", { method: "POST", json: { roll_no: roll.trim(), pin } });
      setStudentName(s.name);
      router.push("/consent");
    } catch (e) {
      const code = e instanceof ApiError ? e.code : "error";
      setErr(code === "bad_credentials" ? t("bad_credentials") : code === "locked" ? t("locked") : t("error_generic"));
      setPin("");
    }
    setBusy(false);
  }

  const key = "min-h-16 rounded-xl border border-slate-300 bg-white text-2xl font-semibold active:bg-slate-100";
  return (
    <section className="mx-auto w-full max-w-md flex-1 py-6">
      <h1 className="text-3xl font-bold text-[#14284b]">{t("login_title")}</h1>
      <label className="mt-6 block text-sm font-medium">{t("roll_no")}
        <input value={roll} onChange={(e) => setRoll(e.target.value)} autoFocus autoCapitalize="characters" enterKeyHint="next"
          onKeyDown={(e) => { if (e.key === "Enter" && roll.trim()) { e.preventDefault(); pinRef.current?.focus(); } }} autoComplete="off" placeholder="CS23001"
          className="mt-1 min-h-14 w-full rounded-xl border border-slate-300 bg-white px-4 text-xl" />
      </label>
      <label className="mt-4 block text-sm font-medium">{t("pin")}
        <input ref={pinRef} value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, "").slice(0, 6))} type="password" inputMode="numeric" autoComplete="off" maxLength={6}
          onKeyDown={(e) => e.key === "Enter" && roll && pin.length >= 4 && submit()}
          className="mt-1 min-h-14 w-full rounded-xl border border-slate-300 bg-white px-4 text-center text-2xl tracking-[0.5em]" />
      </label>
      <div className="mt-4 grid grid-cols-3 gap-2" role="group" aria-label={t("pin")}>
        {["1", "2", "3", "4", "5", "6", "7", "8", "9"].map((d) => <button key={d} type="button" onClick={() => add(d)} className={key}>{d}</button>)}
        <button type="button" onClick={() => setPin("")} className={key + " text-base"}>{t("clear")}</button>
        <button type="button" onClick={() => add("0")} className={key}>0</button>
        <button type="button" onClick={() => setPin((p) => p.slice(0, -1))} aria-label="Backspace" className={key}>⌫</button>
      </div>
      {err && <p role="alert" className="mt-4 rounded-lg bg-red-50 px-4 py-3 text-red-800">{err}</p>}
      <button onClick={submit} disabled={busy || !roll.trim() || pin.length < 4} className="mt-4 min-h-14 w-full rounded-xl bg-[#14284b] text-xl font-semibold text-white disabled:opacity-40">{t("sign_in")}</button>
    </section>
  );
}
