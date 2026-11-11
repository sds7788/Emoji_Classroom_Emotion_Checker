"""Optional webcam inference worker for an OpenAI-compatible vision API.

Frames are sampled into memory, sent to the configured model for inference, and
discarded. This worker never writes source frames or video to disk.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from backend.config import load_local_env

load_local_env()

EMOTION_TYPES = {"happy", "confused", "bored", "sad", "focused", "excited"}
logger = logging.getLogger("emoji_ai")


def parse_prediction(content, threshold):
    try:
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        prediction = json.loads(content)
        if not isinstance(prediction, dict):
            raise ValueError("Expected an object")
        emotion = prediction.get("emoji_type")
        raw_confidence = prediction.get("confidence")
        if isinstance(raw_confidence, bool) or not isinstance(raw_confidence, (int, float)):
            raise ValueError("Expected numeric confidence")
        confidence = float(raw_confidence)
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise ValueError("Confidence out of range")
    except (ValueError, TypeError, OverflowError):
        return {"accepted": False, "reason": "invalid_model_output"}
    if not isinstance(emotion, str) or emotion not in EMOTION_TYPES:
        return {"accepted": False, "reason": "no_supported_emotion"}
    if confidence < threshold:
        return {"accepted": False, "reason": "low_confidence", "emoji_type": emotion, "confidence": confidence}
    return {"accepted": True, "emoji_type": emotion, "confidence": confidence}


def infer_frame(frame, model_url, api_key, model, threshold):
    """Analyze one in-memory frame; callers decide how to persist the result."""
    import cv2

    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    cascade_path = os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml")
    detector = cv2.CascadeClassifier(cascade_path)
    if detector.empty():
        raise RuntimeError("OpenCV Haar 人脸检测器不可用")
    faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40))
    if len(faces) == 0:
        logger.debug("No face detected; sampled frame discarded")
        return {"accepted": False, "reason": "no_face_detected"}

    height, width = frame.shape[:2]
    tile_size = 256
    selected_faces = sorted(faces, key=lambda box: box[2] * box[3], reverse=True)[:8]
    sheet_rows = (len(selected_faces) + 1) // 2
    face_sheet = __import__("numpy").full((sheet_rows * tile_size, 2 * tile_size, 3), 245, dtype="uint8")
    for index, (x, y, face_width, face_height) in enumerate(selected_faces):
        margin_x = int(face_width * 0.12)
        margin_y = int(face_height * 0.16)
        left = max(0, int(x) - margin_x)
        top = max(0, int(y) - margin_y)
        right = min(width, int(x + face_width + margin_x))
        bottom = min(height, int(y + face_height + margin_y))
        crop = frame[top:bottom, left:right]
        if crop.size == 0:
            continue
        tile = cv2.resize(crop, (tile_size, tile_size), interpolation=cv2.INTER_AREA)
        row, column = divmod(index, 2)
        face_sheet[row * tile_size:(row + 1) * tile_size,
                   column * tile_size:(column + 1) * tile_size] = tile

    encoded_ok, encoded_frame = cv2.imencode(".jpg", face_sheet, [cv2.IMWRITE_JPEG_QUALITY, 78])
    if not encoded_ok:
        raise RuntimeError("无法将脸部采样图编码为 JPEG")
    image_data = base64.b64encode(encoded_frame.tobytes()).decode("ascii")
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 120,
        "response_format": {"type": "json_object"},
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": (
                    f"这是一张由本地人脸检测器从课堂采样帧中裁出的脸部拼图，共 {len(selected_faces)} 个样本。"
                    "不要识别身份，只估计这些可见学生中占主导的课堂感受。只返回 JSON："
                    '{"emoji_type":"focused","confidence":0.8}。'
                    "emoji_type 只允许 happy、confused、bored、sad、focused、excited、none；"
                    "confidence 必须为 0 到 1 之间的数值。不要识别身份或输出文字说明。"
                    "如果拼图中无法判断主导情绪则返回 emoji_type=none。"
                )},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_data}", "detail": "low"}},
            ],
        }],
    }
    result = requests.post(
        model_url.rstrip("/") + "/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=35,
    )
    result.raise_for_status()
    content = result.json()["choices"][0]["message"]["content"]
    prediction = parse_prediction(content, threshold)
    return {**prediction, "samples": len(selected_faces)}


def analyze_frame(frame, session_id, service_token, backend_url, model_url, api_key, model, threshold, device_id):
    prediction = infer_frame(frame, model_url, api_key, model, threshold)
    if not prediction["accepted"]:
        return prediction
    emotion, confidence = prediction["emoji_type"], prediction["confidence"]

    stored = requests.post(
        backend_url.rstrip("/") + "/api/ai/emoji-results",
        json={"session_id": session_id, "emoji_type": emotion, "confidence": confidence, "device_id": device_id},
        headers={"X-AI-Service-Token": service_token},
        timeout=10,
    )
    stored.raise_for_status()
    response = stored.json()
    logger.info("Inference submitted session=%s samples=%s type=%s confidence=%.3f",
                session_id, prediction["samples"], emotion, confidence)
    return {**response.get("data", {}), "emoji_type": emotion, "confidence": confidence, "samples": prediction["samples"]}


def run_worker(args):
    api_key = args.api_key or os.environ.get("AI_API_KEY", "")
    service_token = args.service_token or os.environ.get("AI_SERVICE_TOKEN", "")
    model_url = args.model_url or os.environ.get("AI_BASE_URL", "https://api.openai.com/v1")
    model = args.model or os.environ.get("AI_MODEL", "gpt-4o-mini")
    backend_url = args.backend_url or os.environ.get("BACKEND_URL", "http://127.0.0.1:5000")
    threshold = args.threshold if args.threshold is not None else float(os.environ.get("AI_CONFIDENCE_THRESHOLD", "0.55"))
    if not api_key:
        raise SystemExit("缺少 AI_API_KEY。请在环境变量中填写兼容视觉模型的 API Key 后重试。")
    if not service_token:
        raise SystemExit("缺少 AI_SERVICE_TOKEN。请设置与后端一致的独立服务令牌。")
    if (not math.isfinite(threshold) or not 0 <= threshold <= 1
            or not math.isfinite(args.interval) or args.interval < 1 or args.session_id < 1
            or (args.max_samples is not None and args.max_samples < 1)):
        raise SystemExit("置信度阈值需在 0 到 1 之间，采样间隔至少为 1 秒。")

    try:
        import cv2
    except ImportError as exc:
        raise SystemExit("摄像头推理需要可选依赖 opencv-python，请先安装 requirements-ai.txt。") from exc

    # Validate the target before spending model credits or opening the camera.
    try:
        health = requests.get(backend_url.rstrip("/") + "/health", timeout=5)
        health.raise_for_status()
    except requests.RequestException as exc:
        raise SystemExit("无法连接后端，请先启动服务并检查 BACKEND_URL。") from exc
    evidence = None
    if args.evidence:
        evidence_path = Path(args.evidence)
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence = evidence_path.open("a", encoding="utf-8")
    camera = cv2.VideoCapture(args.camera)
    if not camera.isOpened():
        camera.release()
        if evidence:
            evidence.close()
        raise SystemExit(f"无法打开摄像头设备 {args.camera}。")
    logger.info("Camera worker started for session=%s interval=%ss threshold=%.2f", args.session_id, args.interval, threshold)
    logger.info("Source frames are processed in memory only; no image or video is written to disk.")
    backoff = 1
    next_sample = 0.0
    attempts = 0
    accepted = 0
    max_samples = 1 if args.once else args.max_samples
    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                logger.warning("Camera frame unavailable; retrying")
                if max_samples:
                    raise SystemExit("摄像头已打开但无法读取帧，请检查设备占用或权限。")
                time.sleep(min(backoff, 15))
                backoff = min(backoff * 2, 15)
                continue
            if time.monotonic() < next_sample:
                time.sleep(min(0.2, max(0, next_sample - time.monotonic())))
                continue
            next_sample = time.monotonic() + args.interval
            attempts += 1
            started = time.monotonic()
            try:
                outcome = analyze_frame(frame, args.session_id, service_token, backend_url, model_url, api_key,
                                        model, threshold, args.device_id or f"camera-{args.camera}")
                accepted += int(bool(outcome.get("accepted")))
                backoff = 1
            except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                outcome = {"accepted": False, "reason": "request_failed", "error_type": type(exc).__name__, "http_status": status}
                logger.error("Inference failed type=%s http_status=%s", type(exc).__name__, status)
                if not max_samples:
                    time.sleep(backoff)
                backoff = min(backoff * 2, 30)
            finally:
                del frame
            event = {"timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "mode": "live_camera", "session_id": args.session_id, "model": model,
                     "threshold": threshold, "elapsed_seconds": round(time.monotonic() - started, 3), **outcome}
            logger.info("Sample outcome: %s", json.dumps(event, ensure_ascii=False))
            if evidence:
                evidence.write(json.dumps(event, ensure_ascii=False) + "\n")
                evidence.flush()
            if max_samples and attempts >= max_samples:
                return 0 if accepted else 2
    except KeyboardInterrupt:
        logger.info("Camera worker stopped")
    finally:
        camera.release()
        if evidence:
            evidence.close()


def main():
    parser = argparse.ArgumentParser(description="采集摄像头采样帧并提交课堂情绪分析结果")
    parser.add_argument("--session-id", type=int, required=True, help="已创建的课堂 ID")
    parser.add_argument("--camera", type=int, default=0, help="OpenCV 摄像头编号")
    parser.add_argument("--interval", type=float, default=None, help="采样频率对应的秒间隔")
    parser.add_argument("--threshold", type=float, default=None, help="置信度阈值，默认读取 AI_CONFIDENCE_THRESHOLD")
    parser.add_argument("--device-id", default="", help="可选的设备标识")
    parser.add_argument("--once", action="store_true", help="只采样一次；成功入库退出 0，未入库退出 2")
    parser.add_argument("--max-samples", type=int, help="采样指定次数后停止")
    parser.add_argument("--evidence", help="追加脱敏 JSONL 验收记录，不保存图像或密钥")
    parser.add_argument("--backend-url", default="")
    parser.add_argument("--model-url", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--api-key", default="", help=argparse.SUPPRESS)
    parser.add_argument("--service-token", default="", help=argparse.SUPPRESS)
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()
    if args.interval is None:
        args.interval = float(os.environ.get("AI_SAMPLE_INTERVAL_SECONDS", "5"))
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(message)s")
    raise SystemExit(run_worker(args))


if __name__ == "__main__":
    main()
