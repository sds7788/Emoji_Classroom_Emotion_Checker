# 管理员网页 AI 实时识别

管理员可在“AI 实时识别”页开启浏览器所在电脑的摄像头，实时查看画面、对应emoji、置信度、样本数、采样时间和匿名入库状态。课次ID直接显示，无需另开摄像头推理进程。

## Windows / Miniconda 启动

在Windows的Miniconda Prompt进入项目目录，使用已安装依赖的环境：

```bat
conda activate emoji-classroom
python -m pip install -r requirements-ai.txt
python -m scripts.setup_local
```

编辑本机项目根目录 `.env`，填写已有视觉模型的 `AI_API_KEY`、`AI_BASE_URL` 和 `AI_MODEL`。网页模式直接由后端保存结果，独立命令行进程仍使用 `AI_SERVICE_TOKEN`。密钥不会返回网页。

若Windows默认5000端口无法绑定，可配置：

```dotenv
HOST=127.0.0.1
PORT=8000
BACKEND_URL=http://127.0.0.1:8000
CORS_ORIGINS=http://127.0.0.1:8000,http://localhost:8000
AI_CONFIDENCE_THRESHOLD=0.60
AI_SAMPLE_INTERVAL_SECONDS=5
```

执行 `python -m backend.app`，访问 `http://127.0.0.1:8000`（以实际端口为准）。修改.env后重启后端，已有终端环境变量优先。

## 网页操作

1. 管理员登录，进入新增“AI 实时识别”标签。
2. 选择当前开放且在上课时间的课次，页面直接显示“课次ID”。没有可用课次时先到“课堂排课”创建当天课次，状态选“开放记录”。
3. 点击“开启摄像头并识别”，允许浏览器摄像头权限。开启的是浏览器所在电脑的摄像头，即使后端在WSL或另一台服务器，也不要求后端具有物理摄像头。
4. 左侧持续实时预览，右侧显示最近一次完成识别的emoji与置信度。采样缩略图与结果绑定并标注时间，避免误将旧结果当作当前帧预测。多个人脸时显示样本主导情绪，不分别标注身份或个人情绪。
5. 达标结果保存为 `source=AI、user_id=NULL、device_id=browser-camera`，显示记录ID；教师/管理员选同一课次可查看统计更新，管理员可筛选AI来源导出。
6. 点击“停止识别”释放设备；切换管理标签、退出登录或关闭页面都会停止摄像头和后续采样。已经发给模型的请求可能继续完成，但不会重新显示到已停止的界面。

预览不等待模型返回。网页按比例缩小至最多640×480，向后端发送JPEG采样帧；后端复用OpenCV检测和模型调用，仅将人脸裁片拼图发给模型。每次请求完成后等待 `AI_SAMPLE_INTERVAL_SECONDS` 再采样，默认5秒，不叠加并发请求；模型耗时会延长两次结果之间的间隔。

## 状态说明

| 状态 | 网页表现 | 入库 |
| --- | --- | --- |
| 正常达标 | 大号emoji、情绪名称、置信度、样本数与记录ID | 是，匿名AI |
| 低置信度 | 候选emoji与置信度，标明“置信度不足” | 否 |
| 无人脸 | 清空旧结果，提示调整朝向、距离和光线 | 否，不调用模型 |
| 无法判断/响应非法 | 显示明确提示，下次重试 | 否 |
| 模型失败/超时 | 显示错误，实时预览继续 | 否 |
| 账号撤权/课次结束 | 服务器在模型返回后、保存前再次检查并拒绝 | 否 |

摄像头访问需要localhost、127.0.0.1或HTTPS；通过局域网IP的HTTP地址访问时浏览器可能不提供摄像头API，远程使用请部署HTTPS。拒绝权限后可在地址栏站点权限中重新允许。设备被占用时，先停止旧的 `python -m backend.ai_service`、视频会议或OBS摄像头来源。

图像仅在浏览器及后端内存处理，不保存至数据库或磁盘；只有结构化结果入库，响应禁止缓存。参与者同意及裁片外发说明见 [AI接入指南](ai-integration.md)。

## 接口和验证

- `GET /api/admin/ai/status`：仅管理员；返回配置是否齐全、模型、阈值与间隔，不返回凭据。
- `POST /api/admin/ai/analyze`：仅管理员；接收实际session_id及JPEG Data URL；返回emoji、置信度、样本数、丢弃原因或记录ID。
- 请求最多2MiB，JPEG文本最多750,000字符，解码最大1920×1080；已有模型请求运行时返回429。调用前后均检查课次与权限。

接口测试：`python -m unittest tests.test_ai_web -v`。浏览器验收：安装requirements-dev.txt及Chromium后执行 `python -m scripts.ai_browser_acceptance`，默认结果在artifacts/ai-browser。

浏览器验收使用Chromium合成摄像头与受控模型响应，通过真实HTTP和临时SQLite验证画面、emoji、保存、停止、切页、窄屏、缺配置及拒绝权限。不使用真实人脸或外部模型，不能代替用户电脑的真实模型实测。
