# ApiPost 测试 Swagger 接口说明

## 1. 该不该做

应该做。

这个项目已经用 FastAPI 暴露了 Swagger / OpenAPI，ApiPost 可以直接导入接口定义，用来做接口调试、冒烟测试和后续回归测试。

## 2. 为什么

- 三套服务 的 REST API 路径基本一致，只需要切换端口。
- ApiPost 比手写 curl 更适合保存请求、复用环境变量、记录响应。
- Swagger 的 `/openapi.json` 可以直接导入 ApiPost，减少手动录接口的错误。

> ⚠️ 风险提醒：`DELETE /api/records` 会清空向量库集合，并清空 PostgreSQL `documents` 表。除非明确要重置数据，否则不要放进常规测试流。

## 3. 怎么做

### 3.1 启动服务

以 Qdrant 为例，先启动数据库容器和 Web API：

```bash
cd /Users/block/Project/semantic-sandbox/qdrant-service
make start
make web
```

启动后访问：

| 项目 | API Base URL | Swagger UI | OpenAPI 导入地址 |
|---|---|---|---|
| Qdrant | `http://localhost:8888` | `http://localhost:8888/docs` | `http://localhost:8888/openapi.json` |
| Weaviate | `http://localhost:8889` | `http://localhost:8889/docs` | `http://localhost:8889/openapi.json` |
| Milvus | `http://localhost:8890` | `http://localhost:8890/docs` | `http://localhost:8890/openapi.json` |

### 3.2 ApiPost 导入 Swagger

在 ApiPost 中：

1. 新建项目或进入已有项目。
2. 选择 `导入`。
3. 选择 `OpenAPI / Swagger`。
4. 输入导入地址：`http://localhost:8888/openapi.json`。
5. 导入完成后，接口会按 Swagger 分组显示。

> 注意：`/docs` 是 Swagger 页面，给人看的；`/openapi.json` 是 OpenAPI 定义，给工具导入用。
>
> 如果 `.env` 开启了 `WEB_AUTH_ENABLED=1`，`/docs` 和 `/openapi.json` 会先要求 Web 登录。ApiPost 直接 URL 导入受限时，开发环境可临时设 `WEB_AUTH_ENABLED=0` 重新启动服务后导入；生产环境不要为了导入接口长期关闭 Web 登录态。

### 3.3 建议配置环境变量

在 ApiPost 环境变量中配置：

| 变量名 | 值 |
|---|---|
| `qdrant_base_url` | `http://localhost:8888` |
| `weaviate_base_url` | `http://localhost:8889` |
| `milvus_base_url` | `http://localhost:8890` |
| `api_key` | `.env` 中的 `API_KEY` |

后续请求地址统一写成：

```text
{{qdrant_base_url}}/api/search
```

所有 `/api/*` 请求都加统一 Header：

```text
X-API-Key: {{api_key}}
```

切换后端时只换变量即可。

## 4. 推荐测试顺序

| 顺序 | 接口 | 目的 |
|---:|---|---|
| 1 | `GET /api/health/panel` | 确认数据库、模型、记录数状态 |
| 2 | `POST /api/ingest` | 写入测试文本 |
| 3 | `POST /api/search` | 验证语义搜索结果 |
| 4 | `GET /api/documents` | 查看写入后的文档元数据 |
| 5 | `PUT /api/documents/{record_id}` | 验证文档更新和向量重建 |
| 6 | `POST /api/upload` | 验证 JSON / CSV 文件批量导入 |

## 5. ApiPost 请求实例

### 实例 1：健康检查

用于确认当前服务是否可用。

| 配置项 | 值 |
|---|---|
| Method | `GET` |
| URL | `{{qdrant_base_url}}/api/health/panel` |
| Headers | `X-API-Key: {{api_key}}` |
| Body | 无 |

预期响应重点：

```json
{
  "backend": "qdrant",
  "db": {
    "ok": true,
    "collection": "sandbox_docs"
  },
  "metadata_count": 10,
  "vector_count": 10
}
```

如果 `db.ok` 是 `false`，先检查数据库容器是否启动：

```bash
cd /Users/block/Project/semantic-sandbox/qdrant-service
make ps
```

### 实例 2：写入文本

用于向向量库写入几条测试文本。

