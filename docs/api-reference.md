# semantic-sandbox API Reference

适用对象：前端对接、测试验收。

本文档以 `qdrant-service` 为基准，覆盖当前 REST API 的请求代码、参数、正确请求、正确响应和常见错误。`weaviate-service`、`milvus-service` 的接口路径与请求/响应结构保持一致，差异见“多后端差异”。

说明：本文档覆盖 API 对接路径；`/`、`/ingest`、`/documents`、`/health/panel`、`/logs` 等 HTML 页面和表单提交路由属于 Web UI 内部路由，不作为前端 API 对接接口。开启 `WEB_AUTH_ENABLED=1` 后，浏览器页面、Swagger UI 和 `/openapi.json` 需要先通过 `/login` 登录。

## 1. 基础信息

### 1.1 服务地址

| 后端 | 启动目录 | API Base URL | Swagger UI | OpenAPI |
|---|---|---|---|---|
| Qdrant | `qdrant-service/` | `http://localhost:8888` | `http://localhost:8888/docs` | `http://localhost:8888/openapi.json` |
| Weaviate | `weaviate-service/` | `http://localhost:8889` | `http://localhost:8889/docs` | `http://localhost:8889/openapi.json` |
| Milvus | `milvus-service/` | `http://localhost:8890` | `http://localhost:8890/docs` | `http://localhost:8890/openapi.json` |

当前仓库未包含 Chroma、Faiss 目录。本文档只记录实际存在的三个服务。

### 1.2 启动 Qdrant API

```bash
cd /Users/block/Project/semantic-sandbox/qdrant-service
make start
make web
```

### 1.3 通用约定

| 项 | 说明 |
|---|---|
| 鉴权 | REST API 默认使用 `X-API-Key`。Web UI 使用签名 Cookie 登录态。`/health`、`GET /api/count`、`GET /api/model/status`、`GET /api/samples/{lang}` 保持公开，便于探活和 Web UI 基础读取。 |
| 请求格式 | JSON 接口使用 `Content-Type: application/json`。文件上传接口使用 `multipart/form-data`。 |
| 响应格式 | 默认 JSON；失败行下载接口返回 `text/csv`。 |
| ID 规则 | 文档 ID 由 PostgreSQL 自增主键分配。 |
| 重复写入 | 重复文本会被跳过，返回 `skipped` 和 `existing`，属于正常幂等行为。 |
| 分页限制 | `GET /api/documents` 的 `limit` 服务端限制在 `1..200`。 |
| 搜索限制 | 搜索最终返回数量限制在 `1..20`。 |
| 前端跨域 | 当前 FastAPI 应用未配置 CORS。若前端运行在其他端口，浏览器可能因跨域拦截请求；同源调用或后端补充 CORS 后再对接。 |

⚠️ 风险：`DELETE /api/records` 会清空当前向量库集合，并清空 PostgreSQL `documents` 表。测试环境可以用，验收脚本不要默认执行。

### 1.4 通用客户端变量

curl：

```bash
BASE_URL=http://localhost:8888
```

Python：

```python
import requests

BASE_URL = "http://localhost:8888"
```

浏览器 fetch：

```js
const BASE_URL = "http://localhost:8888";
```

Node.js 18+：

```js
const BASE_URL = "http://localhost:8888";
```

若 `.env` 中 `AUTH_ENABLED=1`，写入、搜索、文档管理、导入任务、健康面板等 `/api/*` 请求需要带 API Key：

```bash
API_KEY=change_me_to_a_long_random_secret
curl -H "X-API-Key: $API_KEY" "$BASE_URL/api/documents"
```

```python
HEADERS = {"X-API-Key": "change_me_to_a_long_random_secret"}
```

```js
const HEADERS = {"X-API-Key": "change_me_to_a_long_random_secret"};
```

Web UI 登录态使用单独配置，不替代 REST API Key：

```env
WEB_AUTH_ENABLED=1
WEB_USERNAME=admin
WEB_PASSWORD=change_me_to_a_strong_password
WEB_SESSION_SECRET=change_me_to_a_long_random_session_secret
```

浏览器访问 `/docs` 或 `/openapi.json` 如果被重定向到 `/login`，先登录即可；ApiPost、curl、后端服务调用仍应直接访问 `/api/*` 并携带 `X-API-Key`。

日志口径：

- `audit_logs`：登录、登出、API Key 鉴权失败、写入、上传、更新、删除、清空、重建索引。
- `search_logs`：搜索 query 摘要、过滤条件、结果数、延迟。
- `app_errors`：应用主动捕获的异常。
- 普通访问日志不入库，建议走 Docker / Nginx / 日志系统。

后文每个接口的“正确请求”代码块顺序固定为：`curl`、`Python requests`、浏览器 `fetch`、`Node.js 18+ fetch`。

