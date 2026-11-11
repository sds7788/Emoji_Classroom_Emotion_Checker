-- Emoji Classroom Emotion Checker SQLite schema
-- Applied automatically by backend.database.Repository on first startup.
-- This script intentionally contains no DROP statements and no personal image/video storage.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash BLOB NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('student', 'teacher', 'admin')),
    full_name TEXT NOT NULL,
    email TEXT UNIQUE,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    token_version INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_login TEXT
);

CREATE TABLE IF NOT EXISTS courses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    teacher_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS class_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    class_name TEXT NOT NULL,
    room TEXT NOT NULL DEFAULT '',
    starts_at TEXT NOT NULL,
    ends_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled', 'active', 'ended')),
    created_at TEXT NOT NULL,
    CHECK (ends_at > starts_at)
);

CREATE TABLE IF NOT EXISTS schedule_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES class_sessions(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    scheduled_at TEXT NOT NULL,
    UNIQUE (session_id, user_id)
);

CREATE TABLE IF NOT EXISTS emoji_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    session_id INTEGER NOT NULL REFERENCES class_sessions(id) ON DELETE CASCADE,
    emoji_type TEXT NOT NULL CHECK (emoji_type IN ('happy', 'confused', 'bored', 'sad', 'focused', 'excited')),
    recorded_at TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('MANUAL', 'AI')),
    confidence REAL,
    device_id TEXT,
    CHECK (
        (source = 'MANUAL' AND user_id IS NOT NULL AND confidence IS NULL)
        OR
        (source = 'AI' AND user_id IS NULL AND confidence IS NOT NULL AND confidence >= 0 AND confidence <= 1)
    )
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_id TEXT,
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_records_session_time ON emoji_records(session_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_records_user_time ON emoji_records(user_id, recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_course_time ON class_sessions(course_id, starts_at DESC);
CREATE INDEX IF NOT EXISTS idx_schedules_user ON schedule_users(user_id, session_id);
