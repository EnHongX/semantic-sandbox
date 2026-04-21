"""把 data/sample_*.json 里的文本编码后写入 Milvus。

运行：
    python -m src.ingest                   # 用 .env 里配的数据文件
    python -m src.ingest ../my_data.json   # 或指定别的文件
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pymilvus import DataType, MilvusClient

from .config import COLLECTION_NAME, DATA_FILE, MILVUS_URI
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


def existing_dim(client: MilvusClient) -> int | None:
    info = client.describe_collection(collection_name=COLLECTION_NAME)
    for field in info["fields"]:
        if field["type"] == DataType.FLOAT_VECTOR:
            return field["params"]["dim"]
    return None


def ensure_collection(client: MilvusClient, dim: int) -> None:
    if client.has_collection(COLLECTION_NAME):
        current_dim = existing_dim(client)
        if current_dim != dim:
            raise RuntimeError(
                f"集合 {COLLECTION_NAME} 已存在但维度={current_dim}，当前模型维度={dim}。\n"
                f"请先删除旧集合再重新入库：\n"
                f"    python -c \"from pymilvus import MilvusClient; "
                f"MilvusClient('{MILVUS_URI}').drop_collection('{COLLECTION_NAME}')\""
            )
        print(f"[ingest] 复用已有集合 {COLLECTION_NAME} (维度={current_dim})")
        return

    print(f"[ingest] 创建集合 {COLLECTION_NAME} (维度={dim}, 距离=COSINE)")

    schema = client.create_schema(auto_id=False, enable_dynamic_field=True)
    schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
    schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=dim)
    schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=2048)

    index_params = client.prepare_index_params()
    index_params.add_index(
        field_name="vector",
        index_type="AUTOINDEX",  # Milvus 自行选择合适索引，学习场景够用
        metric_type="COSINE",
    )

    client.create_collection(
        collection_name=COLLECTION_NAME,
        schema=schema,
        index_params=index_params,
    )


def upsert(client: MilvusClient, records: list[dict]) -> None:
    texts = [r["text"] for r in records]
    vectors = embed(texts)
    rows = [
        {
            "id": int(r["id"]),
            "vector": vec,
            "text": r["text"],
            # 透传其他字段（如 category），存入 dynamic field（$meta）
            **{k: v for k, v in r.items() if k not in {"id", "text"}},
        }
        for r, vec in zip(records, vectors)
    ]
    # upsert = 存在就覆盖，不存在就插入。重跑脚本不会产生重复数据。
    client.upsert(collection_name=COLLECTION_NAME, data=rows)
    client.flush(collection_name=COLLECTION_NAME)
    print(f"[ingest] 写入 {len(rows)} 条 → {COLLECTION_NAME}")


def main() -> int:
    data_file = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DATA_FILE
    print(f"[ingest] 读取数据: {data_file}")
    records = load_data(data_file)

    dim = embedding_dim()
    print(f"[ingest] 连接 Milvus {MILVUS_URI} / 向量维度={dim}")
    client = MilvusClient(uri=MILVUS_URI)

    ensure_collection(client, dim)
    upsert(client, records)

    stats = client.get_collection_stats(collection_name=COLLECTION_NAME)
    print(f"[ingest] 完成。集合中共有 {stats.get('row_count', '?')} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
