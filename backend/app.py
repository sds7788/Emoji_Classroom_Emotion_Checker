"""Flask HTTP controllers for the Emoji Classroom Emotion Checker."""

from __future__ import annotations

import csv
import io
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from functools import wraps

import bcrypt
import jwt
from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_sock import Sock

from backend import services
from backend.database import EMOTIONS, Repository


ROLE_LABELS = {"student": "学生", "teacher": "教师", "admin": "管理员"}


def create_app(test_config=None):
    app = Flask(__name__, static_folder="../frontend", static_url_path="")
    app.config.update(
        SECRET_KEY=os.environ.get("JWT_SECRET", "dev-only-change-this-secret-key"),
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(hours=8),
        AI_SERVICE_TOKEN=os.environ.get("AI_SERVICE_TOKEN", ""),
        AI_CONFIDENCE_THRESHOLD=float(os.environ.get("AI_CONFIDENCE_THRESHOLD", "0.55")),
        DATABASE_PATH=os.environ.get("DATABASE_PATH", "data/emotion_checker.db"),
        SEED_DEMO_DATA=os.environ.get("SEED_DEMO_DATA", "true").lower() == "true",
        JSON_SORT_KEYS=False,
    )
    if test_config:
        app.config.update(test_config)
    if app.config["SECRET_KEY"] == "dev-only-change-this-secret-key" and not app.testing:
        app.logger.warning("Using the development JWT secret. Set JWT_SECRET before deployment.")
    CORS(app, resources={r"/api/*": {"origins": os.environ.get("CORS_ORIGINS", "*").split(",")}})
    app.logger.setLevel(logging.INFO)
    db = Repository(app.config["DATABASE_PATH"], app.config["SEED_DEMO_DATA"])
    app.extensions["emotion_repository"] = db
    sockets = Sock(app)

    def response(data=None, status=200, message="ok"):
        return jsonify({"code": status, "message": message, "data": data}), status

    def error(message, status=400, code=None):
        return jsonify({"code": code or status, "message": message, "data": None}), status

    def json_body():
        body = request.get_json(silent=True)
        return body if isinstance(body, dict) else {}

    def parse_iso(value, field):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
        except (AttributeError, TypeError, ValueError):
            raise ValueError(f"{field} 必须是有效的 ISO 8601 时间")

    def current_user_from_token():
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None, error("请先登录", 401)
        try:
            payload = jwt.decode(header[7:], app.config["SECRET_KEY"], algorithms=["HS256"])
            user = db.get_user_by_id(payload["user_id"])
            full_user = db.get_user_by_username(payload["username"])
            if not user or user["status"] != "active" or full_user["token_version"] != payload.get("token_version"):
                return None, error("登录凭证已失效", 401)
            return user, None
        except jwt.ExpiredSignatureError:
            return None, error("登录已过期，请重新登录", 401)
        except (jwt.InvalidTokenError, KeyError, TypeError):
            return None, error("登录凭证无效", 401)

    def authenticated(roles=None):
        def decorator(function):
            @wraps(function)
            def wrapped(*args, **kwargs):
                user, failure = current_user_from_token()
                if failure:
                    return failure
                if roles and user["role"] not in roles:
                    return error("当前账号没有执行此操作的权限", 403)
                return function(user, *args, **kwargs)
            return wrapped
        return decorator

    def handle_integrity_error(exc):
        message = str(exc)
        if "UNIQUE" in message:
            return error("用户名、邮箱或编号已被使用", 409)
        if "FOREIGN KEY" in message:
            return error("关联的课程、教师或课堂不存在", 400)
        if "CHECK constraint" in message:
            return error("提交数据不符合业务约束", 400)
        app.logger.exception("Database integrity error")
        return error("数据保存失败", 400)

    @app.get("/")
    def home():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/health")
    def health():
        return response({"status": "ok", "service": "emoji-classroom-checker"})

    @app.get("/api/openapi.json")
    def openapi_json():
        import json
        with open(os.path.join(os.path.dirname(__file__), "..", "docs", "openapi.json"), encoding="utf-8") as source:
            return jsonify(json.load(source))

    @app.get("/api/docs")
    def api_docs():
        return Response(
            "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>API 文档</title>"
            "<link rel='stylesheet' href='https://unpkg.com/swagger-ui-dist@5/swagger-ui.css'>"
            "<div id='swagger-ui'></div><script src='https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js'></script>"
            "<script>SwaggerUIBundle({url:'/api/openapi.json',dom_id:'#swagger-ui'});</script></html>",
            mimetype="text/html",
        )

    @app.post("/api/auth/register")
    def register():
        data = json_body()
        username = str(data.get("username", "")).strip()
        password = str(data.get("password", ""))
        full_name = str(data.get("full_name", username)).strip()
        email = str(data.get("email", "")).strip().lower() or None
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,32}", username):
            return error("用户名需为 3-32 位字母、数字、点、下划线或短横线")
        if len(password) < 8 or len(password.encode("utf-8")) > 72:
            return error("密码需至少 8 个字符且不超过 72 个 UTF-8 字节")
        if not full_name or len(full_name) > 80:
            return error("姓名不能为空且不超过 80 个字符")
        if email and (len(email) > 120 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)):
            return error("邮箱格式无效")
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12))
        try:
            user_id = db.create_user(username, password_hash, "student", full_name, email)
        except Exception as exc:
            return handle_integrity_error(exc)
        user = db.get_user_by_id(user_id)
        token = jwt.encode(
            {"user_id": user_id, "username": username, "role": "student", "token_version": 0,
             "exp": datetime.now(timezone.utc) + app.config["JWT_ACCESS_TOKEN_EXPIRES"]},
            app.config["SECRET_KEY"], algorithm="HS256",
        )
        db.audit(user_id, "register", "user", user_id)
        return response({"access_token": token, "user": user}, 201, "注册成功")

    @app.post("/api/auth/login")
    def login():
        data = json_body()
        user = db.get_user_by_username(str(data.get("username", "")).strip())
        password = str(data.get("password", ""))
        if len(password.encode("utf-8")) > 72:
            return error("用户名或密码错误", 401)
        if not user or user["status"] != "active" or not bcrypt.checkpw(password.encode("utf-8"), user["password_hash"]):
            return error("用户名或密码错误", 401)
        db.mark_login(user["id"])
        token = jwt.encode(
            {"user_id": user["id"], "username": user["username"], "role": user["role"],
             "token_version": user["token_version"], "exp": datetime.now(timezone.utc) + app.config["JWT_ACCESS_TOKEN_EXPIRES"]},
            app.config["SECRET_KEY"], algorithm="HS256",
        )
        db.audit(user["id"], "login", "user", user["id"])
        return response({"access_token": token, "user": db.get_user_by_id(user["id"])}, message="登录成功")

    @app.get("/api/users/me")
    @authenticated()
    def me(user):
        return response(user)

    @app.put("/api/auth/password")
    @authenticated()
    def change_password(user):
        data = json_body()
        full_user = db.get_user_by_username(user["username"])
        old_password, new_password = str(data.get("old_password", "")), str(data.get("new_password", ""))
        if len(old_password.encode("utf-8")) > 72 or not bcrypt.checkpw(old_password.encode("utf-8"), full_user["password_hash"]):
            return error("当前密码不正确", 400)
        if len(new_password) < 8 or len(new_password.encode("utf-8")) > 72:
            return error("新密码需至少 8 个字符且不超过 72 个 UTF-8 字节")
        db.update_password(user["id"], bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt(rounds=12)))
        db.audit(user["id"], "change_password", "user", user["id"])
        return response(message="密码已修改，请重新登录")

    @app.get("/api/sessions")
    @authenticated()
    def sessions(user):
        return response(services.list_sessions(db, user))

    @app.post("/api/emoji")
    @authenticated({"student"})
    def create_emoji(user):
        data = json_body()
        emoji_type = str(data.get("emoji_type", ""))
        try:
            session_id = int(data.get("session_id"))
        except (TypeError, ValueError):
            return error("session_id 必须是整数")
        if emoji_type not in EMOTIONS:
            return error("emoji_type 必须是支持的情绪类型")
        if not services.can_access_session(db, user, session_id):
            return error("无法访问该课堂", 403)
        session = db.one("SELECT starts_at, ends_at, status FROM class_sessions WHERE id = ?", (session_id,))
        now = datetime.now(timezone.utc)
        try:
            starts = datetime.fromisoformat(session["starts_at"])
            ends = datetime.fromisoformat(session["ends_at"])
            if starts.tzinfo is None:
                starts = starts.replace(tzinfo=timezone.utc)
            if ends.tzinfo is None:
                ends = ends.replace(tzinfo=timezone.utc)
        except ValueError:
            return error("课堂时间设置无效", 409)
        if session["status"] != "active" or not (starts <= now <= ends):
            return error("当前课堂未开放情绪记录", 409)
        record_id, _ = db.execute(
            "INSERT INTO emoji_records (user_id, session_id, emoji_type, recorded_at, source, device_id) VALUES (?, ?, ?, ?, 'MANUAL', ?)",
            (user["id"], session_id, emoji_type, db.now(), str(data.get("device_id", "web"))[:80]),
        )
        return response({"id": record_id, "session_id": session_id, "emoji_type": emoji_type, "source": "MANUAL"}, 201, "情绪已记录")

    @app.get("/api/emoji/history")
    @authenticated()
    def emoji_history(user):
        params = request.args.to_dict()
        try:
            if user["role"] in {"teacher", "admin"} and params.get("session_id"):
                if not services.can_access_session(db, user, int(params["session_id"])):
                    return error("无法访问该课堂数据", 403)
            return response(services.list_history(db, user, params))
        except (TypeError, ValueError):
            return error("筛选参数无效")

    @app.get("/api/emoji/statistics")
    @authenticated()
    def emoji_statistics(user):
        try:
            if user["role"] in {"teacher", "admin"} and request.args.get("session_id"):
                if not services.can_access_session(db, user, int(request.args["session_id"])):
                    return error("无法访问该课堂数据", 403)
            return response(services.statistics(db, user, request.args))
        except (TypeError, ValueError):
            return error("筛选参数无效")

    @app.get("/api/teacher/sessions")
    @authenticated({"teacher"})
    def teacher_sessions(user):
        return response(services.list_sessions(db, user))

    @app.get("/api/admin/dashboard/realtime")
    @authenticated({"teacher", "admin"})
    def realtime_dashboard(user):
        session_id = request.args.get("sessionId", type=int)
        if not session_id:
            return error("sessionId 为必填项")
        if not services.can_access_session(db, user, session_id):
            return error("无法访问该课堂数据", 403)
        dashboard = services.realtime_dashboard(db, session_id)
        if dashboard is None:
            return error("课堂不存在", 404)
        dashboard["generated_at"] = db.now()
        return response(dashboard)

    @app.get("/api/admin/statistics")
    @authenticated({"teacher", "admin"})
    def admin_statistics(user):
        try:
            if request.args.get("session_id") and not services.can_access_session(db, user, int(request.args["session_id"])):
                return error("无法访问该课堂数据", 403)
            return response(services.statistics(db, user, request.args))
        except (TypeError, ValueError):
            return error("筛选参数无效")

    @sockets.route("/ws/dashboard")
    def dashboard_websocket(ws):
        try:
            subscription = request.get_json(silent=True) or __import__("json").loads(ws.receive(timeout=10) or "{}")
            payload = jwt.decode(subscription.get("token", ""), app.config["SECRET_KEY"], algorithms=["HS256"])
            user = db.get_user_by_id(payload["user_id"])
            full_user = db.get_user_by_username(payload["username"])
            session_id = int(subscription.get("session_id"))
            if (not user or not full_user or user["status"] != "active"
                    or full_user["token_version"] != payload.get("token_version")
                    or user["role"] not in {"teacher", "admin"}
                    or not services.can_access_session(db, user, session_id)):
                ws.send(__import__("json").dumps({"error": "无权订阅该课堂"}, ensure_ascii=False))
                return
            while True:
                dashboard = services.realtime_dashboard(db, session_id)
                if dashboard is None:
                    break
                dashboard["generated_at"] = db.now()
                ws.send(__import__("json").dumps({"data": dashboard}, ensure_ascii=False))
                time.sleep(5)
        except Exception as exc:
            app.logger.info("Dashboard websocket closed: %s", exc)

    @app.get("/api/admin/users")
    @authenticated({"admin"})
    def admin_users(user):
        return response(services.list_users(db))

    @app.put("/api/admin/users/<int:user_id>")
    @authenticated({"admin"})
    def admin_update_user(user, user_id):
        data = json_body()
        try:
            updated = services.update_user(db, user_id, data.get("role"), data.get("status"))
        except ValueError as exc:
            return error(str(exc))
        if not updated:
            return error("用户不存在", 404)
        db.audit(user["id"], "update_user", "user", user_id, f"role={updated['role']};status={updated['status']}")
        return response(updated)

    @app.get("/api/admin/courses")
    @authenticated({"admin"})
    def admin_courses(user):
        return response(services.list_courses(db))

    @app.post("/api/admin/courses")
    @authenticated({"admin"})
    def admin_create_course(user):
        data = json_body()
        code, name, teacher_id = str(data.get("course_code", "")).strip(), str(data.get("name", "")).strip(), data.get("teacher_id")
        if not code or not name:
            return error("course_code 和 name 为必填项")
        try:
            teacher_id = int(teacher_id)
        except (TypeError, ValueError):
            return error("teacher_id 必须是整数")
        teacher = db.get_user_by_id(teacher_id)
        if not teacher or teacher["role"] != "teacher":
            return error("teacher_id 必须对应有效教师账号")
        try:
            course_id = services.create_course(db, {"course_code": code, "name": name, "teacher_id": teacher_id})
        except Exception as exc:
            return handle_integrity_error(exc)
        db.audit(user["id"], "create_course", "course", course_id)
        return response({"id": course_id}, 201)

    @app.post("/api/admin/sessions")
    @authenticated({"admin"})
    def admin_create_session(user):
        data = json_body()
        required = ["course_id", "class_name", "starts_at", "ends_at"]
        if not all(data.get(field) for field in required):
            return error("course_id、class_name、starts_at 和 ends_at 为必填项")
        try:
            normalized = dict(data)
            normalized["course_id"] = int(data["course_id"])
            normalized["starts_at"] = parse_iso(data["starts_at"], "starts_at")
            normalized["ends_at"] = parse_iso(data["ends_at"], "ends_at")
            if datetime.fromisoformat(normalized["ends_at"]) <= datetime.fromisoformat(normalized["starts_at"]):
                return error("结束时间必须晚于开始时间")
            if normalized.get("status", "scheduled") not in {"scheduled", "active", "ended"}:
                return error("课堂状态无效")
            session_id = services.create_session(db, normalized)
        except ValueError as exc:
            return error(str(exc))
        except Exception as exc:
            return handle_integrity_error(exc)
        db.audit(user["id"], "create_session", "session", session_id)
        return response({"id": session_id}, 201)

    @app.get("/api/admin/sessions")
    @authenticated({"admin"})
    def admin_list_sessions(user):
        admin_scope = {"id": None, "role": "admin"}
        return response(services.list_sessions(db, admin_scope))

    @app.get("/api/admin/sessions/<int:session_id>/schedule")
    @authenticated({"admin"})
    def get_schedule(user, session_id):
        if not db.one("SELECT id FROM class_sessions WHERE id = ?", (session_id,)):
            return error("课堂不存在", 404)
        return response(db.all(
            "SELECT u.id, u.username, u.full_name, u.email FROM schedule_users su "
            "JOIN users u ON u.id = su.user_id WHERE su.session_id = ? ORDER BY u.username", (session_id,)))

    @app.post("/api/admin/sessions/<int:session_id>/schedule")
    @authenticated({"admin"})
    def set_schedule(user, session_id):
        data = json_body()
        ok, message = services.schedule_students(db, session_id, data.get("user_ids"))
        if not ok:
            return error(message, 404 if message == "课堂不存在" else 400)
        db.audit(user["id"], "schedule_students", "session", session_id, f"user_count={len(set(data['user_ids']))}")
        return response({"session_id": session_id, "user_ids": sorted(set(data["user_ids"]))}, message="课堂名单已更新")

    @app.get("/api/admin/emoji/export")
    @authenticated({"admin"})
    def export_csv(user):
        try:
            records = services.list_history(db, user, {**request.args.to_dict(), "limit": 500})
        except (TypeError, ValueError):
            return error("筛选参数无效")
        output = io.StringIO(newline="")
        writer = csv.writer(output, lineterminator="\r\n")
        writer.writerow(["记录ID", "用户名/匿名", "课程", "班级", "情绪类型", "Emoji", "记录时间", "来源", "置信度", "课堂ID"])
        for item in records:
            cells = [item["id"], item["user_name"], item["course_name"], item["class_name"], item["emoji_type"],
                     item["emoji"], item["recorded_at"], item["source"], item["confidence"], item["session_id"]]
            safe = [f"'{value}" if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")) else value for value in cells]
            writer.writerow(safe)
        db.audit(user["id"], "export_csv", "emoji_records", detail=f"rows={len(records)}")
        filename = f"emoji-records-{datetime.now(timezone.utc):%Y%m%d-%H%M%S}.csv"
        return Response("\ufeff" + output.getvalue(), mimetype="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f"attachment; filename={filename}"})

    @app.post("/api/ai/emoji-results")
    def ai_emoji_results():
        service_token = app.config["AI_SERVICE_TOKEN"]
        supplied = request.headers.get("X-AI-Service-Token", "")
        if not service_token or not supplied or not __import__("hmac").compare_digest(service_token, supplied):
            return error("AI 服务令牌无效或未配置", 401)
        data = json_body()
        try:
            session_id = int(data.get("session_id"))
            confidence = float(data.get("confidence"))
        except (TypeError, ValueError):
            return error("session_id 与 confidence 必须为有效数值")
        emoji_type = str(data.get("emoji_type", ""))
        if emoji_type not in EMOTIONS:
            return error("emoji_type 必须是支持的情绪类型")
        if not 0 <= confidence <= 1:
            return error("confidence 必须在 0 到 1 之间")
        threshold = app.config["AI_CONFIDENCE_THRESHOLD"]
        if confidence < threshold:
            return response({"accepted": False, "threshold": threshold}, message="置信度低于阈值，已丢弃")
        session = db.one("SELECT id, starts_at, ends_at, status FROM class_sessions WHERE id = ?", (session_id,))
        if not session:
            return error("课堂不存在", 404)
        try:
            starts = datetime.fromisoformat(session["starts_at"])
            ends = datetime.fromisoformat(session["ends_at"])
            if starts.tzinfo is None:
                starts = starts.replace(tzinfo=timezone.utc)
            if ends.tzinfo is None:
                ends = ends.replace(tzinfo=timezone.utc)
        except ValueError:
            return error("课堂时间设置无效", 409)
        now = datetime.now(timezone.utc)
        if session["status"] != "active" or not (starts <= now <= ends):
            return error("当前课堂未开放 AI 情绪记录", 409)
        try:
            recorded_at = parse_iso(data.get("recorded_at", db.now()), "recorded_at")
        except ValueError as exc:
            return error(str(exc))
        record_id, _ = db.execute(
            "INSERT INTO emoji_records (user_id, session_id, emoji_type, recorded_at, source, confidence, device_id) "
            "VALUES (NULL, ?, ?, ?, 'AI', ?, ?)",
            (session_id, emoji_type, recorded_at, confidence, str(data.get("device_id", "ai-service"))[:80]),
        )
        app.logger.info("AI result accepted session=%s type=%s confidence=%.3f", session_id, emoji_type, confidence)
        return response({"id": record_id, "accepted": True}, 201, "AI 情绪结果已保存")

    @app.errorhandler(404)
    def not_found(_exc):
        return error("请求的资源不存在", 404)

    @app.errorhandler(405)
    def method_not_allowed(_exc):
        return error("请求方法不受支持", 405)

    @app.errorhandler(500)
    def server_error(exc):
        app.logger.exception("Unhandled request error: %s", exc)
        return error("服务器内部错误", 500)

    return app


app = create_app()


if __name__ == "__main__":
    app.run(host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "5000")), debug=False)