## 2. 数据模型

### 2.1 Document

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | integer | 服务端自增记录 ID。 |
| `document_id` | string | 基于文本 hash 生成的稳定文档 ID，上传时可传入。 |
| `text_hash` | string | 文本归一化后的 SHA-256。 |
| `text` | string | 原始文本。 |
| `category` | string | 分类。 |
| `tags` | string[] | 标签数组。 |
| `source` | string | 来源，例如 `api`、`upload`、`frontend`。 |
| `created_at` | string | UTC ISO 时间。 |
| `updated_at` | string | UTC ISO 时间。 |

### 2.2 标准错误格式

业务主动抛出的错误：

```json
{
  "detail": "文档不存在"
}
```

FastAPI 参数校验错误：

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "texts"],
      "msg": "Field required"
    }
  ]
}
```

常见 HTTP 状态：

| 状态码 | 场景 |
|---:|---|
| `200` | 请求成功。 |
| `400` | 请求内容业务上不合法，例如上传文件解析失败、批量操作未传 ID。 |
| `404` | 资源不存在，例如文档不存在、导入任务不存在、样本语言不支持。 |
| `422` | 请求参数类型不匹配或缺少必填字段。 |
| `500` | 向量数据库不可用、模型加载失败或未捕获异常。 |
| `503` | `/health` 检测到向量数据库不可用。 |

## 3. 接口总览

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/health` | 基础健康检查，不展示在 Swagger。 |
| `GET` | `/api/health/panel` | 健康面板数据，推荐给前端状态页使用。 |
| `GET` | `/api/model/status` | 查看嵌入模型状态。 |
| `GET` | `/model/status` | 兼容旧路径的模型状态接口。 |
| `POST` | `/api/ingest` | JSON 文本写入。 |
| `POST` | `/api/upload` | JSON/CSV 文件批量上传写入。 |
| `POST` | `/api/search` | 语义搜索。 |
| `GET` | `/api/count` | 查询向量库记录数。 |
| `GET` | `/api/documents` | 分页查看文档元数据。 |
| `GET` | `/api/documents/{record_id}` | 查看单条文档。 |
| `PUT` | `/api/documents/{record_id}` | 更新文档并重建向量。 |
| `DELETE` | `/api/documents/{record_id}` | 删除文档和向量。 |
| `DELETE` | `/api/record/{record_id}` | 旧路径，删除指定 ID 的记录。 |
| `POST` | `/api/documents/batch-delete` | 批量删除文档和向量。 |
| `POST` | `/api/documents/batch-reindex` | 批量重建所选文档向量。 |
| `POST` | `/api/reindex` | 按 PostgreSQL `documents` 表重建整个向量集合。 |
| `DELETE` | `/api/records` | 清空全部记录。 |
| `GET` | `/api/import-jobs/{job_id}` | 查看上传导入任务状态。 |
| `GET` | `/api/import-jobs/{job_id}/failed-rows` | 下载上传失败行 CSV。 |
| `GET` | `/api/samples/{lang}` | 获取示例数据文本。 |

## 4. 接口详情

### 4.1 GET `/health`

用途：基础健康检查，用于快速判断 API 与向量数据库是否连通。

参数：无。

正确请求：

```bash
curl "$BASE_URL/health"
```

```python
res = requests.get(f"{BASE_URL}/health", timeout=10)
print(res.status_code, res.json())
```

```js
const res = await fetch(`${BASE_URL}/health`);
console.log(res.status, await res.json());
```

```js
const res = await fetch(`${BASE_URL}/health`);
console.log(res.status, await res.json());
```

正确响应：

```json
{
  "status": "ok",
  "db": "qdrant",
  "metadata_store": "postgres"
}
```

常见错误：

```json
{
  "detail": "向量数据库未连接，请先在项目根目录执行 docker compose --profile qdrant up -d postgres qdrant"
}
```

### 4.2 GET `/api/health/panel`

用途：返回前端健康面板所需数据，包括数据库状态、模型状态、元数据数量、向量数量、最近错误和分类选项。

参数：无。

正确请求：

```bash
curl "$BASE_URL/api/health/panel"
```

```python
res = requests.get(f"{BASE_URL}/api/health/panel", timeout=10)
print(res.json())
```

```js
const res = await fetch(`${BASE_URL}/api/health/panel`);
console.log(await res.json());
```

```js
const res = await fetch(`${BASE_URL}/api/health/panel`);
console.log(await res.json());
```

正确响应：

