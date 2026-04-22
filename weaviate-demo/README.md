# weaviate-demo

用 [Weaviate](https://weaviate.io/) 实现的"入库 + 语义检索"示例。Weaviate 本身支持内置向量化（丢文本进去自己算向量），为了和另外两个子项目对齐，我们这里**关掉**它内置的向量化模块，统一用 `sentence-transformers` 在 Python 端算好向量再写入。

---

## 目录结构

```
weaviate-demo/
├── README.md
├── docker-compose.yml     启动 Weaviate 服务
├── requirements.txt       Python 依赖（weaviate-client v4）
├── .env.example           环境变量模板
└── src/
    ├── config.py
    ├── embedder.py        文本 → 向量
    ├── ingest.py          建集合 + 入库
    └── search.py          交互式检索
```

---

## 一步步跑起来

### 1. 启动 Weaviate

```bash
cd weaviate-demo
docker compose up -d
```

Weaviate 启动约 **5~10 秒**就绪。验证：

```bash
# 查看容器状态（应为 Up 或 running）
docker compose ps

# 健康检查接口，返回 HTTP 200（空 body）说明就绪
curl -o /dev/null -s -w "%{http_code}\n" http://localhost:8080/v1/.well-known/ready
# 输出 200 即可

# 如果容器没起来，查日志
docker compose logs weaviate
```

> Weaviate 还同时监听 **gRPC 端口 50051**，`weaviate-client` v4 会用到它。`docker-compose.yml` 里已经映射好了，不需要额外操作。

### 2. 装 Python 依赖

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> ⚠️ 首次安装会顺带拉 PyTorch（`sentence-transformers` 的依赖），约 **1-2GB**，需要几分钟。
>
> 🇨🇳 国内 HuggingFace 下载慢可以先 `export HF_ENDPOINT=https://hf-mirror.com`。

> 注意：`weaviate-client` **v4** 的 API 和 v3 差别很大。本项目锁死了 v4 版本（见 requirements.txt），如果你在网上看到 `client.query.get(...)` 之类的写法，那是老版 v3，别混用。

### 3. 配置环境变量

```bash
cp .env.example .env
```

用中文：
```bash
# 编辑 .env：
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
DATA_FILE=../data/sample_zh.json
```

### 4. 入库

```bash
python -m src.ingest
```

预期输出：
```
[ingest] 读取数据: .../data/sample_en.json
[embedder] 加载模型: sentence-transformers/all-MiniLM-L6-v2
[ingest] 连接 Weaviate localhost:8080 / 向量维度=384
[ingest] 创建集合 SandboxDocs (vectorizer=none, 距离=cosine)
[ingest] 写入 10 条 → SandboxDocs
[ingest] 完成。集合中共有 10 条。
```

> ⚠️ 本子项目的 `ingest.py` 每次都会**先删除旧集合再重建**，保证幂等。如果你在集合里手动加了别的数据，跑 ingest 前注意备份。

### 5. 搜索

```bash
python -m src.search
```

```
> vector database with cosine similarity
查询: vector database with cosine similarity
------------------------------------------------------------
1. sim=0.6823  doc_id=5
   Vector databases store embeddings and support approximate nearest neighbor search.
2. sim=0.3150  doc_id=10
   A sentence embedding maps a piece of text into a fixed-dimensional vector.
...
```

> Weaviate 返回的是 **distance**（距离）；为了直观，`search.py` 已经换算成了 similarity（相似度 = 1 − 距离），越接近 1 越像。

---

## 带过滤条件的检索

```bash
python -m src.filter_search                              # 交互模式
python -m src.filter_search "neural network" technology
python -m src.filter_search "ocean current" geography
```

**过滤语法**（Weaviate v4 Filter）：

```python
from weaviate.classes.query import Filter

# 单条件
filters=Filter.by_property("category").equal("technology")

# AND / OR
filters=Filter.by_property("category").equal("technology") \
    & Filter.by_property("doc_id").greater_than(100)
```

> Weaviate 的过滤是 pre-filter，先按属性筛选再做向量近邻搜索。注意：`ingest.py` 每次会重建集合，如需保留旧数据请改用 Web UI 写入。

---

## 换数据 / 换模型

### 换数据

```bash
python -m src.ingest /path/to/your_data.json
```

### 换模型

改 `.env` 的 `EMBEDDING_MODEL`，直接重跑 `python -m src.ingest` 即可。因为 ingest 每次都会重建集合，不像 Qdrant 需要手动删。

---

## 代码里这些概念对应什么

| 代码 | Weaviate v4 里的概念 |
|---|---|
| `weaviate.connect_to_local(...)` | v4 官方推荐的本地连接快捷函数 |
| `client.collections.create(name, properties, vectorizer_config=...)` | 建集合，相当于定义一张表 |
| `Property(name, data_type)` | 字段定义；`DataType.TEXT / INT / ...` |
| `Configure.Vectorizer.none()` | 告诉 Weaviate "我自己算向量，你别管" |
| `Configure.VectorIndex.hnsw(distance_metric=...)` | HNSW 索引 + 距离度量 |
| `DataObject(properties=..., uuid=..., vector=...)` | 一条记录；uuid 用 `generate_uuid5` 生成，实现幂等 |
| `collection.data.insert_many(...)` | 批量写入 |
| `collection.query.near_vector(near_vector=..., limit=...)` | 按向量相似度检索 |
| `MetadataQuery(distance=True)` | 让返回结果里带上距离（可选：score、certainty 等） |

---

## 框架配置参数详解

### 连接客户端

```python
import weaviate

# 本地连接（推荐写法，v4 简化了连接 API）
client = weaviate.connect_to_local(
    host="localhost",       # Weaviate HTTP 地址
    port=8080,              # HTTP 端口
    grpc_port=50051,        # gRPC 端口（v4 客户端内部用 gRPC 传输数据）
    # auth_credentials=weaviate.auth.AuthApiKey("YOUR_KEY"),  # 开启鉴权后传入
)

# 用完必须关闭，否则连接不释放
try:
    ...
finally:
    client.close()

# 或者用 with 语句（推荐）
with weaviate.connect_to_local(...) as client:
    ...
```

### 创建集合（`collections.create`）

```python
from weaviate.classes.config import Configure, DataType, Property, VectorDistances

client.collections.create(
    name="MyCollection",       # 集合名必须以大写字母开头（Weaviate 强制要求）
    properties=[
        Property(name="doc_id", data_type=DataType.INT),
        Property(name="text",   data_type=DataType.TEXT),
        # 其他字段类型：DataType.BOOL / NUMBER / DATE / UUID 等
    ],
    vectorizer_config=Configure.Vectorizer.none(),   # 自己提供向量；也可用内置向量化模块
    vector_index_config=Configure.VectorIndex.hnsw(
        distance_metric=VectorDistances.COSINE,      # 距离度量
        # ef_construction=128,  # 构建时搜索宽度，越大精度越高、建索引越慢
        # max_connections=64,   # 每个节点最大连接数，越大精度越高、内存越多
        # ef=64,                # 查询时搜索宽度，可在运行时动态调整
    ),
    # 也可以换成 flat 索引（暴力扫描，适合数据量极小的场景）：
    # vector_index_config=Configure.VectorIndex.flat(distance_metric=VectorDistances.COSINE),
)
```

**距离度量对比**：

| 枚举值 | 说明 |
|---|---|
| `VectorDistances.COSINE` | 余弦距离（= 1 − 余弦相似度）；文本检索最常用 |
| `VectorDistances.DOT` | 内积（负数，越小越相似）；向量未归一化时用 |
| `VectorDistances.L2` | 欧氏距离平方；图像特征常用 |
| `VectorDistances.HAMMING` | 汉明距离；二进制向量用 |

### 写入数据（`insert_many`）

```python
from weaviate.classes.data import DataObject
from weaviate.util import generate_uuid5

collection = client.collections.get("MyCollection")
result = collection.data.insert_many([
    DataObject(
        properties={"doc_id": 1, "text": "文本内容"},
        uuid=generate_uuid5("1"),   # 用固定输入生成稳定 UUID，保证幂等
        vector=[0.1, 0.2, ...],     # 向量列表，长度须与建集合时一致
    )
])
if result.has_errors:
    for idx, err in result.errors.items():
        print(f"第 {idx} 条失败: {err.message}")
```

### 检索（`near_vector`）

```python
from weaviate.classes.query import MetadataQuery

collection = client.collections.get("MyCollection")
res = collection.query.near_vector(
    near_vector=[0.1, 0.2, ...],        # 查询向量
    limit=5,                             # 返回 top-k
    return_metadata=MetadataQuery(
        distance=True,                   # 返回距离值
        # score=True,                    # 也可要求返回 score（BM25/hybrid 搜索时用）
    ),
    # filters=Filter.by_property("doc_id").greater_than(5),  # 结构化过滤
    # distance=0.5,                      # 只返回距离 ≤ 阈值的结果
)

for obj in res.objects:
    similarity = 1 - obj.metadata.distance   # distance 是 cosine 距离，转成相似度
    print(similarity, obj.properties["text"])
```

---

## 使用注意事项

**1. 集合名必须以大写字母开头**
Weaviate 强制要求集合名（class name）首字母大写，如 `SandboxDocs`。小写会报错。

**2. `client.close()` 不能省**
Weaviate v4 客户端内部维护 HTTP + gRPC 双连接。不关闭会导致连接泄漏，长时间运行后报 `Too many open files`。用 `with` 语句是最安全的写法。

**3. ingest.py 会重建集合（会清空数据）**
本项目的命令行 `ingest.py` 每次都先删除再重建集合，保证幂等。但 **Web UI 的写入是增量的**（不删除），两者行为不同，注意区分。

**4. score vs distance**
Weaviate 的 `near_vector` 返回的是**距离**（`distance`），不是相似度：
- COSINE 距离 = 1 − 余弦相似度，范围 0 ~ 2（0 表示完全一样）
- 代码里用 `similarity = 1 - distance` 换算成更直观的相似度

**5. v4 与 v3 API 完全不兼容**
网上很多教程是 v3（`client.query.get(...)`、`client.schema.create(...)`)。v4 的命名空间完全改了，看到 v3 写法一律不要参考。

