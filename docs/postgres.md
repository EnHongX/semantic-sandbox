# PostgreSQL Metadata Store

PostgreSQL 是本项目的业务元数据主库；Qdrant / Weaviate / Milvus 只保存可重建的向量索引。

## 启动

```bash
cp .env.example .env
# .env 默认 COMPOSE_PROFILES=qdrant,weaviate,milvus，会同时启动三套向量后端
docker compose up -d
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
| `VECTOR_BACKEND` | 当前写入的向量后端：`qdrant` / `weaviate` / `milvus` |
| `COMPOSE_PROFILES` | Docker Compose 启动哪些向量后端 |
| `QDRANT_PORT` / `WEAVIATE_HTTP_PORT` / `MILVUS_PORT` | 向量服务映射到宿主机的端口 |
| `ATTU_PORT` / `MINIO_API_PORT` / `MINIO_CONSOLE_PORT` | Milvus 辅助服务映射端口 |
| `AUTH_ENABLED` | 是否启用 REST API Key 鉴权 |
| `API_KEY` | REST API 请求使用的密钥 |
| `API_KEY_HEADER` | API Key 请求头名，默认 `X-API-Key` |
| `DB_POOL_SIZE` | 常驻连接池大小 |
| `DB_MAX_OVERFLOW` | 连接池峰值溢出连接数 |
| `DB_STATEMENT_TIMEOUT_MS` | 单条 SQL 超时，避免慢查询拖死 API |

## 表职责

| 表 | 职责 |
|---|---|
| `documents` | 文档文本、分类、标签、来源和幂等键 |
| `vector_sync_states` | 每个文档在每个向量后端的索引状态 |
| `import_jobs` | 批量导入任务摘要和失败行信息 |
| `search_logs` | 搜索审计日志 |
| `app_errors` | 应用错误日志 |

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
