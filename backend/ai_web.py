"""Administrator-only camera sampling API. Frames remain in request memory."""

import base64
import binascii
import math
import threading

import requests
from flask import request

from backend import services
from backend.ai_service import infer_frame
from backend.database import EMOTIONS


def register_ai_web(app, db, authenticated, response, error, current_user_from_token):
    inference_slot = threading.BoundedSemaphore(1)

    @app.get("/api/admin/ai/status")
    @authenticated({"admin"})
    def ai_status(_user):
        return response({"configured": bool(app.config["AI_API_KEY"]), "model": app.config["AI_MODEL"],
                         "threshold": app.config["AI_CONFIDENCE_THRESHOLD"],
                         "interval": app.config["AI_SAMPLE_INTERVAL_SECONDS"]})

    @app.post("/api/admin/ai/analyze")
    @authenticated({"admin"})
    def ai_analyze(_user):
        if not app.config["AI_API_KEY"]:
            return error("请先在服务端 .env 中填写 AI_API_KEY、AI_BASE_URL 和 AI_MODEL，并重启后端", 503)
        body = request.get_json(silent=True)
        if not isinstance(body, dict) or type(body.get("session_id")) is not int or body["session_id"] < 1:
            return error("session_id 必须是正整数")
        session_id = body["session_id"]
        try:
            services.require_open_ai_session(db, session_id)
        except services.AISessionNotFound as exc:
            return error(str(exc), 404)
        except services.AISessionClosed as exc:
            return error(str(exc), 409)
        data_url = body.get("image")
        prefix = "data:image/jpeg;base64,"
        if not isinstance(data_url, str) or not data_url.startswith(prefix):
            return error("image 必须是 JPEG 格式的 Base64 采样帧")
        if len(data_url) > 750_000:
            return error("采样帧过大，请将画面缩小到 640 像素宽度后重试", 413)
        try:
            import cv2
            import numpy as np
        except ImportError:
            return error("网页识别需要安装摄像头依赖：python -m pip install -r requirements-ai.txt", 503)
        try:
            image_bytes = base64.b64decode(data_url[len(prefix):], validate=True)
            frame = cv2.imdecode(np.frombuffer(image_bytes, dtype="uint8"), cv2.IMREAD_COLOR)
        except (binascii.Error, ValueError, cv2.error):
            return error("无法解析 JPEG 采样帧")
        if frame is None or frame.size == 0:
            return error("无法解析 JPEG 采样帧")
        if frame.shape[0] * frame.shape[1] > 1920 * 1080:
            return error("采样帧分辨率过大", 413)
        if not inference_slot.acquire(blocking=False):
            return error("已有画面正在识别，请等待本次识别完成", 429)
        try:
            prediction = infer_frame(frame, app.config["AI_BASE_URL"], app.config["AI_API_KEY"],
                                     app.config["AI_MODEL"], app.config["AI_CONFIDENCE_THRESHOLD"])
            # A role change or revoked token during a slow model request takes effect before saving.
            user, failure = current_user_from_token()
            if failure:
                return failure
            if user["role"] != "admin":
                return error("当前账号没有执行此操作的权限", 403)
            services.require_open_ai_session(db, session_id)
            if prediction.get("accepted"):
                confidence = prediction.get("confidence")
                if (prediction.get("emoji_type") not in EMOTIONS or isinstance(confidence, bool)
                        or not isinstance(confidence, (int, float)) or not math.isfinite(confidence)
                        or not app.config["AI_CONFIDENCE_THRESHOLD"] <= confidence <= 1):
                    return error("模型返回的数据不符合识别约束", 502)
                prediction.update(services.save_ai_result(db, session_id, prediction["emoji_type"], confidence, "browser-camera"))
            emoji, label = EMOTIONS.get(prediction.get("emoji_type"), ("—", "等待识别"))
            return response({**prediction, "emoji": emoji, "label": label, "session_id": session_id,
                             "model": app.config["AI_MODEL"], "generated_at": db.now()},
                            201 if prediction.get("accepted") else 200)
        except services.AISessionNotFound as exc:
            return error(str(exc), 404)
        except services.AISessionClosed as exc:
            return error(str(exc), 409)
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            app.logger.warning("Browser AI inference failed type=%s status=%s", type(exc).__name__, status)
            suffix = f"（HTTP {status}）" if status else ""
            return error(f"模型请求失败{suffix}，请检查模型配置、网络与可用额度", 502)
        except RuntimeError:
            return error("本地人脸检测器不可用，请检查 OpenCV 摄像头依赖", 503)
        except (ValueError, KeyError, IndexError, TypeError):
            return error("模型返回的数据无法解析，请检查视觉模型与 JSON 输出支持", 502)
        finally:
            inference_slot.release()
