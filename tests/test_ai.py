import base64
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from backend.ai_service import analyze_frame, parse_prediction, run_worker
from tests.support import IsolatedAppTest


class PredictionTests(unittest.TestCase):
    def test_valid_prediction_and_threshold_boundary(self):
        result = parse_prediction('{"emoji_type":"focused","confidence":0.6}', 0.6)
        self.assertTrue(result["accepted"])
        self.assertEqual(result["emoji_type"], "focused")
        blocks = [{"type": "text", "text": '{"emoji_type":"happy","confidence":0.9}'}]
        self.assertTrue(parse_prediction(blocks, 0.6)["accepted"])

    def test_invalid_model_results_are_discarded(self):
        cases = [None, "not JSON", "[]", "null", '{}', [{"text": None}], [{"text": 123}]]
        cases += [json.dumps({"emoji_type": "happy", "confidence": value}) for value in [True, None, "0.9", -1, 1.1, float("nan"), float("inf")]]
        for content in cases:
            with self.subTest(content=content):
                self.assertEqual(parse_prediction(content, 0.6)["reason"], "invalid_model_output")
        self.assertEqual(parse_prediction('{"emoji_type":[],"confidence":0.9}', 0.6)["reason"], "no_supported_emotion")
        self.assertEqual(parse_prediction('{"emoji_type":"none","confidence":0.9}', 0.6)["reason"], "no_supported_emotion")
        self.assertEqual(parse_prediction('{"emoji_type":"happy","confidence":0.59}', 0.6)["reason"], "low_confidence")


class AiPipelineTests(IsolatedAppTest):
    def setUp(self):
        super().setUp()
        try:
            import cv2
            import numpy
        except ImportError:
            self.skipTest("Install requirements-ai.txt for camera pipeline tests")
        self.cv2 = cv2
        self.frame = numpy.zeros((720, 1280, 3), dtype="uint8")
        self.detector = Mock()
        self.detector.empty.return_value = False
        self.detector.detectMultiScale.return_value = [(50, 60, 80, 90)]

    @staticmethod
    def model_result(content):
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
        return response

    def analyze(self, token="test-ai-token", threshold=0.6):
        return analyze_frame(self.frame, self.session_id, token, "http://backend.test",
                             "https://model.test/v1", "fake-model-key", "mock-vision", threshold, "test-camera")

    def test_mock_model_success_reaches_real_api_database_statistics_and_export(self):
        calls = []

        def post(url, **kwargs):
            calls.append((url, kwargs))
            if url.startswith("https://model.test"):
                return self.model_result('{"emoji_type":"focused","confidence":0.91}')
            stored = self.client.post("/api/ai/emoji-results", json=kwargs["json"], headers=kwargs["headers"])
            response = requests.Response()
            response.status_code = stored.status_code
            response._content = stored.data
            return response

        with patch("cv2.CascadeClassifier", return_value=self.detector), patch("backend.ai_service.requests.post", side_effect=post):
            result = self.analyze()
        self.assertTrue(result["accepted"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1]["headers"]["Authorization"], "Bearer fake-model-key")
        self.assertNotIn("Authorization", calls[1][1]["headers"])
        image_url = calls[0][1]["json"]["messages"][0]["content"][1]["image_url"]["url"]
        encoded = __import__("numpy").frombuffer(base64.b64decode(image_url.split(",", 1)[1]), dtype="uint8")
        decoded = self.cv2.imdecode(encoded, self.cv2.IMREAD_COLOR)
        self.assertEqual(decoded.shape[:2], (256, 512))
        row = self.db.one("SELECT * FROM emoji_records WHERE id = ?", (result["id"],))
        self.assertIsNone(row["user_id"])
        self.assertEqual((row["source"], row["emoji_type"], row["confidence"]), ("AI", "focused", 0.91))
        history = self.client.get("/api/emoji/history?source=AI", headers=self.headers()).get_json()["data"]
        self.assertEqual(history[0]["id"], result["id"])
        self.assertEqual(self.client.get("/api/admin/statistics?source=AI", headers=self.headers()).get_json()["data"]["total"], 1)
        self.assertIn("匿名 AI 汇总", self.client.get("/api/admin/emoji/export?source=AI", headers=self.headers()).data.decode("utf-8-sig"))

    def test_low_confidence_and_invalid_response_never_call_ingestion(self):
        for content in ('{"emoji_type":"sad","confidence":0.2}', '{"emoji_type":"none","confidence":0.9}', "bad JSON"):
            with self.subTest(content=content), patch("cv2.CascadeClassifier", return_value=self.detector), patch("backend.ai_service.requests.post", return_value=self.model_result(content)) as post:
                self.assertFalse(self.analyze()["accepted"])
                self.assertEqual(post.call_count, 1)

    def test_backend_threshold_is_authoritative(self):
        def post(url, **kwargs):
            if url.startswith("https://model.test"):
                return self.model_result('{"emoji_type":"happy","confidence":0.5}')
            stored = self.client.post("/api/ai/emoji-results", json=kwargs["json"], headers=kwargs["headers"])
            response = requests.Response()
            response.status_code = stored.status_code
            response._content = stored.data
            return response
        before = self.db.one("SELECT COUNT(*) AS n FROM emoji_records")["n"]
        with patch("cv2.CascadeClassifier", return_value=self.detector), patch("backend.ai_service.requests.post", side_effect=post):
            self.assertFalse(self.analyze(threshold=0.4)["accepted"])
        self.assertEqual(self.db.one("SELECT COUNT(*) AS n FROM emoji_records")["n"], before)

    def test_model_http_error_does_not_write(self):
        response = requests.Response()
        response.status_code = 429
        with patch("cv2.CascadeClassifier", return_value=self.detector), patch("backend.ai_service.requests.post", return_value=response) as post:
            with self.assertRaises(requests.HTTPError):
                self.analyze()
            self.assertEqual(post.call_count, 1)


