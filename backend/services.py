"""Business rules shared by the HTTP controllers."""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from backend.database import EMOTIONS


def csv_safe_cell(value):
    if isinstance(value, str) and (value.startswith(("\t", "\r", "\n"))
                                 or value.lstrip().startswith(("=", "+", "-", "@"))):
        return "'" + value
    return value


class AISessionNotFound(LookupError):
    pass


class AISessionClosed(RuntimeError):
    pass


def require_open_ai_session(db, session_id):
    session = db.one("SELECT id, starts_at, ends_at, status FROM class_sessions WHERE id = ?", (session_id,))
    if not session:
        raise AISessionNotFound("课堂不存在")
    try:
        starts = datetime.fromisoformat(session["starts_at"])
        ends = datetime.fromisoformat(session["ends_at"])
        if starts.tzinfo is None:
            starts = starts.replace(tzinfo=timezone.utc)
        if ends.tzinfo is None:
            ends = ends.replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise AISessionClosed("课堂时间设置无效") from exc
    if session["status"] != "active" or not starts <= datetime.now(timezone.utc) <= ends:
        raise AISessionClosed("当前课堂未开放 AI 情绪记录")
    return session


def save_ai_result(db, session_id, emoji_type, confidence, device_id, recorded_at=None):
    require_open_ai_session(db, session_id)
    record_id, _ = db.execute(
        "INSERT INTO emoji_records (user_id, session_id, emoji_type, recorded_at, source, confidence, device_id) "
        "VALUES (NULL, ?, ?, ?, 'AI', ?, ?)",
        (session_id, emoji_type, recorded_at or db.now(), confidence, str(device_id)[:80]),
    )
    return {"id": record_id, "accepted": True}


def register_user(db, username, password_hash, role, full_name, email, registration_code, bootstrap_token):
    """Create an account and consume its invitation in one serialized transaction."""
    with db.connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        invitation = None
        if role != "student":
            invitation = connection.execute(
                "SELECT id FROM registration_invitations WHERE code_hash = ? AND role = ? "
                "AND used_at IS NULL AND expires_at > ?",
                (hashlib.sha256(registration_code.encode()).hexdigest(), role, db.now()),
            ).fetchone()
            bootstrap_allowed = (
                role == "admin" and bool(bootstrap_token) and bool(registration_code)
                and hmac.compare_digest(bootstrap_token.encode(), registration_code.encode())
                and not connection.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1").fetchone()
                and not connection.execute("SELECT id FROM audit_logs WHERE action = 'admin_bootstrap' LIMIT 1").fetchone()
            )
            if invitation is None and not bootstrap_allowed:
                raise PermissionError("邀请码无效、已使用或已过期；管理员初始化仅限尚无管理员的数据库")
        now = db.now()
        cursor = connection.execute(
            "INSERT INTO users (username, password_hash, role, full_name, email, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (username, password_hash, role, full_name, email, now),
        )
        user_id = cursor.lastrowid
        if invitation:
            connection.execute(
                "UPDATE registration_invitations SET used_at = ?, used_by = ? WHERE id = ?",
                (now, user_id, invitation["id"]),
            )
        connection.execute(
            "INSERT INTO audit_logs (actor_id, action, target_type, target_id, detail, created_at) VALUES (?, 'register', 'user', ?, ?, ?)",
            (user_id, str(user_id), f"role={role}", now),
        )
        if role == "admin" and invitation is None:
            connection.execute(
                "INSERT INTO audit_logs (actor_id, action, target_type, target_id, created_at) VALUES (?, 'admin_bootstrap', 'user', ?, ?)",
                (user_id, str(user_id), now),
            )
    return user_id


def issue_invitation(db, actor_id, role, expires_in_hours):
    code = secrets.token_urlsafe(24)
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=expires_in_hours)).isoformat(timespec="seconds")
    invitation_id, _ = db.execute(
        "INSERT INTO registration_invitations (code_hash, role, created_by, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
        (hashlib.sha256(code.encode()).hexdigest(), role, actor_id, expires_at, db.now()),
    )
    db.audit(actor_id, "create_invitation", "invitation", invitation_id, f"role={role};expires_at={expires_at}")
    return {"id": invitation_id, "code": code, "role": role, "expires_at": expires_at}


