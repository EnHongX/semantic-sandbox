"""把 data/sample_*.json 里的文本编码后写入 Qdrant。

运行：
    python -m src.ingest                   # 用 .env 里配的数据文件
    python -m src.ingest ../my_data.json   # 或指定别的文件

数据文件格式（数组，元素至少包含 id 和 text）：
    [{"id": 1, "text": "..."}, ...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from .config import COLLECTION_NAME, DATA_FILE, QDRANT_HOST, QDRANT_PORT
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


def ensure_collection(client: QdrantClient, dim: int) -> None:
    """集合不存在就建；存在但维度不对就报错提示用户重建。"""
    existing = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME not in existing:
        print(f"[ingest] 创建集合 {COLLECTION_NAME} (维度={dim}, 距离=cosine)")
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
        )
        return

    info = client.get_collection(COLLECTION_NAME)
    current_dim = info.config.params.vectors.size
    if current_dim != dim:
        raise RuntimeError(
            f"集合 {COLLECTION_NAME} 已存在但维度={current_dim}，当前模型维度={dim}。\n"
            f"请先删除旧集合再重新入库：\n"
            f"    curl -X DELETE http://{QDRANT_HOST}:{QDRANT_PORT}/collections/{COLLECTION_NAME}\n"
            f"或在 Python 里执行： client.delete_collection('{COLLECTION_NAME}')"
        )
    print(f"[ingest] 复用已有集合 {COLLECTION_NAME} (维度={current_dim})")


def upsert(client: QdrantClient, records: list[dict]) -> None:
    texts = [r["text"] for r in records]
    vectors = embed(texts)
    points = [
        qm.PointStruct(id=r["id"], vector=vec, payload={"text": r["text"], **{k: v for k, v in r.items() if k not in {"id", "text"}}})
        for r, vec in zip(records, vectors)
    ]
    client.upsert(collection_name=COLLECTION_NAME, points=points, wait=True)
    print(f"[ingest] 写入 {len(points)} 条 → {COLLECTION_NAME}")


def main() -> int:
    data_file = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else DATA_FILE
    print(f"[ingest] 读取数据: {data_file}")
    records = load_data(data_file)

    dim = embedding_dim()
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    ensure_collection(client, dim)
    upsert(client, records)

    count = client.count(COLLECTION_NAME, exact=True).count
    print(f"[ingest] 完成。集合中共有 {count} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
