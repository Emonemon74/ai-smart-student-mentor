"""C8: phone access. QR token exchange, then a session scoped to one roadmap (LLD C8)."""
from __future__ import annotations

import secrets
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from app import auth, db, report, roadmap
from app.schemas import Report, RoadmapView, TaskStatus

router = APIRouter(prefix="/api")


class TaskUpdate(BaseModel):
    status: TaskStatus


@router.get("/r/{token}", response_model=RoadmapView)
def redeem(token: str, response: Response, conn=Depends(db.get_conn)):
    # Atomic and single use: only one request can flip used_at.
    row = conn.execute(
        """UPDATE share_tokens SET used_at = now()
           WHERE token_hash=%s AND used_at IS NULL AND expires_at > now() RETURNING roadmap_id""",
        (db.h(token),),
    ).fetchone()
    if not row:
        conn.commit()
        raise HTTPException(410, "link_used_or_expired")
    rm = conn.execute("SELECT student_id, review_on FROM roadmaps WHERE id=%s", (row["roadmap_id"],)).fetchone()
    sid = secrets.token_urlsafe(32)
    secs = conn.execute(
        """INSERT INTO sessions (id_hash, kind, student_id, roadmap_id, expires_at)
           VALUES (%s, 'phone', %s, %s, (%s::date + 7)::timestamptz)
           RETURNING GREATEST(EXTRACT(EPOCH FROM (expires_at - now())), 60)::int AS secs""",
        (db.h(sid), rm["student_id"], row["roadmap_id"], rm["review_on"]),
    ).fetchone()["secs"]
    db.audit(conn, f"phone:{rm['student_id']}", "share_redeem", str(row["roadmap_id"]))
    conn.commit()
    auth._set_cookie(response, auth.PHONE_COOKIE, sid, max_age=secs)
    return roadmap.view(conn, row["roadmap_id"])


@router.get("/phone/roadmap", response_model=RoadmapView)
def phone_roadmap(s: auth.Session = Depends(auth.phone), conn=Depends(db.get_conn)):
    return roadmap.view(conn, s.roadmap_id)


@router.get("/phone/report", response_model=Report)
def phone_report(s: auth.Session = Depends(auth.phone), conn=Depends(db.get_conn)):
    out = report.build_report(conn, s.roadmap_id, date.today())
    db.audit(conn, f"phone:{s.student_id}", "report_view", str(s.roadmap_id))
    conn.commit()
    return out


@router.patch("/phone/tasks/{task_id}", status_code=204)
def phone_task(task_id: int, body: TaskUpdate, s: auth.Session = Depends(auth.phone), conn=Depends(db.get_conn)):
    cur = conn.execute(
        "UPDATE tasks SET status=%s, status_at=now() WHERE id=%s AND roadmap_id=%s",  # roadmap_id from the session, never the client
        (body.status, task_id, s.roadmap_id),
    )
    if cur.rowcount == 0:
        conn.commit()
        raise HTTPException(404, "not_found")
    db.audit(conn, f"phone:{s.student_id}", "task_update", str(task_id))
    conn.commit()
    return Response(status_code=204)
