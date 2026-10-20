# 系统API接口文档 V2

> 文档编号：TECH-API-2026-003 ｜ 版本：V2.1 ｜ 更新日期：2026-06-18 ｜ 基础路径：`/api`

## 一、接口约定

### 1.1 基础说明

- **协议**：HTTP/1.1 与 HTTP/2，全链路强制 HTTPS；
- **数据格式**：请求与响应均为 UTF-8 编码的 JSON（文件上传除外），时间字段统一为 ISO 8601 格式（如 `2026-06-18T09:30:00+08:00`）；
- **鉴权方式**：所有管理接口需在请求头携带 `Authorization: Bearer <API_KEY>`；对话接口支持 API Key 与临时会话 Token 两种方式；
- **分页约定**：列表接口统一使用 `page`（从 1 开始）与 `page_size` 参数，响应包含 `items / total / page / page_size` 四个字段。

### 1.2 通用错误结构

```json
{
  "detail": "知识库名称「产品文档」已存在（name 唯一约束）"
}
```

| HTTP 状态码 | 含义 | 处理建议 |
| --- | --- | --- |
| 400 | 参数错误或业务规则校验失败 | 检查请求体字段 |
| 401 | 未携带或 API Key 无效 | 刷新凭证 |
| 404 | 资源不存在 | 检查路径中的 ID |
| 409 | 资源冲突（重名等） | 更换名称后重试 |
| 429 | 触发限流（默认 60 次/分钟） | 指数退避重试 |
| 500 | 服务端内部错误 | 联系管理员并附 trace_id |

## 二、知识库管理

### 2.1 创建知识库

`POST /api/admin/kb`

请求体：

```json
{
  "name": "产品文档库",
  "description": "存放产品白皮书、需求文档与发布说明"
}
```

响应 `201`：

```json
{
  "id": 3,
  "name": "产品文档库",
  "description": "存放产品白皮书、需求文档与发布说明",
  "doc_count": 0,
  "chunk_count": 0
}
```

规则说明：`name` 必填且全局唯一（违反返回 409）；`description` 可选，不超过 200 字。

### 2.2 查询知识库列表

`GET /api/admin/kb`

响应为知识库数组，每个元素额外包含 `doc_count`（ready 状态文档数）与 `chunk_count`（切片总数）。

### 2.3 上传文档

`POST /api/admin/kb/{kb_id}/documents`

请求为 `multipart/form-data`，字段名 `file`。支持 md / txt / pdf / docx，单文件不超过 20MB。响应 `202` 返回文档记录，入库流水线异步执行，前端应轮询文档状态直至 `ready` 或 `failed`：

| status | 含义 |
| --- | --- |
| parsing | 正在解析 |
| chunking | 正在切片 |
| embedding | 正在向量化 |
| ready | 入库完成，chunk_count 可用 |
| failed | 失败，查看 error_msg |

### 2.4 文档切片明细

`GET /api/admin/kb/{kb_id}/documents/{doc_id}/chunks?page=1&page_size=8`

返回该文档的切片列表（chunk_no、section_path、content、token_count），`page_size` 上限 50。仅 `ready` 状态文档可查询。

### 2.5 失败重试与删除

- 重试：`POST /api/admin/kb/{kb_id}/documents/{doc_id}/retry`，仅 `failed` 状态可调用，返回 202；
- 删除：`DELETE /api/admin/kb/{kb_id}/documents/{doc_id}`，先清理 ES 索引再删除 MySQL 记录，操作不可恢复。

## 三、对话问答

### 3.1 发起对话（SSE 流式）

`POST /api/chat`

请求体：

```json
{
  "kb_id": 3,
  "question": "系统支持哪些文档格式？",
  "history_id": "conv_9f2a8c",
  "mode": "agentic"
}
```

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| kb_id | int | 是 | 目标知识库 ID |
| question | string | 是 | 用户问题，上限 2000 字符 |
| history_id | string | 否 | 会话 ID，首次对话不传，服务端在首个事件返回 |
| mode | string | 否 | `agentic`（默认，六决策点全开）或 `fast`（跳过反思与补全） |

响应为 `text/event-stream`，事件按顺序推送：

1. `meta`：会话 ID、使用的模型与知识库信息；
2. `decision`：六个决策点事件，`type` 取值 `intent / datasource / grading / crag / reflect / citation`，每个事件携带决策结论、置信度与耗时毫秒数；
3. `retrieval`：检索命中的引用列表（doc_name、chunk_no、score、摘要前 100 字）；
4. `token`：正文增量片段，逐段推送；
5. `done`：统计信息（总耗时、token 消耗、引用数）；
6. `error`：错误事件（流中途失败时推送，随后关闭连接）。

### 3.2 引用溯源

`GET /api/admin/chunks/by-citation?doc_name=产品白皮书&chunk_no=5`

返回引用命中的文档记录与切片原文。`doc_name` 为文档名去掉扩展名；若同名文档多次入库，返回最新一条 ready 记录。

### 3.3 决策日志查询

`GET /api/admin/decision-logs?history_id=conv_9f2a8c`

返回该会话全部决策点日志，用于调试与效果分析。日志默认保留 90 天，可在管理端配置。

## 四、数据源与 NL2SQL

### 4.1 数据源管理

- 新增：`POST /api/admin/datasources`，body 包含 `name / type(mysql|http_api) / config / description`，其中 MySQL 数据源需提供 host、port、user、password、database，密码加密存储；
- 测试连通：`POST /api/admin/datasources/{id}/test`，返回连通耗时与错误详情（如有）；
- 删除：`DELETE /api/admin/datasources/{id}`，已被知识库绑定的数据源不可删除（返回 409）。

### 4.2 数据问答安全规则

生成的 SQL 必须通过只读校验：仅允许 `SELECT` 语句；禁止多语句；执行超时 10 秒；结果集超过 50 行自动截断并在响应中标注 `truncated: true`。

## 五、检索测试

`POST /api/admin/retrieval-test`

```json
{
  "kb_id": 3,
  "query": "年假有几天",
  "top_k": 5,
  "retrievers": ["vector", "bm25", "fused"]
}
```

返回三路召回结果与各自得分，用于评估检索质量。`retrievers` 可传空数组，默认全部执行。

## 六、速率限制与配额

- 对话接口：每 API Key 60 次/分钟，并发流式连接上限 10；
- 文档上传：每知识库每分钟 30 个文件；
- 嵌入接口：批量向量化每分钟 600 条切片；
- 超限返回 429，响应头包含 `Retry-After` 秒数。

## 七、变更记录

- V2.1（2026-06-18）：新增引用溯源接口；决策日志支持按会话查询。
- V2.0（2026-05-06）：对话接口全面切换 SSE；新增 `fast` 模式。
- V1.3（2026-03-02）：新增检索测试接口与决策点可视化事件。
