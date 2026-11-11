import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from backend import services
from tests.support import IsolatedAppTest


class ServiceTests(IsolatedAppTest):
    def test_schedule_replacement_is_validated_and_deduplicated(self):
        student = self.db.get_user_by_username("student")["id"]
        self.assertEqual(services.schedule_students(self.db, self.session_id, [student, student]), (True, None))
        original = self.db.all("SELECT user_id FROM schedule_users WHERE session_id = ?", (self.session_id,))
        for invalid in ([True], [99999], [self.db.get_user_by_username("teacher")["id"]], "bad"):
            with self.subTest(invalid=invalid):
                self.assertFalse(services.schedule_students(self.db, self.session_id, invalid)[0])
                self.assertEqual(self.db.all("SELECT user_id FROM schedule_users WHERE session_id = ?", (self.session_id,)), original)
        self.assertTrue(services.schedule_students(self.db, self.session_id, [])[0])
        self.assertNotIn(self.session_id, [item["id"] for item in services.list_sessions(self.db, self.db.get_user_by_id(student))])

    def test_scope_history_and_stats_resist_injected_filter_values(self):
        admin = self.db.get_user_by_username("admin")
        for injection in ("' OR 1=1 --", "'; DROP TABLE users; --"):
            with self.subTest(injection=injection):
                self.assertEqual(services.list_history(self.db, admin, {"class_name": injection}), [])
                self.assertEqual(services.statistics(self.db, admin, {"class_name": injection})["total"], 0)
        self.assertEqual(self.db.one("SELECT COUNT(*) AS n FROM users")["n"], 3)
        self.assertFalse(services.can_access_session(self.db, admin, 99999))

    def test_last_active_admin_is_protected_and_role_changes_revoke_tokens(self):
        admin = self.db.get_user_by_username("admin")
        for change in ({"role": "student"}, {"status": "disabled"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                services.update_user(self.db, admin["id"], **change)
        old_headers = self.headers("teacher")
        teacher = self.db.get_user_by_username("teacher")
        services.update_user(self.db, teacher["id"], role="student")
        self.assertEqual(self.client.get("/api/users/me", headers=old_headers).status_code, 401)

    def test_csv_formula_prefixes_and_control_characters(self):
        for value in ("=1+1", "+SUM(A1)", "-1+2", "@SUM(A1)", "  =1+1", "\tplain", "\rplain", "\nplain"):
            with self.subTest(value=value):
                self.assertEqual(services.csv_safe_cell(value), "'" + value)
        for value in (None, 0.9, "普通文本", "hello,\"world\""):
            self.assertEqual(services.csv_safe_cell(value), value)

    def test_realtime_window_buckets_counts_and_recent_agree(self):
        now = datetime(2026, 11, 11, 8, 17, 3, tzinfo=timezone.utc)
        self.db.execute("DELETE FROM emoji_records")
        for delta in (-3601, -3600, -3599, -1800, -1, 0, 1):
            self.db.execute(
                "INSERT INTO emoji_records (session_id, emoji_type, source, confidence, recorded_at) VALUES (?, 'focused', 'AI', 0.9, ?)",
                (self.session_id, (now + timedelta(seconds=delta)).isoformat(timespec="seconds")))
        with patch("backend.services.datetime") as clock:
            clock.now.return_value = now
            clock.fromisoformat.side_effect = datetime.fromisoformat
            result = services.realtime_dashboard(self.db, self.session_id)
        self.assertEqual(result["total_last_hour"], 5)
        self.assertEqual(len(result["recent"]), 5)
        self.assertEqual(sum(point["focused"] for point in result["trend"]), 5)
        self.assertEqual(len(result["trend"]), 12)


if __name__ == "__main__":
    unittest.main()
