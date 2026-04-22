# qdrant-demo

用 [Qdrant](https://qdrant.tech/) 实现的"入库 + 语义检索"示例。**推荐作为三者中的第一个练习**：单容器、启动最快、资源占用最小。

---

## 目录结构

```
qdrant-demo/
├── README.md
├── docker-compose.yml     启动 Qdrant 服务
├── requirements.txt       Python 依赖
├── .env.example           环境变量模板
└── src/
    ├── config.py          读取 .env
    ├── embedder.py        文本 → 向量（sentence-transformers）
    ├── ingest.py          读取 JSON 数据 → 入库
    └── search.py          交互式检索
```

---

## 一步步跑起来

### 1. 启动 Qdrant

```bash
cd qdrant-demo
docker compose up -d
```

Qdrant 启动很快，约 **3~5 秒**就绪。验证：

```bash
# 查看容器状态（应为 Up 或 running）
docker compose ps

# 健康检查接口，返回 "all shards are ready" 说明就绪
curl http://localhost:6333/readyz

# 如果容器没起来，查日志
docker compose logs qdrant
```

**Web 控制台**：<http://localhost:6333/dashboard> — 可以在浏览器里直接浏览 collection 和向量数据，入库后来这里确认数据是否写进去了。

### 2. 装 Python 依赖

**强烈建议用虚拟环境**，免得污染全局 Python：

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> ⚠️ 首次安装会顺带拉 PyTorch（`sentence-transformers` 的依赖），约 **1-2GB**，需要几分钟。没卡死，耐心等。
>
> 🇨🇳 国内 HuggingFace 下载慢可以先 `export HF_ENDPOINT=https://hf-mirror.com`，再跑后面的 ingest / search。

### 3. 配置环境变量

```bash
cp .env.example .env
```

默认用英文模型 + 英文数据，开箱即用。要用中文：

```bash
# 编辑 .env，把两行改成：
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
DATA_FILE=../data/sample_zh.json
```

### 4. 入库

```bash
python -m src.ingest
```

看到类似输出：
```
[ingest] 读取数据: .../data/sample_en.json
[embedder] 加载模型: sentence-transformers/all-MiniLM-L6-v2
[ingest] 创建集合 sandbox_docs (维度=384, 距离=cosine)
[ingest] 写入 10 条 → sandbox_docs
[ingest] 完成。集合中共有 10 条。
```

### 5. 搜索

交互式：

```bash
python -m src.search
```

```
> where is the eiffel tower
查询: where is the eiffel tower
------------------------------------------------------------
1. score=0.7432  id=1
   The Eiffel Tower is a wrought-iron lattice tower located in Paris, France.
2. score=0.2105  id=3
   The Great Wall of China stretches for thousands of miles across northern China.
...
```

单次查询：
```bash
python -m src.search "what is a vector database"
```

---

## 带过滤条件的检索

纯向量检索找"语义最近"，过滤检索在此基础上限定只在某个分类里搜索。

```bash
python -m src.filter_search                              # 交互模式
python -m src.filter_search "neural network" technology  # 文本 + 分类
python -m src.filter_search "ocean current" geography
```

**过滤语法**（Qdrant payload filter）：

```python
qm.Filter(
    must=[
        qm.FieldCondition(key="category", match=qm.MatchValue(value="technology")),
    ]
)
```

> 过滤发生在向量检索之前（pre-filter）：Qdrant 先找出满足条件的点，再在这个子集里做近邻搜索。数据需要包含 `category` 字段，用 `sample_large_en.json` 入库效果最好（100 条，8 个分类）。

---

## 换数据 / 换模型

### 换数据

数据文件就是一个 JSON 数组，每条记录有 `id`（整数）和 `text`（字符串）：

```json
[
  {"id": 1, "text": "你的第一条数据"},
  {"id": 2, "text": "你的第二条数据"}
]
```

把你的文件放到任意位置，然后：
```bash
python -m src.ingest /path/to/your_data.json
```
或者改 `.env` 里的 `DATA_FILE`。

### 换模型

改 `.env` 的 `EMBEDDING_MODEL`。**然后必须删掉老集合**（维度不同会报错）：

```bash
curl -X DELETE http://localhost:6333/collections/sandbox_docs
python -m src.ingest
```

---

## 代码里这些概念对应什么

| 代码 | Qdrant 里的概念 |
|---|---|
| `client.create_collection` | 建集合，指定向量维度和距离度量 |
| `qm.Distance.COSINE` | 余弦相似度；因为向量做了归一化，等价于内积 |
| `qm.PointStruct(id, vector, payload)` | 一条记录：id + 向量 + 附加字段（payload） |
| `client.upsert` | 插入或更新（按 id） |
| `client.search` | 给一个向量，返回 top-k 最近邻 |
| `payload` | 类似 MongoDB 的文档，存业务字段 |

---

## 框架配置参数详解

### 连接客户端

```python
from qdrant_client import QdrantClient

client = QdrantClient(
    host="localhost",   # Qdrant 服务地址
    port=6333,          # REST/HTTP 端口（默认 6333）
    # grpc_port=6334,   # 可选：gRPC 端口，大批量写入时吞吐更高
    # api_key="xxx",    # 生产环境开启鉴权后需要传入
    # timeout=10,       # 请求超时秒数，默认无限制
    # https=True,       # 生产环境用 TLS 时开启
)
```

### 创建集合（`create_collection`）

```python
from qdrant_client.http import models as qm

client.create_collection(
    collection_name="my_collection",
    vectors_config=qm.VectorParams(
        size=384,               # 向量维度，必须与嵌入模型一致
        distance=qm.Distance.COSINE,  # 距离度量，见下表
        # on_disk=True,         # 将向量存磁盘而非内存，适合超大数据集
    ),
    # hnsw_config=qm.HnswConfigDiff(  # HNSW 索引调优（一般不需要动）
    #     m=16,                 # 每个节点的最大连接数，越大精度越高但内存更多
    #     ef_construct=100,     # 构建时的搜索宽度，越大精度越高但建索引慢
    # ),
    # optimizers_config=qm.OptimizersConfigDiff(
    #     indexing_threshold=20000,  # 超过多少条开始建 HNSW 索引，默认 20000
    # ),
)
```

**距离度量对比**：

| 枚举值 | 适用场景 |
|---|---|
| `Distance.COSINE` | 文本语义检索（最常用）；向量归一化后等价于内积，推荐 |
| `Distance.DOT` | 向量未归一化时用内积，适合 OpenAI 等不做归一化的模型 |
| `Distance.EUCLID` | 欧氏距离，图像特征向量常用 |
| `Distance.MANHATTAN` | 曼哈顿距离，较少使用 |

### 写入数据（`upsert`）

```python
client.upsert(
    collection_name="my_collection",
    points=[
        qm.PointStruct(
            id=1,                           # 整数或 UUID 字符串，必须唯一
            vector=[0.1, 0.2, ...],         # 长度必须等于 size
            payload={"text": "原始文本",    # 任意 JSON 字段，用于过滤和返回
                     "category": "tech"},
        )
    ],
    wait=True,   # True = 写入完成后才返回（同步），False = 异步写入更快但要自己保证顺序
)
```

### 检索（`search`）

```python
hits = client.search(
    collection_name="my_collection",
    query_vector=[0.1, 0.2, ...],   # 查询向量
    limit=5,                         # 返回 top-k 条
    with_payload=True,               # 是否返回 payload 字段（默认 True）
    # score_threshold=0.5,           # 只返回相似度 ≥ 阈值的结果
    # query_filter=qm.Filter(        # 结构化过滤（先过滤再搜索）
    #     must=[
    #         qm.FieldCondition(
    #             key="category",
    #             match=qm.MatchValue(value="tech"),
    #         )
    #     ]
    # ),
)
```

---

## 使用注意事项

**1. 维度必须与模型一致**
集合创建后维度不能改。换模型（如从 384 维换到 512 维）必须先删集合再重建：
```bash
curl -X DELETE http://localhost:6333/collections/sandbox_docs
python -m src.ingest
```

**2. ID 类型一旦确定不能混用**
Qdrant 支持整数和 UUID 两种 ID，但同一个集合里只能用一种。本项目用整数，不要混入 UUID。

**3. `wait=True` vs `wait=False`**
默认 `wait=True`（同步），upsert 返回后数据立即可搜索。`wait=False` 吞吐更高，但数据不一定立即可见，适合批量预加载场景。

**4. Payload 过滤需要先建索引**
直接用 `query_filter` 可以过滤，但字段没有索引时会做全扫描。大数据量下先建 payload 索引：
```python
client.create_payload_index(
    collection_name="sandbox_docs",
    field_name="category",
    field_schema=qm.PayloadSchemaType.KEYWORD,
)
```

**5. 数据持久化**
默认数据存在 Docker volume（`./qdrant_data/`）。容器删了数据还在；`docker compose down -v` 才会连 volume 一起删。

---

## Web UI 与 API

除了命令行脚本，本子项目还提供一个基于 **FastAPI** 的 Web 界面和 REST API。

### 启动

```bash
# 确保已激活虚拟环境，且 qdrant 容器正在运行
uvicorn src.app:app --reload --port 8888
```

浏览器访问：

| 地址 | 用途 |
|---|---|
| <http://localhost:8888> | 搜索页面（在线输入关键词，看语义检索结果） |
| <http://localhost:8888/ingest> | 写入页面（每行一条文本，点击写入向量库） |
| <http://localhost:8888/docs> | Swagger API 文档（可在线试用接口） |

---

### REST API 说明

#### POST `/api/ingest` — 写入文本

**请求体（JSON）**：

```json
{
  "texts": [
    "第一条要写入的文本",
    "第二条要写入的文本"
  ]
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `texts` | `string[]` | 是 | 要写入的文本列表，每条独立向量化。ID 自动递增，无需手动指定 |

**响应体（JSON）**：

```json
{
  "inserted": 2,
  "ids": [11, 12]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `inserted` | `int` | 实际写入条数 |
| `ids` | `int[]` | 写入记录自动分配的 ID 列表 |

**curl 示例**：

```bash
curl -X POST http://localhost:8888/api/ingest \
  -H "Content-Type: application/json" \
  -d '{"texts": ["巴黎是法国的首都", "向量数据库用于语义检索"]}'
```

> Web/API 写入只接收文本并自动分配 ID；如果需要保留 `category` 等元数据，请使用命令行 `python -m src.ingest your.json`。

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
| `query` | `string` | 是 | — | 查询文本，系统自动向量化 |
| `limit` | `int` | 否 | `5` | 返回结果条数，最大 20 |
| `category` | `string` | 否 | `null` | 可选分类过滤 |

**响应体（JSON）**：

```json
{
  "query": "法国著名地标",
  "results": [
    {"id": 1, "text": "The Eiffel Tower is ...", "score": 0.7432},
    {"id": 3, "text": "The Great Wall of China ...", "score": 0.1205}
  ]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `query` | `string` | 原始查询文本 |
| `results[].id` | `int` | 记录 ID |
| `results[].text` | `string` | 原始文本内容 |
| `results[].score` | `float` | 余弦相似度（-1 ~ 1，越接近 1 越相似） |

**curl 示例**：

```bash
curl -X POST http://localhost:8888/api/search \
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

通过 Web UI 或 API 写入的数据会**双重保存**：

1. **Qdrant**（向量库）：用于语义检索，ID 对应 `PointStruct.id`
2. **`data/user_data.json`**（本地 JSON 文件）：追加写入，格式与 `sample_en.json` 一致，Qdrant 数据清空后可用 `python -m src.ingest ../data/user_data.json` 重新入库

> 为什么双写？ 向量库适合检索，但不擅长原始数据备份。把文本同时存一份 JSON，方便查看、编辑、重新入库，不依赖向量库的健康状态。

---

## 停止和清理

```bash
docker compose down           # 停止容器但保留数据
docker compose down -v        # 连数据一起删
rm -rf qdrant_data/           # 手动删本地数据目录
```

---

## 常见问题

**Q: `Connection refused` / 连不上 6333**
A: 容器没起来，先 `docker compose ps`。如果 `Exit` 了看 `docker compose logs qdrant`。

**Q: 换了中文模型后 ingest 报错**
A: 错误信息里会提示你删集合的命令，照着执行再 ingest 一次。

**Q: `search` 结果里 score 都很低？**
A: 说明库里没有和查询语义相近的内容。英文查询配英文数据、中文查询配中文数据，别混用。

---

## 生产注意事项（学完可忽略）

- 开启 API Key：在 docker-compose 里加环境变量 `QDRANT__SERVICE__API_KEY=...`，客户端连接时传 `api_key=...`
- 数据盘用 SSD、做好备份
- 并发写入用批量 `upsert`，单条 upsert 有 RPC 开销
- 大数据量下开启 HNSW 索引调优（`hnsw_config`）