```json
{
  "backend": "qdrant",
  "db": {
    "ok": true,
    "detail": "Qdrant 连接正常",
    "collection": "sandbox_docs"
  },
  "model": {
    "model": "sentence-transformers/all-MiniLM-L6-v2",
    "source": "/Users/block/Project/semantic-sandbox/models/models--sentence-transformers--all-MiniLM-L6-v2/snapshots/xxx",
    "cache_dir": "/Users/block/Project/semantic-sandbox/models",
    "local_only": true,
    "source_exists": true,
    "dimension": 384,
    "loaded": true
  },
  "metadata_count": 2,
  "vector_count": 2,
  "recent_errors": [],
  "category_options": ["technology", "science", "geography"]
}
```

常见错误：该接口通常返回 `200`。如果数据库不可用，`db.ok` 为 `false`，错误原因在 `db.detail`。

### 4.3 GET `/api/model/status`

用途：查看当前嵌入模型配置与加载状态。

参数：无。

正确请求：

```bash
curl "$BASE_URL/api/model/status"
```

```python
res = requests.get(f"{BASE_URL}/api/model/status", timeout=10)
print(res.json())
```

```js
const res = await fetch(`${BASE_URL}/api/model/status`);
console.log(await res.json());
```

```js
const res = await fetch(`${BASE_URL}/api/model/status`);
console.log(await res.json());
```

正确响应示例：

```json
{
  "model": "sentence-transformers/all-MiniLM-L6-v2",
  "source": "/Users/block/Project/semantic-sandbox/models/models--sentence-transformers--all-MiniLM-L6-v2/snapshots/xxx",
  "cache_dir": "/Users/block/Project/semantic-sandbox/models",
  "local_only": true,
  "source_exists": true,
  "dimension": 384,
  "loaded": true
}
```

常见错误：模型路径缺失或模型加载失败时可能返回 `500`。

### 4.4 GET `/model/status`

用途：兼容旧路径，响应结构与 `/api/model/status` 相同。

参数：无。

正确请求：

```bash
curl "$BASE_URL/model/status"
```

```python
res = requests.get(f"{BASE_URL}/model/status", timeout=10)
print(res.json())
```

```js
const res = await fetch(`${BASE_URL}/model/status`);
console.log(await res.json());
```

```js
const res = await fetch(`${BASE_URL}/model/status`);
console.log(await res.json());
```

正确响应：同 `/api/model/status`。

常见错误：同 `/api/model/status`。

### 4.5 POST `/api/ingest`

用途：把文本列表向量化后写入向量库，同时写入 PostgreSQL `documents` 表并记录向量同步状态。

参数：

| 位置 | 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| body | `texts` | string[] | 是 | 每个字符串会作为独立文档写入。空字符串会被忽略。 |
| body | `category` | string | 否 | 分类，默认空字符串。 |
| body | `tags` | string[] | 否 | 标签数组，默认空数组。 |
| body | `source` | string | 否 | 来源，默认 `api`。 |

正确请求：

```bash
curl -X POST "$BASE_URL/api/ingest" \
  -H "Content-Type: application/json" \
  -d '{
    "texts": ["巴黎是法国的首都", "向量数据库用于语义检索"],
    "category": "geography",
    "tags": ["travel", "sample"],
    "source": "frontend"
  }'
```

```python
payload = {
    "texts": ["巴黎是法国的首都", "向量数据库用于语义检索"],
    "category": "geography",
    "tags": ["travel", "sample"],
    "source": "frontend",
}
res = requests.post(f"{BASE_URL}/api/ingest", json=payload, timeout=60)
res.raise_for_status()
print(res.json())
```

```js
const payload = {
  texts: ["巴黎是法国的首都", "向量数据库用于语义检索"],
  category: "geography",
  tags: ["travel", "sample"],
  source: "frontend"
};
const res = await fetch(`${BASE_URL}/api/ingest`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload)
});
console.log(await res.json());
```

```js
const payload = {
  texts: ["巴黎是法国的首都", "向量数据库用于语义检索"],
  category: "geography",
  tags: ["travel", "sample"],
  source: "node"
};
const res = await fetch(`${BASE_URL}/api/ingest`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload)
});
console.log(await res.json());
```

正确响应：

```json
{
  "inserted": 2,
  "ids": [1, 2],
  "skipped": 0,
  "existing_count": 0,
  "existing": [],
  "failed": 0,
  "errors": [],
  "job_id": null,
  "status": null,
  "failed_rows_download_url": null
}
```

重复写入响应：

```json
{
  "inserted": 0,
  "ids": [],
  "skipped": 2,
  "existing_count": 2,
  "existing": [
    {
      "id": 1,
      "document_id": "doc_xxx",
      "reason": "text_hash",
      "input_index": 1
    }
  ],
  "failed": 0,
  "errors": []
}
```

错误请求：

```bash
curl -X POST "$BASE_URL/api/ingest" \
  -H "Content-Type: application/json" \
  -d '{"category":"geography"}'
```

