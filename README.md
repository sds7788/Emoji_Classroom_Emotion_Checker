# 表情符号课堂情绪检查器系统

面向课堂教学的情绪反馈平台，支持学生手动打卡、教师实时看板、管理员排课统计，以及在网页中查看摄像头画面和 AI 识别的 emoji 情绪。后端使用 Flask，数据保存在 SQLite，首次启动自动建库并生成演示账号。

管理员网页 AI 已支持开启、停止和切换摄像头，显示实时画面、对应采样图、emoji、置信度、样本数及入库状态。[查看页面截图](docs/evidence/ai-browser/01-live-result.png)（截图使用合成摄像头及模拟模型响应）。

## 功能与角色

| 角色 | 主要功能 |
| --- | --- |
| 学生 | 公开注册、查看已安排课次、提交六类表情、查询个人历史、修改密码 |
| 教师 | 查看本人授课课次、近 60 分钟反馈与趋势、按课程/班级/日期查询历史统计 |
| 管理员 | 管理用户和邀请码、创建课程和课次、安排学生、查询统计、查看网页 AI 识别、导出 CSV |
| 独立 AI 进程 | 可选的命令行摄像头采样、模型调用、置信度过滤和匿名入库 |

六类情绪为：😊 开心、😕 困惑、😐 无聊、😔 低落、🤔 专注、🤩 兴奋。学生记录标记为 `MANUAL`，AI 记录标记为 `AI`，AI 结果不关联学生姓名或账号。

## 快速启动：Windows + Miniconda

下面命令在 **Miniconda Prompt（CMD）** 中执行，工作目录为项目根目录，即包含 `requirements-ai.txt` 的目录。建议使用 Python 3.12，项目要求 Python 3.10 或更新版本。

### 1. 创建环境并安装依赖

```bat
conda create -n emoji-classroom python=3.12 -y
conda activate emoji-classroom
python -m pip install -r requirements-ai.txt
python -m scripts.setup_local
```

已有 `emoji-classroom` 环境时，跳过创建环境那一行。`requirements-ai.txt` 已包含普通后端依赖和 OpenCV；如果仅使用手动打卡，可安装 `requirements.txt`。

配置脚本只在 `.env` 不存在时创建文件并生成独立的 JWT 签名密钥与 AI 服务令牌；已有配置会保留，密钥不会打印到终端。

### 2. 配置端口与视觉模型

在本机编辑项目根目录 `.env`。下例统一使用 **8000 端口**；源码未设置 `PORT` 时默认使用 5000。

```dotenv
HOST=127.0.0.1
PORT=8000
BACKEND_URL=http://127.0.0.1:8000
CORS_ORIGINS=http://127.0.0.1:8000,http://localhost:8000

AI_API_KEY=填写你自己的模型API密钥
AI_BASE_URL=https://api.openai.com/v1
AI_MODEL=gpt-4o-mini
AI_CONFIDENCE_THRESHOLD=0.60
AI_SAMPLE_INTERVAL_SECONDS=5
```

保留配置脚本生成的 `JWT_SECRET` 和 `AI_SERVICE_TOKEN`。模型地址与名称沿用仓库示例，也可按实际服务商文档替换：必须支持图像输入、OpenAI Chat Completions 兼容接口及程序使用的 JSON 输出参数。纯文本模型无法处理摄像头画面。`AI_BASE_URL` 不要重复追加 `/chat/completions`，程序会自动追加。

未填写 `AI_API_KEY` 时，学生、教师及管理员普通功能仍可使用，网页 AI 会提示配置模型。后端与独立 AI 进程自动读取根目录 `.env`，**已有终端环境变量优先；修改配置后须重启对应进程**。密钥仅保存在服务端，不需要填到网页。

### 3. 启动并登录

```bat
python -m backend.app
```

出现 `Running on http://127.0.0.1:8000` 后，打开 <http://127.0.0.1:8000>。可访问 <http://127.0.0.1:8000/health> 检查服务。

首次启动默认创建 `data/emotion_checker.db` 和以下演示账号：

| 角色 | 用户名 | 密码 |
| --- | --- | --- |
| 管理员 | `admin` | `admin12345` |
| 教师 | `teacher` | `teacher12345` |
| 学生 | `student` | `student12345` |

若需在 CMD 中临时指定端口，可先执行 `set PORT=8000`；PowerShell 对应写法为 `$env:PORT = "8000"`。访问地址与 `BACKEND_URL` 应使用实际端口。

