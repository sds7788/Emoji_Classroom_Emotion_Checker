import csv
import io
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from backend.app import create_app
from backend.ai_service import analyze_frame


class EmojiCheckerApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-secret-key-that-is-not-used-outside-tests",
            "DATABASE_PATH": str(Path(self.temp_dir.name) / "test.db"),
            "SEED_DEMO_DATA": True,
            "AI_SERVICE_TOKEN": "test-ai-service-token",
            "AI_CONFIDENCE_THRESHOLD": 0.6,
        })
        self.client = self.app.test_client()
        self.db = self.app.extensions["emotion_repository"]
        self.admin_token = self.login("admin", "admin12345")
        self.teacher_token = self.login("teacher", "teacher12345")
        self.student_token = self.login("student", "student12345")

    def tearDown(self):
        self.temp_dir.cleanup()

    def login(self, username, password):
        result = self.client.post("/api/auth/login", json={"username": username, "password": password})
        self.assertEqual(result.status_code, 200, result.get_json())
        return result.get_json()["data"]["access_token"]

    @staticmethod
    def auth(token):
        return {"Authorization": f"Bearer {token}"}

    def test_demo_login_manual_checkin_history_and_statistics(self):
        sessions = self.client.get("/api/sessions", headers=self.auth(self.student_token)).get_json()["data"]
        active_session = next(session for session in sessions if session["status"] == "active")
        result = self.client.post("/api/emoji", headers=self.auth(self.student_token), json={
            "session_id": active_session["id"], "emoji_type": "focused",
        })
        self.assertEqual(result.status_code, 201, result.get_json())
        history = self.client.get("/api/emoji/history", headers=self.auth(self.student_token)).get_json()["data"]
        self.assertEqual(history[0]["emoji_type"], "focused")
        self.assertEqual(history[0]["source"], "MANUAL")
        stats = self.client.get("/api/emoji/statistics", headers=self.auth(self.student_token)).get_json()["data"]
        self.assertEqual(stats["total"], len(history))

    def test_teacher_scope_and_admin_rbac(self):
        admin_headers = self.auth(self.admin_token)
        other_teacher = self.client.post("/api/auth/register", json={
            "username": "newstudent", "password": "Newstudent123", "full_name": "新教师",
        }).get_json()["data"]["user"]["id"]
        self.client.put(f"/api/admin/users/{other_teacher}", headers=admin_headers, json={"role": "teacher"})
        course = self.client.post("/api/admin/courses", headers=admin_headers, json={
            "course_code": "OTHER-1", "name": "其他教师课程", "teacher_id": other_teacher,
        })
        self.assertEqual(course.status_code, 201, course.get_json())
        starts = datetime.now(timezone.utc) - timedelta(minutes=5)
        ends = datetime.now(timezone.utc) + timedelta(minutes=50)
        session = self.client.post("/api/admin/sessions", headers=admin_headers, json={
            "course_id": course.get_json()["data"]["id"], "class_name": "另一个班",
            "starts_at": starts.isoformat(), "ends_at": ends.isoformat(), "status": "active",
        }).get_json()["data"]["id"]
        denied = self.client.get(f"/api/admin/dashboard/realtime?sessionId={session}", headers=self.auth(self.teacher_token))
        self.assertEqual(denied.status_code, 403)
        invalid_filter = self.client.get("/api/emoji/history?session_id=not-a-number", headers=self.auth(self.teacher_token))
        self.assertEqual(invalid_filter.status_code, 400)
        student_admin = self.client.get("/api/admin/users", headers=self.auth(self.student_token))
        self.assertEqual(student_admin.status_code, 403)

    def test_admin_schedule_and_student_session_access(self):
        admin_headers = self.auth(self.admin_token)
        sessions = self.client.get("/api/admin/sessions", headers=admin_headers).get_json()["data"]
        session_id = next(session["id"] for session in sessions if session["status"] == "active")
        student = self.db.get_user_by_username("student")
        scheduled = self.client.post(f"/api/admin/sessions/{session_id}/schedule", headers=admin_headers,
                                     json={"user_ids": [student["id"]]})
        self.assertEqual(scheduled.status_code, 200, scheduled.get_json())
        roster = self.client.get(f"/api/admin/sessions/{session_id}/schedule", headers=admin_headers)
        self.assertEqual(roster.status_code, 200, roster.get_json())
        self.assertEqual([item["id"] for item in roster.get_json()["data"]], [student["id"]])
        student_sessions = self.client.get("/api/sessions", headers=self.auth(self.student_token)).get_json()["data"]
        self.assertTrue(any(item["id"] == session_id for item in student_sessions))
        checkin = self.client.post("/api/emoji", headers=self.auth(self.student_token), json={
            "session_id": session_id, "emoji_type": "happy",
        })
        self.assertEqual(checkin.status_code, 201)

    def test_ai_token_threshold_privacy_and_export_formula_safety(self):
        admin_headers = self.auth(self.admin_token)
        session = next(item for item in self.client.get("/api/admin/sessions", headers=admin_headers).get_json()["data"] if item["status"] == "active")
        wrong_token = self.client.post("/api/ai/emoji-results", headers={"X-AI-Service-Token": "wrong"}, json={
            "session_id": session["id"], "emoji_type": "happy", "confidence": 0.9,
        })
        self.assertEqual(wrong_token.status_code, 401)
        headers = {"X-AI-Service-Token": "test-ai-service-token"}
        dropped = self.client.post("/api/ai/emoji-results", headers=headers, json={
            "session_id": session["id"], "emoji_type": "sad", "confidence": 0.59,
        })
        self.assertEqual(dropped.status_code, 200)
        self.assertFalse(dropped.get_json()["data"]["accepted"])
        stored = self.client.post("/api/ai/emoji-results", headers=headers, json={
            "session_id": session["id"], "emoji_type": "focused", "confidence": 0.91,
        })
        self.assertEqual(stored.status_code, 201, stored.get_json())
        ended_session = next(item for item in self.client.get("/api/admin/sessions", headers=admin_headers).get_json()["data"] if item["status"] == "ended")
        closed = self.client.post("/api/ai/emoji-results", headers=headers, json={
            "session_id": ended_session["id"], "emoji_type": "happy", "confidence": 0.95,
        })
        self.assertEqual(closed.status_code, 409)
        recorded_from = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        recorded_to = (datetime.now(timezone.utc) + timedelta(minutes=1)).isoformat()
        query = {
            "course_id": session["course_id"], "class_name": session["class_name"],
            "session_id": session["id"], "source": "AI", "from": recorded_from, "to": recorded_to,
        }
        filtered = self.client.get("/api/emoji/history", headers=admin_headers, query_string=query)
        self.assertEqual(filtered.status_code, 200, filtered.get_json())
        records = filtered.get_json()["data"]
        ai_record = next(item for item in records if item["id"] == stored.get_json()["data"]["id"])
        self.assertIsNone(ai_record["user_id"])
        self.assertEqual(ai_record["source"], "AI")
        self.assertEqual([item["id"] for item in records], [stored.get_json()["data"]["id"]])

        self.client.post("/api/auth/register", json={
            "username": "exportuser", "password": "exportpass123", "full_name": "=1+1",
        })
        new_student = self.login("exportuser", "exportpass123")
        self.client.post("/api/admin/sessions/%s/schedule" % session["id"], headers=admin_headers,
                         json={"user_ids": [self.db.get_user_by_username("exportuser")["id"]]})
        self.client.post("/api/emoji", headers=self.auth(new_student), json={
            "session_id": session["id"], "emoji_type": "happy",
        })
        export = self.client.get("/api/admin/emoji/export", headers=admin_headers, query_string=query)
        self.assertEqual(export.status_code, 200)
        self.assertIn("text/csv", export.content_type)
        decoded = export.data.decode("utf-8-sig")
        parsed = list(csv.reader(io.StringIO(decoded)))
        self.assertEqual([row for row in parsed[1:] if row[7] == "AI"], [
            [str(stored.get_json()["data"]["id"]), "匿名 AI 汇总", session["course_name"], session["class_name"],
             "focused", "🤔", ai_record["recorded_at"], "AI", "0.91", str(session["id"])],
        ])
        unfiltered_export = self.client.get("/api/admin/emoji/export", headers=admin_headers)
        unfiltered_rows = list(csv.reader(io.StringIO(unfiltered_export.data.decode("utf-8-sig"))))
        self.assertTrue(any(row[1] == "'=1+1" for row in unfiltered_rows))

    def test_password_change_revokes_existing_token(self):
        oversized = self.client.post("/api/auth/login", json={"username": "student", "password": "x" * 100})
        self.assertEqual(oversized.status_code, 401)
        result = self.client.put("/api/auth/password", headers=self.auth(self.student_token), json={
            "old_password": "student12345", "new_password": "studentNew123",
        })
        self.assertEqual(result.status_code, 200, result.get_json())
        stale = self.client.get("/api/users/me", headers=self.auth(self.student_token))
        self.assertEqual(stale.status_code, 401)
        self.login("student", "studentNew123")

    def test_openapi_and_health(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/api/openapi.json").status_code, 200)
        self.assertIn("/api/ai/emoji-results", self.client.get("/api/openapi.json").get_json()["paths"])

    def test_ai_worker_discards_frames_without_detected_faces(self):
        try:
            import cv2  # noqa: F401
            import numpy  # noqa: F401
        except ImportError:
            self.skipTest("Optional camera dependencies are not installed")
        blank_frame = __import__("numpy").zeros((240, 320, 3), dtype="uint8")
        with patch("backend.ai_service.requests.post") as post:
            result = analyze_frame(blank_frame, 1, "token", "http://localhost:5000",
                                   "https://model.example/v1", "api-key", "vision-model", 0.5, "camera-test")
        self.assertEqual(result["reason"], "no_face_detected")
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