错误响应：

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "texts"],
      "msg": "Field required"
    }
  ]
}
```

### 4.6 POST `/api/upload`

用途：上传 JSON 或 CSV 文件批量写入。支持 UTF-8 BOM。CSV 首行必须包含 `text` 列。

参数：

| 位置 | 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| form-data | `file` | file | 是 | `.json` 或 `.csv` 文件。 |

文件格式：

```json
[
  {
    "text": "巴黎是法国的首都",
    "category": "geography",
    "tags": ["travel", "sample"],
    "source": "upload"
  }
]
```

```csv
text,category,tags,source
巴黎是法国的首都,geography,"travel,sample",upload
```

正确请求：

```bash
curl -X POST "$BASE_URL/api/upload" \
  -F "file=@/Users/block/Project/semantic-sandbox/data/sample_zh.json"
```

```python
with open("/Users/block/Project/semantic-sandbox/data/sample_zh.json", "rb") as f:
    res = requests.post(f"{BASE_URL}/api/upload", files={"file": f}, timeout=120)
res.raise_for_status()
print(res.json())
```

```js
const input = document.querySelector('input[type="file"]');
const form = new FormData();
form.append("file", input.files[0]);
const res = await fetch(`${BASE_URL}/api/upload`, {
  method: "POST",
  body: form
});
console.log(await res.json());
```

```js
import { readFile } from "node:fs/promises";

const bytes = await readFile("/Users/block/Project/semantic-sandbox/data/sample_zh.json");
const form = new FormData();
form.append("file", new Blob([bytes], { type: "application/json" }), "sample_zh.json");
const res = await fetch(`${BASE_URL}/api/upload`, {
  method: "POST",
  body: form
});
console.log(await res.json());
```

正确响应：

```json
{
  "inserted": 3,
  "ids": [3, 4, 5],
  "skipped": 0,
  "existing_count": 0,
  "existing": [],
  "failed": 0,
  "errors": [],
  "job_id": "20260427T060000Z_ab12cd34",
  "status": "completed",
  "failed_rows_download_url": null
}
```

部分失败响应：

```json
{
  "inserted": 2,
  "ids": [6, 7],
  "skipped": 0,
  "existing_count": 0,
  "existing": [],
  "failed": 1,
  "errors": ["第 3 行：缺少 text"],
  "job_id": "20260427T060000Z_ab12cd34",
  "status": "completed",
  "failed_rows_download_url": "/api/import-jobs/20260427T060000Z_ab12cd34/failed-rows"
}
```

错误请求：

```bash
curl -X POST "$BASE_URL/api/upload" \
  -F "file=@/tmp/broken.json"
```

错误响应：

```json
{
  "detail": "文件解析失败：JSON 顶层必须是数组"
}
```

### 4.7 POST `/api/search`

用途：把查询文本向量化后做近邻检索，并支持分类、标签、创建时间范围过滤。

参数：

| 位置 | 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| body | `query` | string | 是 | 查询文本。 |
| body | `limit` | integer | 否 | 返回数量，默认 `5`，最终限制 `1..20`。 |
| body | `category` | string/null | 否 | 单分类过滤，兼容旧字段。 |
| body | `categories` | string[] | 否 | 多分类过滤。 |
| body | `tags` | string[] | 否 | 标签过滤，命中任意一个标签即可。 |
| body | `created_at_from` | string/null | 否 | 起始时间，支持 ISO 时间或日期。 |
| body | `created_at_to` | string/null | 否 | 结束时间，支持 ISO 时间或日期。 |

正确请求：

```bash
curl -X POST "$BASE_URL/api/search" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "法国著名地标",
    "limit": 5,
    "categories": ["geography"],
    "tags": ["travel"]
  }'
```

```python
payload = {
    "query": "法国著名地标",
    "limit": 5,
    "categories": ["geography"],
    "tags": ["travel"],
}
res = requests.post(f"{BASE_URL}/api/search", json=payload, timeout=60)
res.raise_for_status()
print(res.json())
```

```js
const payload = {
  query: "法国著名地标",
  limit: 5,
  categories: ["geography"],
  tags: ["travel"]
};
const res = await fetch(`${BASE_URL}/api/search`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload)
});
console.log(await res.json());
```

```js
const payload = {
  query: "法国著名地标",
  limit: 5,
  categories: ["geography"],
  tags: ["travel"]
};
const res = await fetch(`${BASE_URL}/api/search`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload)
});
console.log(await res.json());
```

正确响应：

```json
{
  "query": "法国著名地标",
  "filter": {
    "categories": ["geography"],
    "tags": ["travel"]
  },
  "results": [
    {
      "id": 1,
      "text": "巴黎是法国的首都",
      "score": 0.8732,
      "snippet": "巴黎是法国的首都",
      "matched_terms": ["法国"],
      "score_explanation": "高度相关，score=0.8732，越接近 1 越相似。",
      "category": "geography",
      "tags": ["travel", "sample"],
      "source": "frontend",
      "created_at": "2026-04-27T06:00:00+00:00",
      "updated_at": "2026-04-27T06:00:00+00:00"
    }
  ]
}
```

错误请求：

```bash
curl -X POST "$BASE_URL/api/search" \
  -H "Content-Type: application/json" \
  -d '{"limit":5}'