def _filters(params):
    clauses = []
    values = []
    if params.get("session_id"):
        clauses.append("r.session_id = ?")
        values.append(int(params["session_id"]))
    if params.get("course_id"):
        clauses.append("c.id = ?")
        values.append(int(params["course_id"]))
    if params.get("class_name"):
        clauses.append("s.class_name = ?")
        values.append(params["class_name"])
    boundaries = {}
    for field in ("from", "to"):
        if params.get(field):
            value = datetime.fromisoformat(params[field].replace("Z", "+00:00"))
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            boundaries[field] = value.astimezone(timezone.utc).isoformat(timespec="seconds")
    if boundaries.get("from") and boundaries.get("to") and boundaries["from"] > boundaries["to"]:
        raise ValueError("开始时间不能晚于结束时间")
    if boundaries.get("from"):
        clauses.append("r.recorded_at >= ?")
        values.append(boundaries["from"])
    if boundaries.get("to"):
        clauses.append("r.recorded_at <= ?")
        values.append(boundaries["to"])
    if params.get("source") in {"MANUAL", "AI"}:
        clauses.append("r.source = ?")
        values.append(params["source"])
    return clauses, values


def list_sessions(db, user):
    scope = ""
    params = []
    if user["role"] == "student":
        scope = "WHERE EXISTS (SELECT 1 FROM schedule_users su_scope WHERE su_scope.session_id = s.id AND su_scope.user_id = ?)"
        params.append(user["id"])
    elif user["role"] == "teacher":
        scope = "WHERE c.teacher_id = ?"
        params.append(user["id"])
    query = f"""
        SELECT s.id, s.course_id, c.course_code, c.name AS course_name, c.teacher_id,
               t.full_name AS teacher_name, s.class_name, s.room, s.starts_at, s.ends_at,
               s.status, COUNT(DISTINCT su.user_id) AS student_count,
               MAX(CASE WHEN su.user_id = ? THEN 1 ELSE 0 END) AS is_scheduled
        FROM class_sessions s
        JOIN courses c ON c.id = s.course_id
        JOIN users t ON t.id = c.teacher_id
        LEFT JOIN schedule_users su ON su.session_id = s.id
        {scope}
        GROUP BY s.id
        ORDER BY s.starts_at DESC
    """
    if user["role"] == "student":
        params.insert(0, user["id"])
    else:
        params.insert(0, -1)
    return db.all(query, params)


def can_access_session(db, user, session_id):
    row = db.one(
        "SELECT s.id, c.teacher_id FROM class_sessions s JOIN courses c ON c.id = s.course_id WHERE s.id = ?",
        (session_id,),
    )
    if not row:
        return False
    if user["role"] == "admin":
        return True
    if user["role"] == "teacher":
        return row["teacher_id"] == user["id"]
    return bool(db.one("SELECT id FROM schedule_users WHERE session_id = ? AND user_id = ?", (session_id, user["id"])))


def list_history(db, user, params):
    clauses, values = _filters(params)
    if user["role"] == "student":
        clauses.append("r.user_id = ?")
        values.append(user["id"])
    elif user["role"] == "teacher":
        clauses.append("c.teacher_id = ?")
        values.append(user["id"])
    if user["role"] == "admin" and params.get("user_id"):
        clauses.append("r.user_id = ?")
        values.append(int(params["user_id"]))
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    limit = min(max(int(params.get("limit", 100)), 1), 500)
    return db.all(
        f"""
        SELECT r.id, r.user_id, COALESCE(u.full_name, '匿名 AI 汇总') AS user_name,
               r.session_id, c.name AS course_name, s.class_name, r.emoji_type,
               r.recorded_at, r.source, r.confidence, r.device_id,
               e.emoji, e.label
        FROM emoji_records r
        JOIN class_sessions s ON s.id = r.session_id
        JOIN courses c ON c.id = s.course_id
        LEFT JOIN users u ON u.id = r.user_id
        JOIN (SELECT 'happy' AS code, '😊' AS emoji, '开心' AS label
              UNION ALL SELECT 'confused', '😕', '困惑'
              UNION ALL SELECT 'bored', '😐', '无聊'
              UNION ALL SELECT 'sad', '😔', '低落'
              UNION ALL SELECT 'focused', '🤔', '专注'
              UNION ALL SELECT 'excited', '🤩', '兴奋') e ON e.code = r.emoji_type
        {where}
        ORDER BY r.recorded_at DESC, r.id DESC LIMIT ?
        """,
        [*values, limit],
    )


