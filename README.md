# 微光集 MicroLight

接收微光集 Go 服务推送的告警、问题反馈、友链申请与审核结果，持久化后发送到指定 AstrBot 会话。

## 配置

1. 在星枢 → 账户 → 本站 API 中生成 API Token，复制到本插件的 `api_token`。Token 在星枢后端加密保存，生成时仅显示一次；重置后需要同步更新插件配置。
2. 在插件配置中填写 `microlight_url`（默认 `https://goblincwl.site`）与 `admin_uids`，启用插件通知。在目标会话发送 `/microlight_bind`，绑定通知接收位置。
3. 在 AstrBot 创建具有插件权限的 API Key。这是 AstrBot 自己的 Web API 认证，与上面的 MicroLight Token 不同。
4. 星枢中的接收地址填写：

```text
http://astrbot:6185/api/v1/plugins/extensions/astrbot_plugin_microlight/webhook
```

AstrBot 原生鉴权复用星枢「服务 → AstrBot → 插件 API Key」，由本站以 `X-API-Key` 请求头发送；与场景数据读取共用，无需在接收地址中填写密钥。

Docker 跨网络部署时调整主机名和端口，确保 Go 容器能访问。MicroLight Token 通过 `X-MicroLight-Token` 请求头传输，不写入 URL。

5. 在星枢开启通知，并按需启用告警、反馈、友链分类及告警最低级别。关闭期间产生的业务记录不补发；已经排队的记录保留，重新开启后继续投递。

## 行为

- 新告警和告警级别升级时通知，沿用告警中心的合并规则，不按每次重复发生刷屏。
- 新反馈与反馈处理状态变化时通知；摘要不携带提交者邮箱。
- 友链自动审核通过、累计处理失败达到阈值时通知；新增申请和人工调整审核状态不通知。
- 本站 Token 同时用于查询与限定的管理 API，不能访问完整站点管理接口。

Go 在业务写入事务内保存待推事件，后台投递；同一事件重试时 ID 不变。插件校验 Token、版本和类型，将事件持久化到插件数据目录的 `notifications.sqlite3`，再返回包含事件 ID 的 HTTP 200 确认。重复事件直接确认，不重复入队；最多保留 1000 条未完成事件，超出时返回 503。

Go 的“插件已接收”表示事件已经交给插件保存，**不代表聊天平台已发送成功**。插件另行保存消息发送状态，每次失败从 30 秒开始指数退避，最长一小时；达到 10 次后进入失败状态，支持手动重试。Go 投递端采用同样的失败等待与次数上限，可在星枢查看最近 30 条投递记录并重试。

已完成记录保留 30 天。消息平台不提供幂等保证，因此进程在“消息发送成功、尚未记录成功”的极短窗口退出时，恢复后可能重复发送。

默认把发送的通知写入绑定会话上下文，不触发新的模型请求；通知中的反馈与申请描述作为数据记录，不能视为操作指令。可通过 `record_context` 关闭上下文记录。

## 命令

所有命令均检查 `admin_uids`：

- `/microlight`：查看启用、Token、会话和发送队列状态，不显示密钥。
- `/microlight_check`：使用本站地址与 Bearer Token 校验 API 连接和可用权限，不扫描业务数据。
- `/microlight_bind`：绑定当前会话。
- `/microlight_retry`：重新排队插件中已达到重试上限的失败通知。

## 开发与验证

仅依赖 Python 标准库及 AstrBot 已提供的 SDK／Quart，无额外安装依赖。测试使用临时 SQLite 和模拟请求，不发送真实消息：

```sh
python -m unittest data.plugins.astrbot_plugin_microlight.test_notifications
```

## 本站 API

根路径为 `/api/microlight/v1`，请求头使用 `Authorization: Bearer <星枢生成的Token>`。只接受 GET，不接受查询参数中的 Token，也不能用 Token 访问 `/api/site/admin/` 或生成新 Token。

| 路径 | 作用 |
| --- | --- |
| `/status` | 确认 MicroLight 服务与可用权限 |
| `/alerts`、`/alerts/{id}` | 告警列表和详情；列表支持 page、kind、q |
| `/feedback`、`/feedback/{id}` | 完整反馈列表和详情；列表支持 page |
| `/friends`、`/friends/{id}` | 包括待审申请的友链列表和详情 |