```

错误响应：

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "query"],
      "msg": "Field required"
    }
  ]
}
```

### 4.8 GET `/api/count`

用途：查询向量库中当前记录数。

参数：无。

正确请求：

```bash
curl "$BASE_URL/api/count"
```

```python
res = requests.get(f"{BASE_URL}/api/count", timeout=10)
print(res.json())
```

```js
const res = await fetch(`${BASE_URL}/api/count`);
console.log(await res.json());
```

```js
const res = await fetch(`${BASE_URL}/api/count`);
console.log(await res.json());
```

正确响应：

```json
{
  "count": 2
}
```

常见错误：该接口捕获数据库异常并返回 `{"count": 0}`，不能单独作为数据库健康判断依据。

### 4.9 GET `/api/documents`

用途：分页查看 PostgreSQL 文档元数据。

参数：

| 位置 | 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| query | `offset` | integer | 否 | 起始偏移，默认 `0`，小于 `0` 时按 `0` 处理。 |
| query | `limit` | integer | 否 | 每页数量，默认 `50`，服务端限制 `1..200`。 |

正确请求：

```bash
curl "$BASE_URL/api/documents?offset=0&limit=20"
```

```python
res = requests.get(f"{BASE_URL}/api/documents", params={"offset": 0, "limit": 20}, timeout=10)
print(res.json())
```

```js
const params = new URLSearchParams({ offset: "0", limit: "20" });
const res = await fetch(`${BASE_URL}/api/documents?${params}`);
console.log(await res.json());
```

```js
const params = new URLSearchParams({ offset: "0", limit: "20" });
const res = await fetch(`${BASE_URL}/api/documents?${params}`);
console.log(await res.json());
```

正确响应：

```json
{
  "total": 2,
  "offset": 0,
  "limit": 20,
  "items": [
    {
      "id": 1,
      "document_id": "doc_xxx",
      "text": "巴黎是法国的首都",
      "category": "geography",
      "tags": ["travel", "sample"],
      "source": "frontend"
    }
  ]
}
```

错误请求：

```bash
curl "$BASE_URL/api/documents?offset=abc&limit=20"
```

错误响应：

```json
{
  "detail": [
    {
      "type": "int_parsing",
      "loc": ["query", "offset"],
      "msg": "Input should be a valid integer"
    }
  ]
}
```

### 4.10 GET `/api/documents/{record_id}`

用途：查看单条文档元数据。

参数：

| 位置 | 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| path | `record_id` | integer | 是 | 文档记录 ID。 |

正确请求：

```bash
curl "$BASE_URL/api/documents/1"
```

```python
record_id = 1
res = requests.get(f"{BASE_URL}/api/documents/{record_id}", timeout=10)
print(res.json())
```

```js
const recordId = 1;
const res = await fetch(`${BASE_URL}/api/documents/${recordId}`);
console.log(await res.json());
```

```js
const recordId = 1;
const res = await fetch(`${BASE_URL}/api/documents/${recordId}`);
console.log(await res.json());
```

正确响应：

```json
{
  "id": 1,
  "document_id": "doc_xxx",
  "text_hash": "xxx",
  "text": "巴黎是法国的首都",
  "category": "geography",
  "tags": ["travel", "sample"],
  "source": "frontend",
  "created_at": "2026-04-27T06:00:00+00:00",
  "updated_at": "2026-04-27T06:00:00+00:00"
}
```

错误请求：

```bash
curl "$BASE_URL/api/documents/999999"
```

错误响应：

```json
{
  "detail": "文档不存在"
}
```

### 4.11 PUT `/api/documents/{record_id}`

用途：更新文档元数据，并用新文本重建该文档向量。

参数：

| 位置 | 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| path | `record_id` | integer | 是 | 文档记录 ID。 |
| body | `text` | string | 是 | 新文本，不能为空。 |
| body | `category` | string | 否 | 分类，默认空字符串。 |
| body | `tags` | string[] | 否 | 标签数组。 |
| body | `source` | string | 否 | 来源，默认 `api`。 |

正确请求：

```bash
curl -X PUT "$BASE_URL/api/documents/1" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "巴黎是法国的首都，也是著名旅游城市",
    "category": "geography",
    "tags": ["travel", "city"],
    "source": "frontend"
  }'
```

