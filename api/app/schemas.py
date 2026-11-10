"""Shared request/response models (LLD C1.5). Mirrored 1:1 in web/lib/types.ts."""
from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

Lang = Literal["en", "hi"]
TaskStatus = Literal["pending", "partial", "done"]

class Flag(BaseModel):
    code: Literal["LOW_VS_SELF","LOW_VS_CLASS","DECLINING","LOW_ATTENDANCE","MISSING","WEAK_TOPIC"]
    subject_code: str
    topic: str | None = None
    values: dict[str, float | int | str]     # always includes "n" = assessments behind the flag
    reason: str

class SubjectSummary(BaseModel):
    code: str; name: str
    pct: float | None; attendance_pct: float | None; n_assessments: int
    flags: list[Flag]

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

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]; content: str = Field(max_length=2000)

class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(max_length=40); lang: Lang = "en"

class ChatReply(BaseModel):
    reply: str

class DraftRequest(BaseModel):
    subject_code: str
    days: int = Field(ge=7, le=30)
    daily_minutes: int = Field(ge=15, le=240)
    review_on: date
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
    subject_code: str
    summary: str = Field(max_length=600)
    days: int = Field(ge=7, le=30)
    daily_minutes: int = Field(ge=15, le=240)
    review_on: date
    tasks: list[TaskIn] = Field(min_length=1, max_length=15)

class Resource(BaseModel):
    id: int; topic: str; title: str; url: str; kind: str

class DraftView(BaseModel):
    roadmap: RoadmapIn; resources: dict[int, Resource]

class RoadmapView(BaseModel):
    id: int; version: int; status: str
    subject_code: str; subject_name: str
    summary: str; days: int; daily_minutes: int; start_on: date; review_on: date
    tasks: list[TaskView]; resources: dict[int, Resource]

class RoadmapListItem(BaseModel):
    id: int; subject_code: str; subject_name: str; version: int
    review_on: date; status: str; done: int; total: int

class ShareOut(BaseModel):
    url: str; expires_at: datetime

class TopicChange(BaseModel):
    topic: str; kind: str; baseline_pct: float
    review_pct: float | None; delta: float | None; note: str | None

class SelfReport(BaseModel):
    done: int; partial: int; pending: int; total: int
    overdue: list[TaskView]                # not done and due_on < today

class Report(BaseModel):
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
    kind: Literal["referral", "correction"]
    subject_code: str | None = None
    note: str | None = Field(default=None, max_length=300)

class FeedbackIn(BaseModel):
    rating: int = Field(ge=1, le=5)
