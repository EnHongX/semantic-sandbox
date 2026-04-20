"""交互式语义检索。

运行：
    python -m src.search           # 进入交互模式
    python -m src.search "一句话"   # 单次查询
"""
from __future__ import annotations

import sys

import weaviate
from weaviate.classes.query import MetadataQuery

from .config import (
    COLLECTION_NAME,
    WEAVIATE_GRPC_PORT,
    WEAVIATE_HOST,
    WEAVIATE_HTTP_PORT,
)
from .embedder import embed

TOP_K = 5


def search(client: weaviate.WeaviateClient, query: str, top_k: int = TOP_K) -> None:
    [vector] = embed([query])
    collection = client.collections.get(COLLECTION_NAME)
    res = collection.query.near_vector(
        near_vector=vector,
        limit=top_k,
        return_metadata=MetadataQuery(distance=True),
    )
    if not res.objects:
        print("（没有结果，先跑 ingest 入库）")
        return

    print(f"\n查询: {query}")
    print("-" * 60)
    for i, obj in enumerate(res.objects, 1):
        distance = obj.metadata.distance if obj.metadata else None
        # cosine distance = 1 - cosine similarity；换算成相似度更直观
        similarity = 1 - distance if distance is not None else None
        props = obj.properties or {}
        doc_id = props.get("doc_id")
        text = props.get("text", "<无文本>")
        sim_str = f"sim={similarity:.4f}" if similarity is not None else "sim=?"
        print(f"{i}. {sim_str}  doc_id={doc_id}")
        print(f"   {text}\n")


def main() -> int:
    client = weaviate.connect_to_local(
        host=WEAVIATE_HOST,
        port=WEAVIATE_HTTP_PORT,
        grpc_port=WEAVIATE_GRPC_PORT,
    )
    try:
        if len(sys.argv) > 1:
            search(client, " ".join(sys.argv[1:]))
            return 0

        print(
            f"[search] 已连接 {WEAVIATE_HOST}:{WEAVIATE_HTTP_PORT} / 集合 {COLLECTION_NAME}"
        )
        print("输入查询内容，回车搜索；输入 q 或 Ctrl-C 退出。")
        while True:
            try:
                query = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not query:
                continue
            if query.lower() in {"q", "quit", "exit"}:
                break
            search(client, query)
    finally:
        client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