```python
record_id = 1
payload = {
    "text": "巴黎是法国的首都，也是著名旅游城市",
    "category": "geography",
    "tags": ["travel", "city"],
    "source": "frontend",
}
res = requests.put(f"{BASE_URL}/api/documents/{record_id}", json=payload, timeout=60)
res.raise_for_status()
print(res.json())
```

```js
const recordId = 1;
const payload = {
  text: "巴黎是法国的首都，也是著名旅游城市",
  category: "geography",
  tags: ["travel", "city"],
  source: "frontend"
};
const res = await fetch(`${BASE_URL}/api/documents/${recordId}`, {
  method: "PUT",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload)
});
console.log(await res.json());
```

```js
const recordId = 1;
const payload = {
  text: "巴黎是法国的首都，也是著名旅游城市",
  category: "geography",
  tags: ["travel", "city"],
  source: "node"
};
const res = await fetch(`${BASE_URL}/api/documents/${recordId}`, {
  method: "PUT",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(payload)
});
console.log(await res.json());
```

正确响应：返回更新后的 `Document`。

错误请求：

```bash
curl -X PUT "$BASE_URL/api/documents/1" \
  -H "Content-Type: application/json" \
  -d '{"text": ""}'
```

错误响应：

```json
{
  "detail": "text 不能为空"
}
```

其他常见错误：

| 状态码 | 响应 | 原因 |
|---:|---|---|
| `404` | `{"detail":"文档不存在: 999999"}` | 记录不存在。 |
| `400` | `{"detail":"已有相同文本，不能更新为重复内容"}` | 新文本与其他文档重复。 |

### 4.12 DELETE `/api/documents/{record_id}`

用途：删除指定文档及其向量。推荐使用该路径。

参数：

| 位置 | 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| path | `record_id` | integer | 是 | 文档记录 ID。 |

正确请求：

```bash
curl -X DELETE "$BASE_URL/api/documents/1"
```

```python
record_id = 1
res = requests.delete(f"{BASE_URL}/api/documents/{record_id}", timeout=30)
print(res.json())
```

```js
const recordId = 1;
const res = await fetch(`${BASE_URL}/api/documents/${recordId}`, { method: "DELETE" });
console.log(await res.json());
```

```js
const recordId = 1;
const res = await fetch(`${BASE_URL}/api/documents/${recordId}`, { method: "DELETE" });
console.log(await res.json());
```

正确响应：

```json
{
  "deleted": 1
}
```

错误请求：

```bash
curl -X DELETE "$BASE_URL/api/documents/not-an-int"
```

错误响应：

```json
{
  "detail": [
    {
      "type": "int_parsing",
      "loc": ["path", "record_id"],
      "msg": "Input should be a valid integer"
    }
  ]
}
```

注意：删除不存在的整数 ID 时，当前实现仍返回 `{"deleted": id}`。

### 4.13 DELETE `/api/record/{record_id}`

用途：旧路径，删除指定 ID 的记录。功能与 `/api/documents/{record_id}` 删除路径一致。

参数：

| 位置 | 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| path | `record_id` | integer | 是 | 文档记录 ID。 |

正确请求：

```bash
curl -X DELETE "$BASE_URL/api/record/1"
```

```python
record_id = 1
res = requests.delete(f"{BASE_URL}/api/record/{record_id}", timeout=30)
print(res.json())
```

```js
const recordId = 1;
const res = await fetch(`${BASE_URL}/api/record/${recordId}`, { method: "DELETE" });
console.log(await res.json());
```

```js
const recordId = 1;
const res = await fetch(`${BASE_URL}/api/record/${recordId}`, { method: "DELETE" });
console.log(await res.json());
```

正确响应：

```json
{
  "deleted": 1
}
```

常见错误：同 `/api/documents/{record_id}` 删除接口。

### 4.14 POST `/api/documents/batch-delete`

用途：批量删除文档和向量。

参数：

| 位置 | 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| body | `record_ids` | integer[] | 是 | 要删除的记录 ID。非正整数会被过滤。 |

正确请求：

```bash
curl -X POST "$BASE_URL/api/documents/batch-delete" \
  -H "Content-Type: application/json" \
  -d '{"record_ids":[1,2,3]}'
```

```python
payload = {"record_ids": [1, 2, 3]}
res = requests.post(f"{BASE_URL}/api/documents/batch-delete", json=payload, timeout=60)
print(res.json())
```

```js
const res = await fetch(`${BASE_URL}/api/documents/batch-delete`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ record_ids: [1, 2, 3] })
});
console.log(await res.json());
```

