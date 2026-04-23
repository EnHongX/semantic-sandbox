"""
预下载两个嵌入模型到本地缓存，避免第一次跑 demo 时卡在下载。

用法：
    pip install sentence-transformers python-dotenv
    python scripts/preload_model.py

模型会被缓存到项目根目录 ./models/，三个子项目共用同一份缓存。
服务运行时默认只读 ./models/，不会再访问 HuggingFace。

国内用户如果下载慢/失败，先设置 HuggingFace 镜像再运行：
    export HF_ENDPOINT=https://hf-mirror.com
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

# 从项目根目录的 .env 读取配置（如果存在）
ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

# 模型下载到 项目根/models/，三个子项目共用这一份缓存。
# 这样模型就"跟着项目走"，不会散落到 ~/.cache 里。
MODEL_CACHE = ROOT / "models"
MODEL_CACHE.mkdir(parents=True, exist_ok=True)

MODELS = [
    "sentence-transformers/all-MiniLM-L6-v2",  # 英文/多语言, 384 维
    "BAAI/bge-small-zh-v1.5",                   # 中文, 512 维
]


def main() -> int:
    hf_endpoint = os.environ.get("HF_ENDPOINT")
    print(f"[info] 模型缓存目录: {MODEL_CACHE}")
    if hf_endpoint:
        print(f"[info] HF_ENDPOINT={hf_endpoint} (使用镜像)")
    else:
        print("[info] 使用官方 HuggingFace 站点；国内网络慢可先 export HF_ENDPOINT=https://hf-mirror.com")
    print("[info] 下载来源: HuggingFace Hub（或 HF_ENDPOINT 指定的镜像）")
    print("[info] 下载目标: 项目根目录 ./models/")
    print(f"[info] 将下载 {len(MODELS)} 个模型，合计约 185MB: {', '.join(MODELS)}\n")

    for name in MODELS:
        print(f"[下载] {name}")
        try:
            model = SentenceTransformer(name, cache_folder=str(MODEL_CACHE))
            dim = model.get_sentence_embedding_dimension()
            print(f"[完成] {name}  维度={dim}\n")
        except Exception as exc:  # noqa: BLE001
            print(f"[失败] {name}: {exc}\n", file=sys.stderr)
            return 1

    print(f"全部就绪。模型已保存到 {MODEL_CACHE}，后续子项目直接加载，无需联网。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
