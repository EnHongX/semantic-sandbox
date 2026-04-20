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


def load_data(path: Path) -> list[dict]:
    if not path.exists():
        raise FileNotFoundError(f"数据文件不存在: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    for item in data:
        if "id" not in item or "text" not in item:
            raise ValueError(f"每条记录必须包含 id 和 text 字段: {item}")
    return data


def recreate_collection(client: weaviate.WeaviateClient) -> None:
    if client.collections.exists(COLLECTION_NAME):
        print(f"[ingest] 删除旧集合 {COLLECTION_NAME}")
        client.collections.delete(COLLECTION_NAME)

    print(f"[ingest] 创建集合 {COLLECTION_NAME} (vectorizer=none, 距离=cosine)")
    client.collections.create(
        name=COLLECTION_NAME,
        properties=[
            Property(name="doc_id", data_type=DataType.INT),
            Property(name="text", data_type=DataType.TEXT),
        ],
        # 我们自己提供向量，关掉内置向量化
        vectorizer_config=Configure.Vectorizer.none(),
        vector_index_config=Configure.VectorIndex.hnsw(
            distance_metric=weaviate.classes.config.VectorDistances.COSINE,
        ),
    )


def insert_all(client: weaviate.WeaviateClient, records: list[dict]) -> None:
    texts = [r["text"] for r in records]
    vectors = embed(texts)

    objects = [
        DataObject(
            properties={"doc_id": r["id"], "text": r["text"]},
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
    records = load_data(data_file)

    dim = embedding_dim()
    print(f"[ingest] 连接 Weaviate {WEAVIATE_HOST}:{WEAVIATE_HTTP_PORT} / 向量维度={dim}")

    client = weaviate.connect_to_local(
        host=WEAVIATE_HOST,
        port=WEAVIATE_HTTP_PORT,
        grpc_port=WEAVIATE_GRPC_PORT,
    )
    try:
        recreate_collection(client)
        insert_all(client, records)

        count = client.collections.get(COLLECTION_NAME).aggregate.over_all(total_count=True).total_count
        print(f"[ingest] 完成。集合中共有 {count} 条。")
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
