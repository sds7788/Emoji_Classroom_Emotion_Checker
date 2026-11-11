# AI 接入与真实链路验收

管理员现在可直接在网页查看摄像头与emoji：完成模型配置后启动后端，进入“AI 实时识别”，选择开放课次并点击“开启摄像头并识别”。该模式使用浏览器摄像头，无需运行独立摄像头命令，见 [网页识别指南](ai-web-monitor.md)。以下命令行方式继续保留。

本项目先用本地 OpenCV 检测/裁剪人脸，再通过 OpenAI 兼容的 `POST /chat/completions` 调用视觉模型。本地与后端分别过滤置信度，达标结果以 `source=AI、user_id=NULL` 入库并进入看板。完整帧和脸部拼图均不保存到磁盘。

本轮已完成模拟模型响应到真实后端、SQLite、统计和导出的自动化验证。尚无真实模型凭据和可用摄像头，因此真实 AI 验收仍待在演示电脑完成。

## 1. 安装与配置

在项目根目录执行。Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-ai.txt
.\.venv\Scripts\python.exe -m scripts.setup_local
notepad .env
```

Linux/macOS（Windows与WSL请分别创建虚拟环境，不复用另一系统的.venv）：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-ai.txt
.venv/bin/python -m scripts.setup_local
```

脚本仅在 `.env` 不存在时创建配置，自动生成独立 JWT 签名密钥与 AI 服务令牌，不覆盖已有文件，也不打印密钥。在本机编辑 `.env`：

```dotenv
# JWT_SECRET 和 AI_SERVICE_TOKEN 保留脚本生成的随机值
AI_API_KEY=填写在服务商控制台申请的API密钥
AI_BASE_URL=https://api.openai.com/v1
AI_MODEL=gpt-4o-mini
AI_CONFIDENCE_THRESHOLD=0.60
AI_SAMPLE_INTERVAL_SECONDS=5
BACKEND_URL=http://127.0.0.1:5000
```

以上沿用仓库的 OpenAI 配置示例，所选账号须有模型调用权限与可用额度。其他服务商须提供支持图像输入、`response_format=json_object`、`temperature` 和 `max_tokens` 的兼容接口，按其文档填写基地址和模型名；纯文本模型无法处理摄像头拼图。基地址填到 `/v1` 或服务商指定的兼容根路径，不再追加 `/chat/completions`，程序会自动追加。

OpenAI Docs 官方资料确认 Chat Completions 可接收 URL 或 Base64 图像输入，GPT-4o mini 支持图像输入和文本输出：[图像输入指南](https://developers.openai.com/api/docs/guides/images-vision?api-mode=chat)、[模型说明](https://developers.openai.com/api/docs/models/gpt-4o-mini)。这里不承诺其他服务商支持同样参数。

两个进程都会读取仓库根目录 `.env`，已有终端环境变量优先。修改后重启后端与 AI。`AI_API_KEY` 用于调用模型，`AI_SERVICE_TOKEN` 用于写入项目后端；两端服务令牌和阈值应一致。不要在聊天、截图或录屏中展示 `.env` 内容。

## 2. 启动后端并准备课次

终端 A：

```powershell
.\.venv\Scripts\python.exe -m backend.app
```

访问 `http://127.0.0.1:5000`，管理员登录 `admin / admin12345`，在“课程排课”创建当天课次，开始时间设在当前时间之前，结束时间留足演示时间，状态选“开放记录”，并安排学生。教师应为对应课程的授课教师。

示例课次仅首次建库时开放约 35 分钟，第二天重新运行不会自动延长。录制前新建当天课次，避免沿用过期示例；无需删除数据库。

取得实际课次 ID：管理员登录后，在开发者工具 Network 查看 `GET /api/admin/sessions` 返回的 JSON，找到新课次的 `id`；也可在 `/api/docs` 授权后查询。不要将 `course_id` 当作 `session_id`，也不要固定假设 ID 为 1。

## 3. 单次验证，再连续采样

终端 B，同样进入项目根目录。`3` 只是示例，必须替换为实际课次 ID：

```powershell
.\.venv\Scripts\python.exe -m backend.ai_service --session-id 3 --camera 0 --once --evidence artifacts/ai-live.jsonl
```

Linux/macOS 将前缀换为 `.venv/bin/python`。程序先检查后端是否在线，再读取摄像头。正面面对镜头并保证光线，必要时尝试 `--camera 1`。`--once` 只处理一帧：成功入库退出码为 0；无人脸、低置信度、响应非法或请求失败退出码为 2。

单次成功后，采样 10 次并观察看板：

```powershell
.\.venv\Scripts\python.exe -m backend.ai_service --session-id 3 --camera 0 --max-samples 10 --evidence artifacts/ai-live.jsonl
```

去掉 `--max-samples 10` 可持续运行，按 `Ctrl+C` 停止并释放设备。默认间隔 5 秒，模型调用耗时可能延长实际间隔，10 次不保证恰好 50 秒。连续运行会消耗模型账号额度。OBS 只录桌面和麦克风，避免同时采集同一摄像头导致占用。

## 4. 验收证据

| 环节 | 应保存的实际证据 |
| --- | --- |
| 本地检测 | 日志 `mode=live_camera`、`samples>0`；无人脸事件为 `reason=no_face_detected` |
| 模型返回 | 真实模型名、情绪类型、置信度和本次 `elapsed_seconds` |
| 过滤 | 低于阈值 `accepted=false` 且不入库；不要伪造模型响应 |
| 数据库 | 成功事件含 `accepted=true` 与记录 `id`；管理员查到来源AI、匿名姓名、相同ID及置信度 |
| 看板及导出 | 同一课次的看板自动更新，AI来源CSV包含本次记录 |

`--evidence` 追加 JSONL，每行保存时间、课次、模型、阈值、耗时和结果，失败时记录异常类型及 HTTP 状态；不保存图像、Base64、API Key、JWT 或共享令牌。无人脸时不调用模型。记录能证明处理过程，不能自动证明分类准确。

实测后将脱敏 JSONL、AI来源截图和CSV放入 `docs/evidence/ai-live/`，按 [验收记录](acceptance-record.md) 填写实际设备、时间、模型、课次和结论。没有自然出现低置信度时如实标注，该分支已有模拟测试证据，不强行宣布现场出现。

脸部裁片仍可识别身份，采集与外发前应取得参与者同意并遵守学校要求。结果只用于课堂聚合参考，不代表学生真实内心、学习效果或个人评价。

## 5. 排查

| 现象 | 处理 |
| --- | --- |
| 缺少 `AI_API_KEY` | 编辑根目录`.env`，检查同名终端变量覆盖，重启进程 |
| 后端连接失败 | 先启动终端A；非默认端口同步修改`BACKEND_URL` |
| 摄像头打不开/读不到帧 | 检查权限，关闭视频会议与OBS摄像头采集，尝试编号1；WSL未暴露设备时在Windows原生Python运行摄像头进程，并确保能访问后端 |
| `no_face_detected` | 调整距离、正面姿态和光线；此时不会调用模型 |
| `http_status=401` | 检查模型密钥及两端共享令牌；结合后端日志区分模型拒绝与入库拒绝 |
| `http_status=400/404` | 检查模型图像/JSON参数、基地址重复路径、模型名和课次ID |
| `http_status=409` | 课次须为active，且当前时间位于开始与结束之间 |
| `http_status=429` | 检查额度/限流，增加间隔再重试 |
| `invalid_model_output` | 非JSON对象或置信度缺失/不是0～1数值；结果丢弃 |
| 已入库但看板未变 | 核对课次ID，等待一次推送；确认记录时间在近60分钟内 |
