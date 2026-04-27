# semantic-sandbox

一个可部署的**语义检索服务**：以 **PostgreSQL** 作为业务元数据主库，以 **Qdrant / Weaviate / Milvus** 作为可切换的向量索引后端，提供文本写入、文件导入、语义搜索、元数据过滤、文档管理、健康检查和重建索引能力。

---

## 目录

- [架构概览](#架构概览)
- [功能范围](#功能范围)
- [本次更新记录](#本次更新记录)
- [配置总览](#配置总览)
- [文档索引](#文档索引)
- [快速上手](#快速上手)
- [Web UI](#web-ui)
  - [Makefile 快捷命令](#makefile-快捷命令)
  - [示例数据一键加载](#示例数据一键加载)
  - [健康检查端点](#健康检查端点)
- [API 接口说明](#api-接口说明)
- [PostgreSQL 元数据主库](docs/postgres.md)
- [带元数据过滤的检索](#带元数据过滤的检索)
- [性能基准测试](#性能基准测试)
- [示例数据集](#示例数据集)
- [嵌入模型](#嵌入模型)
- [Docker 安装与配置](#docker-安装与配置)
- [服务器部署](#服务器部署)
- [产品化建议](#产品化建议)
- [三者对比速查](#三者对比速查)
- [目录结构](#目录结构)
- [目录读图建议](#目录读图建议)
- [常见问题](#常见问题)
- [License](#license)

---

## 架构概览

```
  ┌─────────────┐      ┌──────────────────┐      ┌─────────────────┐
  │  原始文本    │ ───► │ 嵌入模型          │ ───► │ 向量 (float[])  │
  │ "埃菲尔铁塔" │      │ sentence-         │      │ [0.12, -0.03,   │
  │              │      │ transformers      │      │  ..., 0.41]     │
  └─────────────┘      └──────────────────┘      └────────┬────────┘
                                                            │
                                                            ▼
  ┌────────────────────────────────────────────────────────────────┐
  │               向量数据库 (Milvus / Weaviate / Qdrant)           │
  │       存储向量 + 建立索引 + 支持"给一个向量找最相近的 N 条"      │
  └─────────────────────────────┬──────────────────────────────────┘
                                 │
                                 ▼
     查询 "巴黎地标" ─► 嵌入 ─► 拿查询向量去库里做近邻检索 ─► Top-K 结果
```

本项目包含**三个独立组件**，正式运行时都要启动：

```
  ┌───────────────────────┐    ┌─────────────────────────────┐    ┌───────────────────────┐
  │ PostgreSQL             │    │ Qdrant / Weaviate / Milvus  │    │ FastAPI + Embeddings   │
  │ 业务元数据主库           │    │ 向量索引与近邻检索            │    │ API / Web / 模型推理     │
  │ documents / logs / jobs │    │ 可通过 profile 切换           │    │ sentence-transformers   │
  └───────────────────────┘    └─────────────────────────────┘    └───────────────────────┘
```

---

## 功能范围

当前项目已经实现的功能：

| 类型 | 功能 |
|---|---|
| 向量后端 | `qdrant-service`、`weaviate-service`、`milvus-service` 三套实现 |
| 数据写入 | 命令行 JSON 入库、Web 多行文本写入、Web/API 上传 JSON 或 CSV |
| 语义搜索 | 命令行交互式搜索、Web 搜索页、`POST /api/search` |
| 元数据过滤 | Web/API 支持 `categories[]`、`tags[]`、`created_at_from`、`created_at_to`；命令行示例保留 `category` 演示 |
| 数据管理 | 文档分页、按 ID 查看、单条更新/删除、批量删除、批量重建；PostgreSQL `documents` 表为元数据主表 |
| 访问控制 | Web UI 使用签名 Cookie 登录态；REST API 使用 `X-API-Key` |
| 运维辅助 | `/health`、`/api/health/panel`、`/logs`、`/api/model/status`、审计日志、搜索日志、应用错误日志、Makefile 常用命令、三库性能基准测试 |

边界也要明确：当前服务已经具备数据库持久化、索引重建、健康检查、基础审计日志、Web UI 登录态和 REST API Key 鉴权，但还没有多租户、限流和告警。正式部署仍建议把 Web/API 放在内网、VPN、网关或反向代理后面。

> ⚠️ **注意元数据写入方式**：命令行 `python -m src.ingest your.json` 会保留 JSON 里的完整元数据；Web UI 和 API 现在支持 `category`、`tags`、`source`，上传文件也支持可选 `document_id`。P1 第一批已经支持多分类、标签和时间范围过滤，但前提仍是你的数据里确实带有这些元数据字段。

---

## 本次更新记录

### 2026-04-27 产品化补充

- Web UI 登录态：新增共享登录模块，三套服务统一支持 `/login`、`/logout` 和签名 Cookie 会话；顶部导航增加“退出登录”入口；未登录访问 `/`、`/ingest`、`/documents`、`/health/panel`、`/logs`、`/docs` 会跳转登录页，`/health` 保持公开用于探活。
- 日志入库：新增 `audit_logs` 表，登录、登出、鉴权失败、写入、上传、删除、清空、重建索引等关键事件写入 PostgreSQL；普通访问日志不入库，交给 Docker / Nginx / 日志系统。
- Web 日志页：新增 `/logs`，支持查看审计日志、搜索日志、错误日志和导入任务摘要；当前已改为表格列表展示，并支持 `page` / `page_size` 分页。
- 鉴权分层：浏览器页面使用 `WEB_*` 配置；REST API 仍使用 `AUTH_ENABLED`、`API_KEY`、`API_KEY_HEADER`，两者互不替代。
- 配置模板：根 `.env.example` 和三套 service `.env.example` 补齐 Web UI 登录态、PostgreSQL、Compose profiles、向量后端端口和模型离线加载配置。
- Docker 部署：根 Compose 默认可同时启动 PostgreSQL + 三套向量后端，并修正 Qdrant / Weaviate / MinIO healthcheck，避免镜像内缺少 `curl` 导致假 `unhealthy`。
- 文档整理：根 README 增加配置总览、详细部署和文档索引；`docs/postgres.md`、`docs/api-reference.md`、`docs/apipost-swagger-testing.md` 同步说明 Web 登录态、API Key、日志分页和 `.env` 配置边界。

### 2026-04-24 补充同步

- 搜索结果页：修复三套 Web UI 在长文本、长标签、长原文场景下的展示溢出；结果摘要、徽标和代码片段现在会自动换行，`查看原文` 区域改为卡片内限高滚动，并补充结果字数提示，避免长内容把页面撑宽或拉坏布局。
- 上传解析：修复带 `UTF-8 BOM` 的 CSV / JSON 上传，避免首列被识别成 `\ufefftext` 后整批报“缺少 text”；并补充回归测试。
- 数据存储职责：PostgreSQL `documents` 表是元数据主表，历史 JSON 文件只作为一次性迁移输入；查询、去重和重建索引都以 PostgreSQL 为准。
- 文档同步：同步根 README、三套服务 README 和 Swagger `/docs` 文案；`/api/records` 的说明更新为同时清空 PostgreSQL `documents` 表。

### P1 第一批

P1 第一批更新把三套服务 从“能跑的教学页面”推进到更接近可试用产品壳：

- 写入页：支持逐行写入、JSON/CSV 批量上传、拖拽上传兜底、已选文件状态展示、导入任务统计和失败行 CSV 下载。
- 检索页：支持多分类、标签、创建时间范围过滤，并展示命中片段、查询词高亮、命中词列表和 score 解释。
- 文档管理：新增分页列表、单条更新 / 删除、当前页批量删除、按元数据批量重建向量。
- 运维可见性：新增健康面板、模型状态接口、搜索审计日志和应用错误日志。
- API 文档：`/docs` 改为 FastAPI 原生 Swagger UI，接口可直接在线试用。
- 模型加载：默认本地离线加载 embedding 模型，配合 `scripts/preload_model.py` 预下载，避免服务运行时隐式访问 HuggingFace。
- 数据幂等：Web/API 写入按 `document_id` / `text_hash` 去重，重复提交返回已存在明细，不再重复入库。

---

## 配置总览

项目根目录的 `.env.example` 是 Docker Compose 和本地服务的主配置模板；三套 service 目录下的 `.env.example` 保留单服务运行时需要的同类配置。

| 配置组 | 关键变量 | 说明 |
|---|---|---|
| Compose profiles | `COMPOSE_PROFILES=qdrant,weaviate,milvus` | 默认同时启动三套向量后端；只跑一个就改成 `qdrant`、`weaviate` 或 `milvus` |
| REST API 鉴权 | `AUTH_ENABLED`、`API_KEY`、`API_KEY_HEADER` | 保护 `/api/*` 写入、搜索、文档管理和运维接口 |
| Web UI 登录态 | `WEB_AUTH_ENABLED`、`WEB_USERNAME`、`WEB_PASSWORD`、`WEB_SESSION_SECRET` | 保护浏览器页面、Swagger UI 和 HTML 表单提交 |
| PostgreSQL | `METADATA_STORE`、`DATABASE_URL`、`DB_POOL_SIZE`、`DB_MAX_OVERFLOW`、`DB_STATEMENT_TIMEOUT_MS` | 元数据主库、连接池和 SQL 超时 |
| 向量后端 | `VECTOR_BACKEND`、`COLLECTION_NAME`、`QDRANT_PORT`、`WEAVIATE_HTTP_PORT`、`MILVUS_PORT` | 当前服务写入哪个向量后端，以及宿主机端口 |
| 模型 | `EMBEDDING_MODEL`、`EMBEDDING_LOCAL_ONLY` | 默认从项目根目录 `models/` 离线加载 embedding 模型 |
| 示例数据 | `DATA_FILE` | 命令行 `python -m src.ingest` 默认加载的数据文件 |

生产部署至少要改这几项：

```env
POSTGRES_PASSWORD=replace_with_strong_password
DATABASE_URL=postgresql://sandbox:replace_with_strong_password@localhost:5432/semantic_sandbox
API_KEY=replace_with_long_random_api_key
WEB_PASSWORD=replace_with_strong_web_password
WEB_SESSION_SECRET=replace_with_long_random_session_secret
WEB_SESSION_HTTPS_ONLY=1
```

`WEB_SESSION_HTTPS_ONLY=1` 只应在 HTTPS 反向代理已经就绪后开启；本地 HTTP 调试保持 `0`。

如果本机端口被占用，直接在 `.env` 改宿主机端口，并同步对应连接串。例如本机已有 PostgreSQL 和 Qdrant：

```env
POSTGRES_PORT=15432
DATABASE_URL=postgresql://sandbox:replace_with_strong_password@localhost:15432/semantic_sandbox
QDRANT_PORT=16333
QDRANT_GRPC_PORT=16334
```

三套服务如果共用同一份根 `.env`，可以共用 `WEB_SESSION_COOKIE` 和 `WEB_SESSION_SECRET`；如果分别部署且会话密钥不同，建议给每个服务配置不同的 `WEB_SESSION_COOKIE`，避免同域 Cookie 互相覆盖。

---

## 文档索引

| 文档 | 用途 |
|---|---|
| [`README.md`](./README.md) | 总览、快速上手、配置说明、Web UI、部署建议和常见问题 |
| [`docs/postgres.md`](./docs/postgres.md) | PostgreSQL 元数据主库、表职责、迁移、备份恢复和关键环境变量 |
| [`docs/api-reference.md`](./docs/api-reference.md) | REST API 对接手册，包含请求参数、响应结构、错误格式和 API Key 说明 |
| [`docs/apipost-swagger-testing.md`](./docs/apipost-swagger-testing.md) | ApiPost / Swagger 导入、环境变量、接口冒烟测试顺序 |
| [`COMPARE.md`](./COMPARE.md) | Qdrant / Weaviate / Milvus API 和能力横向对比 |
| [`qdrant-service/README.md`](./qdrant-service/README.md) | Qdrant 单服务启动、命令行写入、搜索和故障排查 |
| [`weaviate-service/README.md`](./weaviate-service/README.md) | Weaviate 单服务启动、schema 差异、过滤和故障排查 |
| [`milvus-service/README.md`](./milvus-service/README.md) | Milvus 单服务启动、依赖容器、Attu、过滤和故障排查 |

---

## 快速上手

### 前置要求

| 工具 | 版本 | 说明 |
|---|---|---|
| Python | 3.10+ | 建议用 `venv` 创建虚拟环境 |
| Docker | 20+ | 用来启动向量库服务；**Milvus 要求至少 4GB 内存** |
| Docker Compose | v2 | 命令为 `docker compose`（空格），不是老版 `docker-compose` |

```bash
python3 --version && docker --version && docker compose version
```

### 四步部署

```bash
# 步骤 1：准备嵌入模型（只需做一次）
cd semantic-sandbox
python3 -m venv .venv && source .venv/bin/activate

# 国内网络先执行（跳过 HuggingFace 官网直连）
# export HF_ENDPOINT=https://hf-mirror.com

pip install sentence-transformers python-dotenv   # 约 1-2GB，需几分钟
python scripts/preload_model.py                   # 从 HuggingFace/镜像下载模型到 ./models/（约 185MB）

# 步骤 2：复制并修改配置
cp .env.example .env
# 至少修改 POSTGRES_PASSWORD、DATABASE_URL、API_KEY、WEB_PASSWORD、WEB_SESSION_SECRET
# .env 默认 COMPOSE_PROFILES=qdrant,weaviate,milvus

# 步骤 3：启动 PostgreSQL + 向量数据库
docker compose up -d
docker compose ps

# 只想启动 Qdrant 时，把 .env 改成 COMPOSE_PROFILES=qdrant，再执行：
# docker compose up -d

cd qdrant-service
pip install -r requirements.txt                   # 装 Python 客户端
make init-db                                      # 初始化 PostgreSQL 表结构

# 步骤 4：入库 + 搜索
python -m src.ingest                              # 文本 → 向量 → 写入数据库
python -m src.search                              # 交互式语义搜索
```

> **默认启动三套向量后端**：`COMPOSE_PROFILES=qdrant,weaviate,milvus`。只想开一个，就把它改成 `qdrant`、`weaviate` 或 `milvus`。
>
> **端口可配置**：如果本机已有服务占用 `6333`、`8080`、`19530`、`8000` 等端口，直接改 `.env` 里的 `QDRANT_PORT`、`WEAVIATE_HTTP_PORT`、`MILVUS_PORT`、`ATTU_PORT`。
>
> **推荐先验证 Qdrant**：单容器、启动约 3 秒、内存 ≥1GB 即可。跑通后再对比 Weaviate / Milvus。

---

## Web UI

每个子项目都内置了 **FastAPI Web 应用**，可以在浏览器里直接写数据、上传文件、做搜索和清空集合：

```bash
# 先确保根目录 docker compose --profile qdrant up -d postgres qdrant 已执行
cd qdrant-service
source ../.venv/bin/activate    # 或进入对应子项目的虚拟环境
uvicorn src.app:app --reload --port 8888
```

| 子项目 | 端口 | 搜索页 | 写入页 | API 文档 |
|---|---|---|---|---|
| qdrant-service | 8888 | <http://localhost:8888> | <http://localhost:8888/ingest> | <http://localhost:8888/docs> |
| weaviate-service | 8889 | <http://localhost:8889> | <http://localhost:8889/ingest> | <http://localhost:8889/docs> |
| milvus-service | 8890 | <http://localhost:8890> | <http://localhost:8890/ingest> | <http://localhost:8890/docs> |

开启 `WEB_AUTH_ENABLED=1` 后，首次访问 Web UI 会跳转到 `/login`：

```env
WEB_AUTH_ENABLED=1
WEB_USERNAME=admin
WEB_PASSWORD=change_me_to_a_strong_password
WEB_SESSION_SECRET=change_me_to_a_long_random_session_secret
```

登录成功后会写入签名 Cookie；访问 `/logout` 可退出。`/docs` 和 `/openapi.json` 属于浏览器管理入口，也会被 Web 登录态保护；程序调用 `/api/*` 仍按 REST API Key 处理。

搜索页支持：

- 输入查询文本并返回 Top-K 语义相似结果
- 支持多分类、标签、创建时间范围过滤
- 搜索结果会展示命中片段、查询词高亮、命中词列表和 `score` 解释
- 长文本结果会自动换行；`查看原文` 面板在卡片内限高滚动，并显示当前结果字数，避免长病例或大段文本把页面撑坏
- 通过 `limit` 控制返回条数，最大 20
- 自动显示当前集合记录数

文档管理页支持：

- 分页查看文档元数据
- 单条更新 `text/category/tags/source` 并自动重建向量
- 当前页批量删除、批量重建向量

健康面板支持：

- 展示数据库状态、模型状态、元数据数量、向量数量
- 展示当前后端最近错误，便于定位搜索、写入、重建失败

日志页支持：

- `/logs?kind=audit&page=1&page_size=25` 查看登录、鉴权失败、写入、删除、清空、重建等审计事件
- `/logs?kind=search&page=1&page_size=25` 查看当前后端搜索日志、过滤条件、结果数和延迟
- `/logs?kind=errors&page=1&page_size=25` 查看应用错误
- `/logs?kind=imports&page=1&page_size=25` 查看批量导入任务摘要和失败行下载入口

页面支持每页 `10`、`25`、`50`、`100` 条切换；表格里会展示时间、事件、操作者、请求、目标和摘要详情。

写入页支持：

- 每行一条文本的手动写入
- 一键加载英文 / 中文示例数据
- 上传 JSON 或 CSV 文件，文件中必须有 `text` 字段，支持 `UTF-8` / `UTF-8 BOM`
- 文件选择优先使用浏览器系统选择器，并保留原生文件框 fallback
- 支持把 JSON / CSV 文件直接拖拽到上传区域，适合浏览器扩展或系统文件框拦截时兜底
- 选择或拖拽文件后会显示已选文件名和大小，提交前可确认
- 上传后展示导入任务状态，包含成功 / 已存在 / 失败统计
- 失败行支持下载 CSV 复盘
- 清空当前向量集合，以及 PostgreSQL `documents` 表

### Makefile 快捷命令

每个子项目都提供了 `Makefile`，无需手记 uvicorn 参数：

```bash
cd qdrant-service

make help          # 查看所有可用命令
make install       # pip install -r requirements.txt
make web           # 启动 Web UI（uvicorn --reload）
make start         # 启动 PostgreSQL + 当前向量后端
make stop          # docker compose down
make ingest        # 写入 10 条英文示例数据
make ingest-large  # 写入 100 条大数据集
make ingest-zh     # 写入中文示例数据
make search        # 交互式命令行搜索
make filter        # 带元数据过滤的命令行搜索
make logs          # 查看容器日志
make ps            # 查看容器状态
make clean         # 停止容器并删除数据卷（⚠️ 数据清空）
```

三个子项目的 Makefile 命令完全相同，端口号不同（8888 / 8889 / 8890）。

### 示例数据一键加载

写入页（`/ingest`）提供两个快速加载按钮，无需手动粘贴数据：

- **英文示例数据**：加载 `data/sample_en.json`（10 条，含 geography / technology / food 分类）
- **中文示例数据**：加载 `data/sample_zh.json`（10 条，覆盖历史、科技、食物等话题）

点击后通过 `GET /api/samples/{lang}` 接口拉取并填充文本框，再点"写入向量库"即可。

> **注意切换语言时要同步切换嵌入模型**：英文用 `all-MiniLM-L6-v2`（384 维），中文用 `bge-small-zh-v1.5`（512 维）。两种模型维度不同，切换后必须清空集合重建（`make clean` 后重新 `make ingest`）。**不需要重新配置 Docker**。

### 健康检查端点

每个应用都提供 `/health` 端点，返回数据库连接状态：

```bash
curl http://localhost:8888/health
# 正常：{"status":"ok","db":"qdrant","metadata_store":"postgres"}
# 异常：HTTP 503，按提示先启动 PostgreSQL 和当前向量后端
```

Web UI 在数据库未启动时会显示友好提示，而不是直接报 500 错误。

P1 第一批新增的运维面板接口：

```bash
curl http://localhost:8888/api/health/panel
```

返回数据库状态、模型状态、记录数和最近错误摘要；Web 页面入口为 `/health/panel`。

---

## API 接口说明

所有三个子项目提供相同的 REST API（路径和参数一致），只需要替换端口：Qdrant `8888`，Weaviate `8889`，Milvus `8890`。

### POST /api/ingest — 写入数据

```bash
curl -X POST http://localhost:8888/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"texts": ["巴黎是法国的首都", "向量数据库用于语义检索"]}'
```

**请求体：**

| 字段 | 类型 | 说明 |
|---|---|---|
| `texts` | `string[]` | 要写入的文本列表，每条独立向量化；空行自动跳过 |
| `category` | `string` | 可选，写入分类 |
| `tags` | `string[]` | 可选，写入标签 |
| `source` | `string` | 可选，默认 `api` |

**响应：**

```json
{
  "inserted": 2,
  "ids": [11, 12],
  "skipped": 1,
  "existing_count": 1,
  "existing": [
    {
      "id": 3,
      "document_id": "doc_xxx",
      "text_hash": "sha256...",
      "reason": "text_hash"
    }
  ]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `inserted` | `int` | 实际写入的条数（空行自动跳过） |
| `ids` | `int[]` | 自动分配的 ID（从现有最大 ID + 1 起递增） |
| `skipped` | `int` | 因 `document_id` / `text_hash` 已存在而跳过的条数 |
| `existing_count` | `int` | 已存在记录数，等于 `skipped` |
| `existing` | `object[]` | 已存在记录明细，包含命中的 `id`、`document_id`、`text_hash` 和命中原因 |

写入成功后，元数据会先写入 PostgreSQL `documents` 表，并记录向量同步状态，方便向量库清空后重新入库。查询、去重和重建索引都以 PostgreSQL 为准；历史 JSON 文件只作为一次性迁移输入。Web/API 写入会按 `document_id` / 规范化文本生成的 `text_hash` 做幂等判断，同一段文本重复提交时会返回“已存在”明细，不会再次入库。

### POST /api/upload — 上传文件批量写入

```bash
curl -X POST http://localhost:8888/api/upload \
  -F "file=@data/sample_en.json"
```

支持两种文件：

| 文件类型 | 格式要求 |
|---|---|
| JSON | 数组格式，每项至少包含 `text`，例如 `[{"text": "hello"}]`；支持 `UTF-8 BOM` |
| CSV | 首行必须包含 `text` 列；支持 `UTF-8 BOM` |

上传接口支持保留 `document_id`、`category`、`tags`、`source` 等元数据；需要完全自定义 `id` 或走离线批量重建时，仍建议用命令行 `python -m src.ingest your.json`。

Web 写入页的上传控件与该接口走同一条后端链路：按钮选择和拖拽文件都会提交到 `/api/upload` / `/ingest/upload`，不会改变文件格式要求。

上传接口支持的字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `text` | 是 | 文本内容 |
| `document_id` | 否 | 业务侧稳定文档 ID；已存在但文本不同会记为失败行 |
| `category` | 否 | 分类 |
| `tags` | 否 | 标签；CSV 用逗号分隔，JSON 可用数组 |
| `source` | 否 | 来源 |

响应会返回导入任务摘要：

```json
{
  "inserted": 8,
  "skipped": 2,
  "failed": 1,
  "job_id": "20260422T120000Z_ab12cd34",
  "status": "completed",
  "failed_rows_download_url": "/api/import-jobs/20260422T120000Z_ab12cd34/failed-rows"
}
```

如果有失败行，可通过 `failed_rows_download_url` 下载 CSV 复盘。

### POST /api/search — 语义搜索

```bash
curl -X POST http://localhost:8888/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "法国著名地标", "limit": 5, "categories": ["geography"], "tags": ["travel"]}'
```

**请求体：**

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `query` | `string` | 必填 | 查询文本 |
| `limit` | `int` | `5` | 返回条数，最大 20 |
| `category` | `string \| null` | `null` | 兼容旧字段，会并入 `categories` |
| `categories` | `string[]` | `[]` | 可选多分类过滤 |
| `tags` | `string[]` | `[]` | 可选标签过滤，命中任一标签即返回 |
| `created_at_from` | `string \| null` | `null` | 可选创建时间起点，支持 ISO 8601 或 `datetime-local` 格式 |
| `created_at_to` | `string \| null` | `null` | 可选创建时间终点 |

### 文档管理与运维接口

P0 相关接口已经统一到三套服务：

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/api/documents?offset=0&limit=50` | 分页查看文档元数据 |
| `GET` | `/api/documents/{record_id}` | 按 ID 查看单条文档 |
| `PUT` | `/api/documents/{record_id}` | 更新 `text/category/tags/source`，并自动重建向量 |
| `DELETE` | `/api/documents/{record_id}` | 删除文档和向量 |
| `POST` | `/api/documents/batch-delete` | 批量删除所选文档和向量 |
| `POST` | `/api/documents/batch-reindex` | 批量重建所选文档向量 |
| `POST` | `/api/reindex` | 按 PostgreSQL `documents` 表全量重建当前向量集合 |
| `GET` | `/api/model/status` | 查看当前模型、本地路径、维度、是否离线 |
| `GET` | `/model/status` | 与上面相同，兼容旧路径 |
| `GET` | `/api/health/panel` | 查看 DB / 模型 / 记录数 / 最近错误 |
| `GET` | `/api/import-jobs/{job_id}` | 查看批量导入任务状态 |
| `GET` | `/api/import-jobs/{job_id}/failed-rows` | 下载批量导入失败行 CSV |

搜索日志、审计日志和应用层错误会写入 PostgreSQL，用于日志页展示、健康面板展示最近错误和排查慢查询。

**响应：**

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
      "snippet": "...巴黎是法国的首都...",
      "matched_terms": ["法国", "地标"],
      "score_explanation": "高度相关，score=0.8732，越接近 1 越相似。",
      "category": "geography",
      "tags": ["travel"],
      "source": "api",
      "created_at": "2026-04-22T10:00:00+00:00",
      "updated_at": "2026-04-22T10:00:00+00:00"
    }
  ]
}
```

`score` 为余弦相似度，越接近 1 越相似（Weaviate 返回 0~1，Qdrant / Milvus 返回 -1~1）。

### GET /api/count — 查询记录数

```bash
curl http://localhost:8888/api/count
```

响应：

```json
{ "count": 10 }
```

### DELETE /api/record/{record_id} — 删除单条记录

```bash
curl -X DELETE http://localhost:8888/api/record/12
```

响应：

```json
{ "deleted": 12 }
```

### DELETE /api/records — 清空全部记录

```bash
curl -X DELETE http://localhost:8888/api/records
```

该接口会删除并重建当前集合，同时清空 PostgreSQL `documents` 表。

### GET /api/samples/{lang} — 获取示例文本

```bash
curl http://localhost:8888/api/samples/en    # 返回英文示例
curl http://localhost:8888/api/samples/zh    # 返回中文示例
```

**响应：**

```json
{ "lang": "en", "texts": ["Paris is the capital of France", ...] }
```

---

## 带元数据过滤的检索

每个子项目都提供 `src/filter_search.py`，演示向量搜索 + 分类过滤组合使用：

```bash
python -m src.filter_search   # 或 make filter
```

推荐先写入带 `category` 字段的大数据集：

```bash
make ingest-large
python -m src.filter_search "neural network" technology
```

三库过滤语法对比：

| 向量库 | 过滤写法 |
|---|---|
| **Qdrant** | `Filter(must=[FieldCondition(key="category", match=MatchValue(value="technology"))])` |
| **Weaviate** | `Filter.by_property("category").equal("technology")` |
| **Milvus** | `filter='category == "technology"'` |

如果数据是通过 Web UI 手动输入、`POST /api/ingest` 或 `POST /api/upload` 写入的，默认没有 `category` 字段，分类过滤可能返回空结果。

详细对比见 [`COMPARE.md`](./COMPARE.md)。

---

## 性能基准测试

`scripts/benchmark.py` 对三个库执行插入和查询性能测试（1000 条数据，100 次查询）：

```bash
python scripts/benchmark.py all       # 测试全部三个库
python scripts/benchmark.py qdrant    # 仅测试 Qdrant
python scripts/benchmark.py weaviate
python scripts/benchmark.py milvus
```

**输出示例：**

```
=== Qdrant ===
Insert: 1000 records in 4.23s (236.4 QPS)
Query:  avg 12.3ms, 81.3 QPS
Memory: +42MB
```

> 运行前需确保对应的 Docker 容器已启动。安装 `psutil` 可获得内存统计，否则跳过内存报告。

---

## 示例数据集

| 文件 | 条数 | 语言 | 说明 |
|---|---|---|---|
| `data/sample_en.json` | 10 | 英文 | 覆盖 geography / technology / food |
| `data/sample_zh.json` | 10 | 中文 | 中文语义检索示例数据，不含 `category` 字段 |
| `data/sample_large_en.json` | 100 | 英文 | 8 个分类（technology / science / geography / history / food / sports / art / nature），ID 从 101 起，适合演示过滤检索 |

通过 Web UI 或 REST API 写入的自定义文本会先写入 PostgreSQL `documents` 表，并记录向量同步状态；审计日志、搜索日志、应用错误和导入任务摘要会写入 PostgreSQL，导入失败行 CSV 会写入 `data/import_reports/`。本地运行产物已加入 `.gitignore`，不会进仓库。

---

## 嵌入模型

在各子项目的 `.env` 里通过 `EMBEDDING_MODEL` 切换：

| 模型 | 适用 | 维度 | 大小 |
|---|---|---|---|
| `sentence-transformers/all-MiniLM-L6-v2` | 英文 / 多语言 | 384 | ~90MB |
| `BAAI/bge-small-zh-v1.5` | 中文 | 512 | ~95MB |

> ⚠️ **换模型后维度会变**，已建好的 collection 必须删掉重建。执行 `make clean` 清空数据卷，再 `make ingest` 重新入库。**不需要重新配置 Docker**，Docker 只负责运行数据库进程，不感知向量维度。

模型下载和运行规则：

| 项目 | 说明 |
|---|---|
| 下载来源 | HuggingFace Hub；国内服务器可设置 `HF_ENDPOINT=https://hf-mirror.com` 走镜像 |
| 下载命令 | 在项目根目录执行 `python scripts/preload_model.py` |
| 下载内容 | `sentence-transformers/all-MiniLM-L6-v2` 和 `BAAI/bge-small-zh-v1.5` |
| 存放位置 | 项目根目录 `./models/`，内部是 HuggingFace 缓存结构，例如 `models--BAAI--bge-small-zh-v1.5/snapshots/<revision>/` |
| 运行策略 | 默认 `EMBEDDING_LOCAL_ONLY=1`，服务只读 `./models/`，不再访问 HuggingFace |

如果服务器不能联网，可以在本机执行 `python scripts/preload_model.py` 后，把整个 `models/` 目录上传到服务器项目根目录。

**国内网络：**

```bash
export HF_ENDPOINT=https://hf-mirror.com      # 当前终端生效
echo 'export HF_ENDPOINT=https://hf-mirror.com' >> ~/.zshrc  # 永久生效
```

---

## Docker 安装与配置

> 已装好 Docker 可跳过本节，直接看[三者对比速查](#三者对比速查)。

### 安装 Docker

> **Docker Desktop vs Docker Engine**
> - **Docker Desktop**：带图形界面，只用于 macOS 和 Windows 本地开发机，**不能安装在无 GUI 的 Linux 服务器上**。
> - **Docker Engine**：纯命令行，Linux 服务器上安装的就是这个，**不需要任何图形界面**。Compose v2 是 Docker Engine 的一个 CLI 插件，同样纯命令行，与 GUI 无关。

---

**macOS / Windows 本地开发机 — 安装 Docker Desktop**

前往 [https://docs.docker.com/get-docker/](https://docs.docker.com/get-docker/) 下载安装：

| 平台 | 说明 |
|---|---|
| macOS (Apple Silicon) | 下载 `.dmg`，拖到 Applications |
| macOS (Intel) | 同上，选 Intel 版本 |
| Windows 10/11 | 下载 `.exe`，按向导安装（需要 WSL 2，安装器会自动提示） |

安装后启动 Docker Desktop，等待菜单栏图标变为**绿色（Running）**状态，之后在终端使用 `docker` / `docker compose` 命令。

---

**Linux 服务器（无 GUI 纯命令行）— 安装 Docker Engine + Compose 插件**

无需图形界面。推荐官方一键脚本，会同时安装 Docker Engine 和 Compose v2 插件：

```bash
# Ubuntu / Debian
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker
```

验证：

```bash
docker compose version   # 输出 Docker Compose version v2.x.x 即为成功
```

如果 `docker compose version` 报错（部分最小化镜像可能未包含插件），补装方式：

```bash
# 方式一：apt 补装（官方脚本已自动添加 Docker 源）
sudo apt-get install -y docker-compose-plugin

# 方式二：手动下载独立二进制（适用于任何 Linux，包括无法访问 apt 的环境）
COMPOSE_VERSION=$(curl -s https://api.github.com/repos/docker/compose/releases/latest \
  | grep '"tag_name"' | cut -d'"' -f4)
sudo mkdir -p /usr/local/lib/docker/cli-plugins
sudo curl -SL \
  "https://github.com/docker/compose/releases/download/${COMPOSE_VERSION}/docker-compose-linux-x86_64" \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
sudo chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
docker compose version
```

> 国内服务器下载 GitHub Release 可能超时，可在本地下好再 `scp` 传到服务器，放到 `/usr/local/lib/docker/cli-plugins/docker-compose` 后 `chmod +x` 即可。

**CentOS / RHEL 服务器**

```bash
sudo yum install -y yum-utils
sudo yum-config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo yum install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

统一验证（macOS / Linux 均适用）：

```bash
docker --version && docker compose version
docker run hello-world
```

### 为 Milvus 调大 Docker 内存

Milvus 需要同时运行三个容器（etcd + minio + milvus），内存不够会导致反复重启（Exit 137 = OOM Kill）：

| 子项目 | 最低内存 | 推荐 |
|---|---|---|
| Qdrant | 1 GB | 2 GB |
| Weaviate | 1 GB | 2 GB |
| **Milvus** | **4 GB** | **6 GB** |

**macOS / Windows (Docker Desktop)**：Settings → Resources → Advanced → Memory 调到 ≥4GB → Apply & Restart。

**Linux**：默认无限制，确保宿主机可用内存够用（`free -h` 查看）。

### 配置 Docker 镜像加速（国内用户）

**macOS / Windows (Docker Desktop)**：Settings → Docker Engine → 加入：

```json
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://dockerproxy.com"
  ]
}
```

点 Apply & Restart。

**Linux：**

```bash
sudo tee /etc/docker/daemon.json > /dev/null <<'EOF'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://dockerproxy.com"
  ]
}
EOF
sudo systemctl daemon-reload && sudo systemctl restart docker
```

验证：`docker info | grep -A 5 "Registry Mirrors"`

### Docker 常用命令

```bash
docker compose ps                                              # 查看容器状态
docker compose logs -f <服务名>                                # 实时查看日志
docker compose up -d                                           # 后台启动
docker compose down                                            # 停止（保留数据）
docker compose down -v                                         # ⚠️ 停止并清空数据卷
docker compose pull && docker compose up -d --force-recreate  # 更新镜像
docker exec -it sandbox-qdrant sh                              # 进入容器调试
```

---

## 服务器部署

> 本项目可以单机部署为团队内部工具。当前推荐形态是：Docker Compose 管 PostgreSQL 和向量数据库，FastAPI 用 systemd 运行在宿主机，外层用 Nginx/HTTPS 暴露 Web UI。

### 基础部署

1. 确保服务器已安装 Docker Compose v2、Python 3.10+。
2. 克隆项目并按[快速上手](#快速上手)完成模型下载和依赖安装。
3. 复制 `.env.example`：

```bash
cp .env.example .env
```

4. 修改 `.env` 里的必改项：

```env
APP_ENV=production
POSTGRES_PASSWORD=replace_with_strong_password
DATABASE_URL=postgresql://sandbox:replace_with_strong_password@localhost:5432/semantic_sandbox
API_KEY=replace_with_long_random_api_key
WEB_USERNAME=admin
WEB_PASSWORD=replace_with_strong_web_password
WEB_SESSION_SECRET=replace_with_long_random_session_secret
WEB_SESSION_HTTPS_ONLY=1
COMPOSE_PROFILES=qdrant,weaviate,milvus
```

如果只部署一个后端，把 `COMPOSE_PROFILES` 改成 `qdrant`、`weaviate` 或 `milvus`。如果服务器已有 PostgreSQL / Qdrant 等端口占用，改 `POSTGRES_PORT`、`QDRANT_PORT` 等宿主机端口，并同步 `DATABASE_URL` / service `.env`。

5. 启动依赖并初始化表：

```bash
docker compose up -d
docker compose ps
source .venv/bin/activate
python scripts/init_postgres.py
```

6. 后台运行 uvicorn：

```bash
# nohup 简单后台运行
cd qdrant-service
nohup uvicorn src.app:app --host 0.0.0.0 --port 8888 > app.log 2>&1 &
echo $! > app.pid

# 停止
kill $(cat app.pid)
```

### systemd 服务（推荐）

以 qdrant-service 为例，创建 `/etc/systemd/system/qdrant-service.service`：

```ini
[Unit]
Description=Qdrant Service Web UI
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=<your-user>
WorkingDirectory=/path/to/semantic-sandbox/qdrant-service
Environment="PATH=/path/to/semantic-sandbox/.venv/bin:/usr/local/bin:/usr/bin"
ExecStart=/path/to/semantic-sandbox/.venv/bin/uvicorn src.app:app --host 0.0.0.0 --port 8888
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now qdrant-service
sudo systemctl status qdrant-service
journalctl -u qdrant-service -f          # 查看日志
```

Weaviate / Milvus 可按同样方式增加 systemd 服务，只需要改 `WorkingDirectory` 和端口：

| 服务 | WorkingDirectory | 端口 |
|---|---|---|
| Qdrant | `/path/to/semantic-sandbox/qdrant-service` | `8888` |
| Weaviate | `/path/to/semantic-sandbox/weaviate-service` | `8889` |
| Milvus | `/path/to/semantic-sandbox/milvus-service` | `8890` |

### Nginx 反向代理

不建议直接暴露 uvicorn 端口，用 Nginx 做反向代理：

```nginx
server {
    listen 80;
    server_name your-domain.com;   # 或服务器公网 IP

    location / {
        proxy_pass http://127.0.0.1:8888;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 60s;
    }
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

如需 HTTPS，用 Certbot 自动申请证书：

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```

### 防火墙与安全

```bash
# 只对外开放 80/443，不暴露向量数据库端口
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

> ⚠️ **注意事项**：
> - Qdrant（6333）、Weaviate（8080）、Milvus（19530）端口**不要对外暴露**，默认无鉴权。
> - REST API 默认启用 `X-API-Key` 鉴权，密钥从 `.env` 的 `API_KEY` 读取；`/health` 保持公开用于探活。
> - Web UI 默认启用登录态，账号、密码和会话密钥从 `.env` 的 `WEB_USERNAME`、`WEB_PASSWORD`、`WEB_SESSION_SECRET` 读取；浏览器访问 `/login` 登录，顶部“退出登录”会访问 `/logout`。
> - Web 登录态不是企业 SSO / RBAC；正式部署仍建议加 HTTPS、网关访问控制和访问日志。
> - PostgreSQL 数据默认持久化在 `data/postgres/`，Qdrant / Weaviate / Milvus 数据在各 service 目录的持久化目录，定期备份。

### 健康监控

```bash
# 手动检查
curl http://localhost:8888/health

# crontab 自动监控（每 5 分钟）
*/5 * * * * curl -sf http://localhost:8888/health || systemctl restart qdrant-service
```

---

## 上线补强项

当前版本已经把 PostgreSQL 作为业务元数据主库，并把向量库定位为可重建索引。上线前仍建议补齐下面几项。

### 写入幂等

当前 Web UI / REST API 使用 PostgreSQL `documents` 表的 `document_id` / `text_hash` 唯一约束做幂等，能避免重复提交造成重复搜索结果。向量写入失败时，`vector_sync_states` 会保留待重建状态，可通过 `/api/reindex` 或批量重建接口恢复索引。

生产建议：

- 给文本生成稳定的 `text_hash`，例如对规范化文本做 SHA-256。
- 把 `text_hash` 或业务侧 `document_id` 作为唯一键，不只依赖自增 ID。
- 写入链路使用真正的 upsert / 唯一约束 / 幂等键，保证重复请求可安全重试。
- 增加请求级幂等键，覆盖客户端超时重试和批量导入重复提交。

### 代码复用

三套服务为了保留不同向量库的接入差异，仍有相似代码。后续继续加功能时，应优先抽出公共 API 层，只保留向量后端适配器差异。

如果要长期维护，建议抽出公共模块：

- `embedder`：模型路径解析、离线加载、向量化。
- `ingest_utils`：文本规范化、去重、ID 分配、上传文件解析。
- `web_static`：搜索结果高亮 JS 和通用 CSS。

### 上线前冒烟测试

每次部署前建议至少跑一套 Qdrant 冒烟测试，再按需验证 Weaviate / Milvus。

```bash
python scripts/preload_model.py
cp .env.example .env
# 默认启动 PostgreSQL + 三套向量后端；只测 Qdrant 时可在 .env 改 COMPOSE_PROFILES=qdrant
docker compose up -d
cd qdrant-service
make init-db
python -m src.ingest
uvicorn src.app:app --port 8888
set -a; source ../.env; set +a
python ../scripts/smoke_api.py --base-url http://localhost:8888 --api-key "$API_KEY"
```

检查项：

- 服务启动后不再访问 HuggingFace，日志里应加载本地 `models/` 路径。
- 重复提交同一段文本时，接口返回 `skipped > 0`，不会新增重复结果。
- 搜索页能返回结果，并高亮查询词或公共片段。
- `/health` 返回 `{"status":"ok","db":"qdrant"}`。

---

## 三者对比速查

| 项 | Qdrant | Weaviate | Milvus |
|---|---|---|---|
| 本地容器数 | 1 | 1 | 3（etcd + minio + milvus） |
| 最低内存 | 1 GB | 1 GB | 4 GB |
| 启动时间 | ~3s | ~5s | ~30s |
| Python 客户端 | `qdrant-client` | `weaviate-client` v4 | `pymilvus` |
| 额外字段存储 | Payload（无 schema） | Properties（需提前定义） | Dynamic field（需开启） |
| 过滤语法 | FieldCondition 对象 | Filter 链式调用 | SQL-like 字符串 |
| score 含义 | 余弦相似度（-1~1） | 1 - cosine_distance（0~1） | 余弦相似度（-1~1） |
| 写入后可见 | 立即 | 立即（异步索引） | 需 `load_collection()` |
| 推荐入门顺序 | ★★★ 先学这个 | ★★☆ | ★☆☆ 最复杂 |

完整三库 API 横向对比（建集合 / 写入 / 搜索 / 过滤 / 删除）见 [`COMPARE.md`](./COMPARE.md)。

---

## 目录结构

```
semantic-sandbox/
├── README.md                 ← 你正在读的这个
├── COMPARE.md                ← 三库 API 横向对比（三列并排代码块）
├── .gitignore
├── data/
│   ├── sample_en.json        ← 10 条英文示例数据（含 category 字段）
│   ├── sample_zh.json        ← 10 条中文示例数据
│   ├── sample_large_en.json  ← 100 条英文数据，8 个分类，供过滤检索演示
│   ├── postgres/             ← PostgreSQL Docker 数据目录（.gitignore，本地生成）
│   └── import_reports/       ← 导入失败行 CSV（.gitignore，本地生成）
├── scripts/
│   ├── preload_model.py      ← 预下载嵌入模型到 ./models/
│   └── benchmark.py          ← 三库插入/查询性能横向对比
├── qdrant-service/              ← Qdrant 子项目（端口 8888）
│   ├── Makefile
│   ├── src/
│   │   ├── app.py            ← FastAPI Web UI + REST API
│   │   ├── ingest.py         ← 命令行批量入库
│   │   ├── search.py         ← 命令行语义搜索
│   │   └── filter_search.py  ← 带元数据过滤的搜索
│   └── templates/            ← Jinja2 HTML 模板
├── weaviate-service/            ← Weaviate 子项目（端口 8889）
└── milvus-service/              ← Milvus 子项目（端口 8890）
```

---

## 目录读图建议

建议按以下顺序阅读代码：

1. `data/sample_en.json` — 看数据结构（id / text / category）
2. `qdrant-service/src/embedder.py` — 文本如何变成向量
3. `qdrant-service/src/ingest.py` — 向量如何入库
4. `qdrant-service/src/search.py` — 查询如何做
5. `qdrant-service/src/filter_search.py` — 加上元数据过滤
6. `qdrant-service/src/app.py` — Web UI 和 REST API 如何组织
7. 对比阅读 `weaviate-service/` 和 `milvus-service/`，找不同点
8. 查阅 `COMPARE.md` 做系统性横向对比

---

## 常见问题

**Q: 第一次跑脚本为什么很慢？**
A: 两个原因之一：① `python scripts/preload_model.py` 正在下载嵌入模型；② `pip install` 在下载 PyTorch（约 1-2GB）。正式的 ingest/search 服务默认离线加载，不会边运行边下载模型。

**Q: HuggingFace 下载超时或报 `ConnectionError`？**
A: 只在执行 `python scripts/preload_model.py` 时需要访问 HuggingFace。先 `export HF_ENDPOINT=https://hf-mirror.com`，然后重跑预下载命令；建议写进 `~/.zshrc` 永久生效。

**Q: 服务运行时为什么还访问 HuggingFace？**
A: 正常不应该。确认项目根目录存在 `models/`，并且 `.env` 里 `EMBEDDING_LOCAL_ONLY=1`。如果本地模型缺失，服务会直接报“本地模型不可用”，不会反复联网重试。

**Q: 切换了嵌入模型（中英文），需要重新配置 Docker 吗？**
A: **不需要**。Docker 只负责运行向量数据库进程，不感知嵌入模型。但向量维度会变（384 → 512），已有的 collection 必须删掉重建。执行 `make clean` 清空 Docker 数据卷，再 `make ingest` 重新入库即可。

**Q: Docker 启动 Milvus 失败 / 容器反复重启？**
A: 八成是内存不够（Exit Code 137 = OOM Kill）。Docker Desktop 默认内存偏小，调到 ≥4GB 再试：Settings → Resources → Advanced → Memory。

**Q: `docker compose` 提示命令不存在？**
A: 装的可能是老版 Compose v1（`docker-compose`，有连字符）。本项目用 v2，Ubuntu 执行 `sudo apt-get install docker-compose-plugin` 升级。

**Q: 拉镜像超时或 `connection refused`？**
A: 国内访问 Docker Hub 不稳定，参考[配置 Docker 镜像加速](#配置-docker-镜像加速国内用户)。

**Q: Web UI 显示"向量数据库未连接"？**
A: 先在项目根目录执行 `docker compose --profile qdrant up -d postgres qdrant`，然后 `docker compose ps` 确认容器状态为 `running`（Milvus 首次启动约需 30 秒）。也可用 `curl http://localhost:8888/health` 检查。

**Q: `data/postgres/` 或 `data/import_reports/` 出现在 `git status` 里？**
A: 这些是 Web/API 的本地运行产物，已在 `.gitignore` 里忽略。如果文件已被追踪，执行 `git rm --cached <path>` 取消追踪即可。

**Q: 代码里为什么没有 API Key？**
A: REST API Key 在 `.env` 配置：`AUTH_ENABLED=1`、`API_KEY=...`、`API_KEY_HEADER=X-API-Key`。Web UI 登录态单独配置：`WEB_AUTH_ENABLED=1`、`WEB_USERNAME=...`、`WEB_PASSWORD=...`、`WEB_SESSION_SECRET=...`。本地 Docker 起的向量服务默认无鉴权，正式部署必须放在内网或网关后面，并开启 PostgreSQL 强密码、HTTPS 和访问日志。

---

## License

[MIT](./LICENSE) — 随便改、随便用。