**6. UUID 主键与幂等**
Weaviate 用 UUID 作对象主键。用 `generate_uuid5(str(doc_id))` 可以从固定输入生成稳定 UUID，同一 `doc_id` 多次写入不会产生重复记录（后者覆盖前者）。

---

## Web UI 与 API

### 启动

```bash
uvicorn src.app:app --reload --port 8889
```

| 地址 | 用途 |
|---|---|
| <http://localhost:8889> | 搜索页面 |
| <http://localhost:8889/ingest> | 写入页面 |
| <http://localhost:8889/docs> | Swagger API 文档 |

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
{"inserted": 2, "ids": [11, 12]}
```

**curl 示例**：

```bash
curl -X POST http://localhost:8889/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"texts": ["巴黎是法国的首都", "向量数据库用于语义检索"]}'
```

> 与命令行 `ingest.py` 不同，Web API 写入是**增量的**（不会删除已有数据）。Web/API 写入只接收文本并自动分配 ID；如果需要保留 `category` 等元数据，请使用命令行 `python -m src.ingest your.json`。

---

#### POST `/api/search` — 语义搜索

**请求体（JSON）**：

```json
{
  "query": "法国著名地标",
  "limit": 5,
  "category": "geography"
}
```

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|---|---|---|---|---|
| `query` | `string` | 是 | — | 查询文本 |
| `limit` | `int` | 否 | `5` | 返回条数，最大 20 |
| `category` | `string` | 否 | `null` | 可选分类过滤 |

**响应体**：

```json
{
  "query": "法国著名地标",
  "results": [
    {"id": 1, "text": "The Eiffel Tower is ...", "score": 0.7432}
  ]
}
```

`score` = 1 − cosine distance，范围 0 ~ 1，越大越相似。

**curl 示例**：

```bash
curl -X POST http://localhost:8889/api/search \
  -H "Content-Type: application/json" \
  -d '{"query": "法国著名地标", "limit": 3, "category": "geography"}'
