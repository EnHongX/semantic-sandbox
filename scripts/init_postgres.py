"""Initialize the PostgreSQL schema used by the semantic search service."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency is installed in service envs
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv(ROOT_DIR / ".env")
    load_dotenv(Path.cwd() / ".env", override=True)

from semantic_sandbox_postgres import check_connection, close_pool, ensure_schema  # noqa: E402


def main() -> None:
    try:
        ensure_schema()
        info = check_connection()
        print(f"PostgreSQL schema is ready: {info['database']}")
    finally:
        close_pool()


if __name__ == "__main__":
    main()