Linux/macOS 也可使用同名 Conda 环境；使用 `.venv` 时按以下方式安装，然后用 `.venv/bin/python` 执行后续命令：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-ai.txt
.venv/bin/python -m scripts.setup_local
.venv/bin/python -m backend.app
```

Windows 使用 `.venv` 时解释器路径为 `.\.venv\Scripts\python.exe`。Windows 与 WSL 的环境分别创建，不共用另一系统的虚拟环境。

## 管理员网页 AI：从排课到识别

### 1. 准备正在开放的课次

管理员登录后，上方应有五个标签：

**数据概览 → AI 实时识别 → 课堂排课 → 用户管理 → 记录与导出**

在“课堂排课”中：

1. 创建课程，选择授课教师；已有课程可直接使用。
2. 创建课堂课次，填写班级、教室与起止时间，状态选择“开放记录”。开始时间应早于当前时间，结束时间应晚于当前时间。
3. 选择该课次，勾选学生并保存名单，供后续学生打卡及教师查看。

课程与课次不同，一门课程可以有多个课次。首次建库的示例课次只开放约 35 分钟，之后重新启动不会延长；演示前请新建当天课次，无需删除数据库。

### 2. 开启摄像头

1. 进入“AI 实时识别”。
2. 在“识别课次”中选择刚创建的开放课次。页面直接显示“课次 ID”，无需打开开发者工具查询。
3. 点击“开启摄像头并识别”，在浏览器提示中允许摄像头权限。
4. 左侧显示实时画面；右侧显示最近一次采样的 emoji、置信度、样本数、采样缩略图和入库状态。
5. 需要换设备时，使用“摄像头”下拉框；完成后点击“停止识别”。切换管理标签、退出或关闭页面也会停止设备与后续采样。

网页开启的是**浏览器所在电脑**的摄像头，后端可运行在 Windows、WSL 或服务器上。摄像头访问需要 `localhost`、`127.0.0.1` 或 HTTPS；使用局域网 IP 的普通 HTTP 地址时，浏览器可能不提供摄像头接口。

网页模式只需启动后端。若旧的 `python -m backend.ai_service`、视频会议或 OBS 摄像头来源正在使用同一设备，请先停止它们。

### 3. 理解识别结果

| 页面状态 | 含义 | 是否保存 |
| --- | --- | --- |
| 已保存 | 达到阈值，显示情绪、置信度及记录 ID | 匿名 AI 记录入库 |
| 置信度不足 | 显示候选 emoji 和置信度，明确标注未入库 | 否 |
| 未检测到人脸 | 清空上一情绪，提示调整距离、朝向和光线 | 否，不调用模型 |
| 暂时无法判断 / 模型结果无效 | 当前模型结果不能使用 | 否 |
| 识别失败 | 显示模型请求或网络错误，实时预览可继续 | 本次不保存 |

视频预览持续更新，AI 每次请求完成后等待配置的间隔再采样，默认 5 秒；模型耗时也会影响结果更新频率。右侧结果对应所展示的采样缩略图及时间，多个人脸时表示样本中的主导情绪，不为每个人分别标注身份或情绪。

达标结果保存为 `source=AI`、`user_id=NULL`、`device_id=browser-camera`。教师或管理员选择同一课次可查看统计更新；在“记录与导出”选择课次和 AI 来源，可查询并下载 CSV。已经发给模型的请求可能在停止后完成，但不会重新显示到已停止的界面。

完整图像处理与操作说明见 [网页实时识别指南](docs/ai-web-monitor.md)，模型接入及真实链路记录见 [AI 接入指南](docs/ai-integration.md)。

## 学生、教师及管理流程

- **学生**：进入已安排的开放课次，选择表情提交，再到“我的历史”查看记录。名单、课次状态及时间由服务器校验。
- **教师**：选择本人课次，实时总数、积极/专注比例、趋势和最新反馈均为所选课次近 60 分钟数据；课程、班级、日期用于历史分布与统计，实时推送不会覆盖历史筛选。
- **管理员**：“数据概览”支持多维统计与独立实时看板；“用户管理”可签发教师/管理员邀请码并调整账号；“记录与导出”支持筛选和 CSV 下载，每次最多导出最新 500 条。

学生可公开注册。教师与后续管理员需对应角色的一次性邀请码，默认有效 24 小时，可设置 1～168 小时。关闭演示数据的新数据库可用 `ADMIN_BOOTSTRAP_TOKEN` 初始化首个管理员，步骤见 [部署说明](docs/deployment.md)。

多角色演示请使用独立浏览器配置文件或不同浏览器；同一浏览器的普通标签页共享登录状态。全部操作见 [用户手册](docs/user-guide.md)，录制流程见 [5～8 分钟演示指南](docs/demo-script.md)。

## 可选：独立命令行 AI 进程

后端保持运行，在另一个终端激活同一环境并进入项目根目录。先停止网页摄像头，确认 `.env` 中模型配置和 `AI_SERVICE_TOKEN` 有效。

下例中的 `3` 必须替换为实际课次 ID，`--backend-url` 改为实际后端地址：

```bat
conda activate emoji-classroom
python -m backend.ai_service --session-id 3 --camera 0 --backend-url http://127.0.0.1:8000 --once --evidence artifacts/ai-live.jsonl
```

- `--once`：只采样一次；成功入库退出码为 0，未入库为 2。
- `--max-samples 10`：限定采样次数；不加这两项则持续运行，按 `Ctrl+C` 停止。
- `--camera 0`：摄像头编号，可尝试其他编号。
- `--evidence`：追加脱敏 JSONL，记录课次、模型、置信度、耗时及处理结果，不保存图像或密钥。

命令行方式使用运行进程所在电脑的摄像头；WSL 需要实际能访问设备。`AI_SERVICE_TOKEN` 用于该进程写入后端，两端须一致；网页 AI 使用管理员登录权限，不需要用户在网页提供共享令牌。

## 常见问题

| 现象 | 处理方法 |
| --- | --- |
| 看不到“AI 实时识别”标签 | 确认登录管理员，并启动了更新后的项目；Windows 与 WSL 有两份源码时同步到实际运行目录，随后重启后端、按 `Ctrl+F5` 刷新 |
| 更新后页面报脚本或接口不存在 | 完整更新 `backend`、`frontend` 等功能文件，包含新增的 `backend/ai_web.py` 和 `frontend/ai-monitor.js`；保留本机 `.env` 和数据库 |
| Windows 提示套接字访问权限不允许 | 尝试其他可用端口，例如 CMD 中 `set PORT=8000`，同时使用对应网页地址和命令行 `BACKEND_URL` |
| 显示模型未配置 | 在后端所在项目的 `.env` 填写模型配置后重启，检查是否被同名终端环境变量覆盖 |
| 开始按钮不可用 | 检查模型配置、课次状态及起止时间；过期示例课次需要新建当天课次 |
| 摄像头权限拒绝 / 无法访问 | 在地址栏站点权限中允许摄像头，通过 localhost、127.0.0.1 或 HTTPS 访问 |
| 摄像头被占用 / 无法读取 | 停止独立 AI 进程、视频会议或 OBS 摄像头采集，再尝试默认或其他摄像头 |
| 一直显示无人脸 | 调整正面姿态、距离和光线；本地检测不到人脸时不会调用模型 |
| 网页显示模型 HTTP 401 | 检查模型 API Key；独立进程入库返回 401 时另查两端 `AI_SERVICE_TOKEN` |
| 模型 HTTP 400 / 404 / 429 | 检查视觉模型及 JSON 参数支持、模型名、基地址是否重复路径，以及额度或限流 |
| 课次未开放 / HTTP 409 | 当前时间应处于起止时间之间，且课次状态须为 `active` |
| 结果已保存但看板未变 | 选择同一课次，等待下一次推送；实时看板只包含近 60 分钟记录 |
| 直接打开 API 提示请先登录 | 受保护接口需要 Bearer JWT；后台请求会自动携带登录令牌 |

## 配置项

以下为源码默认值，`.env.example` 的示例阈值为 0.60；快速启动示例将端口改为 8000。

| 环境变量 | 源码默认值 | 用途 |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | 后端监听地址 |
| `PORT` | `5000` | 后端监听端口 |
| `JWT_SECRET` | 开发占位值 | JWT 签名密钥；配置脚本自动生成随机值 |
| `DATABASE_PATH` | `data/emotion_checker.db` | SQLite 文件路径 |
| `SEED_DEMO_DATA` | `true` | 空库首次启动时创建演示数据 |
| `ADMIN_BOOTSTRAP_TOKEN` | 空 | 全新数据库初始化首个管理员的凭据 |
| `AI_API_KEY` | 空 | 网页及命令行识别使用的模型密钥 |
| `AI_BASE_URL` | `https://api.openai.com/v1` | 模型兼容接口根地址 |
| `AI_MODEL` | `gpt-4o-mini` | 实际可调用的视觉模型名 |
| `AI_CONFIDENCE_THRESHOLD` | `0.55` | AI 入库置信度下限 |
| `AI_SAMPLE_INTERVAL_SECONDS` | `5` | 采样间隔，实际频率还受请求耗时影响 |
| `AI_SERVICE_TOKEN` | 空 | 独立 AI 进程写入后端的共享令牌 |
| `BACKEND_URL` | `http://127.0.0.1:5000` | 独立 AI 进程访问的后端地址 |
| `CORS_ORIGINS` | `*` | API 跨域允许来源，部署时限制为实际来源 |

