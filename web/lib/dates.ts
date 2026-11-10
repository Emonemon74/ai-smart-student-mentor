// Local-date helpers (never UTC: the server compares against its own local "today").
export const isoLocal = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export const addDays = (iso: string, n: number) => { const [y, m, d] = iso.split("-").map(Number); return isoLocal(new Date(y, m - 1, d + n)); };
export const todayIso = () => isoLocal(new Date());
const fmt = (iso: string, lang: string, opts: Intl.DateTimeFormatOptions) => { const [y, m, d] = iso.split("-").map(Number); return new Date(y, m - 1, d).toLocaleDateString(lang === "hi" ? "hi-IN" : "en-IN", opts); };
export const shortDate = (iso: string, lang: string) => fmt(iso, lang, { day: "numeric", month: "short" });
export const longDate = (iso: string, lang: string) => fmt(iso, lang, { day: "numeric", month: "short", year: "numeric" });
/** "Day 1-3 · 11-13 Nov" using the plan's real start date. */
export function dayRange(start: string, from: number, to: number, lang: string): string {
  const a = addDays(start, from - 1), b = addDays(start, to - 1);
  const days = from === to ? `${from}` : `${from}–${to}`;
  const dates = from === to ? shortDate(a, lang) : `${shortDate(a, lang)} – ${shortDate(b, lang)}`;
  return `${days} · ${dates}`;
}
export const daysUntil = (iso: string) => { const [y, m, d] = iso.split("-").map(Number); return Math.ceil((new Date(y, m - 1, d).getTime() - new Date().setHours(0, 0, 0, 0)) / 864e5); };