class WorkerTests(unittest.TestCase):
    def setUp(self):
        try:
            import cv2  # noqa: F401
            import numpy
        except ImportError:
            self.skipTest("Install requirements-ai.txt for camera worker tests")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.evidence = Path(self.temporary.name) / "events.jsonl"
        self.args = SimpleNamespace(api_key="fake-private-api-key", service_token="fake-private-service-token",
                                    model_url="https://model.test/v1", model="mock-vision", backend_url="http://backend.test",
                                    threshold=0.6, interval=1, session_id=1, max_samples=None, once=True,
                                    evidence=str(self.evidence), camera=0, device_id="test-camera")
        self.camera = Mock()
        self.camera.isOpened.return_value = True
        self.camera.read.return_value = (True, numpy.zeros((100, 100, 3), dtype="uint8"))

    def worker(self, outcome=None, error=None):
        with patch("cv2.VideoCapture", return_value=self.camera), patch("backend.ai_service.requests.get"), patch("backend.ai_service.analyze_frame", return_value=outcome, side_effect=error):
            return run_worker(self.args)

    def test_once_success_writes_only_structured_evidence_and_releases_camera(self):
        self.assertEqual(self.worker({"accepted": True, "id": 99, "samples": 1, "emoji_type": "focused", "confidence": 0.9}), 0)
        event = json.loads(self.evidence.read_text(encoding="utf-8"))
        self.assertEqual((event["mode"], event["id"], event["model"]), ("live_camera", 99, "mock-vision"))
        content = self.evidence.read_text(encoding="utf-8")
        for secret in (self.args.api_key, self.args.service_token, "base64", "image_url"):
            self.assertNotIn(secret, content)
        self.camera.release.assert_called_once()

    def test_once_without_face_exits_two_and_releases_camera(self):
        self.assertEqual(self.worker({"accepted": False, "reason": "no_face_detected"}), 2)
        self.assertEqual(json.loads(self.evidence.read_text())["reason"], "no_face_detected")
        self.camera.release.assert_called_once()

    def test_request_error_evidence_does_not_include_exception_secrets(self):
        error = requests.HTTPError("failed using " + self.args.api_key)
        error.response = requests.Response()
        error.response.status_code = 401
        self.assertEqual(self.worker(error=error), 2)
        content = self.evidence.read_text()
        self.assertNotIn(self.args.api_key, content)
        self.assertEqual(json.loads(content)["http_status"], 401)
        self.camera.release.assert_called_once()

    def test_single_sample_fails_promptly_if_camera_cannot_read(self):
        self.camera.read.return_value = (False, None)
        with self.assertRaises(SystemExit):
            self.worker()
        self.camera.release.assert_called_once()