## API 与测试

Swagger UI 位于 `/api/docs`，OpenAPI JSON 位于 `/api/openapi.json`，定义文件为 [docs/openapi.json](docs/openapi.json)。接口页面使用当前服务地址，端口随启动配置变化。

| 接口 | 用途与权限 |
| --- | --- |
| `GET /health` | 服务健康检查，无需登录 |
| `GET /api/sessions` | 查询当前登录用户可访问的课次 |
| `GET /api/admin/sessions` | 管理员查询全部课次；返回的 `id` 是课次 ID |
| `GET /api/admin/ai/status` | 管理员读取模型配置状态，不返回密钥 |
| `POST /api/admin/ai/analyze` | 管理员提交网页采样帧并识别，达标结果匿名入库 |
| `POST /api/ai/emoji-results` | 独立 AI 进程提交结果，使用服务令牌认证 |

在已激活的环境中运行完整测试：

```bat
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

浏览器验收使用独立临时数据库：

```bat
python -m playwright install chromium
python -m scripts.acceptance
python -m scripts.ai_browser_acceptance
```

两项脚本分别输出至 `artifacts/acceptance/` 和 `artifacts/ai-browser/`。已保留的验收结果为 **51 项自动化测试通过，20 个浏览器场景通过**（三角色 9 项、网页 AI 11 项）：

- [自动化测试输出](docs/evidence/unit-tests.txt)
- [三角色浏览器验收](docs/evidence/browser/results.json)
- [网页 AI 浏览器验收](docs/evidence/ai-browser/results.json)
- [测试报告](docs/test-report.md)

浏览器测试使用合成摄像头与模拟模型响应，不调用真实外部服务，不代表真实摄像头或模型分类效果已验收。仅安装普通依赖时，摄像头相关测试会跳过。

## Docker 部署

项目已提供 Dockerfile 和 Compose 配置，SQLite 使用命名卷 `emoji_data` 持久化。容器端口映射以 5000 为目标；若沿用本地示例的 `.env`（`PORT=8000`），请在 `docker-compose.yml` 的 `app` 服务内添加以下配置，固定容器监听端口：

```yaml
environment:
  PORT: "5000"
