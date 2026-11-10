"""C2: PIN login with lockout, kiosk/phone/staff sessions, consent, student requests (LLD C2)."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app import config, db
from app.schemas import FeedbackIn, RequestIn, StudentInfo

router = APIRouter(prefix="/api")

KIOSK_COOKIE, PHONE_COOKIE, STAFF_COOKIE = "kiosk_sid", "phone_sid", "staff_sid"
STAFF_HOURS = 8


# ---- PIN hashing (stdlib scrypt), stored as salt_hex$hash_hex -------------------------------
def hash_pin(pin: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(pin.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"{salt.hex()}${dk.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
    salt_hex, hash_hex = stored.split("$")
    dk = hashlib.scrypt(pin.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
    return hmac.compare_digest(dk.hex(), hash_hex)


DUMMY_HASH = hash_pin("0000")  # unknown roll numbers still cost one hash: equal timing


# ---- sessions --------------------------------------------------------------------------------
@dataclass
class Session:
    kind: str
    student_id: int | None
    roadmap_id: int | None
    consented: bool


def _set_cookie(response: Response, name: str, token: str, max_age: int | None = None) -> None:
    # ponytail: demo serves the kiosk on http://localhost and the phone via the HTTPS tunnel;
    # set secure=True on a real HTTPS origin
    response.set_cookie(name, token, httponly=True, samesite="lax", path="/", secure=False, max_age=max_age)


def kiosk(request: Request, conn=Depends(db.get_conn)) -> Session:
    tok = request.cookies.get(KIOSK_COOKIE)
    if tok:
        row = conn.execute(
            """UPDATE sessions SET expires_at = now() + interval '15 minutes'
               WHERE id_hash=%s AND kind='kiosk' AND expires_at > now()
               RETURNING student_id, consented_at""",
            (db.h(tok),),
        ).fetchone()
        conn.commit()
        if row:
            return Session("kiosk", row["student_id"], None, row["consented_at"] is not None)
    raise HTTPException(401, "no_session")


def consented(s: Session = Depends(kiosk)) -> Session:
    if not s.consented:
        raise HTTPException(403, "consent_required")
    return s


def phone(request: Request, conn=Depends(db.get_conn)) -> Session:
    tok = request.cookies.get(PHONE_COOKIE)
    if tok:
        row = conn.execute(
            "SELECT student_id, roadmap_id FROM sessions WHERE id_hash=%s AND kind='phone' AND expires_at > now()",
            (db.h(tok),),
        ).fetchone()
        if row:
            return Session("phone", row["student_id"], row["roadmap_id"], True)
    raise HTTPException(401, "no_session")


def staff(request: Request, conn=Depends(db.get_conn)) -> Session:
    tok = request.cookies.get(STAFF_COOKIE)
    if tok:
        row = conn.execute("SELECT 1 FROM sessions WHERE id_hash=%s AND kind='staff' AND expires_at > now()", (db.h(tok),)).fetchone()
        if row:
            return Session("staff", None, None, True)
    raise HTTPException(401, "no_session")


# ---- endpoints -------------------------------------------------------------------------------
class LoginIn(BaseModel):
    roll_no: str = Field(min_length=1, max_length=20)
    pin: str = Field(pattern=r"^\d{4,6}$")


class ConsentIn(BaseModel):
    notice_version: str = Field(min_length=1, max_length=20)


class AdminLoginIn(BaseModel):
    password: str = Field(max_length=200)


@router.post("/auth/login", response_model=StudentInfo)
def login(body: LoginIn, response: Response, conn=Depends(db.get_conn)):
    db.cleanup(conn)
    roll = body.roll_no.strip().upper()
    row = conn.execute(
        "SELECT *, (locked_until IS NOT NULL AND locked_until > now()) AS is_locked FROM students WHERE roll_no=%s", (roll,)
    ).fetchone()
    if row is None:
        verify_pin(body.pin, DUMMY_HASH)
        db.audit(conn, "system", "login_fail", roll[:20])
        conn.commit()
        raise HTTPException(401, "bad_credentials")
    if row["is_locked"]:
        conn.commit()
        raise HTTPException(423, "locked")
    if not verify_pin(body.pin, row["pin_hash"]):
        n = conn.execute("UPDATE students SET failed_attempts = failed_attempts + 1 WHERE id=%s RETURNING failed_attempts", (row["id"],)).fetchone()["failed_attempts"]
        if n >= 5:
            conn.execute("UPDATE students SET failed_attempts=0, locked_until = now() + interval '5 minutes' WHERE id=%s", (row["id"],))
            db.audit(conn, f"student:{row['id']}", "login_locked")
        else:
            db.audit(conn, f"student:{row['id']}", "login_fail")
        conn.commit()
        raise HTTPException(401, "bad_credentials")
    conn.execute("UPDATE students SET failed_attempts=0, locked_until=NULL WHERE id=%s", (row["id"],))
    tok = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions (id_hash, kind, student_id, expires_at) VALUES (%s, 'kiosk', %s, now() + interval '15 minutes')",
        (db.h(tok), row["id"]),
    )
    db.audit(conn, f"student:{row['id']}", "login_ok")
    conn.commit()
    _set_cookie(response, KIOSK_COOKIE, tok)
    return StudentInfo(roll_no=row["roll_no"], name=row["name"], programme=row["programme"], semester=row["semester"])


@router.post("/auth/logout", status_code=204)
def logout(request: Request, s: Session = Depends(kiosk), conn=Depends(db.get_conn)):
    conn.execute("DELETE FROM sessions WHERE id_hash=%s", (db.h(request.cookies.get(KIOSK_COOKIE, "")),))
    db.audit(conn, f"student:{s.student_id}", "logout")
    conn.commit()
    resp = Response(status_code=204)
    resp.delete_cookie(KIOSK_COOKIE, path="/")
    return resp


@router.post("/consent", status_code=204)
def consent(body: ConsentIn, request: Request, s: Session = Depends(kiosk), conn=Depends(db.get_conn)):
    conn.execute("UPDATE sessions SET consented_at = now() WHERE id_hash=%s", (db.h(request.cookies.get(KIOSK_COOKIE, "")),))
    db.audit(conn, f"student:{s.student_id}", "consent", body.notice_version)
    conn.commit()
    return Response(status_code=204)


@router.post("/requests", status_code=204)
def create_request(body: RequestIn, s: Session = Depends(consented), conn=Depends(db.get_conn)):
    conn.execute(
        "INSERT INTO requests (student_id, kind, subject_code, note) VALUES (%s, %s, %s, %s)",
        (s.student_id, body.kind, body.subject_code, body.note),
    )
    db.audit(conn, f"student:{s.student_id}", "request_create", body.kind)
    conn.commit()
    return Response(status_code=204)


@router.post("/feedback", status_code=204)
def feedback(body: FeedbackIn, s: Session = Depends(kiosk), conn=Depends(db.get_conn)):
    conn.execute("INSERT INTO feedback (rating) VALUES (%s)", (body.rating,))  # anonymous: no student id stored
    db.audit(conn, "system", "feedback")
    conn.commit()
    return Response(status_code=204)


@router.delete("/me/plans", status_code=204)
def delete_plans(s: Session = Depends(consented), conn=Depends(db.get_conn)):
    conn.execute("DELETE FROM sessions WHERE kind='phone' AND student_id=%s", (s.student_id,))
    conn.execute("DELETE FROM roadmaps WHERE student_id=%s", (s.student_id,))  # tasks and share tokens cascade
    db.audit(conn, f"student:{s.student_id}", "plans_delete")
    conn.commit()
    return Response(status_code=204)


@router.post("/admin/login", status_code=204)
def admin_login(body: AdminLoginIn, conn=Depends(db.get_conn)):
    if not hmac.compare_digest(body.password.encode(), config.ADMIN_PASSWORD.encode()):
        raise HTTPException(401, "bad_credentials")
    tok = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO sessions (id_hash, kind, expires_at) VALUES (%s, 'staff', now() + make_interval(hours => %s))",
        (db.h(tok), STAFF_HOURS),
    )
    db.audit(conn, "staff", "staff_login")
    conn.commit()
    resp = Response(status_code=204)
    _set_cookie(resp, STAFF_COOKIE, tok, max_age=STAFF_HOURS * 3600)
    return resp
