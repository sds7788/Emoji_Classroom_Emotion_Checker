"""Exercise browser camera controls with synthetic video and simulated predictions.

No physical camera or external model is used. The real HTTP API and database run
against an isolated temporary server. Requires requirements-dev.txt and Chromium.
"""

import argparse
import json
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import requests
from playwright.sync_api import expect, sync_playwright
from werkzeug.serving import make_server

from backend.app import create_app


def run(output):
    output.mkdir(parents=True, exist_ok=True)
    steps, errors = [], []
    zone = timezone(timedelta(hours=8))
    report = {"started_at": datetime.now(zone).isoformat(timespec="seconds"),
              "camera": "Chromium synthetic camera", "model": "simulated predictions; no external API calls",
              "steps": steps}

    def record(name, actual, screenshot=None):
        steps.append({"name": name, "status": "passed", "actual": actual,
                      **({"screenshot": screenshot} if screenshot else {})})
        print("PASS " + name, flush=True)

    with tempfile.TemporaryDirectory(prefix="emoji-ai-browser-") as temporary:
        app = create_app({"TESTING": True, "DATABASE_PATH": str(Path(temporary) / "test.db"),
                          "SECRET_KEY": "browser-camera-test-secret-at-least-32-bytes", "SEED_DEMO_DATA": True,
                          "AI_API_KEY": "private-fake-browser-model-key", "AI_MODEL": "模拟视觉模型",
                          "AI_BASE_URL": "https://not-called.invalid/v1", "AI_CONFIDENCE_THRESHOLD": 0.6,
                          "AI_SAMPLE_INTERVAL_SECONDS": 1})
        db = app.extensions["emotion_repository"]
        session_id = db.one("SELECT id FROM class_sessions WHERE status = 'active'")["id"]
        server = make_server("127.0.0.1", 0, app, threaded=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        phase = {"value": "accepted", "calls": 0}

        def predict(*_args):
            phase["calls"] += 1
            if phase["value"] == "error":
                response = requests.Response()
                response.status_code = 401
                raise requests.HTTPError("private-fake-browser-model-key", response=response)
            return dict({
                "accepted": {"accepted": True, "emoji_type": "happy", "confidence": 0.91, "samples": 1},
                "low": {"accepted": False, "reason": "low_confidence", "emoji_type": "confused", "confidence": 0.4, "samples": 1},
                "no_face": {"accepted": False, "reason": "no_face_detected"},
            }[phase["value"]])

        with patch("backend.ai_web.infer_frame", side_effect=predict):
            thread.start()
            try:
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"])
                    report["browser"] = "Chromium " + browser.version
                    context = browser.new_context(viewport={"width": 1440, "height": 1080}, permissions=["camera"], timezone_id="Asia/Shanghai")
                    page = context.new_page()
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(f"http://127.0.0.1:{server.server_port}")
                    page.locator("#authUsername").fill("admin")
                    page.locator("#authPassword").fill("admin12345")
                    page.locator("#authSubmit").click()
                    expect(page.locator("#adminView")).to_be_visible()
                    page.locator('[data-admin-tab="ai"]').click()
                    page.locator("#aiSessionSelect").select_option(str(session_id))
                    expect(page.locator("#aiSessionInfo")).to_contain_text(f"课次 ID：{session_id}")
                    expect(page.locator("#aiStartButton")).to_be_enabled()
                    record("管理员识别入口与课次ID", "入口可用；课次ID直接显示")

                    page.locator("#aiStartButton").click()
                    expect(page.locator("#aiCameraVideo")).to_be_visible()
                    expect(page.locator("#aiResultLabel")).to_have_text("开心", timeout=12000)
                    expect(page.locator("#aiResultEmoji")).to_have_text("😊")
                    expect(page.locator("#aiResultConfidence")).to_have_text("91%")
                    expect(page.locator("#aiResultSaved")).to_contain_text("已入库")
                    expect(page.locator("#aiSampleImage")).to_be_visible()
                    assert page.evaluate("document.querySelector('#aiCameraVideo').videoWidth > 0")
                    assert db.one("SELECT COUNT(*) AS n FROM emoji_records WHERE source = 'AI'")["n"] >= 1
                    page.screenshot(path=str(output / "01-live-result.png"), full_page=True)
                    record("浏览器画面与emoji对应", "合成摄像头实时预览；开心😊、91%、对应采样缩略图与匿名入库成功", "01-live-result.png")

                    phase["value"] = "low"
                    expect(page.locator("#aiResultStatus")).to_have_text("置信度不足", timeout=10000)
                    expect(page.locator("#aiResultEmoji")).to_have_text("😕")
                    expect(page.locator("#aiResultConfidence")).to_have_text("40%")
                    expect(page.locator("#aiResultSaved")).to_have_text("本次未入库")
                    page.screenshot(path=str(output / "02-low-confidence.png"), full_page=True)
                    record("低置信度显示", "显示困惑😕和40%，明确标注未入库", "02-low-confidence.png")

                    phase["value"] = "no_face"
                    expect(page.locator("#aiResultLabel")).to_have_text("未检测到人脸", timeout=10000)
                    expect(page.locator("#aiResultEmoji")).to_have_text("—")
                    expect(page.locator("#aiResultConfidence")).to_have_text("—")
                    record("无人脸不沿用上一结果", "清除旧emoji与置信度，显示无人脸提示")

                    phase["value"] = "error"
                    expect(page.locator("#aiResultLabel")).to_have_text("识别暂不可用", timeout=10000)
                    expect(page.locator("#aiResultDescription")).to_contain_text("401")
                    assert "private-fake-browser-model-key" not in page.content()
                    record("模型错误与密钥保护", "显示请求失败与HTTP401，页面不包含密钥")

                    page.evaluate("window.testAiTrack = aiMonitor.stream.getVideoTracks()[0]")
                    page.locator("#aiStopButton").click()
                    expect(page.locator("#aiVideoPlaceholder")).to_be_visible()
                    assert page.evaluate("window.testAiTrack.readyState === 'ended'")
                    calls = phase["calls"]
                    page.wait_for_timeout(1300)
                    assert phase["calls"] == calls
                    assert not page.locator("#aiSampleImage").get_attribute("src")
                    record("停止释放设备并停止采样", "视频轨道ended；后续无新请求；清除采样图像")

                    phase["value"] = "accepted"
                    page.locator("#aiStartButton").click()
                    expect(page.locator("#aiResultStatus")).to_have_text("已保存", timeout=10000)
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.screenshot(path=str(output / "03-mobile.png"), full_page=True)
                    record("390px实时识别布局", "摄像头与结果纵向排列，无页面水平溢出", "03-mobile.png")

                    page.evaluate("window.testAiTrack = aiMonitor.stream.getVideoTracks()[0]")
                    page.locator('[data-admin-tab="overview"]').click()
                    assert page.evaluate("window.testAiTrack.readyState === 'ended'")
                    assert page.evaluate("aiMonitor.stream === null")
                    record("切换页面停止采集", "切换数据概览后摄像头轨道释放")

                    app.config["AI_API_KEY"] = ""
                    page.locator('[data-admin-tab="ai"]').click()
                    expect(page.locator("#aiCameraMessage")).to_contain_text("填写 AI_API_KEY")
                    expect(page.locator("#aiStartButton")).to_be_disabled()
                    record("未配置模型的引导", "提示在服务端配置并重启，禁用开始按钮")

                    app.config["AI_API_KEY"] = "private-fake-browser-model-key"
                    page.locator('[data-admin-tab="overview"]').click()
                    page.locator('[data-admin-tab="ai"]').click()
                    expect(page.locator("#aiStartButton")).to_be_enabled()
                    page.evaluate("() => { navigator.mediaDevices.getUserMedia = async () => { throw new DOMException('Permission denied', 'NotAllowedError'); }; }")
                    page.locator("#aiStartButton").click()
                    expect(page.locator("#aiCameraMessage")).to_contain_text("摄像头权限被拒绝")
                    expect(page.locator("#aiStartButton")).to_be_enabled()
                    record("摄像头权限拒绝", "给出可操作提示，恢复开始按钮")
                    assert not errors, errors
                    record("浏览器脚本异常", "pageerror为0")
                    context.close()
                    browser.close()
                report["status"] = "passed"
            except Exception as exc:
                report["status"] = "failed"
                report["failure"] = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                server.shutdown()
                thread.join(timeout=5)
                server.server_close()
                report["finished_at"] = datetime.now(zone).isoformat(timespec="seconds")
                report["page_errors"] = errors
                (output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"验收结果：{output / 'results.json'}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("artifacts/ai-browser"))
    run(parser.parse_args().output.resolve())
