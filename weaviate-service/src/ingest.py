"""把 data/sample_*.json 里的文本编码后写入 Weaviate。

运行：
    python -m src.ingest                   # 用 .env 里配的数据文件
    python -m src.ingest ../my_data.json   # 或指定别的文件

说明：
    为了保证脚本可重复执行（入库语义清晰），本脚本每次会**先删除** COLLECTION_NAME
    指定的集合再新建。真实项目里通常用按 UUID 的 upsert 做增量更新，这里简化处理。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import weaviate
from weaviate.classes.config import Configure, DataType, Property
from weaviate.classes.data import DataObject
from weaviate.util import generate_uuid5

from .config import (
    COLLECTION_NAME,
    DATA_FILE,
    WEAVIATE_GRPC_PORT,
    WEAVIATE_HOST,
    WEAVIATE_HTTP_PORT,
)
from .embedder import embed, embedding_dim

_ROOT_DIR = Path(__file__).resolve().parents[2]
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from semantic_sandbox_common import add_documents, build_documents_from_rows, summarize_import_errors  # noqa: E402
from semantic_sandbox_postgres import close_pool, postgres_enabled  # noqa: E402


def load_data(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"数据文件不存在: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    for item in data:
        if "text" not in item:
            raise ValueError(f"每条记录必须包含 text 字段: {item}")
    return data


def recreate_collection(client: weaviate.WeaviateClient) -> None:
    if client.collections.exists(COLLECTION_NAME):
        print(f"[ingest] 删除旧集合 {COLLECTION_NAME}")
        client.collections.delete(COLLECTION_NAME)

    print(f"[ingest] 创建集合 {COLLECTION_NAME} (vectorizer=none, 距离=cosine)")
    client.collections.create(
        name=COLLECTION_NAME,
        properties=[
            Property(name="doc_id",   data_type=DataType.INT),
            Property(name="text",     data_type=DataType.TEXT),
            Property(name="category", data_type=DataType.TEXT),
        ],
        # 我们自己提供向量，关掉内置向量化
        vectorizer_config=Configure.Vectorizer.none(),
        vector_index_config=Configure.VectorIndex.hnsw(
            distance_metric=weaviate.classes.config.VectorDistances.COSINE,
        ),
    )


def ensure_collection(client: weaviate.WeaviateClient) -> None:
    if client.collections.exists(COLLECTION_NAME):
        print(f"[ingest] 复用已有集合 {COLLECTION_NAME}")
        return
    recreate_collection(client)


def insert_all(client: weaviate.WeaviateClient, records: list[dict]) -> None:
    texts = [r["text"] for r in records]
    vectors = embed(texts)

    objects = [
        DataObject(
            properties={"doc_id": r["id"], "text": r["text"], "category": r.get("category", "")},
            # 用 doc_id 生成稳定 UUID，方便幂等更新
            uuid=generate_uuid5(str(r["id"])),
            vector=vec,
        )
        for r, vec in zip(records, vectors)
    ]

    collection = client.collections.get(COLLECTION_NAME)
    result = collection.data.insert_many(objects)
    if result.has_errors:
        print(f"[ingest] 有 {len(result.errors)} 条写入失败:")
        for idx, err in result.errors.items():
            print(f"  #{idx}: {err.message}")
    print(f"[ingest] 写入 {len(objects) - len(result.errors)} 条 → {COLLECTION_NAME}")


def main() -> int:
    data_file = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DATA_FILE
    print(f"[ingest] 读取数据: {data_file}")
    raw_records = load_data(data_file)
    if postgres_enabled():
        records, existing, errors = build_documents_from_rows(
            raw_records,
            seed_files=[data_file],
            default_source="cli",
        )
        for message in summarize_import_errors(errors):
            print(f"[ingest] 跳过失败行: {message}")
        if existing:
            print(f"[ingest] 已存在 {len(existing)} 条，跳过向量写入")
        if not records:
            print("[ingest] 没有需要写入的新记录")
            close_pool()
            return 0
    else:
        records = raw_records

    dim = embedding_dim()
    print(f"[ingest] 连接 Weaviate {WEAVIATE_HOST}:{WEAVIATE_HTTP_PORT} / 向量维度={dim}")

    client = weaviate.connect_to_local(
        host=WEAVIATE_HOST,
        port=WEAVIATE_HTTP_PORT,
        grpc_port=WEAVIATE_GRPC_PORT,
    )
    try:
        ensure_collection(client)
        insert_all(client, records)
        add_documents(records)

        count = client.collections.get(COLLECTION_NAME).aggregate.over_all(total_count=True).total_count
        print(f"[ingest] 完成。集合中共有 {count} 条。")
    finally:
        client.close()
        close_pool()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
