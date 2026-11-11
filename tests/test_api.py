import csv
import io
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
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

    def test_privileged_registration_uses_role_bound_single_use_invitations(self):
        admin_headers = self.auth(self.admin_token)
        self.assertEqual(self.client.post("/api/admin/invitations", headers=self.auth(self.student_token),
                                         json={"role": "admin"}).status_code, 403)
        for role in ("teacher", "admin"):
            with self.subTest(role=role):
                payload = {"username": f"invited_{role}", "password": "Invitedpass123", "role": role}
                self.assertEqual(self.client.post("/api/auth/register", json=payload).status_code, 403)
                issued = self.client.post("/api/admin/invitations", headers=admin_headers,
                                          json={"role": role, "expires_in_hours": 24})
                self.assertEqual(issued.status_code, 201, issued.get_json())
                self.assertEqual(issued.headers["Cache-Control"], "no-store")
                invitation = issued.get_json()["data"]
                stored = self.db.one("SELECT * FROM registration_invitations WHERE id = ?", (invitation["id"],))
                self.assertNotEqual(stored["code_hash"], invitation["code"])
                self.assertIsNone(stored["used_by"])
                wrong_role = "admin" if role == "teacher" else "teacher"
                denied = self.client.post("/api/auth/register", json={**payload, "role": wrong_role, "registration_code": invitation["code"]})
                self.assertEqual(denied.status_code, 403)
                # A failed duplicate username must not consume a valid invitation.
                duplicate = self.client.post("/api/auth/register", json={**payload, "username": "student", "registration_code": invitation["code"]})
                self.assertEqual(duplicate.status_code, 409)
                created = self.client.post("/api/auth/register", json={**payload, "registration_code": invitation["code"]})
                self.assertEqual(created.status_code, 201, created.get_json())
                self.assertEqual(created.get_json()["data"]["user"]["role"], role)
                replay = self.client.post("/api/auth/register", json={**payload, "username": f"replay_{role}", "registration_code": invitation["code"]})
                self.assertEqual(replay.status_code, 403)
                logs = self.db.all("SELECT detail FROM audit_logs")
                self.assertFalse(any(invitation["code"] in row["detail"] for row in logs))
                token = created.get_json()["data"]["access_token"]
                expected = 200 if role == "admin" else 403
                self.assertEqual(self.client.get("/api/admin/users", headers=self.auth(token)).status_code, expected)

    def test_expired_invitation_and_invalid_registration_input_are_rejected(self):
        headers = self.auth(self.admin_token)
        self.assertEqual(self.client.post("/api/admin/invitations", headers=headers, json={"role": "student"}).status_code, 400)
        self.assertEqual(self.client.post("/api/admin/invitations", headers=headers, json={"role": "teacher", "expires_in_hours": 0}).status_code, 400)
        issued = self.client.post("/api/admin/invitations", headers=headers, json={"role": "teacher"}).get_json()["data"]
        self.db.execute("UPDATE registration_invitations SET expires_at = ? WHERE id = ?",
                        ((datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(timespec="seconds"), issued["id"]))
        payload = {"username": "expired_teacher", "password": "Expiredpass123", "role": "teacher", "registration_code": issued["code"]}
        self.assertEqual(self.client.post("/api/auth/register", json=payload).status_code, 403)
        self.assertEqual(self.client.post("/api/auth/register", json={**payload, "role": []}).status_code, 400)
        self.assertIsNone(self.db.get_user_by_username("expired_teacher"))

    def test_first_admin_bootstrap_is_atomic_and_stays_closed_after_role_changes(self):
        app = create_app({
            "TESTING": True, "SECRET_KEY": "bootstrap-test-secret-that-is-long-enough",
            "DATABASE_PATH": str(Path(self.temp_dir.name) / "bootstrap.db"),
            "SEED_DEMO_DATA": False, "ADMIN_BOOTSTRAP_TOKEN": "local-test-initialization-key",
        })
        client = app.test_client()
        options = client.get("/api/auth/registration-options").get_json()["data"]
        self.assertTrue(options["admin_bootstrap_available"])
        payload = {"username": "firstadmin", "password": "Firstadmin123", "role": "admin"}
        self.assertEqual(client.post("/api/auth/register", json={**payload, "registration_code": "wrong"}).status_code, 403)
        def create_first_admin(index):
            with app.test_client() as concurrent_client:
                return concurrent_client.post("/api/auth/register", json={
                    **payload, "username": f"firstadmin{index}", "registration_code": "local-test-initialization-key",
                }).status_code
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(create_first_admin, range(2))), [201, 403])
        db = app.extensions["emotion_repository"]
        self.assertEqual(db.one("SELECT COUNT(*) AS total FROM users WHERE role = 'admin'")["total"], 1)
        self.assertFalse(client.get("/api/auth/registration-options").get_json()["data"]["admin_bootstrap_available"])
        db.execute("UPDATE users SET role = 'student' WHERE role = 'admin'")
        self.assertFalse(client.get("/api/auth/registration-options").get_json()["data"]["admin_bootstrap_available"])
        self.assertEqual(client.post("/api/auth/register", json={**payload, "registration_code": "local-test-initialization-key"}).status_code, 403)

    def test_admin_multidimensional_statistics_and_realtime_keep_teacher_scope(self):
        headers = self.auth(self.admin_token)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        teacher = self.db.get_user_by_username("teacher")
        course = self.client.post("/api/admin/courses", headers=headers, json={
            "course_code": "STATS-2", "name": "统计验收课程", "teacher_id": teacher["id"],
        }).get_json()["data"]["id"]
        session = self.client.post("/api/admin/sessions", headers=headers, json={
            "course_id": course, "class_name": "统计验收班", "status": "active",
            "starts_at": (now - timedelta(minutes=10)).isoformat(), "ends_at": (now + timedelta(hours=1)).isoformat(),
        }).get_json()["data"]["id"]
        # The record is exactly on the filter boundary, expressed in a different timezone.
        self.db.execute("INSERT INTO emoji_records (user_id, session_id, emoji_type, recorded_at, source) VALUES (?, ?, 'happy', ?, 'MANUAL')",
                        (self.db.get_user_by_username("student")["id"], session, now.isoformat()))
        query = {"course_id": course, "class_name": "统计验收班", "from": now.astimezone(timezone(timedelta(hours=8))).isoformat(),
                 "to": (now + timedelta(minutes=1)).isoformat()}
        result = self.client.get("/api/admin/statistics", headers=headers, query_string=query)
        self.assertEqual(result.status_code, 200, result.get_json())
        stats = result.get_json()["data"]
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["by_course"], [{"course_id": course, "course_name": "统计验收课程", "total": 1}])
        self.assertEqual(stats["by_class"], [{"class_name": "统计验收班", "total": 1}])
        self.assertEqual(stats["daily_trend"], [{"day": now.strftime("%Y-%m-%d"), "emoji_type": "happy", "count": 1}])
        other_class = self.client.get("/api/admin/statistics", headers=headers, query_string={**query, "class_name": "不匹配班级"}).get_json()["data"]
        self.assertEqual(other_class["total"], 0)
        self.assertEqual(other_class["by_course"], [])
        self.assertEqual(self.client.get("/api/admin/statistics", headers=headers, query_string={**query, "from": "invalid"}).status_code, 400)
        self.assertEqual(self.client.get("/api/admin/statistics", headers=headers, query_string={**query, "from": query["to"], "to": now.isoformat()}).status_code, 400)
        live = self.client.get(f"/api/admin/dashboard/realtime?sessionId={session}", headers=headers)
        self.assertEqual(live.status_code, 200)
        self.assertEqual(live.get_json()["data"]["total_last_hour"], 1)
        self.assertEqual(self.client.get(f"/api/admin/dashboard/realtime?sessionId={session}", headers=self.auth(self.student_token)).status_code, 403)
        # A different teacher can see neither the chart groups nor the live classroom.
        self.db.execute("UPDATE users SET role = 'teacher' WHERE username = 'student'")
        other_token = self.login("student", "student12345")
        other_stats = self.client.get("/api/admin/statistics", headers=self.auth(other_token), query_string=query).get_json()["data"]
        self.assertEqual(other_stats["by_class"], [])
        self.assertEqual(self.client.get(f"/api/admin/dashboard/realtime?sessionId={session}", headers=self.auth(other_token)).status_code, 403)

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
