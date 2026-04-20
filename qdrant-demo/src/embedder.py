"""把文本变成向量。三个子项目里这个文件基本一致，方便对比其他部分的差异。"""
from __future__ import annotations

from functools import lru_cache
from typing import Sequence

from sentence_transformers import SentenceTransformer

from .config import EMBEDDING_MODEL


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    print(f"[embedder] 加载模型: {EMBEDDING_MODEL}")
    return SentenceTransformer(EMBEDDING_MODEL)


def embed(texts: Sequence[str]) -> list[list[float]]:
    model = get_model()
    vectors = model.encode(
        list(texts),
        normalize_embeddings=True,  # 归一化后可以用内积当余弦相似度，效率更高
        show_progress_bar=False,
    )
    return vectors.tolist()


def embedding_dim() -> int:
    return get_model().get_sentence_embedding_dimension()
