"""向量库性能基准对比。

测试内容：
  1. 向量化耗时（嵌入 1000 条文本，仅跑一次，三库共用结果）
  2. 批量写入 1000 条向量（每批 100 条）
  3. 随机查询 100 次（top-5）

输出：每个阶段的耗时 / QPS / 平均延迟，以及写入前后的内存增量（需安装 psutil）。

用法：
    # 在项目根目录下，确保已激活虚拟环境（任意子项目的 .venv 均可）
    python scripts/benchmark.py              # 测全部（默认）
    python scripts/benchmark.py qdrant       # 只测 Qdrant
    python scripts/benchmark.py weaviate     # 只测 Weaviate
    python scripts/benchmark.py milvus       # 只测 Milvus

前置条件：
    - 目标数据库已通过 docker compose up -d 启动
    - pip install sentence-transformers qdrant-client weaviate-client pymilvus
    - pip install psutil（可选，用于内存统计）
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# ─── 可选依赖：psutil ──────────────────────────────────────────────────────────
try:
    import psutil
    _PROCESS = psutil.Process()
    def _rss_mb() -> float:
        return _PROCESS.memory_info().rss / 1024 / 1024
except ImportError:
    psutil = None  # type: ignore
    def _rss_mb() -> float:
        return float("nan")

# ─── 项目路径 ──────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "sample_large_en.json"
MODEL_CACHE = ROOT / "models"
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

BENCH_COLLECTION = "benchmark_test"   # 专用于基准测试，不影响 demo 数据
N_INSERT = 1000
N_QUERY  = 100
BATCH    = 100


# ─── 数据准备 ──────────────────────────────────────────────────────────────────

def load_texts(n: int) -> list[dict]:
    """从大数据集循环取 n 条记录（id 重新编号）。"""
    raw: list[dict] = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    records = []
    for i in range(n):
        r = raw[i % len(raw)]
        records.append({"id": i + 1, "text": r["text"], "category": r.get("category", "")})
    return records


def embed_all(texts: list[str]) -> list[list[float]]:
    from sentence_transformers import SentenceTransformer
    print(f"  加载模型 {EMBEDDING_MODEL} ...")
    model = SentenceTransformer(EMBEDDING_MODEL, cache_folder=str(MODEL_CACHE))
    t0 = time.perf_counter()
    vecs = model.encode(texts, batch_size=64, normalize_embeddings=True, show_progress_bar=True)
    elapsed = time.perf_counter() - t0
    print(f"  向量化 {len(texts)} 条  耗时 {elapsed:.2f}s  ({len(texts)/elapsed:.0f} 条/s)")
    return vecs.tolist()


# ─── 各库基准实现 ──────────────────────────────────────────────────────────────

def bench_qdrant(records: list[dict], vectors: list[list[float]], query_vectors: list[list[float]]) -> dict:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qm

    client = QdrantClient(host="localhost", port=6333)
    dim = len(vectors[0])

    # 清理旧测试集合
    if any(c.name == BENCH_COLLECTION for c in client.get_collections().collections):
        client.delete_collection(BENCH_COLLECTION)
    client.create_collection(
        BENCH_COLLECTION,
        vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
    )

    # 写入
    mem_before = _rss_mb()
    t0 = time.perf_counter()
    for i in range(0, len(records), BATCH):
        batch_r = records[i:i + BATCH]
        batch_v = vectors[i:i + BATCH]
        points = [
            qm.PointStruct(id=r["id"], vector=v, payload={"text": r["text"], "category": r["category"]})
            for r, v in zip(batch_r, batch_v)
        ]
        client.upsert(BENCH_COLLECTION, points=points, wait=True)
    insert_time = time.perf_counter() - t0
    mem_after = _rss_mb()

    # 查询
    t0 = time.perf_counter()
    for qv in query_vectors:
        client.search(BENCH_COLLECTION, query_vector=qv, limit=5, with_payload=False)
    query_time = time.perf_counter() - t0

    client.delete_collection(BENCH_COLLECTION)
    return {"insert": insert_time, "query": query_time, "mem_delta": mem_after - mem_before}


def bench_weaviate(records: list[dict], vectors: list[list[float]], query_vectors: list[list[float]]) -> dict:
    import weaviate
    from weaviate.classes.config import Configure, DataType, Property, VectorDistances
    from weaviate.classes.data import DataObject
    from weaviate.util import generate_uuid5

    client = weaviate.connect_to_local(host="localhost", port=8080, grpc_port=50051)
    try:
        col_name = "BenchmarkTest"
        if client.collections.exists(col_name):
            client.collections.delete(col_name)
        client.collections.create(
            name=col_name,
            properties=[
                Property(name="doc_id",   data_type=DataType.INT),
                Property(name="text",     data_type=DataType.TEXT),
                Property(name="category", data_type=DataType.TEXT),
            ],
            vectorizer_config=Configure.Vectorizer.none(),
            vector_index_config=Configure.VectorIndex.hnsw(distance_metric=VectorDistances.COSINE),
        )
        collection = client.collections.get(col_name)

        # 写入
        mem_before = _rss_mb()
        t0 = time.perf_counter()
        for i in range(0, len(records), BATCH):
            batch_r = records[i:i + BATCH]
            batch_v = vectors[i:i + BATCH]
            objects = [
                DataObject(
                    properties={"doc_id": r["id"], "text": r["text"], "category": r["category"]},
                    uuid=generate_uuid5(str(r["id"])),
                    vector=v,
                )
                for r, v in zip(batch_r, batch_v)
            ]
            collection.data.insert_many(objects)
        insert_time = time.perf_counter() - t0
        mem_after = _rss_mb()

        # 查询
        t0 = time.perf_counter()
        for qv in query_vectors:
            collection.query.near_vector(near_vector=qv, limit=5)
        query_time = time.perf_counter() - t0

        client.collections.delete(col_name)
    finally:
        client.close()

    return {"insert": insert_time, "query": query_time, "mem_delta": mem_after - mem_before}


def bench_milvus(records: list[dict], vectors: list[list[float]], query_vectors: list[list[float]]) -> dict:
    from pymilvus import DataType, MilvusClient

    client = MilvusClient(uri="http://localhost:19530")
    dim = len(vectors[0])

    if client.has_collection(BENCH_COLLECTION):
        client.drop_collection(BENCH_COLLECTION)

    schema = client.create_schema(auto_id=False, enable_dynamic_field=True)
    schema.add_field("id",     DataType.INT64,        is_primary=True)
    schema.add_field("vector", DataType.FLOAT_VECTOR, dim=dim)
    schema.add_field("text",   DataType.VARCHAR,      max_length=2048)

    idx = client.prepare_index_params()
    idx.add_index(field_name="vector", index_type="AUTOINDEX", metric_type="COSINE")
    client.create_collection(BENCH_COLLECTION, schema=schema, index_params=idx)

    # 写入
    mem_before = _rss_mb()
    t0 = time.perf_counter()
    for i in range(0, len(records), BATCH):
        batch_r = records[i:i + BATCH]
        batch_v = vectors[i:i + BATCH]
        rows = [{"id": r["id"], "vector": v, "text": r["text"], "category": r["category"]}
                for r, v in zip(batch_r, batch_v)]
        client.upsert(BENCH_COLLECTION, data=rows)
    client.flush(BENCH_COLLECTION)
    insert_time = time.perf_counter() - t0
    mem_after = _rss_mb()

    # 查询
    client.load_collection(BENCH_COLLECTION)
    t0 = time.perf_counter()
    for qv in query_vectors:
        client.search(BENCH_COLLECTION, data=[qv], limit=5,
                      search_params={"metric_type": "COSINE"})
    query_time = time.perf_counter() - t0

    client.drop_collection(BENCH_COLLECTION)
    return {"insert": insert_time, "query": query_time, "mem_delta": mem_after - mem_before}


# ─── 输出格式 ──────────────────────────────────────────────────────────────────

def print_result(name: str, r: dict, n_insert: int, n_query: int) -> None:
    ins_qps  = n_insert / r["insert"]
    q_avg_ms = r["query"] / n_query * 1000
    q_qps    = n_query / r["query"]
    mem      = r["mem_delta"]
    mem_str  = f"{mem:+.1f} MB" if mem == mem else "N/A (pip install psutil)"
    print(f"\n  ┌─ {name} ─────────────────────────────────")
    print(f"  │  写入 {n_insert} 条：{r['insert']:.2f}s  ({ins_qps:.0f} 条/s)")
    print(f"  │  查询 {n_query} 次：{r['query']:.2f}s  (avg {q_avg_ms:.1f}ms  {q_qps:.0f} QPS)")
    print(f"  │  内存增量：{mem_str}")
    print(f"  └────────────────────────────────────────")


# ─── 主流程 ────────────────────────────────────────────────────────────────────

TARGETS = {
    "qdrant":   bench_qdrant,
    "weaviate": bench_weaviate,
    "milvus":   bench_milvus,
}


def main() -> int:
    arg = sys.argv[1].lower() if len(sys.argv) > 1 else "all"
    targets = list(TARGETS.keys()) if arg == "all" else [arg]

    for t in targets:
        if t not in TARGETS:
            print(f"未知目标：{t}，可选：{', '.join(TARGETS)} 或 all")
            return 1

    print(f"\n{'='*50}")
    print(f"向量库性能基准测试")
    print(f"  写入：{N_INSERT} 条 | 批次：{BATCH} | 查询：{N_QUERY} 次 | top-5")
    print(f"  模型：{EMBEDDING_MODEL}")
    print(f"{'='*50}")

    print(f"\n[准备数据]")
    records = load_texts(N_INSERT)
    texts = [r["text"] for r in records]
    print(f"  已加载 {len(records)} 条记录")

    print(f"\n[向量化]")
    vectors = embed_all(texts)
    # 随机取 N_QUERY 条向量作为查询向量（循环取，不需要额外随机）
    query_vectors = [vectors[i % len(vectors)] for i in range(N_QUERY)]

    results: dict[str, dict] = {}
    for name in targets:
        print(f"\n[测试 {name.upper()}]")
        try:
            results[name] = TARGETS[name](records, vectors, query_vectors)
            print(f"  完成")
        except Exception as e:
            print(f"  失败：{e}")
            results[name] = None  # type: ignore

    print(f"\n{'='*50}")
    print(f"测试结果汇总")
    print(f"{'='*50}")
    for name, r in results.items():
        if r is None:
            print(f"\n  {name.upper()}：测试失败（数据库未启动？）")
        else:
            print_result(name.upper(), r, N_INSERT, N_QUERY)

    if not psutil:
        print("\n提示：安装 psutil 可获得内存统计：pip install psutil")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
