"""把文本变成向量。三个子项目里这个文件基本一致，方便对比其他部分的差异。"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Sequence

from sentence_transformers import SentenceTransformer

from .config import EMBEDDING_MODEL

# 模型缓存在 项目根/models/，跟着项目走，拷目录给别人也带着模型。
# 从 子项目/src/embedder.py 往上两层到项目根。
MODEL_CACHE = Path(__file__).resolve().parent.parent.parent / "models"
MODEL_CACHE.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_model() -> SentenceTransformer:
    print(f"[embedder] 加载模型: {EMBEDDING_MODEL}")
    print(f"[embedder] 缓存目录: {MODEL_CACHE}")
    return SentenceTransformer(EMBEDDING_MODEL, cache_folder=str(MODEL_CACHE))


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
