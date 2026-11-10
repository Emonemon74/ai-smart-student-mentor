"""C6: mentor conversation and speech-to-text (LLD C6)."""
from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app import analytics, auth, connector, db, llm
from app.schemas import ChatReply, ChatRequest, Lang

router = APIRouter(prefix="/api")

MAX_AUDIO = 2 * 1024 * 1024
AUDIO_TYPES = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "mp4"}

MENTOR_SYSTEM = """You are the AI Study Mentor on a university campus kiosk, talking with one student.
Rules:
1. For any fact about the student's marks, attendance or assessments use only VERIFIED RECORDS. Never invent or estimate numbers.
2. Keep facts and student statements apart: "Your records show..." vs "You mentioned...".
3. If information is missing, say so and ask. If a finding rests on fewer than 3 assessments, say the evidence is limited.
4. Ask one short question at a time. Replies under 70 words. They are read aloud: plain text, no markdown, no lists.
5. Never guess the student's feelings, motivation, intelligence or ability. Ask instead.
6. Never promise grades, placement, selection or salary. You do not make academic, disciplinary or placement decisions.
7. If the student mentions stress, health, wellbeing, safety, disability or anything sensitive, reply kindly and suggest the "Talk to a human mentor" button. Do not counsel.
8. Mention learning resources only from APPROVED RESOURCES, by title.
9. Skill coverage is an indicator of subject marks only, not a prediction. Use it only if the student shares a career goal.
10. Your goal: learn which topics feel hard, how the student likes to learn, how much time they can study each day, upcoming deadlines that matter to them, and their academic or career goal. When you know enough, tell them to tap "Create my plan".
11. On the first turn (no student message yet), greet the student and raise the single most important finding from VERIFIED RECORDS as a question.
Reply in {language}.

{context}"""

LANGUAGE = {"en": "English", "hi": "Hindi (Devanagari script)"}


def _source(url: str) -> str:
    return urlparse(url).netloc.removeprefix("www.")


def context(conn, student_id: int) -> str:
    """Compact text rendering of the verified profile. Never includes the student's name or roll number:
    the external provider receives no direct identifiers."""
    p = analytics.build_profile(conn, student_id)
    lines = [f"VERIFIED RECORDS (as of {p.as_of})",
             f"Student: {p.student.programme}, semester {p.student.semester}. Overall average {p.overall_pct}%."]
    for s in p.subjects:
        if s.flags:
            detail = "; ".join(f.reason for f in s.flags)
        else:
            detail = "no issues found"
        lines.append(f"- {s.name} ({s.code}) {s.pct}% from {s.n_assessments} assessments: {detail}")
    lines.append("UPCOMING ASSESSMENTS")
    lines += [f"- {u.subject_code} {u.kind} on {u.on}" for u in p.upcoming] or ["- none"]
    lines.append("SKILL COVERAGE BY CAREER ROLE (indicator only)")
    for r in p.roles:
        weak = f" (weakest: {r.weakest_subject})" if r.weakest_subject else ""
        lines.append(f"- {r.role} {r.pct}%{weak}")
    lines.append("APPROVED RESOURCES")
    flagged = [s for s in p.subjects if s.flags][:3]  # top 3 flagged subjects only: keeps the prompt small for free tiers
    for s in flagged:
        for r in connector.get_resources(conn, s.code):
            lines.append(f'- [{r.id}] {s.code} / {r.topic} - "{r.title}" ({_source(r.url)}, {r.kind})')
    if not flagged:
        lines.append("- none")
    return "\n".join(lines)


def build_messages(conn, student_id: int, req: ChatRequest) -> list[dict]:
    system = MENTOR_SYSTEM.format(language=LANGUAGE[req.lang], context=context(conn, student_id))
    msgs = [{"role": "system", "content": system}] + [{"role": m.role, "content": m.content} for m in req.messages[-16:]]
    if not req.messages:
        msgs.append({"role": "user", "content": "(The student has just opened the mentor screen.)"})
    return msgs


@router.post("/mentor/chat", response_model=ChatReply)
def chat(req: ChatRequest, s: auth.Session = Depends(auth.consented), conn=Depends(db.get_conn)):
    # Roles are limited to user/assistant by ChatMessage, so a client cannot inject a system message.
    # The transcript is not stored.
    msgs = build_messages(conn, s.student_id, req)
    conn.commit()  # release the read transaction before the slow external call
    try:
        return ChatReply(reply=llm.chat(msgs, max_tokens=300))
    except llm.AIUnavailable:
        raise HTTPException(502, "ai_unavailable")


@router.post("/stt")
def stt(file: UploadFile = File(...), lang: Lang = Form("en"), s: auth.Session = Depends(auth.consented)):
    kind = (file.content_type or "").split(";")[0].strip().lower()
    if kind not in AUDIO_TYPES:
        raise HTTPException(422, "invalid_audio")
    data = file.file.read(MAX_AUDIO + 1)
    if len(data) > MAX_AUDIO:
        raise HTTPException(413, "audio_too_large")
    try:
        return {"text": llm.transcribe(data, f"speech.{AUDIO_TYPES[kind]}", lang)}
    except llm.STTUnavailable:
        raise HTTPException(503, "stt_unavailable")