def statistics(db, user, params):
    clauses, values = _filters(params)
    if user["role"] == "student":
        clauses.append("r.user_id = ?")
        values.append(user["id"])
    elif user["role"] == "teacher":
        clauses.append("c.teacher_id = ?")
        values.append(user["id"])
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    base = f"""
        FROM emoji_records r JOIN class_sessions s ON s.id = r.session_id
        JOIN courses c ON c.id = s.course_id {where}
    """
    total = db.one(f"SELECT COUNT(*) AS total {base}", values)["total"]
    grouped = db.all(f"SELECT r.emoji_type, COUNT(*) AS count {base} GROUP BY r.emoji_type", values)
    counts = {row["emoji_type"]: row["count"] for row in grouped}
    emotion_counts = [
        {"type": key, "emoji": emoji, "label": label, "count": counts.get(key, 0),
         "share": round((counts.get(key, 0) / total), 4) if total else 0}
        for key, (emoji, label) in EMOTIONS.items()
    ]
    by_session = db.all(
        f"SELECT s.id AS session_id, c.name AS course_name, s.class_name, s.starts_at, COUNT(r.id) AS total {base} GROUP BY s.id ORDER BY s.starts_at DESC LIMIT 30",
        values,
    )
    trend = db.all(
        f"SELECT strftime('%Y-%m-%d', r.recorded_at) AS day, r.emoji_type, COUNT(*) AS count {base} GROUP BY day, r.emoji_type ORDER BY day",
        values,
    )
    by_course = db.all(
        f"SELECT c.id AS course_id, c.name AS course_name, COUNT(*) AS total {base} GROUP BY c.id ORDER BY total DESC, c.id",
        values,
    )
    by_class = db.all(
        f"SELECT s.class_name, COUNT(*) AS total {base} GROUP BY s.class_name ORDER BY total DESC, s.class_name",
        values,
    )
    return {"total": total, "emotions": emotion_counts, "by_session": by_session, "daily_trend": trend,
            "by_course": by_course, "by_class": by_class}


