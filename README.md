# 表情符号课堂情绪检查器系统

本项目把原智能餐饮管理系统改造成课堂情绪反馈平台，覆盖学生自主打卡、教师课堂观察、管理员排课统计与匿名 AI 汇总。默认使用 SQLite，首次启动自动建库并载入可登录的演示账号，不需要 MySQL 或模型密钥即可运行核心功能。

## 功能

- 学生公开注册；教师与管理员使用一次性邀请码注册；空库支持初始化首个管理员。所有角色可登录及修改密码。
- 学生查看排课名单、提交六类情绪、查询个人历史。
- 教师查看本人所授课堂，按课程和日期筛选统计，查看 60 分钟聚合趋势和最新记录。
- 管理员生成注册邀请码、管理用户角色与状态，创建课程和课次、安排学生名单、查询和导出 CSV。
- 管理员按课程、班级、日期筛选情绪分布、每日趋势、课程和班级对比图，并查看任意课堂的 WebSocket 实时看板。
- 独立 AI 服务采样摄像头帧，调用兼容 OpenAI Chat Completions 的视觉模型，根据置信度阈值将匿名情绪结果写入数据库。
- REST API 使用 JWT 与角色校验；AI 使用独立服务令牌；操作数据留审计记录；API 文档可在 `/api/docs` 查看。
- 摄像头完整帧只在内存中处理；本地 OpenCV 检测并裁剪最多 8 张脸部样本发送给配置的模型 API，不写入磁盘或数据库。

## 本地启动

需要 Python 3.10 或更新版本。

```powershell
cd Restaurant_Management_System
python -m pip install -r requirements.txt
$env:JWT_SECRET = "请替换为至少 32 位随机值"
python -m backend.app
```

打开 <http://127.0.0.1:5000>。开发环境首次启动会在 `data/emotion_checker.db` 创建数据库并生成示例账号；可以在管理后台停用或调整这些账号。演示密码如下：

| 角色 | 用户名 | 密码 |
| --- | --- | --- |
| 管理员 | `admin` | `admin12345` |
| 教师 | `teacher` | `teacher12345` |
| 学生 | `student` | `student12345` |

注册页可选择学生、教师或管理员。学生直接注册；教师和后续管理员需现有管理员在“用户管理”中生成对应角色的邀请码。邀请码默认 24 小时有效，支持 1-168 小时，一次使用后失效，数据库只保存哈希。邀请码仅在生成时展示，请单独提供给受邀人。

全新数据库可以关闭演示数据并设置 `ADMIN_BOOTSTRAP_TOKEN`，在注册页选择“管理员”并将该密钥填入邀请码字段。首个管理员成功创建后，初始化入口永久关闭；并发请求也只能创建一个首任管理员。操作步骤见 [部署说明](docs/deployment.md)。

## Docker Compose

复制根目录 `.env.example` 为 `.env`，改写 JWT 和 AI 服务令牌后执行：

```powershell
docker compose up --build
```

SQLite 文件保存在 Docker 命名卷 `emoji_data` 中。容器暴露端口默认为 `5000`。

## AI 摄像头推理

不配置 `AI_API_KEY` 时，普通系统功能完整可用，摄像头推理进程会提示缺少模型凭据后退出。需要启用时，设置后端和模型环境变量，并在**同一个环境**设置共享的 `AI_SERVICE_TOKEN`：

```powershell
$env:AI_SERVICE_TOKEN = "设置一段随机独立令牌"
$env:AI_CONFIDENCE_THRESHOLD = "0.65"
$env:AI_API_KEY = "填写视觉模型 API Key"
$env:AI_BASE_URL = "https://api.openai.com/v1"
$env:AI_MODEL = "gpt-4o-mini"
$env:AI_SAMPLE_INTERVAL_SECONDS = "5"
python -m backend.ai_service --session-id 1 --camera 0
```

后端需以相同的 `AI_SERVICE_TOKEN` 运行。模型服务必须支持带图像输入的 OpenAI Chat Completions 接口。OpenCV 会在本地检测人脸并生成最多 8 个裁片的临时拼图，只有脸部裁片通过 HTTPS 发送给配置的模型服务；完整帧和拼图不落盘。脸部裁片仍属于可识别生物特征数据，启用前应征得课堂参与者同意并遵循学校数据政策。

## 配置项

| 环境变量 | 默认值 | 用途 |
| --- | --- | --- |
| `JWT_SECRET` | 开发专用占位值 | JWT 签名密钥；部署前必须更换 |
| `DATABASE_PATH` | `data/emotion_checker.db` | SQLite 文件路径 |
| `SEED_DEMO_DATA` | `true` | 空库首次启动时创建演示数据 |
| `ADMIN_BOOTSTRAP_TOKEN` | 空 | 无管理员且从未初始化的数据库创建首个管理员时使用；留空关闭 |
| `AI_SERVICE_TOKEN` | 空 | 后端 AI 写入接口的独立令牌 |
| `AI_CONFIDENCE_THRESHOLD` | `0.55` | AI 入库置信度下限 |
| `AI_API_KEY` | 空 | 视觉模型 API Key，仅摄像头服务需要 |
| `AI_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容 API 地址 |
| `AI_MODEL` | `gpt-4o-mini` | 视觉模型名称 |
| `AI_SAMPLE_INTERVAL_SECONDS` | `5` | 摄像头采样间隔 |
| `CORS_ORIGINS` | `*` | API 跨域允许来源，部署时建议限制 |

## API 和测试

OpenAPI JSON 位于 `docs/openapi.json`，Swagger UI 位于 `/api/docs`。接口测试使用标准库 `unittest`：

```powershell
python -m unittest discover -s tests -v
```

测试覆盖登录与改密、邀请码权限/过期/重放、首次管理员并发初始化、角色隔离、多维统计筛选、课堂排课和打卡、AI 服务令牌与阈值、CSV 注入及 API 文档。

## 项目结构

```text
backend/
  app.py             Flask 控制器、认证与 API 路由
  services.py        排课、权限范围、历史、统计与看板业务服务
  database.py        SQLite Repository 与演示数据初始化
  ai_service.py      可选摄像头采样与视觉模型调用进程
frontend/
  index.html         学生、教师、管理员单页 Web 客户端
  script.js          页面状态、API Repository 与交互
  style.css          响应式界面样式
database_setup.sql   安全、幂等的 SQLite Schema
docs/                需求、架构、API、用户手册、测试与部署文档
tests/               API 集成与安全用例
```

更多设计与实验材料：

- [需求规格说明书](docs/requirements.md)
- [系统设计与 ER 模型](docs/design.md)
- [用户手册](docs/user-guide.md)
- [测试报告](docs/test-report.md)
- [部署说明](docs/deployment.md)
- [演示流程](docs/demo-script.md)

## AI 限制与误判风险

面部表情不能可靠代表学生的理解程度、学习意愿或情绪状态。光照、遮挡、摄像头位置、文化差异、神经多样性和模型训练偏差都会造成误判。系统仅将结果作为课堂节奏的聚合参考，不应对个人评分、纪律或其他高影响决定作出自动判断。教师应结合主动反馈、课堂交流等信息解释数据；AI 汇总不关联姓名，但发送给外部模型的脸部裁片仍可能识别身份。
