// Hand-mirrored from api/app/schemas.py (LLD C1.5). Change both in the same commit.
export type Lang = "en" | "hi";
export type TaskStatus = "pending" | "partial" | "done";
export type FlagCode = "LOW_VS_SELF" | "LOW_VS_CLASS" | "DECLINING" | "LOW_ATTENDANCE" | "MISSING" | "WEAK_TOPIC";

export interface Flag { code: FlagCode; subject_code: string; topic: string | null; values: Record<string, number | string>; reason: string }
export interface SubjectSummary { code: string; name: string; pct: number | null; attendance_pct: number | null; n_assessments: number; flags: Flag[] }
export interface Upcoming { subject_code: string; kind: string; topic: string; on: string }
export interface RoleReadiness { role: string; pct: number | null; weakest_subject: string | null }
export interface StudentInfo { roll_no: string; name: string; programme: string; semester: number }
export interface Profile {
  student: StudentInfo; as_of: string | null; imported_at: string | null; overall_pct: number | null;
  subjects: SubjectSummary[]; upcoming: Upcoming[]; roles: RoleReadiness[];
}
export interface ChatMessage { role: "user" | "assistant"; content: string }
export interface ChatRequest { messages: ChatMessage[]; lang: Lang }
export interface ChatReply { reply: string }
export interface DraftRequest { subject_code: string; days: number; daily_minutes: number; review_on: string; lang: Lang; messages: ChatMessage[] }
export interface TaskIn {
  day_from: number; day_to: number; kind: "learn" | "practice" | "checkpoint"; topic: string;
  activity: string; reason: string; minutes: number; resource_id: number; check: string;
}
export interface TaskView extends TaskIn { id: number; due_on: string; status: TaskStatus }
export interface RoadmapIn { subject_code: string; summary: string; days: number; daily_minutes: number; review_on: string; tasks: TaskIn[] }
export interface Resource { id: number; topic: string; title: string; url: string; kind: string }
export interface DraftView { roadmap: RoadmapIn; resources: Record<number, Resource> }
export interface RoadmapView {
  id: number; version: number; status: string; subject_code: string; subject_name: string;
  summary: string; days: number; daily_minutes: number; start_on: string; review_on: string;
  tasks: TaskView[]; resources: Record<number, Resource>;
}
export interface RoadmapListItem { id: number; subject_code: string; subject_name: string; version: number; review_on: string; status: string; done: number; total: number }
export interface ShareOut { url: string; expires_at: string }
export interface TopicChange { topic: string; kind: string; baseline_pct: number; review_pct: number | null; delta: number | null; note: string | null }
export interface SelfReport { done: number; partial: number; pending: number; total: number; overdue: TaskView[] }
export interface Report {
  roadmap_id: number; version: number; subject_code: string; subject_name: string; roll_no: string; programme: string;
  start_on: string; review_on: string; baseline_flags: Flag[]; baseline_subject_pct: number | null; review_subject_pct: number | null;
  has_review_data: boolean; verified: TopicChange[]; self_reported: SelfReport; remaining_flags: Flag[]; caveat: string;
}
export interface RequestIn { kind: "referral" | "correction"; subject_code?: string | null; note?: string | null }
export interface FeedbackIn { rating: number }
