"""Question bank integrity (LLD_next C17.4): the answer keys are the only source of truth for levels."""
from collections import Counter

from app import db

DEMO = {("DSA", "Trees"), ("DSA", "Graphs"), ("DM", "Graph Theory")}


def rows():
    with db.pool.connection() as c:
        return c.execute("SELECT s.code, q.topic, q.tier, q.stem, q.options, q.answer, q.reviewed_by FROM questions q JOIN subjects s ON s.id=q.subject_id").fetchall()


def test_every_dsa_and_dm_topic_has_enough_items(client):
    n = Counter((r["code"], r["topic"], r["tier"]) for r in rows())
    topics = {(c, t) for c, t, _ in n}
    assert {c for c, _ in topics} == {"DSA", "DM"} and len(topics) == 10
    for c, t in topics:
        need = (4, 4, 2) if (c, t) in DEMO else (2, 2, 1)
        assert (n[(c, t, "basic")], n[(c, t, "standard")], n[(c, t, "multi")]) >= need, (c, t)


def test_items_are_well_formed(client):
    seen = set()
    for r in rows():
        assert len(r["options"]) == 4 and len(set(r["options"])) == 4 and 0 <= r["answer"] <= 3
        assert r["reviewed_by"].strip()
        key = (r["code"], r["topic"], r["stem"])
        assert key not in seen
        seen.add(key)
