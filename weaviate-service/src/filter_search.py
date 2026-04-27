"""向量检索 + 属性过滤。演示 Weaviate v4 "Filter + near_vector" 的组合用法。

运行：
    python -m src.filter_search                           # 交互模式
    python -m src.filter_search "database" technology    # 单次查询：文本 + 分类
    python -m src.filter_search "ocean" geography

Weaviate 过滤写法（v4）：
    filters=Filter.by_property("category").equal("technology")

注意：过滤发生在向量检索之前（pre-filter），只在满足条件的子集里做近邻搜索。
"""
from __future__ import annotations

import sys

import weaviate
from weaviate.classes.query import Filter, MetadataQuery

from .config import (
    COLLECTION_NAME,
    WEAVIATE_GRPC_PORT,
    WEAVIATE_HOST,
    WEAVIATE_HTTP_PORT,
)
from .embedder import embed

TOP_K = 5
CATEGORIES = ["geography", "technology", "science", "history", "food", "sports", "art", "nature"]


def filter_search(
    client: weaviate.WeaviateClient,
    query: str,
    category: str | None = None,
    top_k: int = TOP_K,
) -> None:
    [vector] = embed([query])

    collection = client.collections.get(COLLECTION_NAME)
    res = collection.query.near_vector(
        near_vector=vector,
        limit=top_k,
        return_metadata=MetadataQuery(distance=True),
        filters=Filter.by_property("category").equal(category) if category else None,
    )

    filter_str = f"category={category}" if category else "不限分类"
    print(f"\n查询: {query}  [{filter_str}]")
    print("-" * 60)
    if not res.objects:
        print("（没有结果。提示：数据需要含 category 字段，先用 sample_large_en.json 重新入库）")
        return

    for i, obj in enumerate(res.objects, 1):
        props = obj.properties or {}
        distance = obj.metadata.distance if obj.metadata else None
        score = round(1 - distance, 4) if distance is not None else "?"
        print(f"{i}. score={score}  category={props.get('category', '?')}  doc_id={props.get('doc_id', '?')}")
        print(f"   {props.get('text', '<无文本>')}\n")


def main() -> int:
    client = weaviate.connect_to_local(
        host=WEAVIATE_HOST,
        port=WEAVIATE_HTTP_PORT,
        grpc_port=WEAVIATE_GRPC_PORT,
    )
    try:
        if len(sys.argv) >= 2:
            query = sys.argv[1]
            category = sys.argv[2] if len(sys.argv) >= 3 else None
            filter_search(client, query, category)
            return 0

        print(f"[filter_search] 集合={COLLECTION_NAME}  可用分类: {', '.join(CATEGORIES)}")
        print("输入格式：<查询文本> [分类]（分类可省略）")
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
    finally:
        client.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
