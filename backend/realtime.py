"""WebSocket dashboard stream with authorization checked before every update."""

import json

import jwt

from backend import services
from backend.auth import token_user


def stream_dashboard(ws, db, secret, interval=5):
    try:
        subscription = json.loads(ws.receive(timeout=10) or "{}")
        if not isinstance(subscription, dict):
            raise ValueError("Invalid subscription")
        token = subscription.get("token", "")
        session_id = int(subscription.get("session_id"))
        while True:
            user = token_user(db, token, secret)
            if user["role"] not in {"teacher", "admin"} or not services.can_access_session(db, user, session_id):
                raise jwt.InvalidTokenError("Classroom access revoked")
            dashboard = services.realtime_dashboard(db, session_id)
            if dashboard is None:
                raise jwt.InvalidTokenError("Classroom no longer available")
            dashboard["generated_at"] = db.now()
            ws.send(json.dumps({"data": dashboard}, ensure_ascii=False))
            # Wait without busy polling, and notice disconnects before the next update.
            ws.receive(timeout=interval)
    except (jwt.InvalidTokenError, ValueError, TypeError, KeyError):
        ws.send(json.dumps({"error": "登录凭证已失效或无权订阅该课堂"}, ensure_ascii=False))
        ws.close(reason=1008, message="Dashboard authorization failed")
