import csv
import io
from datetime import datetime, timedelta, timezone

import jwt

from tests.support import IsolatedAppTest


class SecurityTests(IsolatedAppTest):
    def test_sql_injection_login_and_filter_parameters(self):
        for value in ("admin' --", "' OR '1'='1", "'; DROP TABLE users; --"):
            with self.subTest(value=value):
                result = self.client.post("/api/auth/login", json={"username": value, "password": "password"})
                self.assertEqual(result.status_code, 401)
                history = self.client.get("/api/emoji/history", headers=self.headers(), query_string={"class_name": value})
                self.assertEqual(history.get_json()["data"], [])
                self.assertEqual(self.client.get("/api/emoji/history", headers=self.headers(), query_string={"session_id": value}).status_code, 400)
        self.assertEqual(self.db.one("SELECT COUNT(*) AS n FROM users")["n"], 3)

    def test_weak_passwords_rejected_at_registration_and_change(self):
        for password in ("", "1234567", "中" * 25):
            with self.subTest(password=password):
                result = self.client.post("/api/auth/register", json={"username": "weak_student", "password": password})
                self.assertEqual(result.status_code, 400)
                result = self.client.put("/api/auth/password", headers=self.headers("student"),
                                         json={"old_password": "student12345", "new_password": password})
                self.assertEqual(result.status_code, 400)
        self.assertIsNone(self.db.get_user_by_username("weak_student"))

    def test_export_permissions_and_csv_round_trip(self):
        for role in ("student", "teacher"):
            self.assertEqual(self.client.get("/api/admin/emoji/export", headers=self.headers(role)).status_code, 403)
        for value in ("=HYPERLINK(\"https://example.invalid\")", "\tplain", "\rplain", "\nplain", "有逗号,引号\"和换行\n文本"):
            self.db.execute("UPDATE users SET full_name = ? WHERE username = 'student'", (value,))
            result = self.client.get("/api/admin/emoji/export", headers=self.headers())
            self.assertTrue(result.data.startswith(b"\xef\xbb\xbf"))
            rows = list(csv.reader(io.StringIO(result.data.decode("utf-8-sig"), newline="")))
            expected = "'" + value if value.startswith(("=", "\t", "\r", "\n")) else value
            self.assertEqual(rows[1][1], expected)
            self.assertTrue(all(len(row) == 10 for row in rows))

    def test_expired_mismatched_and_incomplete_tokens_rejected(self):
        invalid = [self.token(exp=datetime.now(timezone.utc) - timedelta(seconds=1)),
                   self.token(username="student", user_id=self.db.get_user_by_username("teacher")["id"]), "not-a-token",
                   jwt.encode({"user_id": 1, "username": "admin", "token_version": 0}, self.app.config["SECRET_KEY"], algorithm="HS256")]
        for token in invalid:
            self.assertEqual(self.client.get("/api/users/me", headers={"Authorization": "Bearer " + token}).status_code, 401)

    def test_nonfinite_ai_confidence_never_enters_database(self):
        before = self.db.one("SELECT COUNT(*) AS n FROM emoji_records")["n"]
        for confidence in ("NaN", "Infinity", -0.1, 1.1):
            result = self.client.post("/api/ai/emoji-results", headers={"X-AI-Service-Token": "test-ai-token"},
                                      json={"session_id": self.session_id, "emoji_type": "happy", "confidence": confidence})
            self.assertEqual(result.status_code, 400)
        self.assertEqual(self.db.one("SELECT COUNT(*) AS n FROM emoji_records")["n"], before)