def realtime_dashboard(db, session_id):
    session = db.one(
        "SELECT s.id, s.class_name, s.room, s.starts_at, s.ends_at, s.status, c.name AS course_name "
        "FROM class_sessions s JOIN courses c ON c.id = s.course_id WHERE s.id = ?",
        (session_id,),
    )
    if not session:
        return None
    now = datetime.now(timezone.utc).replace(microsecond=0)
    window_start = now - timedelta(minutes=60)
    records = db.all(
        "SELECT emoji_type, recorded_at, source FROM emoji_records "
        "WHERE session_id = ? AND recorded_at >= ? AND recorded_at <= ? ORDER BY recorded_at",
        (session_id, window_start.isoformat(timespec="seconds"), now.isoformat(timespec="seconds")),
    )
    counts = {key: 0 for key in EMOTIONS}
    for row in records:
        counts[row["emoji_type"]] += 1
    bucket_start = window_start
    buckets = []
    for offset in range(12):
        start = bucket_start + timedelta(minutes=offset * 5)
        buckets.append({"time": start.isoformat(timespec="seconds"), **{key: 0 for key in EMOTIONS}})
    for row in records:
        try:
            recorded = datetime.fromisoformat(row["recorded_at"])
            index = min(11, int((recorded - bucket_start).total_seconds() // 300))
            if 0 <= index < len(buckets):
                buckets[index][row["emoji_type"]] += 1
        except (TypeError, ValueError):
            continue
    recent = db.all(
        "SELECT r.id, r.user_id, COALESCE(u.full_name, '匿名 AI 汇总') AS user_name, r.emoji_type, "
        "r.recorded_at, r.source, r.confidence FROM emoji_records r LEFT JOIN users u ON u.id = r.user_id "
        "WHERE r.session_id = ? AND r.recorded_at >= ? AND r.recorded_at <= ? ORDER BY r.recorded_at DESC, r.id DESC LIMIT 30",
        (session_id, window_start.isoformat(timespec="seconds"), now.isoformat(timespec="seconds")),
    )
    for item in recent:
        emoji, label = EMOTIONS[item["emoji_type"]]
        item["emoji"] = emoji
        item["label"] = label
    return {
        "session": session,
        "total_last_hour": len(records),
        "counts": [
            {"type": key, "emoji": emoji, "label": label, "count": counts[key]}
            for key, (emoji, label) in EMOTIONS.items()
        ],
        "trend": buckets,
        "recent": recent,
    }


def list_users(db):
    return db.all(
        "SELECT id, username, role, full_name, email, status, created_at, last_login FROM users ORDER BY created_at DESC"
    )


def update_user(db, user_id, role=None, status=None):
    with db.connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        user = connection.execute("SELECT role, status FROM users WHERE id = ?", (user_id,)).fetchone()
        if user is None:
            return None
        role = user["role"] if role is None else role
        status = user["status"] if status is None else status
        if (not isinstance(role, str) or role not in {"student", "teacher", "admin"}
                or not isinstance(status, str) or status not in {"active", "disabled"}):
            raise ValueError("角色或账号状态无效")
        if user["role"] == "admin" and user["status"] == "active" and (role != "admin" or status != "active"):
            remaining = connection.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin' AND status = 'active' AND id != ?", (user_id,),
            ).fetchone()[0]
            if not remaining:
                raise ValueError("不能停用或降级最后一名启用的管理员")
        connection.execute(
            "UPDATE users SET role = ?, status = ?, token_version = token_version + ? WHERE id = ?",
            (role, status, int(role != user["role"] or status != user["status"]), user_id),
        )
    return db.get_user_by_id(user_id)


def list_courses(db):
    return db.all(
        "SELECT c.id, c.course_code, c.name, c.teacher_id, u.full_name AS teacher_name "
        "FROM courses c JOIN users u ON u.id = c.teacher_id ORDER BY c.name"
    )


def create_course(db, data):
    now = db.now()
    course_id, _ = db.execute(
        "INSERT INTO courses (course_code, name, teacher_id, created_at) VALUES (?, ?, ?, ?)",
        (data["course_code"], data["name"], data["teacher_id"], now),
    )
    return course_id


def create_session(db, data):
    session_id, _ = db.execute(
        "INSERT INTO class_sessions (course_id, class_name, room, starts_at, ends_at, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (data["course_id"], data["class_name"], data.get("room", ""), data["starts_at"], data["ends_at"], data.get("status", "scheduled"), db.now()),
    )
    return session_id


def schedule_students(db, session_id, user_ids):
    if not db.one("SELECT id FROM class_sessions WHERE id = ?", (session_id,)):
        return False, "课堂不存在"
    if not isinstance(user_ids, list) or any(type(item) is not int for item in user_ids):
        return False, "user_ids 必须是整数列表"
    if user_ids:
        placeholders = ",".join("?" for _ in user_ids)
        count = db.one(
            f"SELECT COUNT(*) AS count FROM users WHERE role = 'student' AND status = 'active' AND id IN ({placeholders})",
            user_ids,
        )["count"]
        if count != len(set(user_ids)):
            return False, "名单包含不存在、停用或非学生账号"
    scheduled_at = db.now()
    with db.connection() as connection:
        connection.execute("DELETE FROM schedule_users WHERE session_id = ?", (session_id,))
        connection.executemany(
            "INSERT INTO schedule_users (session_id, user_id, scheduled_at) VALUES (?, ?, ?)",
            [(session_id, user_id, scheduled_at) for user_id in sorted(set(user_ids))],
        )
    return True, None
