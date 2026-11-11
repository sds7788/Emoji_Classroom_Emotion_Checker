# 需求交付与现场验收记录

核对基准：根目录 `requirement.png`。按用户后续要求暂不生成最终提交压缩包。

## 本轮已完成

| 要求 | 实际处理 | 证据 |
| --- | --- | --- |
| 教师指标口径 | 总数、积极/专注比例统一为所选课堂近60分钟；历史分布独立显示筛选总数 | `frontend/script.js`；浏览器步骤3 |
| WebSocket持续授权 | 每次推送前复核JWT有效期、账号状态、令牌版本、角色和课堂归属；失效关闭 | `backend/auth.py`、`backend/realtime.py`；单元及真实连接验证 |
| 补测 | 51项通过、0失败、0跳过；Service、权限、CSV、SQL注入、弱密码、AI模拟链路与采样/配置 | [自动化输出](evidence/unit-tests.txt) |
| 跨角色验收 | 创建课程→开放课次→名单→学生提交→教师推送→管理员统计→来源筛选与CSV下载 | [步骤、预期及实际结果](evidence/browser/results.json) |
| AI可操作性 | 自动读`.env`，生成独立随机密钥，修正JSON提示，校验模型响应，新增单次/限定采样和脱敏JSONL | [AI接入指南](ai-integration.md) |
| 管理员摄像头可视化 | 网页开启/停止摄像头，显示画面、emoji、置信度、采样图及入库状态，展示课次ID | [指南](ai-web-monitor.md)、[11个浏览器场景](evidence/ai-browser/results.json)、[截图](evidence/ai-browser/01-live-result.png) |
| 视频准备 | 5～8分钟分镜、讲解、OBS设置及录后检查 | [录制指南](demo-script.md) |

截图：[排课](evidence/browser/01-schedule.png)、[学生](evidence/browser/02-student.png)、[教师](evidence/browser/03-teacher.png)、[管理员](evidence/browser/04-admin.png)、[AI筛选导出](evidence/browser/05-export.png)、[窄屏](evidence/browser/06-mobile.png)。截图中的AI数据来自受控接口输入，不能作为真实模型结果。

## 尚需现场完成

| 项目 | 当前状态 | 完成时需补齐 |
| --- | --- | --- |
| 真实AI链路 | 本轮自动化使用合成摄像头及模拟模型，未执行用户Windows电脑上的实测 | 网页识别截图、模型名、课次/记录ID及AI来源CSV；CLI可另存JSONL |
| 5～8分钟成片 | 尚未录制 | 可回放MP4、实际时长、路径、全过程及旁白 |
| 目标电脑重装运行 | 本轮在当前WSL新建虚拟环境安装并运行；目标演示电脑待验证 | 系统/Python版本、安装/启动/health、三角色流程和摄像头 |
| Docker运行 | 当前WSL未启用Docker Desktop集成，无法构建运行验收 | 若视频展示Docker，补构建、health、日志、卷持久化 |
| 最终压缩包 | 按用户要求暂缓 | 组号确定后按指导书命名，加入实测/视频，排除密钥、虚拟环境和缓存 |

## 真实AI现场模板

复制本节按实测填写，没有证据时保留“未验证”。

| 字段 | 实际值 |
| --- | --- |
| 验收时间（含时区）/操作人 | 待填写 |
| 系统/Python/摄像头编号 | 待填写 |
| 服务商/模型名（不填密钥） | 待填写 |
| 课次ID/开放时间/状态 | 待填写 |
| 本地及后端阈值/采样次数 | 待填写 |
| 人脸→模型→入库 | 待验证：事件时间、samples、emoji_type、confidence、accepted和记录ID |
| 无人脸 | 待验证：no_face_detected且不入库 |
| 低置信度 | 待验证；未自然出现时注明仅有模拟证据 |
| 看板/筛选/导出 | 待验证：同课次、AI来源、匿名、ID和置信度一致 |
| 失败及重试 | 如实填写异常类型、HTTP状态、处理和结果 |
| 附件与结论 | JSONL路径、截图、CSV；通过/未通过/部分通过 |

## 目标电脑与视频模板

| 步骤 | 预期 | 实际及证据 |
| --- | --- | --- |
| 新虚拟环境安装 | requirements安装成功 | 待填写 |
| 配置并启动 | 不展示密钥；health返回200 | 待填写 |
| 三角色流程 | 排课/提交/查看/筛选/导出成功 | 待填写 |
| 真实AI | 成功事件与数据库/看板对应 | 待填写 |
| Docker（若采用） | 构建/启动/持久化通过 | 未采用则填“不展示Docker部署” |
| 视频回放 | 5～8分钟，画面/声音完整，密钥未暴露 | 待填写路径、时长、结论 |