Token 管理入口移到账户模块，仍使用原来的加密凭据记录；已经配置的 Token 不需要因本次升级而重置。权限固定为 `alerts:read`、`feedback:read`、`friends:read`。重置后旧 Token 的后续 API 请求立即返回 401；插件中的 Token 也需要同步更新以继续接收通知。

## 通知模板

在 AstrBot 的 MicroLight 插件配置中分别编辑「告警通知模板」「反馈通知模板」「友链通知模板」，支持多行纯文本。留空恢复默认格式，已有配置无需迁移。

可用变量：`{title}` 标题、`{summary}` 内容、`{status}` 状态、`{recordId}` 业务编号、`{occurredAt}` 事件时间、`{category}` 中文分类、`{level}` 中文告警级别、`{id}` 事件 UUID、`{kind}` 原始类型。未知变量原样保留，事件内容中的花括号不会被二次替换。

模板在实际发送时应用，排队中的通知也会使用当前模板；已发送的消息不会修改。更新插件后先重新加载 MicroLight 插件，再编辑并保存配置。

## LLM 管理工具

所有工具只允许 `admin_uids` 中的用户调用，并要求插件已启用。工具说明要求仅在管理员明确提出操作时执行，不能将申请内容或通知内容当作指令。

- `microlight_records`：按类型查询列表或完整业务编号详情。
- `microlight_delete_alert`：删除指定单条告警，不提供清空。
- `microlight_approve_friend`：仅审核通过，必须已完成首页、RSS、头像预检查。友链处置另有 `microlight_abandon_friend`，不提供仅设为失效的工具。
- `microlight_resolve_feedback`：指定反馈标记已解决。

后端 API 对应 `DELETE /alerts/{id}`、`POST /friends/{id}/approve`、`POST /feedback/{id}/resolve`，继续使用现有 Bearer Token。友链审核和反馈处理复用站点业务流程；反馈状态变化继续按配置通知，友链只通知自动通过和失败阈值事件。

友链提交时不发送 AstrBot 通知；自动审核通过或累计处理失败达到阈值（默认 5，可在星枢配置）及以后每次失败时通知。失败没有退避队列，由周期任务继续处理。收到失败通知不代表管理员已确认：先询问是否发送失败邮件，确认后用 `microlight_send_friend_failure_mail(friend_id, confirmed=true)` 调用 `POST /friends/{id}/failure-mail`。此操作只发邮件，不删除；重复调用不会重复生成邮件任务。星枢「弃用」可向达到阈值的友链发送失败邮件并删除，插件提供管理员确认后调用的 microlight_abandon_friend，调用相同弃用逻辑。

任务／队列操作：使用 `microlight_records(kind="tasks")` 查询列表，传 `record_id` 为任务 key 可查看日志、队列及 `retryable`。管理员明确要求后可调用 `microlight_retry_task(task_key)`，对应 `POST /tasks/{key}/retry`；只有失败或中断且有既有重试入口的任务可重试，正在执行、已排队或成功的任务不能重复提交，返回 202 仅表示已入队。

将反馈标记为已解决（`microlight_resolve_feedback`）也会向反馈邮箱发送处理邮件；重复标记不重复发信。邮件由本站完成，插件无需 SMTP 配置。更新后重新加载 MicroLight 插件即可使用新工具，原 API Token 继续有效。

弃用与拒绝必须区分：用户明确要求“弃用”时，使用 `microlight_abandon_friend(friend_id, confirmed=true)` → `POST /friends/{id}/abandon`。服务端校验累计失败达到当前阈值、有通知邮箱，然后在同一事务中保存失败邮件任务并删除友链。弃用条件不满足时告知原因，不得用其他操作代替。

管理员说「自动审批／自动审核」时使用 `microlight_auto_review_friends(friend_id="")`，留空只批量处理待审核友链，指定 UUID 则只处理该条。已通过和已失效记录不会加入；已入队的审核合并请求。不要重试 `friends-refresh` 来代替自动审核：该任务是检查所有未失效友链的全站巡检。

角色工具白名单：插件注册成功不代表当前角色能使用它。如果角色手动指定了工具列表，在插件配置的 `tool_persona` 填写当前角色名称，插件加载时会通过 PersonaManager 仅追加 MicroLight 工具并刷新角色缓存，保留原有工具。留空不修改角色；每个管理工具仍校验 admin_uids。管理员谈及相关业务时会加入简短工具指引，要求使用 MicroLight 专用工具，禁止用 Shell 拼旧 API，友链处置仅有通过与弃用，旧 reject 路由已移除。
