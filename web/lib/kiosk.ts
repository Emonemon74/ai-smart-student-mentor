// Hard reset (LLD C11.5): end the session, stop speech, clear browser state and do a FULL page load,
// which drops all React state so the next student never sees the previous one's data.
export async function hardReset(): Promise<void> {
  try { await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" }); } catch {}
  try { window.speechSynthesis?.cancel(); } catch {}
  try { sessionStorage.clear(); } catch {}
  window.location.replace("/");
}

import { ApiError } from "@/lib/api";

/** Shared handling for kiosk API errors: lost session -> hard reset, missing consent -> consent screen.
 *  Returns the code for anything else so the page can show it. */
export function kioskError(e: unknown, push: (path: string) => void): string {
  if (e instanceof ApiError) {
    if (e.code === "no_session") { void hardReset(); return e.code; }
    if (e.code === "consent_required") { push("/consent"); return e.code; }
    return e.code;
  }
  return "error";
}

/** The API accepts at most 40 messages per request and only reads the last 16 (LLD C6.4), so send just those.
 *  Sending the whole history makes long conversations fail with a validation error after about 20 exchanges. */
export const CHAT_WINDOW = 16;
export function recentMessages<T>(messages: T[]): T[] {
  return messages.slice(-CHAT_WINDOW);
}
