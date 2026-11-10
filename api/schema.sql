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