| 配置项 | 值 |
|---|---|
| Method | `POST` |
| URL | `{{qdrant_base_url}}/api/ingest` |
| Headers | `Content-Type: application/json`、`X-API-Key: {{api_key}}` |
| Body 类型 | `JSON` |

Body：

```json
{
  "texts": [
    "巴黎是法国的首都",
    "向量数据库用于语义检索"
  ],
  "category": "geography",
  "tags": ["travel", "sample"],
  "source": "apipost"
}
```

预期响应：

```json
{
  "inserted": 2,
  "ids": [11, 12],
  "skipped": 0,
  "existing_count": 0,
  "existing": []
}
```

字段说明：

| 字段 | 说明 |
|---|---|
| `inserted` | 本次实际写入数量 |
| `ids` | 自动生成的记录 ID |
| `skipped` | 因重复文本或重复 `document_id` 被跳过的数量 |
| `existing` | 已存在记录明细 |

重复提交同一段文本时，预期 `inserted` 可能变成 `0`，`skipped` 大于 `0`。这是正常幂等行为。

### 实例 3：语义搜索

用于验证搜索链路是否跑通。

| 配置项 | 值 |
|---|---|
| Method | `POST` |
| URL | `{{qdrant_base_url}}/api/search` |
| Headers | `Content-Type: application/json`、`X-API-Key: {{api_key}}` |
| Body 类型 | `JSON` |

Body：

```json
{
  "query": "法国著名地标",
  "limit": 5,
  "categories": ["geography"],
  "tags": ["travel"]
}
```

预期响应重点：

```json
{
  "query": "法国著名地标",
  "filter": {
    "categories": ["geography"],
    "tags": ["travel"]
  },
  "results": [
    {
      "id": 11,
      "text": "巴黎是法国的首都",
      "score": 0.8,
      "category": "geography",
      "tags": ["travel", "sample"],
      "source": "apipost"
    }
  ]
}
```

判断标准：

| 检查点 | 通过标准 |
|---|---|
| HTTP 状态码 | `200` |
| `results` | 数组不为空 |
| `score` | 越接近 `1` 越相关 |
| `category` | 和过滤条件一致 |
| `tags` | 至少命中一个过滤标签 |

### 实例 4：分页查看文档

用于查看当前已写入的元数据。

| 配置项 | 值 |
|---|---|
| Method | `GET` |
| URL | `{{qdrant_base_url}}/api/documents?offset=0&limit=10` |
| Headers | `X-API-Key: {{api_key}}` |
| Body | 无 |

预期响应：

```json
{
  "total": 12,
  "offset": 0,
  "limit": 10,
  "items": [
    {
      "id": 1,
      "document_id": "doc_xxx",
      "text": "The Eiffel Tower is a wrought-iron lattice tower located in Paris, France.",
      "category": "geography",
      "tags": [],
      "source": "sample"
    }
  ]
}
```

如果刚才执行过写入接口，可以在 `items` 中查找 `source = apipost` 的记录。

### 实例 5：更新单条文档

用于验证文档更新和向量重建。

| 配置项 | 值 |
|---|---|
| Method | `PUT` |
| URL | `{{qdrant_base_url}}/api/documents/11` |
| Headers | `Content-Type: application/json`、`X-API-Key: {{api_key}}` |
| Body 类型 | `JSON` |

Body：

```json
{
  "text": "埃菲尔铁塔位于法国巴黎，是著名旅游地标。",
  "category": "geography",
  "tags": ["travel", "landmark"],
  "source": "apipost"
}
```

预期响应：

```json
{
  "id": 11,
  "text": "埃菲尔铁塔位于法国巴黎，是著名旅游地标。",
  "category": "geography",
  "tags": ["travel", "landmark"],
  "source": "apipost",
  "updated_at": "2026-04-22T10:00:00+00:00"
}
```

注意：

- URL 中的 `11` 要换成真实存在的记录 ID。
- 更新后会自动重建该文档的向量。
- 如果返回 `404`，说明这个 `record_id` 不存在。

### 实例 6：上传 JSON / CSV 文件

用于验证批量导入。

