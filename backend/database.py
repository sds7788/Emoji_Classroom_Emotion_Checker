"""SQLite repository for the classroom emotion checker."""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt


EMOTIONS = {
    "happy": ("😊", "开心"),
    "confused": ("😕", "困惑"),
    "bored": ("😐", "无聊"),
    "sad": ("😔", "低落"),
    "focused": ("🤔", "专注"),
    "excited": ("🤩", "兴奋"),
}


class Repository:
    def __init__(self, path: str, seed_demo_data: bool = True):
        self.path = path
        if path != ":memory:":
            Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()
        if seed_demo_data:
            self.seed_demo_data()

    def connect(self):
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        return connection

    @contextmanager
    def connection(self):
        connection = self.connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def init_schema(self):
        schema_path = Path(__file__).resolve().parents[1] / "database_setup.sql"
        schema = schema_path.read_text(encoding="utf-8")
        with self.connection() as connection:
            connection.executescript(schema)

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @staticmethod
    def as_dict(row):
        return dict(row) if row is not None else None

    def one(self, sql, params=()):
        with self.connection() as connection:
            row = connection.execute(sql, params).fetchone()
            return self.as_dict(row)

    def all(self, sql, params=()):
        with self.connection() as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def execute(self, sql, params=()):
        with self.connection() as connection:
            cursor = connection.execute(sql, params)
            return cursor.lastrowid, cursor.rowcount

    def seed_demo_data(self):
        if self.one("SELECT id FROM users LIMIT 1"):
            return
        now = datetime.now(timezone.utc)
        created = now.isoformat(timespec="seconds")
        accounts = [
            ("admin", "admin12345", "admin", "系统管理员"),
            ("teacher", "teacher12345", "teacher", "林老师"),
            ("student", "student12345", "student", "陈同学"),
        ]
        with self.connection() as connection:
            user_ids = {}
            for username, password, role, name in accounts:
                password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=10))
                cursor = connection.execute(
                    "INSERT INTO users (username, password_hash, role, full_name, created_at) VALUES (?, ?, ?, ?, ?)",
                    (username, password_hash, role, name, created),
                )
                user_ids[username] = cursor.lastrowid

            cursor = connection.execute(
                "INSERT INTO courses (course_code, name, teacher_id, created_at) VALUES (?, ?, ?, ?)",
                ("SE-101", "软件工程实践", user_ids["teacher"], created),
            )
            course_id = cursor.lastrowid
            live_start = (now - timedelta(minutes=25)).isoformat(timespec="seconds")
            live_end = (now + timedelta(minutes=35)).isoformat(timespec="seconds")
            live_session = connection.execute(
                "INSERT INTO class_sessions (course_id, class_name, room, starts_at, ends_at, status, created_at) VALUES (?, ?, ?, ?, ?, 'active', ?)",
                (course_id, "2024级软件工程1班", "教学楼 A203", live_start, live_end, created),
            ).lastrowid
            yesterday_start = (now - timedelta(days=1, hours=2)).isoformat(timespec="seconds")
            yesterday_end = (now - timedelta(days=1, hours=1)).isoformat(timespec="seconds")
            previous_session = connection.execute(
                "INSERT INTO class_sessions (course_id, class_name, room, starts_at, ends_at, status, created_at) VALUES (?, ?, ?, ?, ?, 'ended', ?)",
                (course_id, "2024级软件工程1班", "教学楼 A203", yesterday_start, yesterday_end, created),
            ).lastrowid

            for session_id in (live_session, previous_session):
                connection.execute(
                    "INSERT INTO schedule_users (session_id, user_id, scheduled_at) VALUES (?, ?, ?)",
                    (session_id, user_ids["student"], created),
                )
            samples = [
                ("happy", -19), ("focused", -16), ("confused", -13),
                ("happy", -10), ("focused", -7), ("excited", -4),
                ("confused", -2),
            ]
            for emoji_type, minutes_ago in samples:
                recorded_at = (now + timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")
                connection.execute(
                    "INSERT INTO emoji_records (user_id, session_id, emoji_type, recorded_at, source) VALUES (?, ?, ?, ?, 'MANUAL')",
                    (user_ids["student"], live_session, emoji_type, recorded_at),
                )
            connection.execute(
                "INSERT INTO emoji_records (user_id, session_id, emoji_type, recorded_at, source) VALUES (?, ?, 'happy', ?, 'MANUAL')",
                (user_ids["student"], previous_session, (now - timedelta(days=1, hours=1, minutes=30)).isoformat(timespec="seconds")),
            )

    def get_user_by_username(self, username):
        return self.one("SELECT * FROM users WHERE username = ?", (username,))

    def get_user_by_id(self, user_id):
        return self.one(
            "SELECT id, username, role, full_name, email, status, token_version, created_at FROM users WHERE id = ?",
            (user_id,),
        )

    def create_user(self, username, password_hash, role, full_name, email):
        return self.execute(
            "INSERT INTO users (username, password_hash, role, full_name, email, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (username, password_hash, role, full_name, email, self.now()),
        )[0]

    def update_password(self, user_id, password_hash):
        return self.execute(
            "UPDATE users SET password_hash = ?, token_version = token_version + 1 WHERE id = ?",
            (password_hash, user_id),
        )[1]

    def mark_login(self, user_id):
        self.execute("UPDATE users SET last_login = ? WHERE id = ?", (self.now(), user_id))

    def audit(self, actor_id, action, target_type, target_id=None, detail=""):
        self.execute(
            "INSERT INTO audit_logs (actor_id, action, target_type, target_id, detail, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (actor_id, action, target_type, str(target_id) if target_id is not None else None, detail, self.now()),
        )
