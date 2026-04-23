"""把文本变成向量。三个子项目里这个文件基本一致，方便对比其他部分的差异。"""
from __future__ import annotations

from functools import lru_cache
import os
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

from .config import EMBEDDING_MODEL

_FALSE_VALUES = {"0", "false", "no", "off"}
LOCAL_ONLY = os.environ.get("EMBEDDING_LOCAL_ONLY", "1").strip().lower() not in _FALSE_VALUES
if LOCAL_ONLY:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# 模型缓存在 项目根/models/，跟着项目走，拷目录给别人也带着模型。
# 从 子项目/src/embedder.py 往上两层到项目根。
MODEL_CACHE = Path(__file__).resolve().parent.parent.parent / "models"
MODEL_CACHE.mkdir(parents=True, exist_ok=True)


def _latest_snapshot(repo_cache: Path) -> Path | None:
    snapshots_dir = repo_cache / "snapshots"
    if not snapshots_dir.exists():
        return None
    snapshots = [p for p in snapshots_dir.iterdir() if p.is_dir()]
    if not snapshots:
        return None
    return max(snapshots, key=lambda p: p.stat().st_mtime)


def _resolve_model_source() -> str:
    configured = Path(EMBEDDING_MODEL).expanduser()
    candidates = [configured] if configured.is_absolute() else [
        Path.cwd() / configured,
        MODEL_CACHE / configured,
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    repo_cache = MODEL_CACHE / f"models--{EMBEDDING_MODEL.replace('/', '--')}"
    snapshot = _latest_snapshot(repo_cache)
    if snapshot is not None:
        return str(snapshot)
    return EMBEDDING_MODEL


def model_status() -> dict:
    source = _resolve_model_source()
    status = {
        "model": EMBEDDING_MODEL,
        "source": source,
        "cache_dir": str(MODEL_CACHE),
        "local_only": LOCAL_ONLY,
        "source_exists": Path(source).exists(),
    }
    try:
        status["dimension"] = embedding_dim()
        status["loaded"] = True
    except Exception as exc:  # noqa: BLE001
        status["loaded"] = False
        status["error"] = str(exc)
    return status


@lru_cache(maxsize=1)
def get_model() -> "SentenceTransformer":
    from sentence_transformers import SentenceTransformer

    source = _resolve_model_source()
    print(f"[embedder] 加载模型: {source}")
    print(f"[embedder] 缓存目录: {MODEL_CACHE}")
    try:
        return SentenceTransformer(
            source,
            cache_folder=str(MODEL_CACHE),
            local_files_only=LOCAL_ONLY,
        )
    except Exception as exc:
        if LOCAL_ONLY:
            raise RuntimeError(
                f"本地模型不可用: {EMBEDDING_MODEL}。请确认模型已放到 {MODEL_CACHE}，"
                "或先执行 `python scripts/preload_model.py` 下载；如确需联网加载，设置 EMBEDDING_LOCAL_ONLY=0。"
            ) from exc
        raise


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
