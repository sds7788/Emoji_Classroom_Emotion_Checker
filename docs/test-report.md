# 测试报告

## 执行环境

- 本轮Python3.13.11、WSL2、Flask测试客户端、独立临时SQLite；浏览器Chromium158.0.8127.18。
- 命令：`python -m unittest discover -s tests -v`。
- 本轮执行：51项通过，0失败，0跳过（2026-11-11）。[原始输出](evidence/unit-tests.txt)内的耗时仅为本机测试运行时间，不是服务性能指标。

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

在原11项API用例基础上，其他测试按类统计：

| 测试类 | 数量 | 判定内容 | 结果 |
| --- | --- | --- | --- |
| `ServiceTests` | 5 | 名单替换与去重/非法名单不变、查询范围与SQL参数化、最后管理员保护/角色变更吊销、CSV前缀、60分钟边界与分桶一致 | 全通过 |
| `SecurityTests` | 5 | 登录及筛选SQL注入、注册/改密弱密码长度和UTF-8字节限制、导出权限与CSV往返、无效/过期/身份不符JWT、非有限AI置信度 | 全通过 |
| `RealtimeTests` | 5 | 非法/无权订阅、连接建立后停用/角色/令牌版本/课程归属变化均停止 | 全通过 |
| `AiPipelineTests` | 4 | 模拟检测框和模型成功响应→实际裁剪编码→后端→SQLite→统计/CSV；低置信度/非法响应不提交、后端阈值最终生效、模型HTTP错误不写入 | 全通过 |
| `PredictionTests` | 2 | 达到阈值与文本块响应；JSON类型、字段缺失、非法情绪、布尔/字符串/非有限置信度拒绝 | 全通过 |
| `WorkerTests` | 4 | 单次成功退出0、无人脸退出2、异常脱敏、读帧失败及时退出；释放摄像头 | 全通过 |
| `ConfigTests` | 1 | 根目录.env加载且终端环境变量优先 | 通过 |
| `BrowserAiTests` | 14 | 网页采样管理员权限、实际编码/模拟模型到入库、低置信度/无人脸、输入/大小限制、缺配置、错误脱敏、慢请求期间撤权/课次结束、并发限制及释放、响应约束 | 全通过 |

模拟链路不调用外部模型，不能证明真实检测成功率或情绪分类准确率。密码测试验证当前规则，没有常见弱密码字典。CSV单元测试与真实下载共同验证公式/制表符/回车/换行及逗号引号转义。

## 浏览器验收

网页AI新增11个场景通过：[结果](evidence/ai-browser/results.json)、[画面与emoji](evidence/ai-browser/01-live-result.png)、[低置信度](evidence/ai-browser/02-low-confidence.png)、[窄屏](evidence/ai-browser/03-mobile.png)。使用合成摄像头和受控模型响应，经真实HTTP与临时SQLite验证画面/emoji/置信度/入库、无人脸清除旧值、模型失败与密钥保护、停止/切页释放及停止采样、缺配置、权限拒绝、390px和零pageerror；不代替真实硬件及模型效果验证。重现：`python -m scripts.ai_browser_acceptance`，默认输出artifacts/ai-browser。

原有9个三角色场景也已复验，两组共20个浏览器场景通过。

本轮执行 `python -m scripts.acceptance --output docs/evidence/browser`，自动启动随机端口的临时服务器、独立数据库和三个隔离浏览器上下文。9个场景全部通过，步骤、预期、实际结果与截图索引见 [results.json](evidence/browser/results.json)：

| 场景 | 预期与实际结果 | 证据 |
| --- | --- | --- |
| 管理员创建课程/课次/名单 | 新课次开放且安排1名学生，实际满足 | [排课截图](evidence/browser/01-schedule.png) |
| 学生提交与历史 | 专注记录成功显示，实际满足 | [学生截图](evidence/browser/02-student.png) |
| 教师实时与历史口径 | 昨日分布1条，当前课次2条、积极/专注各50%；推送不覆盖昨日分布，实际满足 | [教师截图](evidence/browser/03-teacher.png) |
| 管理员组合统计 | 指定课程/班级总数2，实时课次2，实际满足 | [管理截图](evidence/browser/04-admin.png) |
| 模拟AI、过滤、匿名及下载 | 低置信度丢弃，达标结果推送入看板，AI筛选CSV仅1条匿名记录，实际满足 | [截图](evidence/browser/05-export.png)、[CSV](evidence/browser/export.csv) |
| 真实连接停用撤权 | 收到首个data后停用教师，下一条为error，实际满足 | results.json步骤6 |
| 真实连接JWT过期 | 连接建立后等待短JWT过期，下一条为error，实际满足 | results.json步骤7 |
| 390px窄屏 | 无整页水平溢出，实际满足 | [窄屏截图](evidence/browser/06-mobile.png) |
| 浏览器脚本异常 | pageerror为0，实际为0 | results.json |

重现时先安装 `requirements-dev.txt`，再执行 `python -m playwright install chromium` 与 `python -m scripts.acceptance`。默认输出artifacts/acceptance，不修改日常数据库。脚本中的AI输入是受控接口数据，不是摄像头或真实模型推理。

以下保留此前已有验收记录，与本轮自动化结果区分。此前使用5001及5002端口的独立临时库：

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
- CSV对空白后公式前缀及制表符/回车/换行开头的单元格增加文本前缀；修复制表符被lstrip移除后漏判的问题。
- AI 结果缺少或错误服务令牌返回 401；低置信度结果返回未接受且不入库；AI 用户 ID 强制为 NULL。
- 角色/状态变化递增令牌版本；WebSocket每次推送复核有效期与权限；最后一名启用管理员不可被停用或降级。
- 数据表中没有图像/视频字段，摄像头客户端只在内存中保留采样帧及临时脸部拼图；脸部裁片发送给外部模型 API 前需要取得适当授权。

## 尚需现场验证

- 真实摄像头与真实视觉 API 端到端取决于用户配置 API Key、模型地址、模型支持图像输入并授予摄像头权限；当前没有对外模型凭据，因此未声称完成真实推理验收。
- 当前WSL没有摄像头设备，Docker Desktop未启用WSL集成；真实摄像头/模型与容器验收不能在此声称完成。不同系统浏览器、目标演示电脑重装运行、负载及长时间稳定性仍待验证。
- 模型输出易受姿态、光线、遮挡、偏差和文化语境影响；应展示聚合数据并由教师结合主动反馈解释。
