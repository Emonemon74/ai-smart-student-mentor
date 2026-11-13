"""Dev-only synthetic data generator (LLD_next C3.5). `python gen.py [--out DIR] [--anchor YYYY-MM-DD]`.
Deterministic (random.seed(42)): marks are identical on every run, only the dates move. Every date is an offset
from the ANCHOR (default: today), written to ANCHOR so the importer knows what the data is relative to.
The hand-curated files (resources, prereqs, questions, contacts) are copied next to the output.
Resource URLs were each checked to return HTTP 200 before commit (`python -m app.connector check-links`)."""
import argparse
import csv
import datetime as dt
import random
import shutil
from pathlib import Path

_ap = argparse.ArgumentParser()
_ap.add_argument("--out", default=str(Path(__file__).parent))
_ap.add_argument("--anchor", default=None)
_args = _ap.parse_args()

random.seed(42)
HERE = Path(__file__).parent
OUT = Path(_args.out)
OUT.mkdir(parents=True, exist_ok=True)
ANCHOR = dt.date.fromisoformat(_args.anchor) if _args.anchor else dt.date.today()
SUBJ = {
    "DSA": ("Data Structures", ["Arrays", "Linked Lists", "Stacks & Queues", "Trees", "Graphs"]),
    "DBMS": ("Database Systems", ["ER Model", "SQL", "Normalization", "Transactions", "Indexing"]),
    "OS": ("Operating Systems", ["Processes", "Scheduling", "Synchronization", "Memory", "File Systems"]),
    "CN": ("Computer Networks", ["OSI & TCP/IP", "Data Link", "Routing", "Transport", "Application Layer"]),
    "DM": ("Discrete Mathematics", ["Logic", "Sets & Relations", "Combinatorics", "Graph Theory", "Recurrences"]),
}
OFFSET = {"DSA": -2, "DBMS": 2, "OS": 0, "CN": 1, "DM": -1}
NAMES = ["Aarav Sharma", "Priya Nair", "Rohan Das", "Ananya Iyer", "Kabir Singh", "Meera Reddy", "Arjun Patel", "Diya Menon", "Vihaan Gupta", "Ishita Bose",
         "Aditya Rao", "Sneha Kulkarni", "Rahul Verma", "Kavya Pillai", "Siddharth Joshi", "Riya Banerjee", "Karan Malhotra", "Neha Chopra", "Varun Shetty", "Pooja Desai",
         "Yash Agarwal", "Tanvi Mehta", "Harsh Vardhan", "Aisha Khan", "Nikhil Bhat", "Shruti Jain", "Manav Kapoor", "Lakshmi Nambiar", "Dev Thakur", "Zoya Ansari"]
rolls = [f"CS23{i:03d}" for i in range(1, 31)]
clip = lambda x, lo, hi: max(lo, min(hi, x))
half = lambda x: round(x * 2) / 2

# Quiz slot order (same for every subject): the last two quizzes by date are topic 3 q2 and topic 4 q2,
# which the DECLINING rule compares with the first two (topic 0).
SLOTS = [(0, 1), (0, 2), (1, 1), (1, 2), (2, 1), (2, 2), (3, 1), (4, 1), (3, 2), (4, 2)]
D0 = ANCHOR - dt.timedelta(weeks=13)
slot_date = {s: D0 + dt.timedelta(days=7 * k) for k, s in enumerate(SLOTS)}
INTERNALS = [ANCHOR - dt.timedelta(weeks=8), ANCHOR - dt.timedelta(weeks=3)]
UPCOMING = ANCHOR + dt.timedelta(days=11)
REVIEW_Q = [ANCHOR + dt.timedelta(days=13), ANCHOR + dt.timedelta(days=14), ANCHOR + dt.timedelta(days=15)]
REVIEW_INTERNAL = ANCHOR + dt.timedelta(days=15)
LAB_DATES = [ANCHOR - dt.timedelta(weeks=6), ANCHOR - dt.timedelta(weeks=2)]
LAB_TOPICS = (0, 2)                      # labs are topic-specific: topics 0 and 2 of each lab subject
LAB_SUBJECTS = ("DSA", "DBMS", "OS", "CN")

ability = {r: clip(random.gauss(70, 8), 50, 90) for r in rolls}
sub_noise = {(r, s): random.gauss(0, 5) for r in rolls for s in SUBJ}
ability["CS23001"] = 73                      # demo student: solid overall, weak only in DSA
for s in SUBJ:
    sub_noise[("CS23001", s)] = 0


def quiz_pct(r, s, review=False):
    return clip(random.gauss(ability[r] + OFFSET[s] + sub_noise[(r, s)] + (3 if review else 0), 6), 20, 100)


