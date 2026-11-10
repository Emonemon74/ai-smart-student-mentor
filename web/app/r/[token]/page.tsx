"use client";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { useUi } from "@/app/providers";
import { api } from "@/lib/api";

// QR landing: exchange the single-use token for a phone session, then drop the token URL from history.
export default function Redeem() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();
  const { t } = useUi();
  const [failed, setFailed] = useState(false);
  const once = useRef(false);

  useEffect(() => {
    if (once.current) return;
    once.current = true;
    (async () => {
      try { await api(`/r/${token}`); router.replace("/m"); return; } catch {}
      try { await api("/phone/roadmap"); router.replace("/m"); } catch { setFailed(true); } // already redeemed on this phone? the cookie still works
    })();
  }, [token, router]);

  return (
    <main className="mx-auto max-w-md p-6">
      {failed ? <p role="alert" className="rounded-lg bg-amber-50 px-4 py-3 text-amber-900">{t("link_expired")}</p> : <p className="text-slate-500">{t("loading")}</p>}
    </main>
  );
}
