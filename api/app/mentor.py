"""C6: mentor conversation and speech-to-text (LLD C6)."""
from __future__ import annotations

from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from app import analytics, auth, catalogue, connector, db, llm
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
7. If the student reports distress, says they cannot cope, mentions harm, or asks for help with how they feel, begin your reply with [[SUPPORT]], reply kindly in one or two sentences, say a counsellor can help, and do not counsel or ask probing questions about their feelings.
8. Mention learning resources only from APPROVED RESOURCES, by title.
9. Skill coverage is an indicator of subject marks only, not a prediction. Use it only if the student shares a career goal.
10. Your goal: learn which topics feel hard, how the student studies now, their preferred format (videos, reading, practice), how much time they have each day, what gets in the way (barriers), upcoming deadlines, and their goal (semester improvement, backlog, GATE, UPSC, placement, higher studies). When you know enough, tell them to tap "Create my plan".
11. On the first turn (no student message yet), greet the student and raise the single most important finding from VERIFIED RECORDS as a question. (General mode: greet, say you have no records, and ask what they want to work towards.)
12. If a topic level is unknown or the evidence is limited, offer the 5-question concept check ("tap Check my level").
13. Describe levels only as provisional starting points for a topic. Never call them ability, intelligence or IQ.
14. When the plan is agreed, ask once, as an optional question: "How confident do you feel about your study plan today?" Do not interpret the answer beyond offering a mentor if they feel unsure.
15. Follow FLAG RESPONSES when suggesting what to do first.
Reply in {language}.

{context}"""

LANGUAGE = {"en": "English", "hi": "Hindi (Devanagari script)"}

SUPPORT_MARK = "[[SUPPORT]]"
SUPPORT_WORDS = (   # lowercase substrings, English + Hindi (Devanagari and romanised); to be reviewed by the counsellor
    "stress", "anxious", "anxiety", "panic", "depress", "hopeless", "can't cope", "cannot cope", "overwhelmed",
    "lonely", "self harm", "self-harm", "hurt myself", "kill myself", "suicide", "want to die", "no point living",
    "तनाव", "घबराहट", "उदास", "अकेला", "अकेली", "आत्महत्या", "मरना चाहता", "मरना चाहती", "परेशान",
    "tension", "pareshan", "udaas", "akela", "marna chahta",
)
FALLBACK_SUPPORT_REPLY = {
    "en": "I'm sorry it feels heavy right now. A counsellor can help, and you can see their contacts below.",
    "hi": "मुझे खेद है कि अभी बहुत भारी लग रहा है। एक काउंसलर आपकी मदद कर सकते हैं, उनके संपर्क नीचे दिए गए हैं।",
}


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
    if p.backlogs:
        lines.append("BACKLOGS")
        lines += [f"- {b.subject_name} ({b.subject_code}): from semester {b.from_semester}, {b.status}" for b in p.backlogs]
    lines.append("TOPIC LEVELS (provisional; source in brackets)")
    lv_lines = []
    for s in p.subjects:
        for t in s.levels:
            if t.level is None:
                lv_lines.append(f"- {s.code} {t.topic}: unknown (offer the concept check)")
            elif t.source == "check":
                lv_lines.append(f"- {s.code} {t.topic} {t.level} (check on {t.as_of}, {t.n} questions)")
            else:
                lv_lines.append(f"- {s.code} {t.topic} {t.level} (records, {t.n} assessments)")
    lines += lv_lines[:30] or ["- none"]
    lines.append("FLAG RESPONSES")
    seen_resp: set[tuple[str, str | None]] = set()
    for s in p.subjects:
        for f in s.flags:
            key = (f.code, f.topic)
            if key not in seen_resp and f.code in ("PREREQ_GAP", "TARGETED_GAP", "THEORY_PRACTICE_GAP", "BACKLOG", "LOW_EVIDENCE"):
                seen_resp.add(key)
                lines.append(f"- {f.code} {f.topic or s.code}: {f.response}")
    if not seen_resp:
        lines.append("- none")
    lines.append("GOALS AVAILABLE: " + ", ".join(g.name for g in catalogue.GOALS.values()))
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


def general_context(conn) -> str:
    """General guidance mode: no records at all, and the model is told so."""
    lines = ["GENERAL GUIDANCE MODE: you have NO academic records for this student and must not imply you do.",
             "Programme context: none.", "GOALS:"]
    lines += [f"- {g.name}: {g.components} — {g.indicators}" for g in catalogue.GOALS.values()]
    lines.append("APPROVED RESOURCE AREAS:")
    topics: dict[str, set[str]] = {}
    for r in conn.execute("SELECT s.name, r.topic FROM resources r JOIN subjects s ON s.id=r.subject_id GROUP BY s.name, r.topic ORDER BY 1, 2").fetchall():
        topics.setdefault(r["name"], set()).add(r["topic"])
    lines += [f"- {name}: {', '.join(sorted(ts))}" for name, ts in topics.items()]
    lines += ["The student can see approved resources on the Explore screen and can talk to a human mentor at any time.",
              'There is no plan creation, level check or report in this mode: never tell the student to tap "Create my plan" or "Check my level".']
    return "\n".join(lines)


def build_messages(conn, s: auth.Session, req: ChatRequest) -> list[dict]:
    ctx = context(conn, s.student_id) if s.mode == "personal" else general_context(conn)
    system = MENTOR_SYSTEM.format(language=LANGUAGE[req.lang], context=ctx)
    msgs = [{"role": "system", "content": system}] + [{"role": m.role, "content": m.content} for m in req.messages[-16:]]
    if not req.messages:
        msgs.append({"role": "user", "content": "(The student has just opened the mentor screen.)"})
    return msgs


@router.post("/mentor/chat", response_model=ChatReply)
def chat(req: ChatRequest, s: auth.Session = Depends(auth.guided), conn=Depends(db.get_conn)):
    # Roles are limited to user/assistant by ChatMessage, so a client cannot inject a system message.
    # The transcript is not stored, and showing the support panel writes nothing (RB 8).
    msgs = build_messages(conn, s, req)
    conn.commit()  # release the read transaction before the slow external call
    last_user = next((m.content for m in reversed(req.messages) if m.role == "user"), "").lower()
    hit = any(w in last_user for w in SUPPORT_WORDS)
    try:
        reply = llm.chat(msgs, max_tokens=300)
    except llm.AIUnavailable:
        if hit:   # the support panel must never depend on the AI being up
            return ChatReply(reply=FALLBACK_SUPPORT_REPLY[req.lang], support=True)
        raise HTTPException(502, "ai_unavailable")
    marked = SUPPORT_MARK in reply
    reply = reply.replace(SUPPORT_MARK, "").strip() or FALLBACK_SUPPORT_REPLY[req.lang]
    return ChatReply(reply=reply, support=hit or marked)


@router.post("/stt")
def stt(file: UploadFile = File(...), lang: Lang = Form("en"), s: auth.Session = Depends(auth.guided)):
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
