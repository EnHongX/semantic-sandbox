"""交互式语义检索。

运行：
    python -m src.search           # 进入交互模式
    python -m src.search "一句话"   # 单次查询
"""
from __future__ import annotations

import sys

from pymilvus import MilvusClient

from .config import COLLECTION_NAME, MILVUS_URI
from .embedder import embed

TOP_K = 5


def search(client: MilvusClient, query: str, top_k: int = TOP_K) -> None:
    [vector] = embed([query])
    # Milvus 用 COSINE 指标时，返回的 "distance" 实际上是相似度（范围约 -1 ~ 1，越大越像）
    results = client.search(
        collection_name=COLLECTION_NAME,
        data=[vector],
        limit=top_k,
        output_fields=["text"],
        search_params={"metric_type": "COSINE"},
    )
    hits = results[0] if results else []
    if not hits:
        print("（没有结果，先跑 ingest 入库）")
        return

    print(f"\n查询: {query}")
    print("-" * 60)
    for i, hit in enumerate(hits, 1):
        text = hit.get("entity", {}).get("text", "<无文本>")
        score = hit.get("distance")
        print(f"{i}. score={score:.4f}  id={hit['id']}")
        print(f"   {text}\n")


def main() -> int:
    client = MilvusClient(uri=MILVUS_URI)
    # search 前需要确保集合已加载到内存（Milvus 特有）
    client.load_collection(collection_name=COLLECTION_NAME)

    if len(sys.argv) > 1:
        search(client, " ".join(sys.argv[1:]))
        return 0

    print(f"[search] 已连接 {MILVUS_URI} / 集合 {COLLECTION_NAME}")
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