```

---

#### 其他辅助接口

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/api/upload` | 上传 JSON/CSV 批量写入，只读取 `text` 字段 |
| `GET` | `/api/count` | 查询当前集合记录数 |
| `DELETE` | `/api/record/{record_id}` | 删除指定 ID 的记录 |
| `DELETE` | `/api/records` | 清空集合并清空 `data/user_data.json` |
| `GET` | `/api/samples/{lang}` | 返回 `en` 或 `zh` 示例文本 |

---

### 数据存储说明

写入数据双重保存：
1. **Weaviate**（向量库）：用 UUID 主键 + `doc_id` 字段存储
2. **`data/user_data.json`**：本地备份，Weaviate 数据清空后可用 `python -m src.ingest ../data/user_data.json` 重建

---

## 停止和清理

```bash
docker compose down           # 停止容器但保留数据
docker compose down -v        # 连数据一起删
rm -rf weaviate_data/         # 手动删本地数据目录
```

---

## 常见问题

**Q: 连接时报 `gRPC health check failed`**
A: `docker-compose.yml` 里必须映射 50051 端口，并且客户端里要传 `grpc_port=50051`，本项目都配好了，确认容器是不是起来了即可。

**Q: 代码里怎么没有 `client.schema.create(...)`？**
A: 那是 v3 的 API。v4 统一改成了 `client.collections.create(...)`。

**Q: 为什么入库用 `doc_id` 而不是直接用 `id`？**
A: Weaviate 的对象主键叫 `uuid`，必须是 UUID 格式；我们用原始整数 id 作为 `doc_id` 字段保存，另外用 `generate_uuid5(str(id))` 生成稳定的 UUID 作为主键。

---

## 生产注意事项（学完可忽略）

- **开启鉴权**：把 `AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED` 改成 `false`，并配置 API Key 或 OIDC
- **内置向量化**：生产上可以用 `text2vec-openai` / `text2vec-transformers` 让 Weaviate 自己算向量，省去在应用层维护 embedding pipeline
- **多节点**：单容器只能做学习用，生产跑集群；见官方 Helm chart
- **备份**：Weaviate 有 backup API，可以直接导出到 S3 / 本地盘
