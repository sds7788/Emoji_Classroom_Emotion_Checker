"""Optional webcam inference worker for an OpenAI-compatible vision API.

Frames are sampled into memory, sent to the configured model for inference, and
discarded. This worker never writes source frames or video to disk.
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import time

import requests


EMOTION_TYPES = {"happy", "confused", "bored", "sad", "focused", "excited"}
logger = logging.getLogger("emoji_ai")


def analyze_frame(frame, session_id, service_token, backend_url, model_url, api_key, model, threshold, device_id):
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
        raise RuntimeError("无法将匿名脸部采样图编码为 JPEG")
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
                    f"这是一张由本地人脸检测器从课堂采样帧中裁出的匿名脸部拼图，共 {len(selected_faces)} 个样本。"
                    "不要识别身份，只估计这些可见学生中占主导的课堂感受。只返回 JSON："
                    '{"emoji_type":"happy|confused|bored|sad|focused|excited|none",'
                    '"confidence":0到1之间的数值。不要识别身份或输出文字说明。'
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
    if isinstance(content, list):
        content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
    prediction = json.loads(content)
    emotion = prediction.get("emoji_type")
    confidence = float(prediction.get("confidence", 0))
    if emotion not in EMOTION_TYPES:
        logger.info("No supported emotion returned; frame discarded")
        return {"accepted": False, "reason": "no_supported_emotion"}
    if not threshold <= confidence <= 1:
        logger.info("Low-confidence result discarded (%.3f)", confidence)
        return {"accepted": False, "reason": "low_confidence", "confidence": confidence}

    stored = requests.post(
        backend_url.rstrip("/") + "/api/ai/emoji-results",
        json={"session_id": session_id, "emoji_type": emotion, "confidence": confidence, "device_id": device_id},
        headers={"X-AI-Service-Token": service_token},
        timeout=10,
    )
    stored.raise_for_status()
    response = stored.json()
    logger.info("Inference submitted session=%s samples=%s type=%s confidence=%.3f",
                session_id, len(selected_faces), emotion, confidence)
    return response.get("data", {})


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
    if not 0 <= threshold <= 1 or args.interval < 1:
        raise SystemExit("置信度阈值需在 0 到 1 之间，采样间隔至少为 1 秒。")

    try:
        import cv2
    except ImportError as exc:
        raise SystemExit("摄像头推理需要可选依赖 opencv-python，请先安装 requirements-ai.txt。") from exc

    camera = cv2.VideoCapture(args.camera)
    if not camera.isOpened():
        raise SystemExit(f"无法打开摄像头设备 {args.camera}。")
    logger.info("Camera worker started for session=%s interval=%ss threshold=%.2f", args.session_id, args.interval, threshold)
    logger.info("Source frames are processed in memory only; no image or video is written to disk.")
    backoff = 1
    next_sample = 0.0
    try:
        while True:
            ok, frame = camera.read()
            if not ok:
                logger.warning("Camera frame unavailable; retrying")
                time.sleep(min(backoff, 15))
                backoff = min(backoff * 2, 15)
                continue
            if time.monotonic() < next_sample:
                time.sleep(min(0.2, max(0, next_sample - time.monotonic())))
                continue
            next_sample = time.monotonic() + args.interval
            try:
                analyze_frame(frame, args.session_id, service_token, backend_url, model_url, api_key,
                              model, threshold, args.device_id or f"camera-{args.camera}")
                backoff = 1
            except (requests.RequestException, ValueError, KeyError, IndexError, json.JSONDecodeError) as exc:
                logger.exception("Inference request failed; retrying after %ss", backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 30)
            finally:
                del frame
    except KeyboardInterrupt:
        logger.info("Camera worker stopped")
    finally:
        camera.release()


def main():
    parser = argparse.ArgumentParser(description="采集摄像头采样帧并提交课堂情绪分析结果")
    parser.add_argument("--session-id", type=int, required=True, help="已创建的课堂 ID")
    parser.add_argument("--camera", type=int, default=0, help="OpenCV 摄像头编号")
    parser.add_argument("--interval", type=float, default=None, help="采样频率对应的秒间隔")
    parser.add_argument("--threshold", type=float, default=None, help="置信度阈值，默认读取 AI_CONFIDENCE_THRESHOLD")
    parser.add_argument("--device-id", default="", help="可选的设备标识")
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
    run_worker(args)


if __name__ == "__main__":
    main()
