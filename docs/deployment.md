# 部署说明

## 本地开发

建议 Python 3.10+。进入仓库根目录后运行：

```powershell
python -m pip install -r requirements.txt
$env:JWT_SECRET = "替换为随机高熵密钥"
$env:DATABASE_PATH = "data/emotion_checker.db"
python -m backend.app
```

SQLite Schema 在第一次启动时幂等应用。不要把数据库文件、API Key 或 `.env` 提交到 Git。

## Docker Compose

将 `.env.example` 复制成 `.env`，替换 `JWT_SECRET` 和 `AI_SERVICE_TOKEN`。空 `AI_API_KEY` 不影响普通服务。然后执行 `docker compose up --build -d`，访问 `http://localhost:5000`。命名卷 `emoji_data` 持久化 SQLite 数据。查看日志：`docker compose logs -f app`；停止服务：`docker compose down`。

## 生产配置

- 使用至少 32 随机字节的 `JWT_SECRET`，令牌仅通过 HTTPS 传输。
- 设置专用、不可预测的 `AI_SERVICE_TOKEN`，限制 AI 服务到后端的网络路径。
- 设置准确的 `CORS_ORIGINS`，不要在公网部署时允许 `*`。
- 按学校要求启用 HTTPS、数据库备份和日志轮转；SQLite 文件应有受限的文件系统权限。
- `SEED_DEMO_DATA=false` 可关闭空库演示数据，但关闭后需通过安全管理流程建立第一个管理员账号。当前版本未提供公网管理员自助注册接口。
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