```js
const res = await fetch(`${BASE_URL}/api/documents/batch-delete`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ record_ids: [1, 2, 3] })
});
console.log(await res.json());
```

正确响应：

```json
{
  "requested": 3,
  "deleted": 3,
  "record_ids": [1, 2, 3]
}
```

错误请求：

```bash
curl -X POST "$BASE_URL/api/documents/batch-delete" \
  -H "Content-Type: application/json" \
  -d '{"record_ids":[]}'
```

错误响应：

```json
{
  "detail": "请至少选择一条文档"
}
```

### 4.15 POST `/api/documents/batch-reindex`

用途：批量重建所选文档的向量。

参数：

| 位置 | 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| body | `record_ids` | integer[] | 是 | 要重建向量的记录 ID。 |

正确请求：

```bash
curl -X POST "$BASE_URL/api/documents/batch-reindex" \
  -H "Content-Type: application/json" \
  -d '{"record_ids":[1,2]}'
```

```python
payload = {"record_ids": [1, 2]}
res = requests.post(f"{BASE_URL}/api/documents/batch-reindex", json=payload, timeout=120)
print(res.json())
```

```js
const res = await fetch(`${BASE_URL}/api/documents/batch-reindex`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ record_ids: [1, 2] })
});
console.log(await res.json());
```

```js
const res = await fetch(`${BASE_URL}/api/documents/batch-reindex`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ record_ids: [1, 2] })
});
console.log(await res.json());
```

正确响应：

```json
{
  "requested": 2,
  "reindexed": 2,
  "record_ids": [1, 2]
}
```

错误请求：

```bash
curl -X POST "$BASE_URL/api/documents/batch-reindex" \
  -H "Content-Type: application/json" \
  -d '{"record_ids":[999999]}'
```

错误响应：

```json
{
  "detail": "未找到所选文档"
}
```

### 4.16 POST `/api/reindex`

用途：按 PostgreSQL `documents` 表重建当前向量库集合。适合换模型、集合损坏、向量库数据与 PostgreSQL 元数据不一致时使用。

参数：无。

正确请求：

```bash
curl -X POST "$BASE_URL/api/reindex"
```

```python
res = requests.post(f"{BASE_URL}/api/reindex", timeout=180)
print(res.json())
```

```js
const res = await fetch(`${BASE_URL}/api/reindex`, { method: "POST" });
console.log(await res.json());
```

```js
const res = await fetch(`${BASE_URL}/api/reindex`, { method: "POST" });
console.log(await res.json());
```

正确响应：

```json
{
  "indexed": 2,
  "collection": "sandbox_docs"
}
```

常见错误：向量数据库不可用或模型加载失败时可能返回 `500`。

### 4.17 DELETE `/api/records`

用途：清空当前向量库集合，并清空 PostgreSQL 文档元数据。

参数：无。

正确请求：

```bash
curl -X DELETE "$BASE_URL/api/records"
```

```python
res = requests.delete(f"{BASE_URL}/api/records", timeout=60)
print(res.json())
```

```js
const res = await fetch(`${BASE_URL}/api/records`, { method: "DELETE" });
console.log(await res.json());
```

```js
const res = await fetch(`${BASE_URL}/api/records`, { method: "DELETE" });
console.log(await res.json());
```

正确响应：

```json
{
  "cleared": true
}
```

常见错误：向量数据库不可用或集合重建失败时可能返回 `500`。

⚠️ 风险：这是破坏性接口。前端如要暴露该能力，应至少加确认弹窗；自动化验收不应默认执行。

### 4.18 GET `/api/import-jobs/{job_id}`

用途：查看文件上传导入任务状态。

参数：

| 位置 | 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| path | `job_id` | string | 是 | `/api/upload` 响应中的 `job_id`。 |

正确请求：

```bash
curl "$BASE_URL/api/import-jobs/20260427T060000Z_ab12cd34"
```

```python
job_id = "20260427T060000Z_ab12cd34"
res = requests.get(f"{BASE_URL}/api/import-jobs/{job_id}", timeout=10)
print(res.json())
```

```js
const jobId = "20260427T060000Z_ab12cd34";
const res = await fetch(`${BASE_URL}/api/import-jobs/${jobId}`);
console.log(await res.json());
```

```js
const jobId = "20260427T060000Z_ab12cd34";
const res = await fetch(`${BASE_URL}/api/import-jobs/${jobId}`);
console.log(await res.json());
```

正确响应：

```json
{
  "job_id": "20260427T060000Z_ab12cd34",
  "source_filename": "sample.csv",
  "status": "completed",
  "inserted": 2,
  "existing_count": 0,
  "skipped": 0,
  "failed": 1,
  "created_at": "2026-04-27T06:00:00+00:00",
  "failed_rows_download_url": "/api/import-jobs/20260427T060000Z_ab12cd34/failed-rows"
}
```

