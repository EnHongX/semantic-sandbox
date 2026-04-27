"""向量检索 + payload 字段过滤。演示 Qdrant "先过滤、再向量检索" 的组合用法。

运行：
    python -m src.filter_search                           # 交互模式
    python -m src.filter_search "database" technology    # 单次查询：文本 + 分类
    python -m src.filter_search "ocean" geography        # 只在地理分类里搜

Qdrant 过滤写法：
    query_filter=qm.Filter(
        must=[qm.FieldCondition(key="category", match=qm.MatchValue(value="technology"))]
    )
"""
from __future__ import annotations

import sys

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from .config import COLLECTION_NAME, QDRANT_HOST, QDRANT_PORT
from .embedder import embed

TOP_K = 5
CATEGORIES = ["geography", "technology", "science", "history", "food", "sports", "art", "nature"]


def filter_search(
    client: QdrantClient,
    query: str,
    category: str | None = None,
    top_k: int = TOP_K,
) -> None:
    [vector] = embed([query])

    # 有 category 时加过滤条件；不传则退化为普通向量检索
    query_filter = None
    if category:
        query_filter = qm.Filter(
            must=[
                qm.FieldCondition(
                    key="category",
                    match=qm.MatchValue(value=category),
                )
            ]
        )

    hits = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=vector,
        query_filter=query_filter,
        limit=top_k,
        with_payload=True,
    )

    filter_str = f"category={category}" if category else "不限分类"
    print(f"\n查询: {query}  [{filter_str}]")
    print("-" * 60)
    if not hits:
        print("（没有结果。提示：数据需要含 category 字段，先用 sample_large_en.json 重新入库）")
        return

    for i, hit in enumerate(hits, 1):
        payload = hit.payload or {}
        print(f"{i}. score={hit.score:.4f}  category={payload.get('category', '?')}  id={hit.id}")
        print(f"   {payload.get('text', '<无文本>')}\n")


def main() -> int:
    client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)

    if len(sys.argv) >= 2:
        query = sys.argv[1]
        category = sys.argv[2] if len(sys.argv) >= 3 else None
        filter_search(client, query, category)
        return 0

    print(f"[filter_search] 集合={COLLECTION_NAME}  可用分类: {', '.join(CATEGORIES)}")
    print("输入格式：<查询文本> [分类]（分类可省略，省略则不过滤）")
    print("示例：database technology    ocean geography    q 退出")

    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line or line.lower() in {"q", "quit", "exit"}:
            break
        parts = line.rsplit(" ", 1)
        if len(parts) == 2 and parts[1].lower() in CATEGORIES:
            query, category = parts[0], parts[1].lower()
        else:
            query, category = line, None
        filter_search(client, query, category)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
