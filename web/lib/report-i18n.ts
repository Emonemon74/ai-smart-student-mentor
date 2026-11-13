// Localises the report texts the API writes in English (LLD_next C11: indicator labels, next-step texts by code,
// limitations by kind). The API keeps its English strings; known patterns are mapped to i18n templates and anything
// unknown falls back to the English text, so a new API sentence never breaks the screen.
import { dict, type Key } from "@/lib/i18n";
import type { Lang } from "@/lib/types";

type T = (k: Key) => string;
const fill = (tpl: string, a = "", b = "") => tpl.replace("{a}", a).replace("{b}", b);

export function indicatorLabel(code: string, label: string, t: T): string {
  const k = `ind_${code}` as Key;
  return k in dict.en ? t(k) : label;
}

export function indicatorValue(v: string, t: T): string {
  if (v === "No comparable assessment yet") return t("val_no_marks");
  if (v === "No concept check yet") return t("val_no_check");
  let m = v.match(/^(\d+) of (\d+) topics$/);
  if (m) return fill(t("val_of_topics"), m[1], m[2]);
  m = v.match(/^(\d+) of (\d+)$/);
  if (m) return fill(t("val_of"), m[1], m[2]);
  m = v.match(/^(\d+) s$/);
  if (m) return fill(t("val_seconds"), m[1]);
  return v;
}

export function nextStepText(text: string, t: T): string {
  const exact: [string, Key][] = [
    ["Take the 5-question topic check to see where you are now.", "nsx_check"],
    ["New marks are not in yet. This report updates after the next assessment import.", "nsx_await_evidence"],
    ["Fit the plan to the time you have: fewer minutes a day or fewer topics.", "nsx_fit"],
    ["Pick your next topic or goal.", "nsx_continue"],
  ];
  for (const [en, k] of exact) if (text === en) return t(k);
  let m = text.match(/^Make a short plan for (.+) first, then return to (.+)\.$/);
  if (m) return fill(t("nsx_prerequisite"), m[1], m[2]);
  m = text.match(/^Talk to a faculty mentor about (.+): the plan has not moved it yet\.$/);
  if (m) return fill(t("nsx_mentor"), m[1]);
  m = text.match(/^Make a revised plan focused on (.+)\.$/);
  if (m) return fill(t("nsx_revise"), m[1]);
  return text;
}

export function limitationText(text: string, t: T, lang: Lang, fmtDate: (iso: string) => string): string {
  if (text === "No review assessment has been imported yet.") return t("lim_no_review");
  if (text === "Concept checks have 5 questions; levels are provisional.") return t("lim_checks");
  if (text === "Task ticks are your own record and are not verified.") return t("lim_ticks");
  let m = text.match(/^(.+) rests on (\d+) assessments\.$/);
  if (m) return fill(t("lim_thin"), m[1], m[2]);
  m = text.match(/^(.+) is a track without institutional marks\.$/);
  if (m) return fill(t("lim_track"), m[1]);
  m = text.match(/^Records as of (\d{4}-\d{2}-\d{2}|not available); review data not yet imported\.$/);
  if (m) return fill(t("lim_asof_none"), m[1] === "not available" ? "-" : fmtDate(m[1]));
  m = text.match(/^Records as of (\d{4}-\d{2}-\d{2}|not available); review data imported (\d{4}-\d{2}-\d{2})\.$/);
  if (m) return fill(t("lim_asof_rev"), m[1] === "not available" ? "-" : fmtDate(m[1]), fmtDate(m[2]));
  void lang;
  return text;
}