错误请求：

```bash
curl "$BASE_URL/api/import-jobs/not-found"
```

错误响应：

```json
{
  "detail": "导入任务不存在"
}
```

### 4.19 GET `/api/import-jobs/{job_id}/failed-rows`

用途：下载上传导入失败行 CSV。只有上传任务存在失败行时才有文件。

参数：

| 位置 | 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| path | `job_id` | string | 是 | `/api/upload` 响应中的 `job_id`。 |

正确请求：

```bash
curl -L "$BASE_URL/api/import-jobs/20260427T060000Z_ab12cd34/failed-rows" \
  -o failed-rows.csv
```

```python
job_id = "20260427T060000Z_ab12cd34"
res = requests.get(f"{BASE_URL}/api/import-jobs/{job_id}/failed-rows", timeout=30)
res.raise_for_status()
open("failed-rows.csv", "wb").write(res.content)
```

```js
const jobId = "20260427T060000Z_ab12cd34";
const res = await fetch(`${BASE_URL}/api/import-jobs/${jobId}/failed-rows`);
const csv = await res.text();
console.log(csv);
```

```js
import { writeFile } from "node:fs/promises";

const jobId = "20260427T060000Z_ab12cd34";
const res = await fetch(`${BASE_URL}/api/import-jobs/${jobId}/failed-rows`);
if (!res.ok) throw new Error(await res.text());
await writeFile("failed-rows.csv", await res.text(), "utf8");
```

正确响应：`text/csv` 文件，表头如下。

```csv
row_number,error,text,document_id,category,tags,source,row_json
3,缺少 text,,,,,,"{...}"
```

错误请求：

```bash
curl "$BASE_URL/api/import-jobs/not-found/failed-rows"
```

错误响应：

```json
{
  "detail": "失败行文件不存在"
}
```

### 4.20 GET `/api/samples/{lang}`

用途：获取项目内置示例数据文本列表，供前端“一键加载样例”使用。

参数：

| 位置 | 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|---|
| path | `lang` | string | 是 | 只支持 `en` 或 `zh`。 |

正确请求：

```bash
curl "$BASE_URL/api/samples/zh"
```

```python
lang = "zh"
res = requests.get(f"{BASE_URL}/api/samples/{lang}", timeout=10)
print(res.json())
```

```js
const lang = "zh";
const res = await fetch(`${BASE_URL}/api/samples/${lang}`);
console.log(await res.json());
```

```js
const lang = "zh";
const res = await fetch(`${BASE_URL}/api/samples/${lang}`);
console.log(await res.json());
```

正确响应：

```json
{
  "lang": "zh",
  "texts": [
    "巴黎是法国的首都",
    "向量数据库用于语义检索"
  ]
}
```

错误请求：

```bash
curl "$BASE_URL/api/samples/jp"
```

错误响应：

```json
{
  "detail": "lang 只支持 en 或 zh，收到 'jp'"
}
```

## 5. 多后端差异

接口路径、请求体和主要响应结构一致。差异主要在服务端连接方式、端口、健康检查文案和搜索分数来源。

| 后端 | API Base URL | `backend` 字段 | 分数说明 | 常见连接错误提示 |
|---|---|---|---|---|
| Qdrant | `http://localhost:8888` | `qdrant` | Qdrant cosine score，越接近 `1` 越相似。 | `向量数据库未连接，请先在项目根目录执行 docker compose --profile qdrant up -d postgres qdrant` |
| Weaviate | `http://localhost:8889` | `weaviate` | `1 - cosine distance`，越接近 `1` 越相似。 | `向量数据库未连接，请先在项目根目录执行 docker compose --profile weaviate up -d postgres weaviate` |
| Milvus | `http://localhost:8890` | `milvus` | COSINE 相似度，越接近 `1` 越相似。 | `向量数据库未连接，请先在项目根目录执行 docker compose --profile milvus up -d postgres milvus-etcd milvus-minio milvus attu（Milvus 首次启动约需 30 秒）` |

切换后端时，客户端只需要替换 `BASE_URL`。

## 6. 推荐验收顺序

1. `GET /api/health/panel`：确认 `db.ok=true`、模型状态正常。
2. `POST /api/ingest`：写入 2 条测试文本。
3. `POST /api/search`：用相关语义查询验证结果非空。
4. `GET /api/documents`：确认元数据已写入。
5. `PUT /api/documents/{record_id}`：确认更新后可搜索到新文本。
6. `POST /api/upload`：上传 JSON/CSV，验证 `job_id` 与失败行报告。
7. `POST /api/documents/batch-reindex`：确认向量重建链路可用。

不建议把 `DELETE /api/records` 放进默认验收链路；它适合手工重置测试环境。
