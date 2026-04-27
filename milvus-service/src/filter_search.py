"""向量检索 + 标量字段过滤。演示 Milvus "filter + search" 的组合用法。

运行：
    python -m src.filter_search                           # 交互模式
    python -m src.filter_search "database" technology    # 单次查询：文本 + 分类
    python -m src.filter_search "ocean" geography

Milvus 过滤写法：
    filter='category == "technology"'    # 标量表达式字符串

说明：
- category 存在 dynamic field（$meta）中，因为 enable_dynamic_field=True
- 过滤与向量检索同时进行（Milvus 内部做 filtered ANN），结果已满足过滤条件
"""
from __future__ import annotations

import sys

from pymilvus import MilvusClient

from .config import COLLECTION_NAME, MILVUS_URI
from .embedder import embed

TOP_K = 5
CATEGORIES = ["geography", "technology", "science", "history", "food", "sports", "art", "nature"]


def filter_search(
    client: MilvusClient,
    query: str,
    category: str | None = None,
    top_k: int = TOP_K,
) -> None:
    [vector] = embed([query])

    search_kwargs: dict = dict(
        collection_name=COLLECTION_NAME,
        data=[vector],
        limit=top_k,
        output_fields=["text", "category"],
        search_params={"metric_type": "COSINE"},
    )
    if category:
        search_kwargs["filter"] = f'category == "{category}"'

    results_raw = client.search(**search_kwargs)
    hits = results_raw[0] if results_raw else []

    filter_str = f"category={category}" if category else "不限分类"
    print(f"\n查询: {query}  [{filter_str}]")
    print("-" * 60)
    if not hits:
        print("（没有结果。提示：数据需要含 category 字段，先用 sample_large_en.json 重新入库）")
        return

    for i, hit in enumerate(hits, 1):
        entity = hit.get("entity", {})
        score = round(float(hit.get("distance", 0)), 4)
        print(f"{i}. score={score}  category={entity.get('category', '?')}  id={hit['id']}")
        print(f"   {entity.get('text', '<无文本>')}\n")


def main() -> int:
    client = MilvusClient(uri=MILVUS_URI)
    client.load_collection(collection_name=COLLECTION_NAME)

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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
