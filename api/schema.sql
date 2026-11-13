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
  name text NOT NULL,
  kind text NOT NULL DEFAULT 'course' CHECK (kind IN ('course','track'))   -- track: non-assessed goal content
);
CREATE TABLE IF NOT EXISTS assessments (
  id serial PRIMARY KEY,
  student_id int NOT NULL REFERENCES students ON DELETE CASCADE,
  subject_id int NOT NULL REFERENCES subjects,
  topic text NOT NULL,                          -- 'All' for whole-syllabus tests
  kind text NOT NULL CHECK (kind IN ('quiz','internal','assignment','lab')),
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
CREATE TABLE IF NOT EXISTS backlogs (
  student_id int NOT NULL REFERENCES students ON DELETE CASCADE,
  subject_id int NOT NULL REFERENCES subjects,
  from_semester int NOT NULL CHECK (from_semester >= 1),
  status text NOT NULL CHECK (status IN ('pending','cleared')),
  batch text NOT NULL CHECK (batch IN ('baseline','review')),
  PRIMARY KEY (student_id, subject_id, batch)
);
CREATE TABLE IF NOT EXISTS topic_prereqs (
  subject_id int NOT NULL REFERENCES subjects,
  topic text NOT NULL,
  prereq_subject_id int NOT NULL REFERENCES subjects,
  prereq_topic text NOT NULL,
  PRIMARY KEY (subject_id, topic, prereq_subject_id, prereq_topic)
);
CREATE TABLE IF NOT EXISTS resources (
  id serial PRIMARY KEY,
  subject_id int NOT NULL REFERENCES subjects,
  topic text NOT NULL,
  title text NOT NULL,
  url text UNIQUE NOT NULL,
  kind text NOT NULL CHECK (kind IN ('video','article','practice','course')),      -- the RB 7 "format"
  level text NOT NULL DEFAULT 'beginner' CHECK (level IN ('foundation','beginner','intermediate','advanced')),
  lang text NOT NULL DEFAULT 'en' CHECK (lang IN ('en','hi')),
  minutes int NOT NULL DEFAULT 30 CHECK (minutes BETWEEN 5 AND 600),               -- typical session length
  goals text[] NOT NULL DEFAULT '{}',                                               -- empty = suits every goal
  link_ok boolean NOT NULL DEFAULT true,
  checked_on date
);
CREATE TABLE IF NOT EXISTS questions (
  id serial PRIMARY KEY,
  subject_id int NOT NULL REFERENCES subjects,
  topic text NOT NULL,
  tier text NOT NULL CHECK (tier IN ('basic','standard','multi')),
  stem text NOT NULL,
  options jsonb NOT NULL,                       -- exactly 4 strings
  answer int NOT NULL CHECK (answer BETWEEN 0 AND 3),
  explanation text NOT NULL,
  reviewed_by text NOT NULL,
  UNIQUE (subject_id, topic, stem)
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
  mode text CHECK (mode IN ('personal','general')),   -- kiosk sessions, set at consent
  role text CHECK (role IN ('admin','counsellor')),   -- staff sessions
  expires_at timestamptz NOT NULL
);
CREATE TABLE IF NOT EXISTS roadmaps (
  id serial PRIMARY KEY,
  student_id int NOT NULL REFERENCES students ON DELETE CASCADE,
  goal text NOT NULL DEFAULT 'semester' CHECK (goal IN ('semester','backlog','gate','upsc','placement','higher_studies')),
  subject_id int NOT NULL REFERENCES subjects,
  version int NOT NULL,
  summary text NOT NULL,
  evidence jsonb NOT NULL,                      -- baseline snapshot, see C7.6
  levels jsonb NOT NULL DEFAULT '{}',           -- {topic: TopicLevel} used for this plan
  days int NOT NULL,
  daily_minutes int NOT NULL,
  start_on date NOT NULL,
  review_on date NOT NULL,
  target_date date,                             -- exam / deadline the goal aims at
  status text NOT NULL DEFAULT 'active' CHECK (status IN ('active','superseded')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (student_id, goal, subject_id, version)
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
CREATE TABLE IF NOT EXISTS diagnostics (
  id serial PRIMARY KEY,
  student_id int NOT NULL REFERENCES students ON DELETE CASCADE,
  subject_id int NOT NULL REFERENCES subjects,
  topic text NOT NULL,
  purpose text NOT NULL CHECK (purpose IN ('level','review')),
  roadmap_id int REFERENCES roadmaps ON DELETE SET NULL,
  question_ids int[] NOT NULL,                  -- display order
  started_at timestamptz NOT NULL DEFAULT now(),
  submitted_at timestamptz,
  answers jsonb,                                -- list[int|null], aligned with question_ids
  basic int, standard int, multi int, correct int, total int, seconds int,
  level text CHECK (level IN ('foundation','beginner','intermediate','advanced'))
);
CREATE TABLE IF NOT EXISTS reviews (
  id serial PRIMARY KEY,
  roadmap_id int NOT NULL REFERENCES roadmaps ON DELETE CASCADE,
  at timestamptz NOT NULL DEFAULT now(),
  confidence int CHECK (confidence BETWEEN 1 AND 3),
  plan_fit int CHECK (plan_fit BETWEEN 1 AND 5)
);
CREATE TABLE IF NOT EXISTS requests (            -- human-mentor referrals and data-correction requests
  id serial PRIMARY KEY,
  student_id int NOT NULL REFERENCES students ON DELETE CASCADE,
  category text NOT NULL CHECK (category IN ('academic','wellbeing','correction')),   -- team = ROUTING[category]
  subject_code text,
  note text,                                    -- wellbeing: only when the student ticked "share"
  status text NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
  created_at timestamptz NOT NULL DEFAULT now(),
  closed_at timestamptz
);
CREATE TABLE IF NOT EXISTS feedback (            -- anonymous post-session rating (brief §19)
  id serial PRIMARY KEY,
  rating int NOT NULL CHECK (rating BETWEEN 1 AND 5),
  comment text CHECK (length(comment) <= 300),  -- RB 16 qualitative comments; still no student id
  at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS audit_log (
  id bigserial PRIMARY KEY,
  at timestamptz NOT NULL DEFAULT now(),
  actor text NOT NULL,                          -- 'student:12' | 'phone:12' | 'staff' | 'system'
  action text NOT NULL,
  target text
);
