"""Shared request/response models (LLD C1.5). Mirrored 1:1 in web/lib/types.ts."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Lang = Literal["en", "hi"]
TaskStatus = Literal["pending", "partial", "done"]
Level = Literal["foundation", "beginner", "intermediate", "advanced"]
LevelSource = Literal["check", "records", "student"]
GoalCode = Literal["semester", "backlog", "gate", "upsc", "placement", "higher_studies"]
Mode = Literal["personal", "general"]
Format = Literal["video", "article", "practice", "course"]

class Flag(BaseModel):
    code: Literal["LOW_VS_SELF","LOW_VS_CLASS","DECLINING","LOW_ATTENDANCE","MISSING","WEAK_TOPIC",
                  "BACKLOG","THEORY_PRACTICE_GAP","PREREQ_GAP","TARGETED_GAP","LOW_EVIDENCE"]
    subject_code: str
    topic: str | None = None
    values: dict[str, float | int | str]     # always includes "n" = assessments behind the flag
    reason: str
    response: str = ""                       # RB 5.3 recommended response; default keeps stored v1 snapshots valid

class TopicLevel(BaseModel):
    topic: str                               # catalogue topic
    level: Level | None                      # None = unknown -> offer a check if has_check
    source: LevelSource | None
    as_of: date | None
    n: int                                   # questions (check) or assessments (records) behind it
    has_check: bool = False                  # the bank has questions for this topic

class Backlog(BaseModel):
    subject_code: str; subject_name: str; from_semester: int; status: Literal["pending", "cleared"]

class SubjectSummary(BaseModel):
    code: str; name: str; kind: Literal["course", "track"] = "course"
    pct: float | None; attendance_pct: float | None; n_assessments: int
    flags: list[Flag]
    levels: list[TopicLevel] = []            # every topic with records or a check, weakest first

class Upcoming(BaseModel):
    subject_code: str; kind: str; topic: str; on: date

class RoleReadiness(BaseModel):              # coverage indicator, not a prediction
    role: str; pct: float | None; weakest_subject: str | None

class StudentInfo(BaseModel):
    roll_no: str; name: str; programme: str; semester: int

class Profile(BaseModel):
    student: StudentInfo
    as_of: date | None                     # latest assessment date in the batch
    imported_at: datetime | None           # last import of the batch
    overall_pct: float | None
    subjects: list[SubjectSummary]          # most flags first, then lowest pct
    upcoming: list[Upcoming]
    roles: list[RoleReadiness]
    backlogs: list[Backlog] = []
    reviews_due: list[int] = []              # roadmap ids ready for a review check-in

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]; content: str = Field(max_length=2000)

class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(max_length=40); lang: Lang = "en"

class ChatReply(BaseModel):
    reply: str
    support: bool = False                    # show the support panel

class ConsentIn(BaseModel):
    notice_version: str = Field(min_length=1, max_length=20)
    scope: Mode = "personal"

class Contact(BaseModel):
    team: Literal["faculty_mentor", "counsellor", "records_office", "urgent"]
    name: str; name_hi: str | None = None; how: str; hours: str

class RequestOut(BaseModel):
    team: str; contacts: list[Contact]       # the team's contacts + urgent ones

class GoalSubject(BaseModel):
    code: str; name: str; kind: Literal["course", "track"]

class Goal(BaseModel):
    code: GoalCode; name: str; name_hi: str; components: str; indicators: str
    needs_target_date: bool
    subjects: list[GoalSubject]              # personal mode: eligible for this student; general: all

class DraftRequest(BaseModel):
    goal: GoalCode = "semester"
    subject_code: str
    days: int = Field(ge=7, le=30)
    daily_minutes: int = Field(ge=15, le=240)
    review_on: date
    target_date: date | None = None
    level_overrides: dict[str, Level] = Field(default={}, max_length=10)   # catalogue topic -> level chosen by the student
    lang: Lang = "en"
    messages: list[ChatMessage] = Field(max_length=40)

class TaskIn(BaseModel):
    day_from: int = Field(ge=1); day_to: int = Field(ge=1)
    kind: Literal["learn", "practice", "checkpoint"]
    topic: str = Field(max_length=80)
    activity: str = Field(max_length=300)
    reason: str = Field(max_length=160)
    minutes: int = Field(ge=10, le=240)
    resource_id: int
    check: str = Field(max_length=160)

    @model_validator(mode="after")
    def _range(self):
        if self.day_to < self.day_from:
            raise ValueError("day_to must be >= day_from")
        return self

class TaskView(TaskIn):
    id: int; due_on: date; status: TaskStatus

class RoadmapIn(BaseModel):                  # draft returned by the AI and sent back on save
    goal: GoalCode = "semester"
    subject_code: str
    target_date: date | None = None
    level_overrides: dict[str, Level] = Field(default={}, max_length=10)
    summary: str = Field(max_length=600)
    days: int = Field(ge=7, le=30)
    daily_minutes: int = Field(ge=15, le=240)
    review_on: date
    tasks: list[TaskIn] = Field(min_length=1, max_length=15)

class Resource(BaseModel):
    id: int; topic: str; title: str; url: str; kind: Format
    level: Level = "beginner"; lang: Lang = "en"; minutes: int = 30
    source: str = ""                         # URL host without www.

class DraftView(BaseModel):
    roadmap: RoadmapIn; resources: dict[int, Resource]
    levels: dict[str, TopicLevel] = {}       # what the plan was built on (display)

class RoadmapView(BaseModel):
    id: int; version: int; status: str
    goal: GoalCode = "semester"; goal_name: str = ""; target_date: date | None = None
    levels: dict[str, TopicLevel] = {}
    subject_code: str; subject_name: str
    summary: str; days: int; daily_minutes: int; start_on: date; review_on: date
    tasks: list[TaskView]; resources: dict[int, Resource]

class RoadmapListItem(BaseModel):
    id: int; subject_code: str; subject_name: str; version: int
    goal: GoalCode = "semester"; goal_name: str = ""; daily_minutes: int = 0
    review_on: date; status: str; done: int; total: int

class ShareOut(BaseModel):
    url: str; expires_at: datetime

class TopicChange(BaseModel):
    topic: str; kind: str; baseline_pct: float
    review_pct: float | None; delta: float | None; note: str | None

class SelfReport(BaseModel):
    done: int; partial: int; pending: int; total: int
    overdue: list[TaskView]                # not done and due_on < today

class CheckChange(BaseModel):
    topic: str
    before_level: Level | None = None; before_score: str | None = None; before_on: date | None = None   # "2/5"
    after_level: Level | None = None; after_score: str | None = None; after_on: date | None = None
    note: str | None = None

class Indicator(BaseModel):
    code: str; label: str; value: str
    source: Literal["verified", "kiosk_check", "self_reported"]
    note: str | None = None

class NextStep(BaseModel):
    code: Literal["continue", "revise", "prerequisite", "mentor", "check", "await_evidence"]
    text: str

class Report(BaseModel):
    goal: GoalCode = "semester"; goal_name: str = ""; semester: int = 0; target_date: date | None = None
    baseline_as_of: date | None = None; review_imported_at: datetime | None = None
    checks: list[CheckChange] = []           # kiosk_check, kept apart from `verified`
    indicators: list[Indicator] = []
    next_steps: list[NextStep] = []
    academic_referral: Literal["none", "open", "closed"] = "none"   # wellbeing requests never appear on a report
    confidence_review: int | None = None     # self-reported at the latest check-in
    limitations: list[str] = []
    roadmap_id: int; version: int; subject_code: str; subject_name: str
    roll_no: str; programme: str
    start_on: date; review_on: date
    baseline_flags: list[Flag]
    baseline_subject_pct: float | None; review_subject_pct: float | None
    has_review_data: bool
    verified: list[TopicChange]
    self_reported: SelfReport
    remaining_flags: list[Flag]
    caveat: str

class RequestIn(BaseModel):
    category: Literal["academic", "wellbeing", "correction"]
    subject_code: str | None = None
    note: str | None = Field(default=None, max_length=300)
    share_note: bool = False                 # wellbeing note stored only when True

class FeedbackIn(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=300)

# --- concept check (C17) ---
class DiagnosticStart(BaseModel):
    subject_code: str; topic: str = Field(max_length=80)
    purpose: Literal["level", "review"] = "level"
    roadmap_id: int | None = None

class QuestionOut(BaseModel):
    id: int; tier: Literal["basic", "standard", "multi"]; stem: str; options: list[str]

class DiagnosticOut(BaseModel):
    id: int; subject_code: str; topic: str; questions: list[QuestionOut]; expires_at: datetime

class DiagnosticSubmit(BaseModel):
    answers: list[int | None] = Field(min_length=5, max_length=5)   # aligned with questions; None = skipped

    @model_validator(mode="after")
    def _range(self):
        if any(a is not None and not (0 <= a <= 3) for a in self.answers):
            raise ValueError("each answer must be 0..3 or null")
        return self

class QuestionResult(BaseModel):
    id: int; chosen: int | None; answer: int; correct: bool; explanation: str

class DiagnosticResult(BaseModel):
    id: int; subject_code: str; topic: str
    correct: int; total: int; basic: int; standard: int; multi: int; seconds: int
    level: Level
    items: list[QuestionResult]
    note: str

class ReviewIn(BaseModel):
    confidence: int | None = Field(default=None, ge=1, le=3)     # self-reported
    plan_fit: int | None = Field(default=None, ge=1, le=5)       # "Did this plan fit your level, goal and time?"
