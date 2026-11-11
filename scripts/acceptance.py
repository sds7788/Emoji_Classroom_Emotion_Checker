"""Run a real browser workflow against a disposable local server and database.

Usage: python -m scripts.acceptance --output artifacts/acceptance
Requires requirements-dev.txt and `python -m playwright install chromium`.
"""

import argparse
import csv
import io
import json
import os
import platform
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
import requests
import websocket
from playwright.sync_api import expect, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
LOCAL_ZONE = timezone(timedelta(hours=8))


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    steps = []
    errors = []
    report = {"started_at": datetime.now(LOCAL_ZONE).isoformat(timespec="seconds"),
              "python": platform.python_version(), "platform": platform.platform(),
              "ai_verification": "simulated API ingestion only; no real camera or external model",
              "steps": steps}

    def record(name, expected, actual, screenshot=None):
        steps.append({"name": name, "expected": expected, "actual": actual, "status": "passed",
                      **({"screenshot": screenshot} if screenshot else {})})
        print(f"PASS {name}", flush=True)

    http = requests.Session()
    http.trust_env = False
    with tempfile.TemporaryDirectory(prefix="emoji-acceptance-") as temporary:
        with socket.socket() as port_socket:
            port_socket.bind(("127.0.0.1", 0))
            port = port_socket.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        signing_key, ai_token = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
        env = {**os.environ, "DATABASE_PATH": str(Path(temporary) / "acceptance.db"),
               "JWT_SECRET": signing_key, "AI_SERVICE_TOKEN": ai_token, "AI_CONFIDENCE_THRESHOLD": "0.6",
               "SEED_DEMO_DATA": "true", "ADMIN_BOOTSTRAP_TOKEN": "", "HOST": "127.0.0.1", "PORT": str(port)}
        env.pop("AI_API_KEY", None)
        with (output / "server.log").open("w", encoding="utf-8") as server_log:
            server = subprocess.Popen([sys.executable, "-m", "backend.app"], cwd=ROOT, env=env,
                                      stdout=server_log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 20
                while True:
                    try:
                        if http.get(base + "/health", timeout=1).status_code == 200:
                            break
                    except requests.RequestException:
                        pass
                    if server.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Temporary server did not start; see server.log")
                    time.sleep(0.2)
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch()
                    report["browser"] = "Chromium " + browser.version
                    contexts = [browser.new_context(viewport={"width": 1440, "height": 1000}, timezone_id="Asia/Shanghai") for _ in range(3)]
                    admin, student, teacher = [context.new_page() for context in contexts]
                    for page in (admin, student, teacher):
                        page.on("pageerror", lambda error: errors.append(str(error)))

                    def login(page, username):
                        page.goto(base)
                        page.locator("#authUsername").fill(username)
                        page.locator("#authPassword").fill(username + "12345")
                        page.locator("#authSubmit").click()
                        expect(page.locator("#logoutButton")).to_be_visible()

                    login(admin, "admin")
                    headers = {"Authorization": "Bearer " + admin.evaluate("localStorage.getItem('emotionToken')")}
                    admin.locator('[data-admin-tab="schedule"]').click()
                    admin.locator('#courseForm [name="course_code"]').fill("E2E-101")
                    admin.locator('#courseForm [name="name"]').fill("端到端验收课程")
                    admin.locator('#courseForm button').click()
                    expect(admin.locator("#courseFormMessage")).to_have_text("课程已创建")
                    courses = http.get(base + "/api/admin/courses", headers=headers).json()["data"]
                    course = next(item for item in courses if item["course_code"] == "E2E-101")
                    admin.locator("#scheduleCourse").select_option(str(course["id"]))
                    admin.locator('#sessionForm [name="class_name"]').fill("端到端验收班")
                    admin.locator('#sessionForm [name="room"]').fill("验收教室")
                    now = datetime.now(LOCAL_ZONE)
                    for field, value in (("starts_at", now - timedelta(minutes=5)), ("ends_at", now + timedelta(hours=2))):
                        admin.locator(f'#sessionForm [name="{field}"]').fill(value.strftime("%Y-%m-%dT%H:%M"))
                    admin.locator('#sessionForm [name="status"]').select_option("active")
                    admin.locator('#sessionForm button').click()
                    expect(admin.locator("#sessionFormMessage")).to_have_text("课堂已创建")
                    sessions = http.get(base + "/api/admin/sessions", headers=headers).json()["data"]
                    session_id = next(item["id"] for item in sessions if item["course_id"] == course["id"])
                    admin.locator("#rosterSessionSelect").select_option(str(session_id))
                    admin.locator("#studentRoster input").check()
                    admin.locator("#saveScheduleButton").click()
                    expect(admin.locator("#scheduleMessage")).to_contain_text("已安排 1 名学生")
                    admin.screenshot(path=str(output / "01-schedule.png"), full_page=True)
                    record("管理员创建课程、课次并保存名单", "创建成功且安排1名学生", "新课次已安排1名学生", "01-schedule.png")

                    login(student, "student")
                    student.locator("#studentSessionSelect").select_option(str(session_id))
                    student.locator('[data-emoji="focused"]').click()
                    expect(student.locator("#checkinMessage")).to_contain_text("已记录")
                    expect(student.locator("#studentRecentHistory")).to_contain_text("专注")
                    student.screenshot(path=str(output / "02-student.png"), full_page=True)
                    record("学生提交与个人历史", "专注记录成功并显示手动来源", "专注记录已显示", "02-student.png")

                    login(teacher, "teacher")
                    teacher.locator("#teacherSessionSelect").select_option(str(session_id))
                    expect(teacher.locator("#metricTotal")).to_have_text("1")
                    expect(teacher.locator("#metricFocused")).to_have_text("100%")
                    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
                    teacher.locator("#teacherFromFilter").fill(yesterday)
                    teacher.locator("#teacherToFilter").fill(yesterday)
                    teacher.locator("#teacherApplyFilter").click()
                    expect(teacher.locator("#teacherHistorySummary")).to_contain_text("共 1 条")
                    expect(teacher.locator("#metricPositive")).to_have_text("0%")
                    expect(teacher.locator("#metricFocused")).to_have_text("100%")
                    before_distribution = teacher.locator("#emotionDistribution").inner_text()
                    # A second check-in must arrive through the existing real WebSocket.
                    teacher.wait_for_function("state.dashboardSocket?.readyState === WebSocket.OPEN")
                    student.locator('[data-emoji="happy"]').click()
                    expect(teacher.locator("#metricTotal")).to_have_text("2", timeout=12000)
                    expect(teacher.locator("#metricPositive")).to_have_text("50%")
                    expect(teacher.locator("#metricFocused")).to_have_text("50%")
                    assert teacher.locator("#emotionDistribution").inner_text() == before_distribution
                    teacher.screenshot(path=str(output / "03-teacher.png"), full_page=True)
                    record("教师实时更新与历史筛选口径", "近一小时2条、积极50%、专注50%，昨日分布保持1条", "全部满足，历史分布未被实时推送覆盖", "03-teacher.png")

                    admin.locator('[data-admin-tab="overview"]').click()
                    admin.locator("#adminLiveSessionSelect").select_option(str(session_id))
                    admin.locator("#adminStatsCourseFilter").select_option(str(course["id"]))
                    admin.locator("#adminStatsClassFilter").select_option("端到端验收班")
                    admin.locator("#adminApplyStatsFilter").click()
                    expect(admin.locator("#adminRecordCount")).to_have_text("2")
                    expect(admin.locator("#adminLiveTotal")).to_have_text("2")
                    admin.screenshot(path=str(output / "04-admin.png"), full_page=True)
                    record("管理员课程、班级统计和实时看板", "筛选总数2、实时总数2", "两个区域均为2", "04-admin.png")

                    dropped = http.post(base + "/api/ai/emoji-results", headers={"X-AI-Service-Token": ai_token},
                                        json={"session_id": session_id, "emoji_type": "sad", "confidence": 0.2})
                    assert dropped.status_code == 200 and not dropped.json()["data"]["accepted"]
                    accepted = http.post(base + "/api/ai/emoji-results", headers={"X-AI-Service-Token": ai_token},
                                         json={"session_id": session_id, "emoji_type": "focused", "confidence": 0.91})
                    assert accepted.status_code == 201
                    expect(admin.locator("#adminLiveTotal")).to_have_text("3", timeout=12000)
                    admin.locator('[data-admin-tab="records"]').click()
                    admin.locator("#adminRecordSession").select_option(str(session_id))
                    admin.locator("#adminRecordSource").select_option("AI")
                    admin.locator("#adminRecordSearch").click()
                    expect(admin.locator("#adminRecordsTable")).to_contain_text("匿名 AI 汇总")
                    with admin.expect_download() as download_event:
                        admin.locator("#exportCsvButton").click()
                    download_event.value.save_as(str(output / "export.csv"))
                    rows = list(csv.reader(io.StringIO((output / "export.csv").read_text(encoding="utf-8-sig"))))
                    assert len(rows) == 2 and rows[1][7] == "AI" and rows[1][1] == "匿名 AI 汇总"
                    admin.screenshot(path=str(output / "05-export.png"), full_page=True)
                    record("模拟AI过滤、匿名入库、看板与CSV下载", "低置信度丢弃；达标结果进入看板并导出1条匿名AI记录", "全部满足；仅验证模拟接口结果，未调用真实模型", "05-export.png")

                    teacher_token = teacher.evaluate("localStorage.getItem('emotionToken')")
                    teacher_id = http.get(base + "/api/users/me", headers={"Authorization": "Bearer " + teacher_token}).json()["data"]["id"]
                    with closing(websocket.create_connection(base.replace("http://", "ws://") + "/ws/dashboard", timeout=10)) as live:
                        live.send(json.dumps({"token": teacher_token, "session_id": session_id}))
                        assert "data" in json.loads(live.recv())
                        assert http.put(base + f"/api/admin/users/{teacher_id}", headers=headers, json={"status": "disabled"}).status_code == 200
                        assert "error" in json.loads(live.recv())
                    record("真实WebSocket停用撤权", "既有连接下一次推送前拒绝访问", "收到error并结束订阅")
                    admin_user = http.get(base + "/api/users/me", headers=headers).json()["data"]
                    short_token = jwt.encode({"user_id": admin_user["id"], "username": admin_user["username"],
                                              "token_version": admin_user["token_version"], "exp": datetime.now(timezone.utc) + timedelta(seconds=2)}, signing_key, algorithm="HS256")
                    with closing(websocket.create_connection(base.replace("http://", "ws://") + "/ws/dashboard", timeout=10)) as live:
                        live.send(json.dumps({"token": short_token, "session_id": session_id}))
                        assert "data" in json.loads(live.recv())
                        assert "error" in json.loads(live.recv())
                    record("真实WebSocket令牌过期", "连接建立后JWT过期，下一次推送拒绝访问", "收到error并结束订阅")

                    admin.set_viewport_size({"width": 390, "height": 844})
                    assert admin.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    admin.screenshot(path=str(output / "06-mobile.png"), full_page=True)
                    record("390px窄屏", "页面无水平溢出", "无水平溢出", "06-mobile.png")
                    assert not errors, errors
                    record("浏览器脚本异常", "0条pageerror", "0条pageerror")
                    browser.close()
                report["status"] = "passed"
            except Exception as exc:
                report["status"] = "failed"
                report["failure"] = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                server.terminate()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.kill()
                    server.wait()
                report["finished_at"] = datetime.now(LOCAL_ZONE).isoformat(timespec="seconds")
                report["page_errors"] = errors
                (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"验收记录已写入 {output / 'results.json'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/acceptance"))
    run(parser.parse_args().output.resolve())
