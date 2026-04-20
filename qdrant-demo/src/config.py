"""集中读取 .env，其他模块都从这里拿配置。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")

EMBEDDING_MODEL: str = os.environ.get(
    "EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
QDRANT_HOST: str = os.environ.get("QDRANT_HOST", "localhost")
QDRANT_PORT: int = int(os.environ.get("QDRANT_PORT", "6333"))
COLLECTION_NAME: str = os.environ.get("COLLECTION_NAME", "sandbox_docs")

_default_data = PROJECT_DIR.parent / "data" / "sample_en.json"
DATA_FILE: Path = Path(os.environ.get("DATA_FILE", str(_default_data)))
if not DATA_FILE.is_absolute():
    DATA_FILE = (PROJECT_DIR / DATA_FILE).resolve()
