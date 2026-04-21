# 三库 API 横向对比

同一件事，三种写法。对比 **Qdrant / Weaviate / Milvus** 在六个核心操作上的 API 差异。

---

## 目录

1. [客户端连接](#1-客户端连接)
2. [创建集合](#2-创建集合)
3. [写入数据](#3-写入数据)
4. [纯向量检索](#4-纯向量检索)
5. [向量 + 元数据过滤检索](#5-向量--元数据过滤检索)
6. [删除集合](#6-删除集合)
7. [关键差异速查表](#7-关键差异速查表)

---

## 1. 客户端连接

**Qdrant**
```python
from qdrant_client import QdrantClient

client = QdrantClient(host="localhost", port=6333)
# 无需手动关闭，连接自动复用
```

**Weaviate**
```python
import weaviate

client = weaviate.connect_to_local(host="localhost", port=8080, grpc_port=50051)
# ⚠️ 必须显式关闭，否则连接泄漏
try:
    ...
finally:
    client.close()
# 或用 with 语句
```

**Milvus**
```python
from pymilvus import MilvusClient

client = MilvusClient(uri="http://localhost:19530")
# 无需手动关闭
```

> **差异**：Weaviate v4 客户端维护双连接（HTTP + gRPC），必须手动 close。Qdrant 和 Milvus 的客户端用完不需要显式释放。

---

## 2. 创建集合

**Qdrant**
```python
from qdrant_client.http import models as qm

client.create_collection(
    collection_name="sandbox_docs",
    vectors_config=qm.VectorParams(
        size=384,                    # 向量维度
        distance=qm.Distance.COSINE, # 距离度量
    ),
)
```

**Weaviate**
```python
from weaviate.classes.config import Configure, DataType, Property, VectorDistances

client.collections.create(
    name="SandboxDocs",              # ⚠️ 名称必须首字母大写
    properties=[
        Property(name="doc_id",   data_type=DataType.INT),
        Property(name="text",     data_type=DataType.TEXT),
        Property(name="category", data_type=DataType.TEXT),
    ],
    vectorizer_config=Configure.Vectorizer.none(),       # 自己提供向量
    vector_index_config=Configure.VectorIndex.hnsw(
        distance_metric=VectorDistances.COSINE,
    ),
)
```

**Milvus**
```python
from pymilvus import DataType

schema = client.create_schema(auto_id=False, enable_dynamic_field=True)
schema.add_field("id",     DataType.INT64,        is_primary=True)
schema.add_field("vector", DataType.FLOAT_VECTOR, dim=384)
schema.add_field("text",   DataType.VARCHAR,      max_length=2048)

index_params = client.prepare_index_params()
index_params.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")

client.create_collection("sandbox_docs", schema=schema, index_params=index_params)
```

> **差异**：
> - Qdrant 最简洁，只需指定维度和距离。
> - Weaviate 需要显式定义每个字段的类型（Properties），且集合名必须首字母大写。
> - Milvus 需要分别定义 Schema 和 Index，概念最多；但 `enable_dynamic_field=True` 允许存储 schema 之外的字段（如 `category`），无需预先声明。

---

## 3. 写入数据

假设已有向量 `vector: list[float]`，原始记录 `{"id": 1, "text": "...", "category": "tech"}`。

**Qdrant**
```python
from qdrant_client.http import models as qm

client.upsert(
    collection_name="sandbox_docs",
    points=[
        qm.PointStruct(
            id=1,
            vector=vector,
            payload={"text": "...", "category": "technology"},  # payload 存业务字段
        )
    ],
    wait=True,  # 同步写入，返回后立即可搜索
)
```

**Weaviate**
```python
from weaviate.classes.data import DataObject
from weaviate.util import generate_uuid5

collection = client.collections.get("SandboxDocs")
result = collection.data.insert_many([
    DataObject(
        properties={"doc_id": 1, "text": "...", "category": "technology"},
        uuid=generate_uuid5("1"),   # 从固定输入生成稳定 UUID，实现幂等
        vector=vector,
    )
])
# ⚠️ 必须检查是否有局部失败
if result.has_errors:
    for idx, err in result.errors.items():
        print(f"第 {idx} 条失败: {err.message}")
```

**Milvus**
```python
client.upsert(
    collection_name="sandbox_docs",
    data=[{"id": 1, "vector": vector, "text": "...", "category": "technology"}],
    # category 存入 dynamic field（$meta），因为 schema 里没有预先定义
)
# ⚠️ 写入后必须 flush，否则数据还在内存 buffer，可能搜不到
client.flush(collection_name="sandbox_docs")
```

> **差异**：
> - Qdrant / Milvus 用整数 id；Weaviate 主键是 UUID，需要额外生成。
> - Weaviate `insert_many` 可能局部失败且不抛异常，必须检查 `result.has_errors`。
> - Milvus 写入后必须 `flush` 才落盘；Qdrant / Weaviate 无此步骤。

---

## 4. 纯向量检索

**Qdrant**
```python
hits = client.search(
    collection_name="sandbox_docs",
    query_vector=query_vector,
    limit=5,
    with_payload=True,
)
for hit in hits:
    print(hit.score, hit.payload["text"])
    # score 是余弦相似度，-1 ~ 1，越大越相似
```

**Weaviate**
```python
from weaviate.classes.query import MetadataQuery

collection = client.collections.get("SandboxDocs")
res = collection.query.near_vector(
    near_vector=query_vector,
    limit=5,
    return_metadata=MetadataQuery(distance=True),
)
for obj in res.objects:
    similarity = 1 - obj.metadata.distance   # distance 是余弦距离，转成相似度
    print(similarity, obj.properties["text"])
```

**Milvus**
```python
# ⚠️ 搜索前必须先 load_collection（Qdrant/Weaviate 没有这一步）
client.load_collection("sandbox_docs")

results = client.search(
    collection_name="sandbox_docs",
    data=[query_vector],          # 外层包一个 list，支持批量查询
    limit=5,
    output_fields=["text", "category"],
    search_params={"metric_type": "COSINE"},
)
for hit in results[0]:            # results[0] 对应第一个查询
    print(hit["distance"], hit["entity"]["text"])
    # COSINE 下 distance 实际是相似度（越大越相似），命名有些反直觉
```

> **差异**：
> - Milvus 搜索前必须 `load_collection`，Qdrant 和 Weaviate 没有这步。
> - Weaviate 返回**余弦距离**（值越小越相似），需要用 `1 - distance` 换算成相似度。
> - Milvus COSINE 模式下返回的 `distance` 字段实际是**相似度**（命名反直觉）。
> - Milvus `search` 的 `data` 参数是二维 list，支持批量；Qdrant / Weaviate 是单向量。

---

## 5. 向量 + 元数据过滤检索

在向量检索的同时，限定只在 `category == "technology"` 的记录里搜索。

**Qdrant**
```python
from qdrant_client.http import models as qm

hits = client.search(
    collection_name="sandbox_docs",
    query_vector=query_vector,
    limit=5,
    query_filter=qm.Filter(
        must=[
            qm.FieldCondition(
                key="category",
                match=qm.MatchValue(value="technology"),
            )
        ]
    ),
)
```

更复杂的过滤（多条件 AND / OR）：
```python
qm.Filter(
    must=[
        qm.FieldCondition(key="category", match=qm.MatchValue(value="technology")),
        qm.FieldCondition(key="score",    range=qm.Range(gte=0.5)),
    ],
    should=[  # OR
        qm.FieldCondition(key="lang", match=qm.MatchValue(value="zh")),
    ],
)
```

**Weaviate**
```python
from weaviate.classes.query import Filter

res = collection.query.near_vector(
    near_vector=query_vector,
    limit=5,
    filters=Filter.by_property("category").equal("technology"),
)
```

更复杂的过滤：
```python
from weaviate.classes.query import Filter

Filter.by_property("category").equal("technology") \
    & Filter.by_property("doc_id").greater_than(100)   # AND
Filter.by_property("category").equal("technology") \
    | Filter.by_property("category").equal("science")  # OR
```

**Milvus**
```python
results = client.search(
    collection_name="sandbox_docs",
    data=[query_vector],
    limit=5,
    output_fields=["text", "category"],
    filter='category == "technology"',   # 标量表达式字符串
    search_params={"metric_type": "COSINE"},
)
```

更复杂的过滤（SQL-like 表达式）：
```python
filter='category == "technology" and doc_id > 100'
filter='category in ["technology", "science"]'
filter='category == "technology" or category == "science"'
```

> **差异**：
> - **Qdrant**：用 Python 对象（`Filter` / `FieldCondition`）构建过滤条件，类型安全但稍显冗长。
> - **Weaviate v4**：链式调用 `Filter.by_property(...).equal(...)`，支持 `&` / `|` 运算符，语法最简洁。
> - **Milvus**：SQL-like 字符串表达式，最接近 SQL 习惯，但需要注意字符串拼接的安全性。

---

## 6. 删除集合

**Qdrant**
```python
client.delete_collection("sandbox_docs")
# 或用 REST API：curl -X DELETE http://localhost:6333/collections/sandbox_docs
```

**Weaviate**
```python
client.collections.delete("SandboxDocs")
# 或检查存在再删：
if client.collections.exists("SandboxDocs"):
    client.collections.delete("SandboxDocs")
```

**Milvus**
```python
client.drop_collection("sandbox_docs")
# 或用 Python 一行：
# python -c "from pymilvus import MilvusClient; MilvusClient('http://localhost:19530').drop_collection('sandbox_docs')"
```

---

## 7. 关键差异速查表

| 操作 | Qdrant | Weaviate | Milvus |
|---|---|---|---|
| **集合名规则** | 任意字符串 | **首字母必须大写** | 任意字符串 |
| **主键类型** | 整数 或 UUID 字符串 | UUID（必须手动生成） | 整数（推荐）或字符串 |
| **额外字段** | payload（任意 JSON） | Properties（需预定义） | dynamic field（无需预定义） |
| **写入后可见** | 立即（`wait=True`） | 立即 | **需 `flush()` 落盘** |
| **搜索前准备** | 无 | 无 | **必须 `load_collection()`** |
| **score 含义** | 余弦相似度（↑大越好） | 余弦**距离**（↓小越好，用 `1-d` 换算） | COSINE 时实为相似度（↑大越好，命名反直觉） |
| **过滤语法** | Python 对象（`Filter`/`FieldCondition`） | 链式调用（`Filter.by_property()`） | SQL-like 字符串 |
| **部分写入失败** | 抛异常 | **静默！必须检查 `result.has_errors`** | 抛异常 |
| **客户端关闭** | 无需 | **必须 `client.close()`** | 无需 |
| **Python 包** | `qdrant-client` | `weaviate-client`（注意 v4 vs v3 不兼容） | `pymilvus` |
| **默认端口** | 6333 (HTTP) / 6334 (gRPC) | 8080 (HTTP) / 50051 (gRPC) | 19530 |

---

## 附：过滤检索运行方式

三个子项目都有对应的 `filter_search.py`，用大数据集（`sample_large_en.json`）入库后效果最明显：

```bash
# 先用大数据集入库（100 条，含 category 字段）
python -m src.ingest ../data/sample_large_en.json

# 然后运行过滤检索
python -m src.filter_search                          # 交互模式
python -m src.filter_search "neural network" technology   # 单次查询
python -m src.filter_search "ocean current" geography
```
