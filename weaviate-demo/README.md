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

# 验证
curl http://localhost:8080/v1/.well-known/ready
# 返回空 200 就 OK
```

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
