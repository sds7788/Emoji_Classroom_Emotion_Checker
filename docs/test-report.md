# 测试报告

## 执行环境

- Python 3.12，Flask 测试客户端，独立临时 SQLite 数据库。
- 命令：`python -m unittest discover -s tests -v`。
- 本次执行：11 项通过，0 项失败（2026-11-11）。

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
| `test_privileged_registration_uses_role_bound_single_use_invitations` | 学生不能签发邀请码；教师/管理员凭对应角色邀请码注册；重复用户名回滚；邀请码不可重放、明文不入库 | 通过 |
| `test_expired_invitation_and_invalid_registration_input_are_rejected` | 过期邀请码、错误身份及非法有效期参数被拒绝 | 通过 |
| `test_first_admin_bootstrap_is_atomic_and_stays_closed_after_role_changes` | 空库初始化密钥校验；并发仅创建一名首任管理员；角色变更后初始化仍关闭 | 通过 |
| `test_admin_multidimensional_statistics_and_realtime_keep_teacher_scope` | 课程/班级/时间组合筛选、时区边界、每日和课程/班级分组、实时接口与教师数据隔离 | 通过 |

## 浏览器验收

使用独立临时 SQLite 数据库和 `127.0.0.1:5001` 服务；空库初始化使用 `127.0.0.1:5002`。未向演示数据库写入验收账号。

| 场景 | 观察结果 |
| --- | --- |
| 教师受邀注册 | 管理员在“用户管理”生成教师邀请码，受邀人注册后自动进入教师看板；尚未分配课程时正确展示空状态 |
| 管理员受邀注册 | 使用管理员邀请码注册后进入管理端，能查看统计和实时课堂数据 |
| 课程、班级和日期组合筛选 | 选择示例课程、班级及前一天日期后，反馈总数、分布和课程/班级对比均为 1 条 |
| 跨角色实时更新 | 学生提交专注反馈后，管理员实时反馈数从 7 变为 8，最新记录出现专注反馈；历史日期筛选仍保持 1 条 |
| 首任管理员初始化 | 关闭演示种子后使用初始化密钥注册成功；退出并重新进入注册页后，初始化提示已关闭，仅提示使用邀请码 |
| 空状态与窄屏 | 未来日期显示 0 条反馈，未选择实时课堂显示空状态；390px 视口下筛选器、指标和图表可用，无页面横向溢出 |

[管理员统计与实时看板验收截图](screenshots/admin-dashboard.png)。验收页面未记录浏览器警告或 JavaScript 错误。另通过 JavaScript 语法检查、Python 编译检查、Git 差异空白检查和 OpenAPI 的 22 条路径及 8 处引用核对。

## 关键风险检查

- 密码哈希使用 bcrypt；明文密码只在注册/登录请求和演示提示中短暂存在。
- 学生的历史接口固定当前用户 ID；教师查询自动限制所属教师 ID；管理接口校验 admin 角色。
- SQL 使用 SQLite 参数占位符，数据表含外键和枚举 CHECK。
- 教师/管理员邀请码由管理员签发，按角色、有效期及使用状态校验，明文仅在生成响应中返回；注册与核销在同一事务中提交。
- 首任管理员初始化检查和持久关闭标记在同一事务中提交，避免并发开户或角色变更后重新开放初始化。
- CSV 对 `= + - @`、制表符和回车开头的文本单元格增加前缀，避免常见电子表格公式执行。
- AI 结果缺少或错误服务令牌返回 401；低置信度结果返回未接受且不入库；AI 用户 ID 强制为 NULL。
- 数据表中没有图像/视频字段，摄像头客户端只在内存中保留采样帧及临时脸部拼图；脸部裁片发送给外部模型 API 前需要取得适当授权。

## 尚需现场验证

- 真实摄像头与真实视觉 API 端到端取决于用户配置 API Key、模型地址、模型支持图像输入并授予摄像头权限；当前没有对外模型凭据，因此未声称完成真实推理验收。
- Docker 镜像及不同系统浏览器的现场兼容性需在目标演示环境执行。
- 模型输出易受姿态、光线、遮挡、偏差和文化语境影响；应展示聚合数据并由教师结合主动反馈解释。
