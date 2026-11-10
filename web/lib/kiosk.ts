// Hard reset (LLD C11.5): end the session, stop speech, clear browser state and do a FULL page load,
// which drops all React state so the next student never sees the previous one's data.
export async function hardReset(): Promise<void> {
  try { await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" }); } catch {}
  try { window.speechSynthesis?.cancel(); } catch {}
  try { sessionStorage.clear(); } catch {}
  window.location.replace("/");
}
