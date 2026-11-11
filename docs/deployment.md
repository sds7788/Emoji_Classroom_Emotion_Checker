# 部署说明

## 本地开发

建议 Python 3.10+。进入仓库根目录后运行：

```powershell
python -m pip install -r requirements.txt
python -m scripts.setup_local
$env:DATABASE_PATH = "data/emotion_checker.db"
python -m backend.app
```

SQLite Schema 在第一次启动时幂等应用。不要把数据库文件、API Key 或 `.env` 提交到 Git。

建议在虚拟环境运行，跨平台命令见 [README](../README.md)。`scripts.setup_local` 只在根目录 `.env` 不存在时生成配置和随机密钥，不覆盖已有文件。后端和AI均自动读取 `.env`，外部环境变量优先；模型配置和现场验证见 [AI接入指南](ai-integration.md)。本次当前WSL的新虚拟环境安装及浏览器流程已完成，目标演示电脑仍须按 [验收模板](acceptance-record.md) 独立核验。

## 创建首个管理员

正式部署可以使用一个新的数据库文件，并关闭演示账号：

```powershell
$env:SEED_DEMO_DATA = "false"
$env:DATABASE_PATH = "data/production.db"
$env:ADMIN_BOOTSTRAP_TOKEN = "替换为至少32位随机初始化密钥"
$env:JWT_SECRET = "替换为独立的至少32位随机签名密钥"
python -m backend.app
```

在注册页选择“管理员”，填写账号信息，将 `ADMIN_BOOTSTRAP_TOKEN` 的值填入邀请码字段。成功后初始化入口自动永久关闭，即使管理员之后停用或改变角色也不会重新打开。完成后移除该环境变量并重启服务。已有演示管理员的数据库无需初始化，可以直接由管理员生成教师或管理员邀请码。不要把初始化密钥写入提交材料或截图。

初始化密钥及 JWT、AI 令牌相互独立。初始化状态通过 `GET /api/auth/registration-options` 查询，但密钥从不返回前端。后续开户在“用户管理”生成一次性邀请码，默认 24 小时、最长 168 小时。

## Docker Compose

将 `.env.example` 复制成 `.env`，替换 `JWT_SECRET` 和 `AI_SERVICE_TOKEN`。空 `AI_API_KEY` 不影响普通服务。然后执行 `docker compose up --build -d`，访问 `http://localhost:5000`。命名卷 `emoji_data` 持久化 SQLite 数据。查看日志：`docker compose logs -f app`；停止服务：`docker compose down`。

也可先运行 `python -m scripts.setup_local` 自动生成密钥。当前WSL未启用Docker Desktop集成，未完成真实容器验收；如采用Docker，请在目标电脑开启相应集成并执行构建、`docker compose ps`、`curl http://localhost:5000/health`、日志检查，再重启容器确认数据保留。不要使用 `docker compose down -v`，该命令会删除命名卷。

## 生产配置

- 使用至少 32 随机字节的 `JWT_SECRET`，令牌仅通过 HTTPS 传输。
- 设置专用、不可预测的 `AI_SERVICE_TOKEN`，限制 AI 服务到后端的网络路径。
- 设置准确的 `CORS_ORIGINS`，不要在公网部署时允许 `*`。
- 按学校要求启用 HTTPS、数据库备份和日志轮转；SQLite 文件应有受限的文件系统权限。
- `SEED_DEMO_DATA=false` 关闭空库演示数据；首任管理员按上述初始化流程建立，后续教师和管理员使用角色邀请码注册。
- 摄像头采样帧通过 HTTPS 发给配置的视觉模型 API；检查模型提供方数据保留策略及学校授权要求。

## 故障排查

| 现象 | 检查项 |
| --- | --- |
| 页面显示连接失败 | 后端是否启动；端口 `5000` 是否被占用 |
| 登录令牌无效 | 前后端是否使用同一服务实例；`JWT_SECRET` 是否一致 |
| 学生看不到课堂 | 管理员是否保存名单；账号角色/状态；课堂是否安排给该账号 |
| 表情按钮不可用 | 课堂状态是否为 active；系统时间是否落在开始与结束之间 |
| AI 进程拒绝启动 | `AI_API_KEY`、独立令牌、摄像头权限及 `opencv-python` 是否已配置 |
| 看板没有 WebSocket 数据 | 检查反向代理的 Upgrade/Connection 转发；前端会自动回退到 HTTP 轮询 |
