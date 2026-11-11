"""Isolated, inexpensive fixtures for focused business and integration tests."""

import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt

from backend.app import create_app
from backend.database import Repository


class IsolatedAppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template_dir = tempfile.TemporaryDirectory()
        cls.template = Path(cls.template_dir.name) / "template.db"
        Repository(str(cls.template), seed_demo_data=True)

    @classmethod
    def tearDownClass(cls):
        cls.template_dir.cleanup()

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database = Path(self.temp_dir.name) / "test.db"
        shutil.copyfile(self.template, database)
        self.app = create_app({"TESTING": True, "DATABASE_PATH": str(database), "SEED_DEMO_DATA": False,
                               "SECRET_KEY": "isolated-test-secret-with-at-least-32-bytes",
                               "AI_SERVICE_TOKEN": "test-ai-token", "AI_CONFIDENCE_THRESHOLD": 0.6})
        self.db = self.app.extensions["emotion_repository"]
        self.client = self.app.test_client()
        self.session_id = self.db.one("SELECT id FROM class_sessions WHERE status = 'active'")["id"]

    def tearDown(self):
        self.temp_dir.cleanup()

    def token(self, username="teacher", **overrides):
        user = self.db.get_user_by_username(username)
        payload = {key: user[key] for key in ("username", "role", "token_version")}
        payload.update(user_id=user["id"], exp=datetime.now(timezone.utc) + timedelta(hours=1))
        payload.update(overrides)
        return jwt.encode(payload, self.app.config["SECRET_KEY"], algorithm="HS256")

    def headers(self, username="admin"):
        return {"Authorization": "Bearer " + self.token(username)}
