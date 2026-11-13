"use client";
import { useState } from "react";
import { useUi } from "@/app/providers";
import { api } from "@/lib/api";
import type { Contact, RequestOut } from "@/lib/types";

/** Support contacts (LLD_next C11). Showing this panel writes nothing. A referral is created only when the student asks,
 *  and the note is shared with the counsellor only when they tick the box. Closes on idle reset like every modal. */
export function SupportPanel({ contacts, canRequest = true, onClose }: { contacts: Contact[]; canRequest?: boolean; onClose?: () => void }) {
  const { t, lang } = useUi();
  const [note, setNote] = useState("");
  const [open, setOpen] = useState(false);
  const [share, setShare] = useState(false);
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState("");

  const urgent = contacts.filter((c) => c.team === "urgent");
  const others = contacts.filter((c) => c.team !== "urgent");
  const name = (c: Contact) => (lang === "hi" && c.name_hi ? c.name_hi : c.name);

  async function request() {
    setErr("");
    try {
      await api<RequestOut>("/requests", { method: "POST", json: { category: "wellbeing", note: note.trim() || null, share_note: share && !!note.trim() } });
      setSent(true);
    } catch { setErr(t("error_generic")); }
  }

  return (
    <section role="region" aria-label={t("support_title")} className="rounded-2xl border-2 border-blue-300 bg-blue-50 p-4">
      <div className="flex items-start justify-between gap-2">
        <h2 className="text-lg font-semibold text-blue-950">{t("support_title")}</h2>
        {onClose && <button onClick={onClose} className="min-h-12 rounded-lg border border-blue-300 bg-white px-3 text-sm">{t("close")}</button>}
      </div>
      {urgent.map((c) => (
        <p key={c.name} className="mt-2 text-lg font-semibold text-red-800">{t("support_urgent")} {c.how}</p>
      ))}
      <ul className="mt-2 space-y-1 text-sm text-slate-800">
        {others.map((c) => <li key={c.name}><b>{name(c)}</b> · {c.how} · {c.hours}</li>)}
      </ul>
      {canRequest && !sent && (
        <div className="mt-3">
          {!open ? (
            <button onClick={() => setOpen(true)} className="min-h-12 rounded-lg bg-[#14284b] px-5 text-white">{t("request_counsellor")}</button>
          ) : (
            <div className="space-y-2">
              <label className="block text-sm font-medium">{t("add_note")}
                <textarea value={note} onChange={(e) => setNote(e.target.value.slice(0, 300))} rows={2} className="mt-1 w-full rounded-lg border border-slate-300 p-2" />
              </label>
              <label className="flex min-h-12 items-center gap-2 text-sm"><input type="checkbox" checked={share} onChange={(e) => setShare(e.target.checked)} className="h-5 w-5" />{t("share_note")}</label>
              <button onClick={request} className="min-h-12 rounded-lg bg-[#14284b] px-5 text-white">{t("request_counsellor")}</button>
            </div>
          )}
        </div>
      )}
      {sent && <p role="status" className="mt-3 rounded-lg bg-white px-3 py-2 text-emerald-800">{t("referral_sent")}</p>}
      {err && <p role="alert" className="mt-2 text-red-800">{err}</p>}
    </section>
  );
}