| 配置项 | 值 |
|---|---|
| Method | `POST` |
| URL | `{{qdrant_base_url}}/api/upload` |
| Headers | `X-API-Key: {{api_key}}` |
| Body 类型 | `form-data` |

ApiPost Body 配置：

| Key | Type | Value |
|---|---|---|
| `file` | `File` | `/Users/block/Project/semantic-sandbox/data/sample_zh.json` |

预期响应：

```json
{
  "inserted": 10,
  "ids": [1, 2, 3],
  "skipped": 0,
  "existing_count": 0,
  "failed": 0,
  "errors": [],
  "job_id": "20260422T120000Z_ab12cd34",
  "status": "completed"
}
```

上传文件格式要求：

| 文件类型 | 要求 |
|---|---|
| JSON | 顶层是数组，每项至少有 `text` |
| CSV | 首行必须包含 `text` 列 |

JSON 示例：

```json
[
  {
    "text": "埃菲尔铁塔是位于法国巴黎的一座铁制镂空结构塔。",
    "category": "geography",
    "tags": ["travel"],
    "source": "apipost-upload"
  }
]
```

CSV 示例：

```csv
text,document_id,category,tags,source
埃菲尔铁塔位于法国巴黎。,poi_eiffel,geography,"travel,landmark",apipost-upload
向量数据库支持语义检索。,tech_vector_db,technology,"vector,search",apipost-upload
```

### 实例 7：查询记录数

用于快速确认向量库当前记录数量。

| 配置项 | 值 |
|---|---|
| Method | `GET` |
| URL | `{{qdrant_base_url}}/api/count` |
| Headers | 无特殊要求 |
| Body | 无 |

预期响应：

```json
{
  "count": 10
}
```

### 实例 8：批量重建向量

用于在文档元数据存在、向量库需要重新同步时执行。

| 配置项 | 值 |
|---|---|
| Method | `POST` |
| URL | `{{qdrant_base_url}}/api/documents/batch-reindex` |
| Headers | `Content-Type: application/json`、`X-API-Key: {{api_key}}` |
| Body 类型 | `JSON` |

Body：

```json
{
  "record_ids": [11, 12]
}
```

预期响应：

```json
{
  "requested": 2,
  "reindexed": 2,
  "record_ids": [11, 12]
}
```

## 6. 高风险接口

以下接口建议单独放到 ApiPost 的“危险操作”目录，不要放进默认批量测试。

| Method | URL | 风险 |
|---|---|---|
| `DELETE` | `{{qdrant_base_url}}/api/record/{record_id}` | 删除单条向量和文档元数据 |
| `DELETE` | `{{qdrant_base_url}}/api/documents/{record_id}` | 删除单条文档和向量 |
| `POST` | `{{qdrant_base_url}}/api/documents/batch-delete` | 批量删除文档和向量 |
| `DELETE` | `{{qdrant_base_url}}/api/records` | 清空集合，并清空 PostgreSQL 文档元数据 |

## 7. 三套后端怎么切换

接口路径和请求体保持一致，只替换 Base URL。

| 后端 | 示例 |
|---|---|
| Qdrant | `{{qdrant_base_url}}/api/search` |
| Weaviate | `{{weaviate_base_url}}/api/search` |
| Milvus | `{{milvus_base_url}}/api/search` |

建议先用 Qdrant 跑通，再复制 ApiPost 环境切到 Weaviate / Milvus。

## 8. 常见问题

### ApiPost 导入失败

先确认 OpenAPI 地址能访问：

```bash
curl http://localhost:8888/openapi.json
```

如果访问失败，说明 Web API 没启动或端口不对。

### 搜索结果为空

优先检查：

- 是否已经执行过 `POST /api/ingest` 或 `POST /api/upload`。
- 搜索时是否加了过窄的 `categories` / `tags` 过滤。
- `GET /api/health/panel` 中 `metadata_count` 和 `vector_count` 是否大于 `0`。

### 写入接口返回 skipped

这是正常的幂等保护。同一段文本重复提交时，系统会按 `text_hash` / `document_id` 判断为已存在，不会重复入库。

### 更新接口返回 404

URL 中的 `record_id` 不存在。先调用：

```text
GET {{qdrant_base_url}}/api/documents?offset=0&limit=50
```

从返回的 `items[].id` 中选一个真实 ID 再更新。