```

这样现有 `${PORT:-5000}:5000` 映射将宿主机 8000 转发到容器 5000，再执行：

```bat
docker compose up --build -d
```

网页模式使用浏览器摄像头，容器中无需映射物理摄像头设备。当前容器构建与目标电脑部署仍需实测，配置与持久化验证步骤见 [部署说明](docs/deployment.md)。

## 项目结构与文档

```text
backend/
  app.py                   应用配置、认证和 API 路由
  ai_web.py                管理员网页采样接口、权限与大小校验
  ai_service.py            共享视觉识别逻辑及可选命令行摄像头进程
  services.py              排课、统计、课次校验及 AI 结果保存
  database.py              SQLite Repository 与演示数据
  auth.py / realtime.py    JWT 校验与实时看板授权
  config.py                根目录 .env 加载
frontend/
  index.html               学生、教师、管理员页面
  ai-monitor.js            浏览器摄像头、定时采样、结果显示和设备释放
  script.js / style.css    页面交互、图表与响应式样式
scripts/
  setup_local.py           首次创建本地配置和随机密钥
  acceptance.py            三角色浏览器验收
  ai_browser_acceptance.py 网页 AI 浏览器验收
tests/                     API、Service、安全及 AI 链路测试
database_setup.sql         SQLite Schema
docs/                      设计、接口、使用说明及验收材料
```

更多材料：[网页 AI 使用](docs/ai-web-monitor.md)、[模型接入](docs/ai-integration.md)、[用户手册](docs/user-guide.md)、[需求规格](docs/requirements.md)、[系统设计](docs/design.md)、[实验报告](docs/experiment-report.md)、[验收记录](docs/acceptance-record.md)、[视频录制](docs/demo-script.md)。

## 图像处理与使用边界

实时画面在浏览器预览，采样帧及人脸拼图在内存中处理，不保存至数据库或磁盘；结构化结果可以查询和导出。后端最多裁剪 8 张人脸组成拼图发给配置的模型服务，裁片仍可能识别身份，采集与外发前应取得参与者同意并遵循学校要求。

表情不能可靠代表学生的理解程度、学习意愿或真实内心。光线、遮挡、姿态、文化差异和模型偏差都会造成误判，结果只作为课堂节奏的聚合参考，应结合学生主动反馈解释，不用于个人评分或纪律判断。
