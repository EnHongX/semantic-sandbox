# PostgreSQL Metadata Store

PostgreSQL 是本项目的业务元数据主库；Qdrant / Weaviate / Milvus 只保存可重建的向量索引。

## 启动

```bash
cp .env.example .env
# 至少修改 POSTGRES_PASSWORD、DATABASE_URL、API_KEY、WEB_PASSWORD、WEB_SESSION_SECRET
# .env 默认 COMPOSE_PROFILES=qdrant,weaviate,milvus，会同时启动三套向量后端
docker compose up -d
docker compose ps
source .venv/bin/activate
python scripts/init_postgres.py
```

只启动一个向量后端时，修改 `.env`：

```env
COMPOSE_PROFILES=qdrant
```

可选值：

```bash
COMPOSE_PROFILES=qdrant
COMPOSE_PROFILES=weaviate
COMPOSE_PROFILES=milvus
COMPOSE_PROFILES=qdrant,weaviate,milvus
```

## 关键环境变量

| 变量 | 说明 |
|---|---|
| `METADATA_STORE=postgres` | 启用 PostgreSQL 元数据主库 |
| `DATABASE_URL` | API / 脚本连接 PostgreSQL 的 DSN |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_PORT` | Docker PostgreSQL 数据库名、账号、密码和宿主机端口 |
| `VECTOR_BACKEND` | 当前写入的向量后端：`qdrant` / `weaviate` / `milvus` |
| `COMPOSE_PROFILES` | Docker Compose 启动哪些向量后端 |
| `QDRANT_PORT` / `WEAVIATE_HTTP_PORT` / `MILVUS_PORT` | 向量服务映射到宿主机的端口 |
| `ATTU_PORT` / `MINIO_API_PORT` / `MINIO_CONSOLE_PORT` | Milvus 辅助服务映射端口 |
| `AUTH_ENABLED` | 是否启用 REST API Key 鉴权 |
| `API_KEY` | REST API 请求使用的密钥 |
| `API_KEY_HEADER` | API Key 请求头名，默认 `X-API-Key` |
| `WEB_AUTH_ENABLED` | 是否启用 Web UI 登录态 |
| `WEB_USERNAME` / `WEB_PASSWORD` | Web UI 登录账号密码 |
| `WEB_SESSION_SECRET` | 签名 Cookie 使用的会话密钥，生产必须替换 |
| `WEB_SESSION_COOKIE` | Web UI 会话 Cookie 名 |
| `WEB_SESSION_MAX_AGE_SECONDS` | Web UI 会话有效期，默认 86400 秒 |
| `WEB_SESSION_HTTPS_ONLY` | HTTPS-only Cookie 开关；本地 HTTP 调试用 `0`，HTTPS 反代后用 `1` |
| `DB_POOL_SIZE` | 常驻连接池大小 |
| `DB_MAX_OVERFLOW` | 连接池峰值溢出连接数 |
| `DB_STATEMENT_TIMEOUT_MS` | 单条 SQL 超时，避免慢查询拖死 API |

## 表职责

| 表 | 职责 |
|---|---|
| `documents` | 文档文本、分类、标签、来源和幂等键 |
| `vector_sync_states` | 每个文档在每个向量后端的索引状态 |
| `import_jobs` | 批量导入任务摘要和失败行信息 |
| `audit_logs` | Web 登录、登出、API Key 鉴权失败、写入、上传、删除、清空、重建索引等关键审计事件 |
| `search_logs` | 搜索请求摘要、过滤条件、结果数和延迟 |
| `app_errors` | 应用错误日志 |

普通访问日志不写入 PostgreSQL，建议由 Docker、Nginx 或日志系统收集。数据库只保存有审计、恢复、排障价值的日志，且不记录密码、完整 API Key 和全文请求体。

Web UI 日志页入口：

```text
/logs?kind=audit&page=1&page_size=25
/logs?kind=search&page=1&page_size=25
/logs?kind=errors&page=1&page_size=25
/logs?kind=imports&page=1&page_size=25
```

`page_size` 支持 `10`、`25`、`50`、`100`，页面以表格列表展示时间、事件、操作者、请求、目标和摘要详情。

## 端口冲突示例

如果服务器或本机已有 PostgreSQL 占用 `5432`，可以在 `.env` 中改宿主机端口：

```env
POSTGRES_PORT=15432
DATABASE_URL=postgresql://sandbox:sandbox_password@localhost:15432/semantic_sandbox
```

如果 Qdrant 默认端口被占用：

```env
QDRANT_PORT=16333
QDRANT_GRPC_PORT=16334
```

同时确认 `qdrant-service/.env` 没有把 `QDRANT_PORT` 覆盖回旧值。

## 旧 JSON 迁移

```bash
METADATA_STORE=postgres \
DATABASE_URL=postgresql://sandbox:sandbox_password@localhost:5432/semantic_sandbox \
python scripts/migrate_json_to_postgres.py --input data/documents.json
```

迁移脚本按 `document_id` / `text_hash` 幂等写入，可重复执行。

## 备份恢复

```bash
docker exec semantic-sandbox-postgres pg_dump -U sandbox semantic_sandbox > semantic_sandbox.sql
cat semantic_sandbox.sql | docker exec -i semantic-sandbox-postgres psql -U sandbox semantic_sandbox
```

生产环境建议使用托管 PostgreSQL 或至少配置独立备份任务；本地 Docker 数据目录 `data/postgres/` 只适合开发和单机部署。
