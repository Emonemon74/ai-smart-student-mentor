"""Dev-only synthetic data generator (LLD C3.4). Run once: `python gen.py`; the CSVs are committed.
Deterministic (random.seed(42)). Resource URLs were each checked to return HTTP 200 before commit."""
import csv
import datetime as dt
import random
from pathlib import Path

random.seed(42)
HERE = Path(__file__).parent
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
D0 = dt.date(2026, 8, 10)
slot_date = {s: D0 + dt.timedelta(days=7 * k) for k, s in enumerate(SLOTS)}
INTERNALS = [dt.date(2026, 9, 15), dt.date(2026, 10, 20)]
UPCOMING = dt.date(2026, 11, 24)
REVIEW_Q = [dt.date(2026, 11, 26), dt.date(2026, 11, 27), dt.date(2026, 11, 28)]

ability = {r: clip(random.gauss(70, 8), 50, 90) for r in rolls}
sub_noise = {(r, s): random.gauss(0, 5) for r in rolls for s in SUBJ}
ability["CS23001"] = 73                      # demo student: solid overall, weak only in DSA
for s in SUBJ:
    sub_noise[("CS23001", s)] = 0


def quiz_pct(r, s, review=False):
    return clip(random.gauss(ability[r] + OFFSET[s] + sub_noise[(r, s)] + (3 if review else 0), 6), 20, 100)


ass, att = [], []
for r in rolls:
    for s, (_, topics) in SUBJ.items():
        for (ti, qn), d in slot_date.items():  # baseline
            p = quiz_pct(r, s)
            if r == "CS23001" and s == "DSA":
                p = {0: 70, 1: 72, 2: 70, 3: 55, 4: 40}[ti]          # designed: weak Trees / Graphs, falling trend
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
        a = 41 if (r == "CS23002" and s == "OS") else int(clip(random.gauss(53, 3), 47, 60))   # designed: OS attendance 68%
        att.append([r, s, a, 60, "baseline"])
        for ti, t in enumerate(topics):  # review
            p = quiz_pct(r, s, review=True)
            if r == "CS23001" and s == "DSA":
                p = {3: 70, 4: 62}.get(ti, p)                         # designed: partial improvement
            ass.append([r, s, t, "quiz", half(p / 10), 10, REVIEW_Q[ti % 3], "review"])
        ass.append([r, s, "All", "internal", half(quiz_pct(r, s, True) * 30 / 100), 30, dt.date(2026, 11, 28), "review"])
        att.append([r, s, int(clip(random.gauss(18, 1), 14, 20)), 20, "review"])


def w(name, header, rows):
    with open(HERE / name, "w", newline="") as f:
        cw = csv.writer(f)
        cw.writerow(header)
        cw.writerows(rows)


w("students.csv", ["roll_no", "name", "programme", "semester", "pin"], [[r, n, "B.Tech CSE", 3, "1234"] for r, n in zip(rolls, NAMES)])
w("subjects.csv", ["code", "name"], [[c, n] for c, (n, _) in SUBJ.items()])
w("assessments.csv", ["roll_no", "subject_code", "topic", "kind", "score", "max", "taken_on", "batch"], ass)
w("attendance.csv", ["roll_no", "subject_code", "attended", "total", "batch"], att)
w("roles.csv", ["role", "subject_code"],
  [["Software Developer", s] for s in ("DSA", "DBMS", "OS")] + [["Data Analyst", s] for s in ("DBMS", "DM")]
  + [["Network / Cloud Engineer", s] for s in ("CN", "OS")] + [["AI/ML Engineer", s] for s in ("DSA", "DM")])
# resources.csv is hand-curated (50 verified URLs) and not regenerated here.
print(len(ass), "assessment rows;", len(att), "attendance rows")
