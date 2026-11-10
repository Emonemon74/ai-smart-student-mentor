# AI Smart Student Mentor — Component Technical Design (LLD)

| | |
|---|---|
| Version | 1.1 — 10 Nov 2026 (review pass against the brief) |
| Companion | `docs/HLD.md` |

This document is the build contract: each component lists the files it owns, its interfaces, data, rules, errors and a definition of done (DoD). Components only talk to each other through the interfaces written here, so they can be built in parallel.

---

## 0. Conventions

| Topic | Decision |
|---|---|
| Python | 3.12, `uv`, FastAPI, **sync** endpoints (run in FastAPI's threadpool), psycopg 3 + `psycopg_pool`, `dict_row` |
| Backend deps | `fastapi[standard]` (includes `python-multipart`), `psycopg[binary,pool]`, `openai`; dev: `pytest` |
| Frontend | Next.js (App Router, TypeScript, Tailwind from the template). All pages are client components (`"use client"`); route params via `useParams()`; data via `fetch('/api/...')` |
| Frontend deps | `qrcode.react` (only addition to the template) |
| SQL | Hand-written, parameterised (`%s`). No ORM. Schema in `api/schema.sql`, applied on startup (idempotent) |
| Transactions | **Every write endpoint calls `conn.commit()` before returning**, so a client never receives a response before its data is visible to the next request |
| Module calls | Call other modules through the module (`from app import llm; llm.chat(...)`), never `from app.llm import chat`, so tests can monkeypatch |
| Times | `timestamptz` in DB, ISO-8601 in JSON, server clock is the source of truth |
| Errors | `HTTPException(status, detail="<code>")`; the frontend switches on `detail` codes in §0.1 |
| Logging | stdlib `logging`, one JSON line per event. Never log PINs, passwords, tokens, prompts or replies. Token-bearing paths are redacted (`/api/r/:token`) |
| Tokens | `secrets.token_urlsafe(32)` sent to the client; only `sha256(token)` stored in DB |
| HTTP headers | API responses: `Cache-Control: no-store`. Web: `Referrer-Policy: no-referrer` (set in `next.config.ts`) |

### 0.1 Error codes

| Status | `detail` | Meaning | Frontend action |
|---|---|---|---|
| 401 | `no_session` | Missing / expired session cookie | Kiosk → `/`; phone → "link expired" screen |
| 401 | `bad_credentials` | Wrong roll no / PIN / admin password | Show error, clear PIN |
| 423 | `locked` | 5 failed PINs, locked 5 min | Show "try again later" |
| 403 | `consent_required` | Session has not consented | → `/consent` |
| 404 | `not_found` | Missing **or not owned** (never leak existence) | Show not found |
| 410 | `link_used_or_expired` | Share token used / expired | Fall back to phone cookie, else "scan a new QR" |
| 422 | (FastAPI default) or `invalid_plan` | Request validation / saved plan fails checks | Show field error |
| 502 | `ai_unavailable` | All LLM providers failed / invalid output after retry | "AI is busy" + human mentor button |
| 503 | `stt_unavailable` | Transcription failed | "Please type instead" |

### 0.2 Repository layout and ownership

```
emon/
  docker-compose.yml  .env.example  scripts/dev.sh  README.md        C15
  api/
    pyproject.toml  schema.sql                                         C1
    app/config.py  app/db.py  app/main.py  app/schemas.py              C1
    app/auth.py                                                        C2
    app/connector.py  seed/gen.py  seed/*.csv                          C3
    app/analytics.py                                                   C4
    app/llm.py                                                         C5
    app/mentor.py                                                      C6
    app/roadmap.py                                                     C7
    app/phone.py                                                       C8
    app/report.py                                                      C9
    app/admin.py                                                       C10
    tests/conftest.py                                                  C1
    tests/test_<component>.py                                          owner of the component
  web/
    next.config.ts  lib/api.ts  lib/types.ts  lib/i18n.ts              C11
    app/layout.tsx  app/providers.tsx                                  C11
    app/(kiosk)/layout.tsx  components/KioskShell.tsx                  C11
    lib/voice.ts                                                       C13
    app/(kiosk)/{page,login,consent,profile,mentor,roadmap,report,end}/  C12
    app/r/[token]/  app/m/                                             C14
    app/admin/                                                         C10
  docs/HLD.md  docs/LLD.md
```

`(kiosk)` is a Next.js route group: it adds the kiosk layout (idle logout, health overlay, header) without changing URLs. `/r`, `/m` and `/admin` sit outside it.

### 0.3 Component map

```mermaid
flowchart TB
    subgraph Web
      C11[C11 Web shell]
      C12[C12 Kiosk screens]
      C13[C13 Voice]
      C14[C14 Phone view]
    end
    subgraph API
      C1[C1 Core: config, db, audit, health]
      C2[C2 Auth, sessions, requests]
      C3[C3 Data connector]
      C4[C4 Analytics]
      C5[C5 LLM gateway]
      C6[C6 Mentor]
      C7[C7 Roadmap & share]
      C8[C8 Phone access]
      C9[C9 Report]
      C10[C10 Admin]
    end
    C12 --> C11 & C13
    C14 --> C11
    C11 -->|/api| C2 & C4 & C6 & C7 & C8 & C9 & C10
    C4 --> C3
    C6 --> C4 & C5 & C3
    C7 --> C4 & C5 & C3
    C8 --> C7 & C9
    C9 --> C3 & C4
    C10 --> C4
    C2 & C3 & C7 & C8 & C9 & C10 --> C1
```

---

## C1 — Core platform

**Owns:** `api/pyproject.toml`, `api/schema.sql`, `api/app/{config,db,main,schemas}.py`, `api/tests/conftest.py`.
**Responsibility:** configuration, DB pool, schema, audit helper, retention cleanup, health, router wiring, logging, shared Pydantic models, test harness.

### C1.1 `config.py`

Plain module-level values from `os.environ` (no `pydantic-settings`, no `python-dotenv`). `scripts/dev.sh` exports `api/.env` before starting the API; tests set env in `conftest.py` before importing the app.

```python
@dataclass(frozen=True)
class Provider:
    name: str; base_url: str; api_key: str; model: str

DATABASE_URL: str          # postgresql://emon:emon@localhost:5432/emon
PUBLIC_BASE_URL: str       # https://xyz.trycloudflare.com (no trailing slash)
PROVIDERS: list[Provider]  # LLM_PROVIDERS=groq,gemini,... + {NAME}_BASE_URL/_API_KEY/_MODEL; empty key → skipped
STT: Provider              # STT_PROVIDER (reuses that provider's URL/key) + STT_MODEL
ADMIN_PASSWORD: str        # ≥ 12 chars; startup fails if shorter
```

Model choice: use **non-reasoning** chat models (reasoning models spend `max_tokens` on hidden reasoning and can return empty content). Check current model ids in each provider console when creating keys.

### C1.2 `schema.sql`

```sql
CREATE TABLE IF NOT EXISTS students (
  id serial PRIMARY KEY,
  roll_no text UNIQUE NOT NULL,
  name text NOT NULL,
  programme text NOT NULL,
  semester int NOT NULL,
  pin_hash text NOT NULL,
  failed_attempts int NOT NULL DEFAULT 0,
  locked_until timestamptz
);
CREATE TABLE IF NOT EXISTS subjects (
  id serial PRIMARY KEY,
  code text UNIQUE NOT NULL,
  name text NOT NULL
);
CREATE TABLE IF NOT EXISTS assessments (
  id serial PRIMARY KEY,
  student_id int NOT NULL REFERENCES students ON DELETE CASCADE,
  subject_id int NOT NULL REFERENCES subjects,
  topic text NOT NULL,                          -- 'All' for whole-syllabus tests
  kind text NOT NULL CHECK (kind IN ('quiz','internal','assignment')),
  score numeric CHECK (score >= 0),             -- NULL + past date = missing; NULL + future date = upcoming
  max numeric NOT NULL CHECK (max > 0),
  taken_on date NOT NULL,
  batch text NOT NULL CHECK (batch IN ('baseline','review')),
  CHECK (score IS NULL OR score <= max),
  UNIQUE (student_id, subject_id, topic, kind, taken_on, batch)   -- rejects duplicate imports
);
CREATE TABLE IF NOT EXISTS attendance (
  student_id int NOT NULL REFERENCES students ON DELETE CASCADE,
  subject_id int NOT NULL REFERENCES subjects,
  batch text NOT NULL CHECK (batch IN ('baseline','review')),
  attended int NOT NULL,
  total int NOT NULL CHECK (total > 0 AND attended BETWEEN 0 AND total),
  PRIMARY KEY (student_id, subject_id, batch)
);
CREATE TABLE IF NOT EXISTS resources (
  id serial PRIMARY KEY,
  subject_id int NOT NULL REFERENCES subjects,
  topic text NOT NULL,
  title text NOT NULL,
  url text UNIQUE NOT NULL,
  kind text NOT NULL CHECK (kind IN ('video','article','practice','course'))
);
CREATE TABLE IF NOT EXISTS role_subjects (       -- career readiness map (brief §9)
  role text NOT NULL,
  subject_id int NOT NULL REFERENCES subjects,
  PRIMARY KEY (role, subject_id)
);
CREATE TABLE IF NOT EXISTS imports (
  id serial PRIMARY KEY,
  batch text NOT NULL,
  imported_at timestamptz NOT NULL DEFAULT now(),
  counts jsonb NOT NULL,
  errors jsonb NOT NULL                         -- row-level rejections
);
CREATE TABLE IF NOT EXISTS sessions (
  id_hash text PRIMARY KEY,                     -- sha256 of cookie value
  kind text NOT NULL CHECK (kind IN ('kiosk','phone','staff')),
  student_id int REFERENCES students ON DELETE CASCADE,
  roadmap_id int,                               -- phone sessions only
  consented_at timestamptz,                     -- kiosk sessions only
  expires_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS roadmaps (
  id serial PRIMARY KEY,
  student_id int NOT NULL REFERENCES students ON DELETE CASCADE,
  subject_id int NOT NULL REFERENCES subjects,
  version int NOT NULL,
  summary text NOT NULL,
  evidence jsonb NOT NULL,                      -- baseline snapshot, see C7.6
  days int NOT NULL,
  daily_minutes int NOT NULL,
  start_on date NOT NULL,
  review_on date NOT NULL,
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','superseded')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (student_id, subject_id, version)
);
CREATE TABLE IF NOT EXISTS tasks (
  id serial PRIMARY KEY,
  roadmap_id int NOT NULL REFERENCES roadmaps ON DELETE CASCADE,
  position int NOT NULL,
  day_from int NOT NULL,
  day_to int NOT NULL CHECK (day_to >= day_from),
  due_on date NOT NULL,                         -- start_on + day_to - 1
  kind text NOT NULL CHECK (kind IN ('learn','practice','checkpoint')),
  topic text NOT NULL,
  activity text NOT NULL,
  reason text NOT NULL,                         -- why this task (links to evidence or goal)
  minutes int NOT NULL,                         -- estimated effort per day
  resource_id int NOT NULL REFERENCES resources,
  check_text text NOT NULL,                     -- completion check
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','partial','done')),
  status_at timestamptz
);
CREATE TABLE IF NOT EXISTS share_tokens (
  token_hash text PRIMARY KEY,
  roadmap_id int NOT NULL REFERENCES roadmaps ON DELETE CASCADE,
  expires_at timestamptz NOT NULL,
  used_at timestamptz
);
CREATE TABLE IF NOT EXISTS requests (            -- human-mentor referrals and data-correction requests
  id serial PRIMARY KEY,
  student_id int NOT NULL REFERENCES students ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('referral','correction')),
  subject_code text,
  note text,
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS feedback (            -- anonymous post-session rating (brief §19)
  id serial PRIMARY KEY,
  rating int NOT NULL CHECK (rating BETWEEN 1 AND 5),
  at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS audit_log (
  id bigserial PRIMARY KEY,
  at timestamptz NOT NULL DEFAULT now(),
  actor text NOT NULL,                          -- 'student:12' | 'phone:12' | 'staff' | 'system'
  action text NOT NULL,
  target text
);
```

### C1.3 `db.py`

```python
pool = ConnectionPool(DATABASE_URL, kwargs={"row_factory": dict_row}, open=False)

def init():                      # lifespan: open pool, apply schema, cleanup()
def get_conn():                  # FastAPI dependency: with pool.connection() as c: yield c  (rolls back on exception)
def audit(conn, actor: str, action: str, target: str | None = None) -> None
def h(token: str) -> str         # sha256 hex
def cleanup(conn) -> None        # retention, run at startup and on every login
```

Retention rules (`cleanup`):

| Data | Kept until |
|---|---|
| `sessions`, `share_tokens` | Expiry (deleted when expired) |
| `roadmaps` + `tasks` | Student deletes them (`DELETE /api/me/plans`) or end of semester (admin re-import) |
| `audit_log` | 180 days |
| `feedback` | Kept (anonymous) |
| Chat transcripts, audio | Never stored |

Audit actions (closed list): `login_ok`, `login_fail`, `login_locked`, `logout`, `consent`, `profile_view`, `draft_ok`, `draft_fail`, `roadmap_save`, `plans_delete`, `share_create`, `share_redeem`, `task_update`, `report_view`, `request_create`, `request_close`, `feedback`, `import`, `staff_login`, `admin_view`.

### C1.4 `main.py`

- Lifespan: `db.init()`, JSON logging.
- `app.include_router(...)` for every module router, **all registered in phase 0 with stub routers** so parallel builders never edit `main.py`.
- `GET /api/healthz` → `{"db": bool, "llm": {"last_ok": iso|None, "last_error": str|None}, "providers": [names]}`. DB = `SELECT 1`; LLM status is C5's in-memory state (no extra API calls).
- Middleware: sets `Cache-Control: no-store`; logs `method`, redacted path (`re.sub(r"^/api/r/[^/]+", "/api/r/:token", path)`), `status`, `latency_ms`.

### C1.5 `schemas.py` (shared contract, mirrored 1:1 in `web/lib/types.ts`)

```python
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
    # model_validator: day_to >= day_from

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
```

### C1.6 Test harness (`tests/conftest.py`)

- Sets `DATABASE_URL` to database `emon_test` before importing the app; creates the database if missing (autocommit connection to `postgres`).
- Session scope: `with TestClient(app) as client` (runs lifespan → schema), imports `seed/` baseline **once** (PIN hashing is deliberately slow).
- Per test: `TRUNCATE sessions, roadmaps, tasks, share_tokens, requests, feedback, audit_log RESTART IDENTITY CASCADE`; `UPDATE students SET failed_attempts=0, locked_until=NULL`; `DELETE FROM assessments WHERE batch='review'`.
- Helper `login(client, roll_no="CS23001")` logs in and consents.
- The LLM is never called in tests: monkeypatch `app.llm.chat`, `app.llm.chat_json`, `app.llm.transcribe`.

**DoD:** `docker compose up -d && uv run fastapi dev app/main.py` starts; schema applies twice without error; `/api/healthz` returns `db: true`; `/docs` lists every stub router; `uv run pytest` runs (empty suite passes).

---

## C2 — Auth, sessions, consent and student requests

**Owns:** `api/app/auth.py`, `tests/test_auth.py`.

### C2.1 Endpoints

| Method | Path | Body | Response | Auth |
|---|---|---|---|---|
| POST | `/api/auth/login` | `{roll_no, pin}` (pin: 4–6 digits) | `StudentInfo` + cookie `kiosk_sid` | none |
| POST | `/api/auth/logout` | – | 204, clears cookie, deletes row | kiosk |
| POST | `/api/consent` | `{notice_version: str}` | 204; sets `consented_at`; audit `consent` | kiosk |
| POST | `/api/requests` | `RequestIn` | 204; audit `request_create` | consented |
| POST | `/api/feedback` | `FeedbackIn` | 204; stored without student id | kiosk |
| DELETE | `/api/me/plans` | – | 204; deletes the student's roadmaps (cascade) and phone sessions; audit `plans_delete` | consented |
| POST | `/api/admin/login` | `{password}` | 204 + cookie `staff_sid` (8 h); `hmac.compare_digest` | none |

### C2.2 Login algorithm

```
cleanup(conn)
row = SELECT * FROM students WHERE roll_no=%s
if row is None: verify_pin(pin, DUMMY_HASH); 401 bad_credentials          # equal timing
if row.locked_until and row.locked_until > now(): 423 locked
if not verify_pin(pin, row.pin_hash):
    failed_attempts += 1
    if failed_attempts >= 5: locked_until = now()+5 min, failed_attempts = 0; audit login_locked
    else: audit login_fail
    commit; 401 bad_credentials
failed_attempts = 0; create kiosk session (15 min sliding); audit login_ok; commit
```

PIN hashing (stdlib): `hashlib.scrypt(pin.encode(), salt=os.urandom(16), n=2**14, r=8, p=1)`, stored as `salt_hex$hash_hex`; compare with `hmac.compare_digest`.

### C2.3 Session dependencies (used by every other router)

```python
@dataclass
class Session: kind: str; student_id: int | None; roadmap_id: int | None; consented: bool

def kiosk(req, conn) -> Session       # cookie kiosk_sid; slides expiry 15 min
def consented(s=Depends(kiosk))       # 403 consent_required if not s.consented
def phone(req, conn) -> Session       # cookie phone_sid; fixed expiry
def staff(req, conn) -> Session       # cookie staff_sid; fixed expiry
```

Validate-and-slide in one statement:

```sql
UPDATE sessions SET expires_at = now() + interval '15 minutes'
WHERE id_hash=%s AND kind='kiosk' AND expires_at > now()
RETURNING student_id, consented_at
```

Phone/staff: `SELECT ... WHERE id_hash=%s AND kind=%s AND expires_at > now()`. Each dependency reads only its own cookie, so a phone cookie can never reach kiosk routes.

Cookies: `httponly=True, samesite="lax", path="/"`, `secure=False` with `# ponytail: demo serves the kiosk on http://localhost and the phone via the HTTPS tunnel; set secure=True on a real HTTPS origin`.

### C2.4 Tests (`test_auth.py`)

- Correct PIN → 200 + cookie; wrong → 401; 5 wrong → 423 even with the correct PIN; after `locked_until` passes → 200.
- `/api/me/profile` without consent → 403; after `/api/consent` → 200.
- Logout → next call 401.
- `DELETE /api/me/plans` removes only the caller's plans.

---

## C3 — Data connector and synthetic data

**Owns:** `api/app/connector.py`, `api/seed/gen.py`, `api/seed/*.csv`, `tests/test_connector.py`.
**Responsibility:** the only code that knows where academic data comes from. Replacing CSV import with a university API changes only this file.

### C3.1 CSV contract (`api/seed/`)

| File | Columns |
|---|---|
| `students.csv` | roll_no, name, programme, semester, pin |
| `subjects.csv` | code, name |
| `assessments.csv` | roll_no, subject_code, topic, kind, score (blank = missing/upcoming), max, taken_on, batch |
| `attendance.csv` | roll_no, subject_code, attended, total, batch |
| `resources.csv` | subject_code, topic, title, url, kind |
| `roles.csv` | role, subject_code |

PINs are plain text in `students.csv` only because the data is synthetic; they are hashed on import.

### C3.2 Interface

```python
PERMITTED = ("programme", "semester", "subjects", "assessments", "attendance")  # shown on the consent screen

def import_csv(conn, folder: Path, batch: Literal["baseline", "review"]) -> dict
def get_records(conn, student_id: int, batch: str = "baseline") -> StudentRecords
def class_means(conn, batch: str = "baseline") -> dict[str, float]     # subject_code -> mean pct of scored rows
def get_resources(conn, subject_code: str) -> list[Resource]
def role_map(conn) -> dict[str, list[str]]                             # role -> subject codes
def student_info(conn, student_id: int) -> StudentInfo
def last_import(conn, batch: str) -> datetime | None
```

```python
@dataclass
class Row: topic: str; kind: str; score: float | None; max: float; taken_on: date
@dataclass
class SubjectRecords: code: str; name: str; rows: list[Row]; attended: int | None; total: int | None
@dataclass
class StudentRecords: student_id: int; subjects: list[SubjectRecords]
```

### C3.3 Import algorithm (validation and synchronization)

1. Parse every CSV row and validate before writing: known `roll_no` / `subject_code`; `kind`, `batch` in allowed sets; numbers parse; `0 ≤ score ≤ max`; `attended ≤ total`; valid date; no duplicate natural key within the file. Invalid rows are collected as `{"file", "line", "error"}` and skipped.
2. In one transaction: baseline → upsert `subjects`, `students` (hash PIN), `resources` (by url), `role_subjects`; then `DELETE` that batch from `assessments`/`attendance` and insert valid rows. Review → only the review rows.
3. Insert an `imports` row with counts and errors; audit `import`; commit.
4. Print the summary; exit code 1 if any row was rejected.

CLI: `uv run python -m app.connector import seed --batch baseline|review`.

### C3.4 Synthetic generator (`seed/gen.py`, dev-only, run once, CSVs committed)

- `random.seed(42)`. 30 students `CS23001…CS23030`, B.Tech CSE, semester 3, PIN `1234` for all (demo only).
- Subjects and topics:

| Code | Subject | Topics |
|---|---|---|
| DSA | Data Structures | Arrays, Linked Lists, Stacks & Queues, Trees, Graphs |
| DBMS | Database Systems | ER Model, SQL, Normalization, Transactions, Indexing |
| OS | Operating Systems | Processes, Scheduling, Synchronization, Memory, File Systems |
| CN | Computer Networks | OSI & TCP/IP, Data Link, Routing, Transport, Application Layer |
| DM | Discrete Mathematics | Logic, Sets & Relations, Combinatorics, Graph Theory, Recurrences |

- **Baseline** per student × subject: 2 quizzes per topic (max 10, Aug–Oct 2026), 2 internals (topic `All`, max 30), attendance out of 60, and **one upcoming internal on 2026-11-24 with a blank score**. Scores ~ N(student ability + subject offset, σ), clipped to [0, max].
- **Review**: 1 quiz per topic (26–28 Nov 2026) + 1 internal, attendance for November.
- Designed cases:
  - `CS23001` (demo): DSA Trees ≈ 55 %, Graphs ≈ 40 %, quiz trend falling ≈ 70 % → 48 %, overall ≈ 70 %. Review: Trees ≈ 70 %, Graphs ≈ 62 %.
  - `CS23002`: OS attendance 68 %.
  - `CS23003`: one past DBMS internal with a blank score (missing).
- `roles.csv`: Software Developer → DSA, DBMS, OS; Data Analyst → DBMS, DM; Network / Cloud Engineer → CN, OS; AI/ML Engineer → DSA, DM.
- `resources.csv`: 2 per topic (50 rows) from NPTEL, MIT OCW, GeeksforGeeks, cp-algorithms, VisuAlgo, Khan Academy. **Every URL must return 200 to `curl -sIL -o /dev/null -w '%{http_code}'` before committing.**

### C3.5 Tests (`test_connector.py`)

Import twice → same counts; row counts in DB equal valid CSV rows (data accuracy, brief §18); a CSV with an unknown roll no, `score > max` and a duplicate row reports 3 errors and imports the rest; review import leaves baseline rows untouched.

---

## C4 — Academic analytics

**Owns:** `api/app/analytics.py`, `tests/test_analytics.py`.
**Responsibility:** pure, explainable rules. No I/O inside rule functions; the router is a thin wrapper.

### C4.1 Rules

```python
RULES = {"self_gap": 10, "class_gap": 10, "decline": 10, "trend_quizzes": 4,
         "attendance": 75, "weak_topic": 50}       # faculty-tunable
```

Definitions: `pct(rows) = 100 * Σscore / Σmax` over **scored** rows (weighted by max marks); `None` if none. Rows with `score is None` are *missing* if `taken_on ≤ today`, *upcoming* otherwise; neither counts in `pct`. Comparisons use unrounded values; display rounds to 1 decimal.

| Code | Condition | `values` | `reason` |
|---|---|---|---|
| `LOW_VS_SELF` | `subject_pct < overall_pct − self_gap` | subject_pct, overall_pct, n | "{name} average {s}% vs your overall {o}%" |
| `LOW_VS_CLASS` | `subject_pct < class_mean − class_gap` | subject_pct, class_mean, n | "{name} {s}% vs class average {c}%" |
| `DECLINING` | ≥ `trend_quizzes` scored quizzes; mean of the last 2 by date < mean of the first 2 − `decline` | first_pct, last_pct, n | "{name} quiz scores fell from {f}% to {l}%" |
| `LOW_ATTENDANCE` | `attended / total * 100 < attendance` | pct, attended, total, n=total | "Attendance {p}% ({a} of {t} classes)" |
| `MISSING` | `score is None and taken_on ≤ today` (one flag per row) | kind, taken_on, n=1 | "{kind} on {date} has no recorded score" |
| `WEAK_TOPIC` | subject has `LOW_VS_SELF`, `LOW_VS_CLASS` or `DECLINING`; topic ≠ `All`; topic pct < `weak_topic` | pct, n | "{topic}: {p}% across {n} assessments" |

Role readiness (brief §9 indicator): for each role, `pct` = mean of the student's subject pcts for the role's subjects; `weakest_subject` = lowest of them. Shown as "skill coverage", never as a prediction.

### C4.2 Interface

```python
def pct(rows: list[Row]) -> float | None
def topic_pcts(rows: list[Row]) -> dict[tuple[str, str], tuple[float, int]]   # (topic, kind) -> (pct, n), scored rows, topic != 'All'
def analyse(rec: StudentRecords, means: dict[str, float], today: date) -> list[SubjectSummary]
def readiness(subjects: list[SubjectSummary], roles: dict[str, list[str]]) -> list[RoleReadiness]
def upcoming(rec: StudentRecords, today: date) -> list[Upcoming]
def build_profile(conn, student_id: int, batch="baseline") -> Profile          # connector + the above

router: GET /api/me/profile  (Depends(consented)) → Profile; audit profile_view
```

### C4.3 Tests (`test_analytics.py`, no DB)

Per rule: one crafted record set where the flag fires and one just past the threshold where it does not. Also: `WEAK_TOPIC` does not fire on an unflagged subject; `pct` ignores `None`; a future blank score is upcoming, not `MISSING`; a `CS23001`-like fixture yields `LOW_VS_SELF`, `DECLINING` and `WEAK_TOPIC(Graphs)` for DSA; readiness of a role equals the mean of its subjects.

---

## C5 — LLM gateway

**Owns:** `api/app/llm.py`, `tests/test_llm.py`.
**Responsibility:** the one place that talks to OpenAI-compatible providers, with fallback, timeouts and metadata-only logging.

### C5.1 Interface

```python
class AIUnavailable(Exception): ...
class STTUnavailable(Exception): ...

def chat(messages: list[dict], *, max_tokens: int = 300, temperature: float = 0.4) -> str
def chat_json(messages: list[dict], model_cls: type[BaseModel], *,
              validate: Callable[[BaseModel], None] | None = None, max_tokens: int = 1500) -> BaseModel
def transcribe(audio: bytes, filename: str, lang: Lang) -> str
STATUS = {"last_ok": None, "last_error": None}       # read by /api/healthz
```

### C5.2 Behaviour

```python
_clients = {p.name: OpenAI(base_url=p.base_url, api_key=p.api_key, timeout=20, max_retries=0)
            for p in PROVIDERS}

def chat(messages, **kw):
    for p in PROVIDERS:
        try:
            r = _clients[p.name].chat.completions.create(model=p.model, messages=messages, **kw)
            text = (r.choices[0].message.content or "").strip()
            if not text: raise ValueError("empty reply")
            log(provider, model, ms, usage); STATUS["last_ok"] = now(); return text
        except (openai.APIError, ValueError) as e:      # 429, 5xx, timeout, connection, bad config, empty
            log_warn(provider, type(e).__name__); STATUS["last_error"] = f"{p.name}: {type(e).__name__}"
    raise AIUnavailable
```

- `max_retries=0` so fallback is immediate instead of the SDK retrying a rate-limited provider.
- 401/404 (bad key or model id) also fall through, logged at `ERROR` because they are config bugs.
- `chat_json`: no `response_format` (support differs between free providers). The prompt demands JSON only; the reply is cut from the first `{` to the last `}` → `model_cls.model_validate_json` → `validate(obj)`. On `ValidationError`/`ValueError`: one retry with the bad reply and `"That was invalid: {error}. Return only the corrected JSON."` appended. Second failure → `AIUnavailable`.
- `transcribe`: `client.audio.transcriptions.create(model=STT.model, file=(filename, audio), language=lang)`; any error → `STTUnavailable` (`# ponytail: single STT provider; add a second if Whisper limits bite`).
- Never logs message content.

### C5.3 Tests

Fake clients: first raises `RateLimitError` → second answers; empty content → next provider; all fail → `AIUnavailable`; `chat_json` parses JSON wrapped in prose; invalid then valid → valid; invalid twice → `AIUnavailable`.

---

## C6 — Mentor conversation

**Owns:** `api/app/mentor.py`, `tests/test_mentor.py`.

### C6.1 Endpoints (both `Depends(consented)`)

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/mentor/chat` | `ChatRequest` (empty `messages` = opening turn) | `ChatReply` |
| POST | `/api/stt` | multipart `file` (≤ 2 MB; `audio/webm`, `audio/ogg`, `audio/mp4`), `lang` | `{"text": str}` |

### C6.2 Context building

`context(conn, student_id) -> str` renders compact text (not JSON) from `build_profile`. **It never includes the student's name or roll number**: the external provider receives no direct identifiers.

```
VERIFIED RECORDS (as of 2026-10-28)
Student: B.Tech CSE, semester 3. Overall average 70.2%.
- Data Structures (DSA) 54.0% from 12 assessments: average 54.0% vs your overall 70.2%; quiz scores fell from 70.0% to 48.0%; Graphs: 40.0% across 2 assessments; Trees: 55.0% across 2 assessments
- Operating Systems (OS) 66.0% from 12 assessments: no issues found
UPCOMING ASSESSMENTS
- DSA internal on 2026-11-24
SKILL COVERAGE BY CAREER ROLE (indicator only)
- Software Developer 63.0% (weakest: DSA)
APPROVED RESOURCES
- [12] DSA / Graphs — "BFS and DFS" (VisuAlgo, practice)
```

Resources are listed for the top 3 flagged subjects only (keeps the prompt within small free-tier context windows).

### C6.3 System prompt (`MENTOR_SYSTEM`)

```
You are the AI Study Mentor on a university campus kiosk, talking with one student.
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
Reply in {English | Hindi (Devanagari script)}.

{context}
```

### C6.4 Chat handler

```
messages = [system] + req.messages[-16:]           # bound context (some free tiers allow ~8K tokens)
if not req.messages: messages.append({"role": "user", "content": "(The student has just opened the mentor screen.)"})
reply = llm.chat(messages, max_tokens=300)         # AIUnavailable → 502 ai_unavailable
```

Roles are restricted to `user`/`assistant` by `ChatMessage`, so the client cannot inject a system message. The transcript is not stored.

### C6.5 Tests

Monkeypatch `llm.chat` and capture messages: the system prompt contains the student's flags and not another student's; it contains neither name nor roll number; empty `messages` adds the opening instruction; > 16 messages are trimmed; `lang="hi"` selects the Hindi line; `AIUnavailable` → 502.

---

## C7 — Roadmap engine and sharing

**Owns:** `api/app/roadmap.py`, `tests/test_roadmap.py`, `tests/test_share.py`.

### C7.1 Endpoints (all `Depends(consented)`, owner-scoped)

| Method | Path | Body | Response |
|---|---|---|---|
| POST | `/api/roadmaps/draft` | `DraftRequest` | `DraftView` |
| POST | `/api/roadmaps` | `RoadmapIn` (edited draft) | `RoadmapView` |
| GET | `/api/roadmaps` | – | `list[RoadmapListItem]` |
| GET | `/api/roadmaps/{id}` | – | `RoadmapView` |
| POST | `/api/roadmaps/{id}/share` | – | `ShareOut` |

### C7.2 Draft request checks

`subject_code` must be a subject the student has records for (404 otherwise); `review_on ≥ today + days` (422).

### C7.3 Draft generation

The LLM writes only `summary` and `tasks`; subject, days, minutes and review date come from the request.

```python
class LLMPlan(BaseModel):
    summary: str = Field(max_length=600)
    tasks: list[TaskIn] = Field(min_length=3, max_length=15)
```

Prompt:

```
[system] You write personalised study plans for a university student. Output only one JSON object, no other text.
[user]
SUBJECT: Data Structures (DSA)
EVIDENCE: <flags for this subject with reasons and n>
WEAK TOPICS: Graphs 40.0% (2 assessments), Trees 55.0% (2 assessments)
UPCOMING ASSESSMENTS: internal on 2026-11-24 (day 14 of the plan)
CONSTRAINTS: {days} days starting today, at most {daily_minutes} minutes per day, review on {review_on}.
APPROVED RESOURCES (use only these ids): [12] Graphs - "BFS and DFS" (practice) ...
CONVERSATION: <last 16 messages as "Student:" / "Mentor:" lines>
Write all text fields in {language}. Keep JSON keys and "kind" values in English.
Return: {"summary": "...", "tasks": [{"day_from": 1, "day_to": 3, "kind": "learn", "topic": "...",
  "activity": "...", "reason": "...", "minutes": 60, "resource_id": 12, "check": "..."}]}
Rules:
- Weakest topics first. Revise before any upcoming assessment.
- Tasks are in order, do not overlap, and cover every day from 1 to {days}.
- "minutes" is effort per day and must not exceed {daily_minutes}.
- At least one "checkpoint" task in every 7 days, and the last task is a checkpoint.
- "reason" says why, citing the evidence or the student's stated goal.
- "check" is a concrete way to know the task is complete.
```

`validate(plan, allowed_ids, days, daily_minutes)` raises `ValueError` with a short message on the first failure:

1. Every `resource_id` ∈ allowed ids for the subject.
2. Sorted by `day_from`; first `day_from == 1`; each next `day_from == prev.day_to + 1`; last `day_to == days`.
3. Every `minutes ≤ daily_minutes`.
4. At least `ceil(days / 7)` checkpoints and the last task is a checkpoint.

On success audit `draft_ok`; on `AIUnavailable` audit `draft_fail` and return 502. Response: `DraftView(roadmap=RoadmapIn(...), resources={id: Resource})`.

### C7.4 Save

Never trust the client copy. Re-run checks 1 and 3 and require ranges within `1..days`, sorted and non-overlapping (gaps are allowed because the student may delete tasks). Failure → 422 `invalid_plan`. Then in one transaction:

```
start_on = today
evidence = snapshot(conn, student_id, subject_code)              # C7.6, recomputed server-side
UPDATE roadmaps SET status='superseded' WHERE student_id=%s AND subject_id=%s AND status='active'
version = COALESCE(MAX(version), 0) + 1 for (student, subject)
INSERT roadmaps (..., start_on, review_on) RETURNING id
INSERT tasks (position = index, due_on = start_on + day_to - 1)
audit roadmap_save; commit
```

### C7.5 Share

```
assert owner
DELETE FROM sessions WHERE kind='phone' AND roadmap_id=%s          -- revoke old phones
DELETE FROM share_tokens WHERE roadmap_id=%s AND used_at IS NULL
token = secrets.token_urlsafe(32); INSERT share_tokens(h(token), id, now() + 10 min)
audit share_create; commit
return ShareOut(url=f"{PUBLIC_BASE_URL}/r/{token}", expires_at)
```

### C7.6 Evidence snapshot (baseline for the report)

```json
{
  "flags": [Flag, ...],
  "subject_pct": 54.0,
  "topics": [{"topic": "Graphs", "kind": "quiz", "pct": 40.0, "n": 2}],
  "as_of": "2026-10-28"
}
```

### C7.7 Tests

`validate` rejects: unknown `resource_id`; a gap; overlap; last day ≠ `days`; minutes over budget; missing final checkpoint. Save ignores client-supplied evidence (there is no such field), supersedes the previous active plan, bumps the version and sets `due_on`. Student B gets 404 for student A's roadmap, report and share. A second share revokes the phone session created from the first.

---

## C8 — Phone access

**Owns:** `api/app/phone.py` (tests in `tests/test_share.py`).

### C8.1 Endpoints

| Method | Path | Auth | Response |
|---|---|---|---|
| GET | `/api/r/{token}` | token | `RoadmapView` + cookie `phone_sid` |
| GET | `/api/phone/roadmap` | `phone` | `RoadmapView` |
| GET | `/api/phone/report` | `phone` | `Report` (C9, scoped to the session's roadmap) |
| PATCH | `/api/phone/tasks/{task_id}` | `phone` | body `{status: TaskStatus}` → 204 |

### C8.2 Token exchange (atomic, single use)

```sql
UPDATE share_tokens SET used_at = now()
WHERE token_hash=%s AND used_at IS NULL AND expires_at > now()
RETURNING roadmap_id
```

No row → 410 `link_used_or_expired`. Otherwise create a phone session `(kind='phone', student_id, roadmap_id, expires_at = review_on + 7 days)`, set cookie `phone_sid`, audit `share_redeem`, commit.

### C8.3 Task update

```sql
UPDATE tasks SET status=%s, status_at=now()
WHERE id=%s AND roadmap_id=%s          -- roadmap_id from the session, never from the client
```

0 rows → 404. Audit `task_update`. Commit.

### C8.4 Tests

Token works once, second use → 410; expired token → 410; the phone cookie can update its own task, gets 404 for a task in another roadmap, gets 401 on `/api/me/profile`; `/api/phone/report` returns the same report as the kiosk endpoint.

---

## C9 — Progress report

**Owns:** `api/app/report.py`, `tests/test_report.py`.

### C9.1 Interface

```python
def build_report(conn, roadmap_id: int, today: date) -> Report
router: GET /api/roadmaps/{id}/report  (Depends(consented), owner) → Report; audit report_view
```

C8 calls `build_report` for `/api/phone/report`.

### C9.2 Algorithm

```
plan = roadmap + tasks; base = plan.evidence
review = get_records(conn, student_id, "review"), plan subject only
has_review_data = review has any scored row
review_topics = analytics.topic_pcts(review rows)
verified = for each (topic, kind) in base.topics:
    present in review_topics → TopicChange(baseline_pct, review_pct, delta = review - baseline, note=None)
    absent                   → TopicChange(..., review_pct=None, delta=None, note="No comparable assessment yet")
review_subject_pct = pct(review rows whose (topic, kind) also exist in the baseline)     # like-for-like only
self_reported = SelfReport(counts by status, overdue = status != 'done' and due_on < today)
remaining_flags = analyse(review, class_means("review"), today)[subject].flags if has_review_data else []
caveat = "Changes compare similar assessments before and after the plan. They do not show that the plan caused the change."
```

**Invariant:** `verified` and `review_subject_pct` come only from `assessments`; `self_reported` only from `tasks`. No field mixes them.

### C9.3 Tests

Marking every task `done` leaves `verified` and `review_subject_pct` unchanged; a topic without a review quiz yields `note`, not a delta; no review batch → `has_review_data=False` and empty `remaining_flags`; an overdue pending task appears in `overdue`.

---

## C10 — Admin (should-have)

**Owns:** `api/app/admin.py`, `web/app/admin/`.

| Method | Path | Response |
|---|---|---|
| GET | `/api/admin/summary` | see below |
| POST | `/api/admin/requests/{id}/close` | 204; audit `request_close` |

```json
{
  "subjects": [{"code": "DSA", "students": 30, "flagged": 7, "avg_pct": 63.1, "active_plans": 3}],
  "metrics": {
    "login_success_rate_7d": 0.92,
    "draft_success_rate_7d": 0.88,
    "feedback_avg": 4.3, "feedback_n": 12,
    "plans_with_progress": 0.6
  },
  "requests": [{"id": 4, "roll_no": "CS23001", "kind": "referral", "subject_code": "DSA", "note": "...", "created_at": "..."}],
  "last_import": {"baseline": "...", "review": null},
  "health": {"db": true, "llm": {"last_ok": "...", "last_error": null}},
  "recent_audit": [{"at": "...", "actor": "student:12", "action": "roadmap_save"}]
}
```

- `subjects` runs `analyse` for every student (`# ponytail: O(students) per request, fine for one cohort; precompute when cohorts grow`). Rows with `students < 5` return counts as `null` (small-group suppression).
- `metrics` map to brief §19: login and draft success rates from `audit_log` (`login_ok` / (`login_ok`+`login_fail`), `draft_ok` / (`draft_ok`+`draft_fail`)), usefulness from `feedback`, engagement = share of active plans with ≥ 1 task not pending, reliability from `health`.
- `requests` is the intervention queue: open referrals and correction requests. Showing the roll number is allowed because the student asked for contact.
- No student-level record lookup in the MVP. Audit `admin_view`.
- Web `/admin`: password form → tables + Close buttons + Refresh.

---

## C11 — Web shell

**Owns:** `web/next.config.ts`, `web/lib/{api,types,i18n}.ts`, `web/app/layout.tsx`, `web/app/providers.tsx`, `web/app/(kiosk)/layout.tsx`, `web/components/KioskShell.tsx`.

### C11.1 `next.config.ts`

```ts
import type { NextConfig } from "next";
const config: NextConfig = {
  async rewrites() { return [{ source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" }]; },
  async headers() { return [{ source: "/:path*", headers: [{ key: "Referrer-Policy", value: "no-referrer" }] }]; },
  allowedDevOrigins: ["*.trycloudflare.com"],
};
export default config;
```

### C11.2 `lib/api.ts`

```ts
export class ApiError extends Error { constructor(public status: number, public code: string) { super(code); } }
export async function api<T>(path: string, init?: RequestInit & { json?: unknown }): Promise<T>
// fetch("/api" + path) with credentials "same-origin"; JSON body + header when json is given;
// non-2xx → throw ApiError(status, body.detail ?? "error"); 204 → undefined
```

Kiosk pages map `no_session` → hard reset (C11.5) and `consent_required` → `/consent`.

### C11.3 `lib/types.ts`

Hand-mirrored from `schemas.py` (§C1.5). Any change to `schemas.py` updates this file in the same commit.

### C11.4 `lib/i18n.ts`, `providers.tsx`

- `const dict = { en: {...}, hi: {...} }` for all fixed UI strings (≈ 70 keys); `t(key)`.
- `UiContext`: `lang`, `setLang`, `textSize` (`normal` | `large`, applied as a class on `<html>`); stored in `sessionStorage` (try/catch), cleared on logout.
- Analytics `reason` strings stay English; the mentor explains them in the chosen language.

### C11.5 `KioskShell` (used by `app/(kiosk)/layout.tsx`)

- **Idle timer:** reset on `pointerdown` / `keydown`; at 100 s show a 20 s countdown modal; at zero → hard reset.
- **Hard reset** (idle, End session, `no_session`): `POST /api/auth/logout` (ignore errors), `speechSynthesis.cancel()`, clear `sessionStorage`, then `window.location.replace("/")`, a full page load that drops all React state.
- **Back-button safety:** `window.addEventListener("pageshow", e => { if (e.persisted) location.reload(); })` so a page restored from the browser's back-forward cache never shows the previous student's data.
- **Health:** poll `/api/healthz` every 30 s; on failure or `db:false` show a full-screen "Kiosk temporarily unavailable, please visit the help desk" overlay.
- **Header** (after login): student name, language toggle, text-size toggle (A / A+), "Talk to a human mentor" (→ `POST /api/requests {kind:"referral"}` → modal with counsellor desk text), "End session" (→ `/end`).

---

## C12 — Kiosk screens

**Owns:** `web/app/(kiosk)/{page,login,consent,profile,mentor,roadmap,report,end}/`.

| Route | Calls | Behaviour |
|---|---|---|
| `/` | – | Welcome, language buttons (English / हिन्दी), text-size toggle, "Start". No data. |
| `/login` | `POST /auth/login` | Roll no field + on-screen numeric PIN pad (masked). Errors: `bad_credentials`, `locked`. |
| `/consent` | `POST /consent` | Notice `v1` (see C12.1). Accept → `/profile`; Decline → hard reset. |
| `/profile` | `GET /me/profile`, `GET /roadmaps`, `DELETE /me/plans` | Subject cards (pct, attendance, flags with reasons and n). "Records as of {as_of}, imported {imported_at}". Upcoming assessments. Skill coverage by role (labelled "indicator from your marks, not a prediction"). "Report a data error" → `POST /requests {kind:"correction", subject_code, note}`. "Your plans" with Open / Report links and "Delete my plans" (confirm dialog). "Talk to mentor" → `/mentor`. |
| `/mentor` | `POST /mentor/chat`, `POST /stt` | On mount: chat with `[]` → opening message. Message list, text input, hold-to-talk mic (C13), mute toggle. Every reply is shown (captions) and spoken. "Create my plan" → `/roadmap/new` (messages passed via `sessionStorage`). |
| `/roadmap/new` | `GET /me/profile`, `POST /roadmaps/draft`, `POST /roadmaps` | Form: subject (default first flagged), days (14), minutes/day (60), review date (`<input type="date">`, default today + days). "Generate" → spinner (≤ 15 s) → editable table (edit activity text, delete row) with each task's reason, effort, resource and check → "Save plan" → `/roadmap/{id}`. "Regenerate" allowed. |
| `/roadmap/[id]` | `GET /roadmaps/{id}`, `POST /roadmaps/{id}/share` | Plan with real dates (`Day 1–3 · 11–13 Nov`), due dates, checkpoints highlighted. "Send to my phone" → `QRCodeSVG` + 10 min countdown + "New code". "Print / Save PDF" → `window.print()`. |
| `/report/[id]` | `GET /roadmaps/{id}/report` | Two visually separate blocks: **Verified results** (`TopicChange` table, subject before/after) and **Your reported activity** (done / partial / pending, overdue list). Remaining gaps; next step ("Create a new plan"); "Talk to a human mentor" prompt when gaps remain; caveat; Print. |
| `/end` | `POST /feedback` | "Was this session useful?" 1–5 buttons (optional) → then hard reset. Auto hard reset after 15 s. |

Print CSS: header, buttons and QR hidden with Tailwind `print:hidden`; A4 margins via `@page`.

### C12.1 Consent notice v1 (en + hi)

- **What we use:** your programme, semester, subjects, marks, attendance and assessment dates from university records.
- **Why:** to show where you could focus and to build a study plan you agree to.
- **AI processing:** your messages, and your voice when you use the mic, are sent to an external AI service to produce replies. Your name and roll number are not sent. Audio and chat are not stored.
- **Who can see it:** only you. Staff see anonymous totals, plus requests you choose to send.
- **How long:** this session ends when you log out or after 2 minutes of inactivity. Saved plans are kept until you delete them (Profile → Delete my plans) or the semester ends.
- **No camera, no recording.** Prefer not to use the kiosk? Visit the help desk.

**DoD:** the full journey for `CS23001` works with touch/mouse only and with keyboard only; Back after logout never shows the previous student's data.

---

## C13 — Voice

**Owns:** `web/lib/voice.ts`.

```ts
export function useRecorder(onText: (t: string) => void, lang: "en" | "hi"): {
  recording: boolean; busy: boolean; error: string | null; start(): void; stop(): void;
}
export function speak(text: string, lang: "en" | "hi"): void
export function stopSpeaking(): void
```

- **Recording:** `getUserMedia({ audio: true })` on first use; `MediaRecorder` with `audio/webm;codecs=opus` if `isTypeSupported`, else browser default; hold-to-talk (`pointerdown` start; `pointerup` / `pointerleave` stop); hard stop at 30 s; stop mic tracks after each recording so the browser's mic indicator turns off.
- **Upload:** `FormData{file: blob "speech.webm", lang}` → `POST /api/stt` → `onText(text)`. The text goes into the input box for the student to edit and send (no auto-send). `stt_unavailable` → "Please type instead".
- **TTS:** `speechSynthesis.cancel()` then speak; `utterance.lang = "en-IN" | "hi-IN"`; pick a voice whose `lang` starts with `en` / `hi` after `voiceschanged`; if no Hindi voice exists, stay silent (captions remain). Starting a recording cancels speech.

**DoD:** English and Hindi round trip on the demo laptop; mic indicator visible only while recording.

---

## C14 — Phone view

**Owns:** `web/app/r/[token]/page.tsx`, `web/app/m/page.tsx`. No `KioskShell`.

| Route | Behaviour |
|---|---|
| `/r/[token]` | `GET /api/r/{token}` → on success `router.replace("/m")` (the token URL leaves history). On 410 → try `GET /api/phone/roadmap`; success → `/m`; else "This link was already used or has expired. Scan a new code at the kiosk." |
| `/m` | Tabs **Plan** and **Progress**. Plan: subject, summary, review date with days left, tasks with dates, due badges (overdue in red), reason, resource link (new tab), check text, three-state control (pending / partial / done) → optimistic `PATCH /api/phone/tasks/{id}`, revert on error. Progress: `GET /api/phone/report`, same two-block layout as the kiosk. "Save as PDF" → `window.print()`. Footer: "Ticks are your own record; reports show them separately from your marks." 401 → expired message. |

**DoD:** scan the QR on a real phone through the tunnel, mark a task done, see it in the kiosk report's self-reported block, and save the plan as PDF on the phone.

---

## C15 — Dev and demo tooling

**Owns:** `docker-compose.yml`, `.env.example`, `scripts/dev.sh`, `README.md`.

- `docker-compose.yml`: `postgres:16`, user / password / db `emon`, port 5432, named volume.
- `.env.example`: every key from C1.1 with placeholders.
- `scripts/dev.sh`: start compose → start `cloudflared tunnel --url http://localhost:3000` in the background and read its log until an `https://*.trycloudflare.com` URL appears → export `PUBLIC_BASE_URL` → `set -a; . api/.env; set +a` → start API (`uv run fastapi run app/main.py --port 8000`) and web (`npm run build && npm start`) → print the URL → trap Ctrl-C to stop everything.
- Kiosk browser: `google-chrome --kiosk --user-data-dir=$HOME/.emon-kiosk http://localhost:3000`. Grant the microphone once for `localhost:3000` in that profile before the demo; the permission persists.
- `README.md`: setup, demo script (import baseline → journey → phone → import review → report), reset (`TRUNCATE` + re-import).

---

## 1. Requirement traceability (brief → components)

| Brief | Requirement | Component(s) |
|---|---|---|
| §5.1 | Welcome screen | C12 `/` |
| §5.2, §14 | Consent, non-camera authentication | C2, C12 consent |
| §5.3 | Retrieve only permitted fields | C3 `PERMITTED`, C4 |
| §5.4 | Diagnosis that explains why | C4 reasons + n |
| §5.5, §7 | Mentor asks about topics, format, time, interests, goals; facts vs statements | C6 |
| §5.6, §8 | Time-bound plan; reason, effort, resource, check per task; checkpoints; adjustable | C7 |
| §5.7 | One-time / expiring QR, open or download | C7.5, C8, C14 print |
| §5.8–9, §10 | Review, report, escalation | C9, C12 report, C2 requests |
| §6-A | Accessibility, timeout, language | C11 (text size, captions, keyboard), C12, C13 |
| §6-C | Data validation and synchronization | C3.3, `imports` |
| §6-I | Health, aggregates, audit, intervention queue | C10 |
| §9 | Skill gaps and readiness indicator, no promises | C4 readiness, C6 rules 6 and 9 |
| §11 | Mobile view: tasks, resources, completion, deadlines, progress report | C14 |
| §12 | Stack layers | HLD §2.2 |
| §14 | Minimization, access control, session safety, reliability, fairness | C2, C6.2, C11.5, C1 retention |
| §18 | Functional, data accuracy, privacy tests | Tests in each component |
| §19 | Success metrics | C10 metrics, C12 `/end` |
| §20 | Correction requests, data timestamps | C12 profile, C4 `as_of` / `imported_at` |

---

## 2. Build order for parallel agents

```mermaid
flowchart LR
    P0["Phase 0 (serial)<br/>C1 core + schemas.py + conftest<br/>C11 shell + types.ts<br/>C15 tooling<br/>stub routers"] --> A & B & C & D & E
    A["C3 connector + seed"] --> F
    B["C4 analytics"] --> F
    C["C5 LLM gateway"] --> F
    D["C2 auth"] --> F
    E["C13 voice + C12 static screens"] --> F
    F["Phase 2<br/>C6 mentor · C7 roadmap/share · C8 phone<br/>C12 data wiring · C14"] --> G["Phase 3<br/>C9 report · C10 admin<br/>E2E demo run"]
```

| Phase | Work | Parallel? | Gate to next phase |
|---|---|---|---|
| 0 | C1, C11 skeleton, `schemas.py` ↔ `types.ts`, stub routers, conftest, C15 | No (contract) | App boots, `/docs` shows all routes, web proxies `/api/healthz`, the tunnel reaches a phone |
| 1 | C2, C3, C4, C5, C13 + static C12 screens | Yes: each agent owns only its files | Each component's tests pass |
| 2 | C6, C7 + C8, C12 wiring, C14 | Yes: C6 / C7+C8 / web | Journey up to QR works on a phone |
| 3 | C9, C10, E2E | Yes | Full demo script passes twice in a row |

Rules for agents: touch only owned files; never edit `schemas.py` / `types.ts` without updating both; run `uv run pytest` before reporting done.
