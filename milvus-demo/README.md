# milvus-demo

用 [Milvus](https://milvus.io/) 实现的"入库 + 语义检索"示例。

Milvus 是三个库里概念最多、启动最重的（要同时跑 **etcd + minio + milvus** 三个容器），但它也是生产环境大规模向量场景里用得最多的。学习它对理解"为什么向量库是一个独立系统，而不是一个 Python 库"很有帮助。

---

## 目录结构

```
milvus-demo/
├── README.md
├── docker-compose.yml     启动 Milvus standalone（含 etcd / minio / 可选 Attu Web UI）
├── requirements.txt       Python 依赖（pymilvus v2.5）
├── .env.example
└── src/
    ├── config.py
    ├── embedder.py        文本 → 向量
    ├── ingest.py          建集合 + 索引 + 入库
    └── search.py          交互式检索
```

---

## 一步步跑起来

### 0. 先确认 Docker 内存给够

⚠️ **Docker Desktop 默认分配的内存通常 ≤ 2GB，Milvus 起不来。必须先调大，再做后面的步骤。**

**macOS / Windows (Docker Desktop)**：

1. 打开 Docker Desktop → 右上角 ⚙️ Settings
2. 左侧点 **Resources → Advanced**
3. **Memory** 滑块拖到 **≥ 4 GB**（推荐 6 GB）
4. 点右下角 **Apply & Restart**，等 Docker Desktop 重启完成（约 30 秒）

**Linux**：

```bash
# 查看当前可用内存，确保至少有 4GB free
free -h
```

如果可用内存不足，先停掉其他占内存的进程，或换一台内存更大的机器。

---

> **为什么 Milvus 需要这么多内存？**
> Milvus standalone 实际上跑了三个独立进程：
> - **etcd**：分布式键值存储，保存 Milvus 的元数据（集合定义、schema 等）
> - **minio**：对象存储，持久化存放向量数据文件
> - **milvus**：主进程，负责索引构建、向量检索
>
> 三个进程加起来，冷启动就要占 ~2-3 GB 内存。容器内存不足时会被 Linux OOM Killer 杀掉，表现为容器不停重启（Exit Code 137）。

### 1. 启动 Milvus

```bash
cd milvus-demo
docker compose up -d
```

启动需要 **30~60 秒**（要等 etcd 和 minio 就绪后 milvus 才会健康）。用以下命令观察状态：

```bash
# 查看各容器状态（等所有容器都变为 healthy 或 running）
docker compose ps

# 实时查看 milvus 主容器的启动日志
docker compose logs -f milvus
```

`STATUS` 列全部变为 `healthy` 或 `running` 后再继续。典型的就绪输出：

```
NAME                        IMAGE                    STATUS
sandbox-milvus-etcd         quay.io/coreos/etcd      healthy
sandbox-milvus-minio        minio/minio              healthy
sandbox-milvus-standalone   milvusdb/milvus          healthy
sandbox-milvus-attu         zilliz/attu              running
```

如果 milvus 容器一直 `Restarting`：
1. 先看 `docker compose logs milvus`，90% 是内存不足（OOM）
2. 回到第 0 步，把 Docker Desktop 内存调到 ≥ 4 GB

验证 Milvus 已就绪：
```bash
curl http://localhost:9091/healthz    # 返回 "OK"
```

**附带的可视化 UI**：
- **Attu**（Milvus 官方管理界面）：<http://localhost:8000> — 可以直接在浏览器里看集合、查数据、做搜索
- **MinIO 控制台**：<http://localhost:9001>，账号密码均为 `minioadmin`（看底层对象存储用，一般不需要）

### 2. 装 Python 依赖

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> ⚠️ 首次安装会顺带拉 PyTorch（`sentence-transformers` 的依赖），约 **1-2GB**，需要几分钟。
>
> 🇨🇳 国内 HuggingFace 下载慢可以先 `export HF_ENDPOINT=https://hf-mirror.com`，再到项目根目录跑 `python scripts/preload_model.py`。

### 3. 配置环境变量

```bash
cp .env.example .env
```

中文场景：
```bash
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
DATA_FILE=../data/sample_zh.json
```

模型需要先在项目根目录下载：

```bash
(cd .. && python scripts/preload_model.py)
```

脚本从 HuggingFace Hub（或 `HF_ENDPOINT` 指定的镜像）下载 `sentence-transformers/all-MiniLM-L6-v2` 和 `BAAI/bge-small-zh-v1.5`，统一放到项目根目录 `models/`。服务默认 `EMBEDDING_LOCAL_ONLY=1`，运行时只读本地 `models/`，不会再访问 HuggingFace。

### 4. 入库

```bash
python -m src.ingest
```

预期输出：
```
[ingest] 读取数据: .../data/sample_en.json
[embedder] 加载模型: .../models/...
[ingest] 连接 Milvus http://localhost:19530 / 向量维度=384
[ingest] 创建集合 sandbox_docs (维度=384, 距离=COSINE)
[ingest] 写入 10 条 → sandbox_docs
[ingest] 完成。集合中共有 10 条。
```

### 5. 搜索

```bash
python -m src.search
```

```
> how does machine learning work
查询: how does machine learning work
------------------------------------------------------------
1. score=0.5921  id=4
   Machine learning is a subfield of artificial intelligence focused on data-driven models.
2. score=0.2340  id=2
   Python is a high-level programming language known for its readability.
...
```

> Milvus 在 `COSINE` 指标下，`search` 返回的 `distance` 字段实际上是**相似度**（-1 ~ 1，越大越相似），不是距离 —— 这是 Milvus 的一个小坑，代码注释里有提。

---

## 带过滤条件的检索

```bash
python -m src.filter_search                              # 交互模式
python -m src.filter_search "neural network" technology
python -m src.filter_search "ocean current" geography
```

**过滤语法**（Milvus 标量表达式）：

```python
filter='category == "technology"'
filter='category in ["technology", "science"]'
filter='category == "technology" and doc_id > 100'
```

> `category` 存在 dynamic field（`$meta`）中，无需修改 schema。过滤与向量检索同时进行（filtered ANN），结果天然满足过滤条件。

---

## 换数据 / 换模型

### 换数据

```bash
python -m src.ingest /path/to/your_data.json
```

`ingest.py` 用的是 `upsert`（按 id 覆盖），同一个 id 重跑不会重复。

### 换模型

改 `.env` 的 `EMBEDDING_MODEL` 后维度会变，需要先删旧集合：

```bash
python -c "from pymilvus import MilvusClient; MilvusClient('http://localhost:19530').drop_collection('sandbox_docs')"
python -m src.ingest
```

或者用 Attu Web UI 手动删除集合，一样效果。

---

## 代码里这些概念对应什么

| 代码 | Milvus 里的概念 |
|---|---|
| `MilvusClient(uri=...)` | 新版客户端入口，比老的 `connections.connect` 简单 |
| `client.create_schema(...)` + `add_field(...)` | 集合 schema，指定主键、向量字段、业务字段 |
| `DataType.FLOAT_VECTOR` | 向量字段；`dim=384` 必须写死 |
| `enable_dynamic_field=True` | 允许写入 schema 之外的字段（存在 `$meta` 里） |
| `prepare_index_params()` + `AUTOINDEX` | 向量索引。学习场景 AUTOINDEX 让 Milvus 自己挑 |
| `metric_type="COSINE"` | 距离度量；也可以是 `L2`、`IP` |
| `client.upsert(...)` | 按主键插入/更新 |
| `client.flush(...)` | 强制把数据从内存刷到持久化存储（否则搜索可能漏新数据） |
| `client.load_collection(...)` | **搜索前必须加载**，把集合加载进内存，这是 Milvus 比较特别的一点 |
| `client.search(...)` | 检索，返回 `List[List[Hit]]`，多查询批量时外层就是每个查询 |

---

## 框架配置参数详解

### 连接客户端

```python
from pymilvus import MilvusClient

client = MilvusClient(
    uri="http://localhost:19530",  # Milvus gRPC/HTTP 地址；standalone 默认 19530
    # token="user:password",       # 开启认证后传入，格式 "user:password"
    # timeout=10,                  # 请求超时秒数
)
```

> Milvus 也支持本地 lite 模式：`MilvusClient("./local.db")`，不需要 Docker，适合极小数据量的快速验证。

### 定义 Schema 并创建集合

```python
from pymilvus import DataType

schema = client.create_schema(
    auto_id=False,              # False = 自己管 ID，True = Milvus 自动生成
    enable_dynamic_field=True,  # True = schema 之外的字段存进 $meta（类似 JSON 列）
)
schema.add_field(field_name="id",     datatype=DataType.INT64,        is_primary=True)
schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=384)  # dim 必须与模型一致
schema.add_field(field_name="text",   datatype=DataType.VARCHAR,      max_length=2048)

index_params = client.prepare_index_params()
index_params.add_index(
    field_name="vector",
    index_type="AUTOINDEX",     # 自动选择索引，学习场景够用；生产见下方说明
    metric_type="COSINE",       # 距离度量，见下表
    # params={"nlist": 128},    # 手动指定索引时才需要，AUTOINDEX 不用
)

client.create_collection(
    collection_name="my_col",
    schema=schema,
    index_params=index_params,
)
```

**距离度量对比**：

| `metric_type` | 说明 |
|---|---|
| `"COSINE"` | 余弦相似度，文本检索最常用；**注意：Milvus 返回的 distance 字段实际是相似度值** |
| `"IP"` | 内积（Inner Product）；向量已归一化时与 COSINE 等价，速度略快 |
| `"L2"` | 欧氏距离；图像特征向量常用，值越小越相似（与上面两者相反） |

**索引类型说明**（生产场景参考）：

| `index_type` | 适用场景 |
|---|---|
| `AUTOINDEX` | 学习 / 云托管；Milvus 自行决定，开源版默认 HNSW |
| `HNSW` | 通用首选，内存索引，高精度高速度 |
| `IVF_FLAT` | 数据量中等（百万级），精度高但内存占用大 |
| `IVF_PQ` | 数据量大（千万级+），用量化压缩内存，有一定精度损失 |
| `DISKANN` | 数据量超大，索引存磁盘，内存占用极低 |

### 写入数据（`upsert`）

```python
client.upsert(
    collection_name="my_col",
    data=[
        {"id": 1, "vector": [0.1, 0.2, ...], "text": "文本内容"},
        {"id": 2, "vector": [0.3, 0.4, ...], "text": "另一条"},
    ],
)
# 写入后必须 flush，否则数据还在内存缓冲区，search 可能搜不到
client.flush(collection_name="my_col")
```

### 加载集合与检索

```python
# Milvus 独有：搜索前必须先把集合加载进内存
client.load_collection(collection_name="my_col")

results = client.search(
    collection_name="my_col",
    data=[[0.1, 0.2, ...]],             # 外层 list = 批量查询；单次查询也要包一层
    limit=5,                             # top-k
    output_fields=["text"],              # 指定要返回的字段（向量字段默认不返回）
    search_params={"metric_type": "COSINE"},
    # filter='text like "Python%"',      # 标量过滤（先过滤再搜索）
    # anns_field="vector",               # 多向量字段时指定用哪个
)

hits = results[0]   # results 是二维列表，外层对应每个查询
for hit in hits:
    print(hit["id"], hit["entity"]["text"], hit["distance"])
```

---

## 使用注意事项

**1. 搜索前必须 `load_collection`**
这是 Milvus 最容易踩的坑。集合数据存在磁盘（MinIO），搜索前需要加载进内存，否则报 `collection not loaded`。本项目的 `search.py` 启动时已自动调用。

**2. `upsert` 后要 `flush`**
`upsert` 先写入内存 buffer，`flush` 才落盘。不 flush 的话：
- 数据可能搜不到（还在 buffer 里）
- 容器重启后数据丢失

**3. COSINE 指标下 `distance` 实际是相似度**
Milvus 的命名有些反直觉：用 COSINE 时，`hit["distance"]` 返回的值越大越相似（范围 -1 ~ 1），和"距离"的直觉相反。换 L2 时 `distance` 才是真正的距离（值越小越相似）。

**4. 维度改变需删集合重建**
Schema 创建后不可修改（包括向量维度）。换嵌入模型后：
```python
client.drop_collection("sandbox_docs")
# 然后重跑 python -m src.ingest
```

**5. 三个容器缺一不可**
Milvus standalone 需要 etcd（元数据）+ minio（存储）+ milvus（主进程）同时健康。`docker compose ps` 任何一个 Exiting 都会导致 Milvus 功能异常。

**6. `auto_id=True` 时不能手动指定 ID**
一旦 schema 设置了 `auto_id=True`，写入数据时不能包含主键字段，否则报错。本项目用 `auto_id=False` 来保持对 ID 的控制。

---

## Web UI 与 API

### 启动

```bash
uvicorn src.app:app --reload --port 8890
```

| 地址 | 用途 |
|---|---|
| <http://localhost:8890> | 搜索页面（多分类 / 标签 / 时间范围过滤，展示片段、高亮和 score 解释） |
| <http://localhost:8890/ingest> | 写入页面（逐行写入、JSON/CSV 上传、拖拽上传、导入状态统计） |
| <http://localhost:8890/documents> | 文档管理页（分页查看、单条编辑、批量删除、批量重建） |
| <http://localhost:8890/health/panel> | 健康面板（DB / 模型 / 记录数 / 最近错误） |
| <http://localhost:8890/docs> | Swagger API 文档 |

---

### REST API 说明

#### POST `/api/ingest` — 写入文本

**请求体（JSON）**：

```json
{
  "texts": ["第一条文本", "第二条文本"]
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `texts` | `string[]` | 是 | 要写入的文本列表，ID 自动递增 |

**响应体**：

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
| `inserted` | `int` | 实际写入条数 |
| `ids` | `int[]` | 写入记录自动分配的 ID 列表 |
| `skipped` | `int` | 因 `document_id` / `text_hash` 重复被跳过的条数 |
| `existing_count` | `int` | 已存在记录数，等于 `skipped` |
| `existing` | `object[]` | 已存在记录明细，包含命中的 `id`、`document_id`、`text_hash` 和原因 |

**curl 示例**：

```bash
curl -X POST http://localhost:8890/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"texts": ["巴黎是法国的首都", "向量数据库用于语义检索"]}'
```

> Web/API 写入支持 `category`、`tags`、`source`；会按 `document_id` / 规范化文本生成的 `text_hash` 做幂等判断。重复提交不会再次入库，而是返回已存在记录明细。

#### POST `/api/upload` — 上传 JSON / CSV 批量写入

Web 写入页支持按钮选择和拖拽上传两种入口，最终都走同一条上传链路。选择或拖拽文件后页面会显示文件名和大小，提交前可确认。

上传文件支持 `UTF-8` / `UTF-8 BOM` 编码；CSV 首行需要 `text` 列，JSON 顶层需要是数组。

支持字段：

| 字段 | 必填 | 说明 |
|---|---|---|
| `text` | 是 | 文本内容 |
| `document_id` | 否 | 业务侧稳定文档 ID |
| `category` | 否 | 分类 |
| `tags` | 否 | 标签 |
| `source` | 否 | 来源 |

响应除了 `inserted / ids / skipped`，还会返回 `existing_count`、`existing`、`failed`、`errors`、`job_id`、`status` 和 `failed_rows_download_url`。

---

#### POST `/api/search` — 语义搜索

**请求体（JSON）**：

```json
{
  "query": "法国著名地标",
  "limit": 5,
  "categories": ["geography"],
  "tags": ["travel"],
  "created_at_from": "2026-04-20T00:00:00+00:00",
  "created_at_to": "2026-04-22T23:59:59+00:00"
}
```

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `query` | `string` | 是 | — | 查询文本 |
| `limit` | `int` | 否 | `5` | 返回条数，最大 20 |
| `category` | `string` | 否 | `null` | 兼容旧字段，会并入 `categories` |
| `categories` | `string[]` | 否 | `[]` | 可选多分类过滤 |
| `tags` | `string[]` | 否 | `[]` | 可选标签过滤，命中任一标签即返回 |
| `created_at_from` | `string` | 否 | `null` | 可选创建时间起点 |
| `created_at_to` | `string` | 否 | `null` | 可选创建时间终点 |

**响应体**：

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
      "text": "The Eiffel Tower is ...",
      "score": 0.7432,
      "snippet": "...Eiffel Tower is a wrought-iron lattice tower...",
      "matched_terms": ["tower", "france"],
      "score_explanation": "相关性较强，score=0.7432，越接近 1 越相似。",
      "category": "geography",
      "tags": ["travel"],
      "source": "api",
      "created_at": "2026-04-22T10:00:00+00:00",
      "updated_at": "2026-04-22T10:00:00+00:00"
    }
  ]
}
```

`score` 为 COSINE 相似度（-1 ~ 1，越接近 1 越相似）。

> Milvus 小坑：`COSINE` 指标下 `search` 返回的 `distance` 字段实际是**相似度**（不是距离），直接用即可。

**curl 示例**：

```bash
curl -X POST http://localhost:8890/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "法国著名地标", "limit": 3, "categories": ["geography"], "tags": ["travel"]}'
```

---

#### 其他辅助接口

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/api/upload` | 上传 JSON/CSV 批量写入，支持 `text/document_id/category/tags/source` |
| `GET` | `/api/count` | 查询当前集合记录数 |
| `DELETE` | `/api/record/{record_id}` | 删除指定 ID 的记录 |
| `DELETE` | `/api/records` | 清空集合并清空 `data/documents.json` / `data/user_data.json` |
| `GET` | `/api/samples/{lang}` | 返回 `en` 或 `zh` 示例文本 |
| `GET` | `/api/documents` | 分页查看文档元数据 |
| `GET` | `/api/documents/{record_id}` | 查看单条文档 |
| `PUT` | `/api/documents/{record_id}` | 更新文档并自动重建向量 |
| `DELETE` | `/api/documents/{record_id}` | 删除文档和向量 |
| `POST` | `/api/documents/batch-delete` | 批量删除所选文档和向量 |
| `POST` | `/api/documents/batch-reindex` | 批量重建所选文档向量 |
| `POST` | `/api/reindex` | 按 `data/documents.json` 重建当前向量集合 |
| `GET` | `/api/model/status` / `/model/status` | 查看模型状态 |
| `GET` | `/api/health/panel` | 查看 DB / 模型 / 记录数 / 最近错误 |
| `GET` | `/api/import-jobs/{job_id}` | 查看导入任务状态 |
| `GET` | `/api/import-jobs/{job_id}/failed-rows` | 下载失败行 CSV |

搜索审计日志会写入 `../data/search_logs.jsonl`；应用层错误会写入 `../data/app_errors.jsonl`，健康面板直接读取最近错误摘要。

---

### 数据存储说明

写入数据双重保存：
1. **Milvus**（向量库）：使用 `upsert`，相同 id 会覆盖，不产生重复
2. **`data/documents.json`**：产品化元数据主文件，包含 `document_id`、`text_hash`、`source`、`tags`、`created_at`、`updated_at`
3. **`data/user_data.json`**：兼容镜像，Milvus 数据清空后可用 `python -m src.ingest ../data/user_data.json` 重建

> 查询 / 去重优先读取 `data/documents.json`；只有主文件缺失或为空时，才回退到 `data/user_data.json`。

---

## 停止和清理

```bash
docker compose down             # 停三个容器
docker compose down -v          # 连 volume 一起删
rm -rf volumes/                 # 手动删除本地数据目录（etcd / minio / milvus 都在里面）
```

---

## 常见问题

**Q: milvus 容器 `Exited (137)` 或不停重启**
A: 绝大多数是 OOM。检查 Docker 内存分配（上面第 0 步），改到 ≥4GB。

**Q: `load_collection` 报 "collection not loaded"**
A: 本项目的 `search.py` 启动时就会调用 `load_collection`，不会有这个问题。如果你自己写脚本，**搜索前必须先 load**，这是 Milvus 的强制流程（Qdrant / Weaviate 没有这一步）。

**Q: 新入的数据搜不到**
A: 可能还没刷盘。入库后显式调用 `client.flush(collection_name)`，本项目的 `ingest.py` 已经这么做了。

**Q: 为什么 `score` 有时候是负数？**
A: COSINE 相似度范围是 [-1, 1]，负数表示方向相反。如果看到负数结果，说明库里没有跟查询语义相近的内容。

---

## 生产注意事项（学完可忽略）

- **开启认证**：`MilvusClient(uri=..., token="user:pass")`；docker-compose 需要配置 `common.security.authorizationEnabled=true`
- **standalone vs cluster**：本 demo 是 standalone（单机）。生产推荐 cluster 模式，写读分离、能水平扩展
- **索引选型**：`AUTOINDEX` 在云上是 Milvus 自家实现，开源版默认到 HNSW。大数据量下要手选（IVF_FLAT / IVF_PQ / DISKANN 等）并调参
- **数据分区（partition）**：可以按业务维度（比如租户 id）分区，检索时指定分区提升性能
- **备份**：用官方 `milvus-backup` 工具
