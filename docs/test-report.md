# 测试报告

## 执行环境

- Python 3.12，Flask 测试客户端，独立临时 SQLite 数据库。
- 命令：`python -m unittest discover -s tests -v`。
- 本次执行：7 项通过，0 项失败。

## 自动化用例

| 用例 | 验证内容 | 结果 |
| --- | --- | --- |
| `test_demo_login_manual_checkin_history_and_statistics` | 示例登录、学生课堂可见、提交情绪、个人历史和统计 | 通过 |
| `test_teacher_scope_and_admin_rbac` | 教师不得读取其他教师课堂，学生不得访问用户管理 | 通过 |
| `test_admin_schedule_and_student_session_access` | 管理员安排学生名单，学生随后可访问并提交 | 通过 |
| `test_ai_token_threshold_privacy_and_export_formula_safety` | AI 服务令牌校验、阈值过滤、匿名入库、CSV 公式注入转义 | 通过 |
| `test_password_change_revokes_existing_token` | 旧密码校验、改密、令牌版本吊销旧 JWT | 通过 |
| `test_openapi_and_health` | 健康检查与 OpenAPI JSON | 通过 |
| `test_ai_worker_discards_frames_without_detected_faces` | 无人脸采样帧不会发送到模型 API | 通过 |

## 关键风险检查

- 密码哈希使用 bcrypt；明文密码只在注册/登录请求和演示提示中短暂存在。
- 学生的历史接口固定当前用户 ID；教师查询自动限制所属教师 ID；管理接口校验 admin 角色。
- SQL 使用 SQLite 参数占位符，数据表含外键和枚举 CHECK。
- CSV 对 `= + - @`、制表符和回车开头的文本单元格增加前缀，避免常见电子表格公式执行。
- AI 结果缺少或错误服务令牌返回 401；低置信度结果返回未接受且不入库；AI 用户 ID 强制为 NULL。
- 数据表中没有图像/视频字段，摄像头客户端只在内存中保留采样帧及临时脸部拼图；脸部裁片发送给外部模型 API 前需要取得适当授权。

## 尚需现场验证

- 真实摄像头与真实视觉 API 端到端取决于用户配置 API Key、模型地址、模型支持图像输入并授予摄像头权限；当前没有对外模型凭据，因此未声称完成真实推理验收。
- Docker 镜像及不同系统浏览器的现场兼容性需在目标演示环境执行。
- 模型输出易受姿态、光线、遮挡、偏差和文化语境影响；应展示聚合数据并由教师结合主动反馈解释。
