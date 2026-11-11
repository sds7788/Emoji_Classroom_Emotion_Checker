import base64
import json
from unittest.mock import Mock, patch

import requests

from tests.support import IsolatedAppTest


class BrowserAiTests(IsolatedAppTest):
    def setUp(self):
        super().setUp()
        try:
            import cv2
            import numpy as np
        except ImportError:
            self.skipTest("Install requirements-ai.txt for browser AI tests")
        self.cv2 = cv2
        self.np = np
        self.app.config.update(AI_API_KEY="private-fake-api-key", AI_BASE_URL="https://model.test/v1", AI_MODEL="mock-vision")
        _, encoded = cv2.imencode(".jpg", np.zeros((240, 320, 3), dtype="uint8"))
        self.body = {"session_id": self.session_id, "image": "data:image/jpeg;base64," + base64.b64encode(encoded).decode()}
        self.accepted = {"accepted": True, "emoji_type": "happy", "confidence": 0.91, "samples": 1}

    def post(self, body=None, username="admin", headers=None):
        return self.client.post("/api/admin/ai/analyze", json=self.body if body is None else body,
                                headers=self.headers(username) if headers is None else headers)

    def count(self):
        return self.db.one("SELECT COUNT(*) AS n FROM emoji_records")["n"]

    def test_status_and_sampling_are_admin_only(self):
        self.assertEqual(self.client.get("/api/admin/ai/status").status_code, 401)
        self.assertEqual(self.client.post("/api/admin/ai/analyze", json=self.body).status_code, 401)
        for username in ("student", "teacher"):
            self.assertEqual(self.client.get("/api/admin/ai/status", headers=self.headers(username)).status_code, 403)
            self.assertEqual(self.post(username=username).status_code, 403)
        result = self.client.get("/api/admin/ai/status", headers=self.headers())
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.get_json()["data"]["configured"])
        self.assertNotIn(self.app.config["AI_API_KEY"], result.get_data(as_text=True))
        self.assertIn("no-store", result.headers["Cache-Control"])

    def test_actual_frame_encoding_and_mock_model_are_saved_anonymously(self):
        detector = Mock()
        detector.empty.return_value = False
        detector.detectMultiScale.return_value = [(50, 60, 80, 80)]
        model_response = requests.Response()
        model_response.status_code = 200
        model_response._content = json.dumps({"choices": [{"message": {"content": '{"emoji_type":"happy","confidence":0.91}'}}]}).encode()
        with patch("cv2.CascadeClassifier", return_value=detector), patch("backend.ai_service.requests.post", return_value=model_response) as model:
            result = self.post()
        self.assertEqual(result.status_code, 201, result.get_json())
        data = result.get_json()["data"]
        self.assertEqual((data["emoji"], data["label"], data["confidence"]), ("😊", "开心", 0.91))
        self.assertEqual(model.call_count, 1)
        row = self.db.one("SELECT * FROM emoji_records WHERE id = ?", (data["id"],))
        self.assertIsNone(row["user_id"])
        self.assertEqual((row["source"], row["device_id"]), ("AI", "browser-camera"))
        self.assertNotIn("image", row)
        self.assertNotIn("base64", result.get_data(as_text=True))
        self.assertIn("no-store", result.headers["Cache-Control"])

    def test_low_confidence_has_emoji_but_is_not_saved(self):
        before = self.count()
        with patch("backend.ai_web.infer_frame", return_value={"accepted": False, "reason": "low_confidence", "emoji_type": "confused", "confidence": 0.4, "samples": 1}):
            result = self.post()
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.get_json()["data"]["emoji"], "😕")
        self.assertFalse(result.get_json()["data"]["accepted"])
        self.assertEqual(self.count(), before)

    def test_no_face_frame_does_not_call_model_or_save(self):
        before = self.count()
        with patch("backend.ai_service.requests.post") as model:
            result = self.post()
        self.assertEqual(result.get_json()["data"]["reason"], "no_face_detected")
        self.assertEqual(self.count(), before)
        model.assert_not_called()

    def test_invalid_images_are_rejected(self):
        for image in (None, "https://example.invalid/image.jpg", "data:image/png;base64,abcd", "data:image/jpeg;base64,%%%", "data:image/jpeg;base64,abcd"):
            with self.subTest(image=image):
                self.assertEqual(self.post({**self.body, "image": image}).status_code, 400)
        for session_id in (True, "1", -1, None):
            self.assertEqual(self.post({**self.body, "session_id": session_id}).status_code, 400)

    def test_oversized_body_and_resolution_are_rejected(self):
        self.assertEqual(self.post({**self.body, "image": "data:image/jpeg;base64," + "A" * 800_000}).status_code, 413)
        self.assertEqual(self.post({**self.body, "image": "A" * 2_200_000}).status_code, 413)
        _, encoded = self.cv2.imencode(".jpg", self.np.zeros((1100, 2000, 3), dtype="uint8"))
        image = "data:image/jpeg;base64," + base64.b64encode(encoded).decode()
        self.assertEqual(self.post({**self.body, "image": image}).status_code, 413)

    def test_missing_and_closed_sessions_are_rejected_before_inference(self):
        with patch("backend.ai_web.infer_frame") as infer:
            self.assertEqual(self.post({**self.body, "session_id": 99999}).status_code, 404)
            self.db.execute("UPDATE class_sessions SET status = 'ended' WHERE id = ?", (self.session_id,))
            self.assertEqual(self.post().status_code, 409)
        infer.assert_not_called()

    def test_missing_configuration_is_reported_without_model_call(self):
        self.app.config["AI_API_KEY"] = ""
        with patch("backend.ai_web.infer_frame") as infer:
            self.assertEqual(self.post().status_code, 503)
        infer.assert_not_called()

    def test_model_http_failure_is_redacted_and_does_not_save(self):
        error = requests.HTTPError("private-fake-api-key must never be exposed")
        error.response = requests.Response()
        error.response.status_code = 401
        before = self.count()
        with patch("backend.ai_web.infer_frame", side_effect=error):
            result = self.post()
        self.assertEqual(result.status_code, 502)
        self.assertNotIn("private-fake-api-key", result.get_data(as_text=True))
        self.assertIn("401", result.get_json()["message"])
        self.assertEqual(self.count(), before)

    def test_token_revoked_while_model_is_running_cannot_save(self):
        headers = self.headers()
        before = self.count()
        def revoked(*_args):
            self.db.execute("UPDATE users SET token_version = token_version + 1 WHERE username = 'admin'")
            return dict(self.accepted)
        with patch("backend.ai_web.infer_frame", side_effect=revoked):
            self.assertEqual(self.post(headers=headers).status_code, 401)
        self.assertEqual(self.count(), before)

    def test_session_closed_while_model_is_running_cannot_save(self):
        before = self.count()
        def closed(*_args):
            self.db.execute("UPDATE class_sessions SET status = 'ended' WHERE id = ?", (self.session_id,))
            return dict(self.accepted)
        with patch("backend.ai_web.infer_frame", side_effect=closed):
            self.assertEqual(self.post().status_code, 409)
        self.assertEqual(self.count(), before)

    def test_concurrent_model_call_is_rejected_and_slot_is_released(self):
        def busy(*_args):
            with self.app.test_client() as other_client:
                nested = other_client.post("/api/admin/ai/analyze", json=self.body, headers=self.headers())
                self.assertEqual(nested.status_code, 429)
            return {"accepted": False, "reason": "no_face_detected"}
        with patch("backend.ai_web.infer_frame", side_effect=busy):
            self.assertEqual(self.post().status_code, 200)
        with patch("backend.ai_web.infer_frame", return_value=dict(self.accepted)):
            self.assertEqual(self.post().status_code, 201)

    def test_missing_model_fields_return_502_instead_of_session_404(self):
        with patch("backend.ai_web.infer_frame", side_effect=KeyError("choices")):
            self.assertEqual(self.post().status_code, 502)
        with patch("backend.ai_web.infer_frame", return_value=dict(self.accepted)):
            self.assertEqual(self.post().status_code, 201)

    def test_invalid_accepted_predictions_never_save(self):
        before = self.count()
        for confidence in (True, None, "0.9", float("nan"), float("inf"), 0.1):
            with self.subTest(confidence=confidence), patch("backend.ai_web.infer_frame", return_value={**self.accepted, "confidence": confidence}):
                self.assertEqual(self.post().status_code, 502)
        self.assertEqual(self.count(), before)
