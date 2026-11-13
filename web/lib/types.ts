// Hand-mirrored from api/app/schemas.py (LLD C1.5). Change both in the same commit.
export type Lang = "en" | "hi";
export type TaskStatus = "pending" | "partial" | "done";
export type Level = "foundation" | "beginner" | "intermediate" | "advanced";
export type LevelSource = "check" | "records" | "student";
export type GoalCode = "semester" | "backlog" | "gate" | "upsc" | "placement" | "higher_studies";
export type Mode = "personal" | "general";
export type FlagCode =
  | "LOW_VS_SELF" | "LOW_VS_CLASS" | "DECLINING" | "LOW_ATTENDANCE" | "MISSING" | "WEAK_TOPIC"
  | "BACKLOG" | "THEORY_PRACTICE_GAP" | "PREREQ_GAP" | "TARGETED_GAP" | "LOW_EVIDENCE";

export interface Flag { code: FlagCode; subject_code: string; topic: string | null; values: Record<string, number | string>; reason: string; response: string }
export interface TopicLevel { topic: string; level: Level | null; source: LevelSource | null; as_of: string | null; n: number; has_check: boolean }
export interface Backlog { subject_code: string; subject_name: string; from_semester: number; status: "pending" | "cleared" }
export interface SubjectSummary { code: string; name: string; kind: "course" | "track"; pct: number | null; attendance_pct: number | null; n_assessments: number; flags: Flag[]; levels: TopicLevel[] }
export interface Upcoming { subject_code: string; kind: string; topic: string; on: string }
export interface RoleReadiness { role: string; pct: number | null; weakest_subject: string | null }
export interface StudentInfo { roll_no: string; name: string; programme: string; semester: number }
export interface Profile {
  student: StudentInfo; as_of: string | null; imported_at: string | null; overall_pct: number | null;
  subjects: SubjectSummary[]; upcoming: Upcoming[]; roles: RoleReadiness[]; backlogs: Backlog[]; reviews_due: number[];
}
export interface ChatMessage { role: "user" | "assistant"; content: string }
export interface ChatRequest { messages: ChatMessage[]; lang: Lang }
export interface ChatReply { reply: string; support: boolean }
export interface DraftRequest { goal: GoalCode; subject_code: string; days: number; daily_minutes: number; review_on: string; target_date: string | null; level_overrides: Record<string, Level>; lang: Lang; messages: ChatMessage[] }
export interface TaskIn {
  day_from: number; day_to: number; kind: "learn" | "practice" | "checkpoint"; topic: string;
  activity: string; reason: string; minutes: number; resource_id: number; check: string;
}
export interface TaskView extends TaskIn { id: number; due_on: string; status: TaskStatus }
export interface RoadmapIn { goal: GoalCode; subject_code: string; target_date: string | null; level_overrides: Record<string, Level>; summary: string; days: number; daily_minutes: number; review_on: string; tasks: TaskIn[] }
export interface Resource { id: number; topic: string; title: string; url: string; kind: string; level: Level; lang: Lang; minutes: number; source: string }
export interface DraftView { roadmap: RoadmapIn; resources: Record<number, Resource>; levels: Record<string, TopicLevel> }
export interface RoadmapView {
  id: number; version: number; status: string; goal: GoalCode; goal_name: string; target_date: string | null; levels: Record<string, TopicLevel>;
  subject_code: string; subject_name: string;
  summary: string; days: number; daily_minutes: number; start_on: string; review_on: string;
  tasks: TaskView[]; resources: Record<number, Resource>;
}
export interface RoadmapListItem { id: number; subject_code: string; subject_name: string; version: number; goal: GoalCode; goal_name: string; daily_minutes: number; review_on: string; status: string; done: number; total: number }
export interface ShareOut { url: string; expires_at: string }
export interface TopicChange { topic: string; kind: string; baseline_pct: number; review_pct: number | null; delta: number | null; note: string | null }
export interface SelfReport { done: number; partial: number; pending: number; total: number; overdue: TaskView[] }
export interface CheckChange {
  topic: string; before_level: Level | null; before_score: string | null; before_on: string | null;
  after_level: Level | null; after_score: string | null; after_on: string | null; note: string | null;
}
export interface Indicator { code: string; label: string; value: string; source: "verified" | "kiosk_check" | "self_reported"; note: string | null }
export interface NextStep { code: "continue" | "revise" | "prerequisite" | "mentor" | "check" | "await_evidence"; text: string }
export interface Report {
  goal: GoalCode; goal_name: string; semester: number; target_date: string | null; baseline_as_of: string | null; review_imported_at: string | null;
  checks: CheckChange[]; indicators: Indicator[]; next_steps: NextStep[]; academic_referral: "none" | "open" | "closed";
  confidence_review: number | null; limitations: string[];
  roadmap_id: number; version: number; subject_code: string; subject_name: string; roll_no: string; programme: string;
  start_on: string; review_on: string; baseline_flags: Flag[]; baseline_subject_pct: number | null; review_subject_pct: number | null;
  has_review_data: boolean; verified: TopicChange[]; self_reported: SelfReport; remaining_flags: Flag[]; caveat: string;
}
export interface RequestIn { category: "academic" | "wellbeing" | "correction"; subject_code?: string | null; note?: string | null; share_note?: boolean }
export interface FeedbackIn { rating: number; comment?: string | null }
export interface Contact { team: "faculty_mentor" | "counsellor" | "records_office" | "urgent"; name: string; name_hi: string | null; how: string; hours: string }
export interface RequestOut { team: string; contacts: Contact[] }
export interface GoalSubject { code: string; name: string; kind: "course" | "track" }
export interface Goal { code: GoalCode; name: string; name_hi: string; components: string; indicators: string; needs_target_date: boolean; subjects: GoalSubject[] }
export interface QuestionOut { id: number; tier: "basic" | "standard" | "multi"; stem: string; options: string[] }
export interface DiagnosticOut { id: number; subject_code: string; topic: string; questions: QuestionOut[]; expires_at: string }
export interface QuestionResult { id: number; chosen: number | null; answer: number; correct: boolean; explanation: string }
export interface DiagnosticResult { id: number; subject_code: string; topic: string; correct: number; total: number; basic: number; standard: number; multi: number; seconds: number; level: Level; items: QuestionResult[]; note: string }
export interface ReviewIn { confidence?: number | null; plan_fit?: number | null }
