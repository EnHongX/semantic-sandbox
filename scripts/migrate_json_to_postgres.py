"""Migrate legacy JSON metadata into PostgreSQL."""
from __future__ import annotations

import argparse
import json
import os
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

os.environ.setdefault("METADATA_STORE", "postgres")

from semantic_sandbox_common import make_document_id, normalize_text, parse_tags, text_hash, utc_now  # noqa: E402
from semantic_sandbox_postgres import close_pool, insert_document  # noqa: E402


def _load_rows(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("JSON 顶层必须是数组")
    return [item for item in data if isinstance(item, dict)]


def _normalize_row(row: dict) -> dict | None:
    text = normalize_text(str(row.get("text", "")))
    if not text:
        return None
    hash_value = str(row.get("text_hash") or text_hash(text))
    now = str(row.get("created_at") or utc_now())
    return {
        "document_id": str(row.get("document_id") or make_document_id(hash_value)),
        "text_hash": hash_value,
        "text": text,
        "category": str(row.get("category", "")),
        "tags": parse_tags(row.get("tags")),
        "source": str(row.get("source") or "migration"),
        "created_at": now,
        "updated_at": str(row.get("updated_at") or now),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input",
        default=str(ROOT_DIR / "data" / "documents.json"),
        help="legacy JSON metadata file",
    )
    args = parser.parse_args()

    source = Path(args.input).expanduser().resolve()
    rows = _load_rows(source)
    inserted = 0
    skipped = 0
    failed = 0
    for row in rows:
        try:
            record = _normalize_row(row)
            if record is None:
                failed += 1
                continue
            reason, _doc = insert_document(record)
            if reason == "inserted":
                inserted += 1
            else:
                skipped += 1
        except Exception as exc:
            failed += 1
            print(f"failed: {exc}")
    close_pool()

    print(f"migration completed: inserted={inserted}, skipped={skipped}, failed={failed}")


if __name__ == "__main__":
    main()