ass, att = [], []
back = []
for r in rolls:
    for s, (_, topics) in SUBJ.items():
        if r == "CS23006" and s == "CN":                     # designed: only 2 scored assessments (LOW_EVIDENCE)
            for d in INTERNALS:
                ass.append([r, s, "All", "internal", half(quiz_pct(r, s) * 30 / 100), 30, d, "baseline"])
            ass.append([r, s, "All", "internal", "", 30, UPCOMING, "baseline"])
            att.append([r, s, int(clip(random.gauss(53, 3), 47, 60)), 60, "baseline"])
            for ti, t in enumerate(topics):
                ass.append([r, s, t, "quiz", half(quiz_pct(r, s, True) / 10), 10, REVIEW_Q[ti % 3], "review"])
            ass.append([r, s, "All", "internal", half(quiz_pct(r, s, True) * 30 / 100), 30, REVIEW_INTERNAL, "review"])
            att.append([r, s, int(clip(random.gauss(18, 1), 14, 20)), 20, "review"])
            continue
        for (ti, qn), d in slot_date.items():  # baseline
            p = quiz_pct(r, s)
            if r == "CS23001" and s == "DSA":
                p = {0: 70, 1: 72, 2: 70, 3: 55, 4: 40}[ti]          # designed: weak Trees / Graphs, falling trend
            if r == "CS23004" and s == "DBMS":
                p = clip(random.gauss(75, 2), 70, 80)               # designed: strong theory, weak labs
            if r == "CS23007" and s == "DM":
                p = 45 if ti == 3 else 78                                # designed: Graph Theory weak, Logic / Sets strong
            ass.append([r, s, topics[ti], "quiz", half(p / 10), 10, d, "baseline"])
        for d in INTERNALS:
            p = quiz_pct(r, s)
            if r == "CS23001" and s == "DSA":
                p = 57 if d == INTERNALS[0] else 59
            sc = half(p * 30 / 100)
            if r == "CS23003" and s == "DBMS" and d == INTERNALS[1]:
                sc = ""                                               # designed: past internal with no recorded score
            ass.append([r, s, "All", "internal", sc, 30, d, "baseline"])
        ass.append([r, s, "All", "internal", "", 30, UPCOMING, "baseline"])  # upcoming internal, blank score
        if s in LAB_SUBJECTS:                                          # labs: topic-specific, same ability model, max 20
            for li, d in enumerate(LAB_DATES):
                lp = clip(random.gauss(ability[r] + OFFSET[s] + sub_noise[(r, s)], 3), 20, 100)
                if r == "CS23001" and s == "DSA":
                    lp = 58                                            # designed: labs only on Arrays and Stacks & Queues
                if r == "CS23004" and s == "DBMS":
                    lp = 50                                            # designed: theory ~75, labs ~50 (THEORY_PRACTICE_GAP)
                ass.append([r, s, topics[LAB_TOPICS[li]], "lab", half(lp / 5), 20, d, "baseline"])
        a = 41 if (r == "CS23002" and s == "OS") else int(clip(random.gauss(53, 3), 47, 60))   # designed: OS attendance 68%
        att.append([r, s, a, 60, "baseline"])
        for ti, t in enumerate(topics):  # review
            p = quiz_pct(r, s, review=True)
            if r == "CS23001" and s == "DSA":
                p = {3: 70, 4: 62}.get(ti, p)                         # designed: partial improvement
            ass.append([r, s, t, "quiz", half(p / 10), 10, REVIEW_Q[ti % 3], "review"])
        ass.append([r, s, "All", "internal", half(quiz_pct(r, s, True) * 30 / 100), 30, REVIEW_INTERNAL, "review"])
        if s in LAB_SUBJECTS:
            ass.append([r, s, topics[LAB_TOPICS[0]], "lab", half(clip(random.gauss(ability[r] + OFFSET[s] + sub_noise[(r, s)] + 3, 3), 20, 100) / 5), 20, REVIEW_INTERNAL, "review"])
        att.append([r, s, int(clip(random.gauss(18, 1), 14, 20)), 20, "review"])
        if r == "CS23005" and s == "DM":
            back.append([r, s, 2, "pending", "baseline"])
            back.append([r, s, 2, "pending", "review"])


def w(name, header, rows):
    with open(OUT / name, "w", newline="") as f:
        cw = csv.writer(f)
        cw.writerow(header)
        cw.writerows(rows)


w("students.csv", ["roll_no", "name", "programme", "semester", "pin"], [[r, n, "B.Tech CSE", 3, "1234"] for r, n in zip(rolls, NAMES)])
w("assessments.csv", ["roll_no", "subject_code", "topic", "kind", "score", "max", "taken_on", "batch"], ass)
w("attendance.csv", ["roll_no", "subject_code", "attended", "total", "batch"], att)
w("backlogs.csv", ["roll_no", "subject_code", "from_semester", "status", "batch"], back)
w("roles.csv", ["role", "subject_code"],
  [["Software Developer", s] for s in ("DSA", "DBMS", "OS")] + [["Data Analyst", s] for s in ("DBMS", "DM")]
  + [["Network / Cloud Engineer", s] for s in ("CN", "OS")] + [["AI/ML Engineer", s] for s in ("DSA", "DM")])
(OUT / "ANCHOR").write_text(ANCHOR.isoformat() + "\n")
for name in ("subjects.csv", "resources.csv", "prereqs.csv", "questions.csv", "contacts.json"):   # hand-curated
    if OUT.resolve() != HERE.resolve():
        shutil.copy(HERE / name, OUT / name)
print(len(ass), "assessment rows;", len(att), "attendance rows;", len(back), "backlog rows; anchor", ANCHOR)
