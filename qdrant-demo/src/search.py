"""交互式语义检索。

运行：
    python -m src.search           # 进入交互模式
    python -m src.search "一句话"   # 单次查询
"""
from __future__ import annotations

import sys

from qdrant_client import QdrantClient

from .config import COLLECTION_NAME, QDRANT_HOST, QDRANT_PORT
from .embedder import embed

TOP_K = 5


def search(client: QdrantClient, query: str, top_k: int = TOP_K) -> None:
    [vector] = embed([query])
    hits = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=vector,
        limit=top_k,
        with_payload=True,
    )
    if not hits:
        print("（没有结果，先跑 ingest 入库）")
        return

    print(f"\n查询: {query}")
    print("-" * 60)
    for i, hit in enumerate(hits, 1):
        text = (hit.payload or {}).get("text", "<无文本>")
        print(f"{i}. score={hit.score:.4f}  id={hit.id}")
        print(f"   {text}\n")


def main() -> int:
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    if len(sys.argv) > 1:
        search(client, " ".join(sys.argv[1:]))
        return 0

    print(f"[search] 已连接 {QDRANT_HOST}:{QDRANT_PORT} / 集合 {COLLECTION_NAME}")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
