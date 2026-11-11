import json
from datetime import datetime, timedelta, timezone

from backend.realtime import stream_dashboard
from backend.services import update_user
from tests.support import IsolatedAppTest


class FakeSocket:
    def __init__(self, subscription, after_update=lambda: None):
        self.subscription = subscription
        self.after_update = after_update
        self.messages = []
        self.closed = False
        self.reads = 0

    def receive(self, timeout=None):
        self.reads += 1
        if self.reads == 1:
            return self.subscription
        self.after_update()

    def send(self, message):
        self.messages.append(json.loads(message))

    def close(self, **kwargs):
        self.closed = True


class RealtimeTests(IsolatedAppTest):
    def test_subscription_rejects_invalid_payloads_and_student_role(self):
        subscriptions = ["[]", "not json", "{}", json.dumps({"session_id": self.session_id, "token": self.token("student")}),
                         json.dumps({"session_id": self.session_id, "token": self.token(exp=datetime.now(timezone.utc) - timedelta(seconds=1))})]
        for subscription in subscriptions:
            ws = FakeSocket(subscription)
            stream_dashboard(ws, self.db, self.app.config["SECRET_KEY"], interval=0)
            self.assertTrue(ws.closed)
            self.assertEqual(len(ws.messages), 1)
            self.assertIn("error", ws.messages[0])

    def assert_revoked_after_first_update(self, change):
        ws = FakeSocket(json.dumps({"session_id": self.session_id, "token": self.token()}), change)
        stream_dashboard(ws, self.db, self.app.config["SECRET_KEY"], interval=0)
        self.assertEqual(len(ws.messages), 2)
        self.assertIn("data", ws.messages[0])
        self.assertIn("error", ws.messages[1])
        self.assertTrue(ws.closed)

    def test_disabled_account_stops_existing_stream(self):
        self.assert_revoked_after_first_update(lambda: self.db.execute("UPDATE users SET status = 'disabled' WHERE username = 'teacher'"))

    def test_role_change_stops_existing_stream(self):
        teacher = self.db.get_user_by_username("teacher")
        self.assert_revoked_after_first_update(lambda: update_user(self.db, teacher["id"], role="student"))

    def test_password_change_stops_existing_stream(self):
        self.assert_revoked_after_first_update(lambda: self.db.execute("UPDATE users SET token_version = token_version + 1 WHERE username = 'teacher'"))

    def test_reassigned_course_stops_existing_stream(self):
        self.assert_revoked_after_first_update(lambda: self.db.execute("UPDATE courses SET teacher_id = (SELECT id FROM users WHERE username = 'admin')"))
