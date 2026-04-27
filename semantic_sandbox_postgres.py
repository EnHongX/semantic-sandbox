"""PostgreSQL-backed metadata store for the semantic search service."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT_DIR = Path(__file__).resolve().parent
SCHEMA_FILE = ROOT_DIR / "db" / "schema.sql"

_POOL = None
_SCHEMA_READY = False


def postgres_enabled() -> bool:
    return os.environ.get("METADATA_STORE", "json").strip().lower() == "postgres"


def current_vector_backend(default: str = "qdrant") -> str:
    return os.environ.get("VECTOR_BACKEND", default).strip().lower() or default


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("METADATA_STORE=postgres 时必须配置 DATABASE_URL")
    return url.replace("postgresql+psycopg://", "postgresql://", 1)


def _pool_size() -> int:
    return max(int(os.environ.get("DB_POOL_SIZE", "5")), 1)


def _max_pool_size() -> int:
    return _pool_size() + max(int(os.environ.get("DB_MAX_OVERFLOW", "10")), 0)


def _statement_timeout_ms() -> int:
    return max(int(os.environ.get("DB_STATEMENT_TIMEOUT_MS", "5000")), 0)


def _configure_connection(conn) -> None:
    timeout = _statement_timeout_ms()
    if timeout:
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {timeout}")
        conn.commit()


def _get_pool():
    global _POOL
    if _POOL is None:
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as exc:
            raise RuntimeError("PostgreSQL 存储需要安装 psycopg[binary,pool]") from exc

        _POOL = ConnectionPool(
            conninfo=_database_url(),
            min_size=1,
            max_size=_max_pool_size(),
            timeout=float(os.environ.get("DB_POOL_TIMEOUT", "30")),
            configure=_configure_connection,
            open=True,
        )
    return _POOL


def close_pool() -> None:
    global _POOL, _SCHEMA_READY
    if _POOL is not None:
        _POOL.close()
    _POOL = None
    _SCHEMA_READY = False


def _dict_row():
    try:
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError("PostgreSQL 存储需要安装 psycopg[binary,pool]") from exc
    return dict_row


def ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    schema_sql = SCHEMA_FILE.read_text(encoding="utf-8")
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(schema_sql)
        conn.commit()
    _SCHEMA_READY = True


def check_connection() -> dict:
    ensure_schema()
    with _get_pool().connection() as conn:
        with conn.cursor(row_factory=_dict_row()) as cur:
            cur.execute("SELECT current_database() AS database, version() AS version")
            row = cur.fetchone()
    return {"ok": True, "database": row["database"], "version": row["version"] if row else ""}


def _iso(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")
    return str(value)


def _doc_from_row(row: dict[str, Any]) -> dict:
    return {
        "id": int(row.get("id") or 0),
        "document_id": str(row.get("document_id") or ""),
        "text_hash": str(row.get("text_hash") or ""),
        "text": str(row.get("text") or ""),
        "category": str(row.get("category") or ""),
        "tags": list(row.get("tags") or []),
        "source": str(row.get("source") or ""),
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
    }


def _json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def load_documents() -> list[dict]:
    ensure_schema()
    with _get_pool().connection() as conn:
        with conn.cursor(row_factory=_dict_row()) as cur:
            cur.execute("SELECT * FROM documents ORDER BY id ASC")
            return [_doc_from_row(row) for row in cur.fetchall()]


def list_documents(offset: int = 0, limit: int = 50) -> tuple[list[dict], int]:
    ensure_schema()
    with _get_pool().connection() as conn:
        with conn.cursor(row_factory=_dict_row()) as cur:
            cur.execute("SELECT COUNT(*) AS total FROM documents")
            total = int(cur.fetchone()["total"])
            cur.execute(
                "SELECT * FROM documents ORDER BY id ASC OFFSET %s LIMIT %s",
                (max(offset, 0), min(max(limit, 1), 500)),
            )
            return [_doc_from_row(row) for row in cur.fetchall()], total


def get_document(record_id: int) -> dict | None:
    ensure_schema()
    with _get_pool().connection() as conn:
        with conn.cursor(row_factory=_dict_row()) as cur:
            cur.execute("SELECT * FROM documents WHERE id = %s", (record_id,))
            row = cur.fetchone()
    return _doc_from_row(row) if row else None


def get_documents_by_ids(record_ids: Iterable[int]) -> list[dict]:
    ids = [int(item) for item in record_ids if int(item) > 0]
    if not ids:
        return []
    ensure_schema()
    with _get_pool().connection() as conn:
        with conn.cursor(row_factory=_dict_row()) as cur:
            cur.execute("SELECT * FROM documents WHERE id = ANY(%s) ORDER BY id ASC", (ids,))
            return [_doc_from_row(row) for row in cur.fetchall()]


def insert_document(record: dict, *, vector_backend: str | None = None) -> tuple[str, dict]:
    ensure_schema()
    backend = vector_backend or current_vector_backend()
    params = {
        "document_id": str(record["document_id"]),
        "text_hash": str(record["text_hash"]),
        "text": str(record["text"]),
        "category": str(record.get("category", "")),
        "tags": list(record.get("tags") or []),
        "source": str(record.get("source") or "api"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
    }
    with _get_pool().connection() as conn:
        with conn.cursor(row_factory=_dict_row()) as cur:
            cur.execute(
                """
                INSERT INTO documents (
                    document_id, text_hash, text, category, tags, source, created_at, updated_at
                )
                VALUES (
                    %(document_id)s, %(text_hash)s, %(text)s, %(category)s, %(tags)s, %(source)s,
                    COALESCE(%(created_at)s::timestamptz, now()),
                    COALESCE(%(updated_at)s::timestamptz, now())
                )
                ON CONFLICT DO NOTHING
                RETURNING *
                """,
                params,
            )
            row = cur.fetchone()
            if row:
                _set_vector_status(cur, str(row["document_id"]), backend, status="pending")
                conn.commit()
                return "inserted", _doc_from_row(row)

            cur.execute("SELECT * FROM documents WHERE document_id = %s", (params["document_id"],))
            existing = cur.fetchone()
            if existing:
                doc = _doc_from_row(existing)
                if doc["text_hash"] != params["text_hash"]:
                    raise ValueError(f"document_id 已存在但文本不同: {params['document_id']}")
                if _needs_indexing(cur, doc["document_id"], backend):
                    _set_vector_status(cur, doc["document_id"], backend, status="pending")
                    conn.commit()
                    return "inserted", doc
                conn.commit()
                return "document_id", doc

            cur.execute("SELECT * FROM documents WHERE text_hash = %s", (params["text_hash"],))
            existing = cur.fetchone()
            if existing:
                doc = _doc_from_row(existing)
                if _needs_indexing(cur, doc["document_id"], backend):
                    _set_vector_status(cur, doc["document_id"], backend, status="pending")
                    conn.commit()
                    return "inserted", doc
                conn.commit()
                return "text_hash", doc

            raise RuntimeError("文档写入失败且未找到冲突记录")


def replace_documents(docs: list[dict]) -> None:
    ensure_schema()
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE documents RESTART IDENTITY CASCADE")
            for doc in sorted(docs, key=lambda item: int(item.get("id", 0))):
                cur.execute(
                    """
                    INSERT INTO documents (
                        id, document_id, text_hash, text, category, tags, source, created_at, updated_at
                    )
                    VALUES (
                        %(id)s, %(document_id)s, %(text_hash)s, %(text)s, %(category)s, %(tags)s,
                        %(source)s, %(created_at)s::timestamptz, %(updated_at)s::timestamptz
                    )
                    ON CONFLICT (id) DO UPDATE SET
                        document_id = EXCLUDED.document_id,
                        text_hash = EXCLUDED.text_hash,
                        text = EXCLUDED.text,
                        category = EXCLUDED.category,
                        tags = EXCLUDED.tags,
                        source = EXCLUDED.source,
                        created_at = EXCLUDED.created_at,
                        updated_at = EXCLUDED.updated_at
                    """,
                    {
                        "id": int(doc["id"]),
                        "document_id": str(doc["document_id"]),
                        "text_hash": str(doc["text_hash"]),
                        "text": str(doc["text"]),
                        "category": str(doc.get("category", "")),
                        "tags": list(doc.get("tags") or []),
                        "source": str(doc.get("source") or "api"),
                        "created_at": doc.get("created_at"),
                        "updated_at": doc.get("updated_at"),
                    },
                )
            cur.execute(
                """
                SELECT setval(
                    pg_get_serial_sequence('documents', 'id'),
                    GREATEST(COALESCE((SELECT MAX(id) FROM documents), 0), 1),
                    COALESCE((SELECT MAX(id) FROM documents), 0) > 0
                )
                """
            )
        conn.commit()


def _set_vector_status(cur, document_id: str, backend: str, *, status: str, error: str | None = None) -> None:
    cur.execute(
        """
        INSERT INTO vector_sync_states (
            document_id, vector_backend, status, last_error, indexed_at, updated_at
        )
        VALUES (
            %s, %s, %s, %s,
            CASE WHEN %s = 'indexed' THEN now() ELSE NULL END,
            now()
        )
        ON CONFLICT (document_id, vector_backend) DO UPDATE SET
            status = EXCLUDED.status,
            last_error = EXCLUDED.last_error,
            indexed_at = CASE WHEN EXCLUDED.status = 'indexed' THEN now() ELSE vector_sync_states.indexed_at END,
            updated_at = now()
        """,
        (document_id, backend, status, error, status),
    )


def _needs_indexing(cur, document_id: str, backend: str) -> bool:
    cur.execute(
        """
        SELECT status
        FROM vector_sync_states
        WHERE document_id = %s AND vector_backend = %s
        """,
        (document_id, backend),
    )
    row = cur.fetchone()
    return row is None or str(row["status"]) != "indexed"


def mark_documents_indexed(records: list[dict], *, vector_backend: str | None = None) -> None:
    if not records:
        return
    ensure_schema()
    backend = vector_backend or current_vector_backend()
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            for record in records:
                _set_vector_status(cur, str(record["document_id"]), backend, status="indexed")
        conn.commit()


def update_document(record_id: int, changes: dict) -> dict:
    ensure_schema()
    with _get_pool().connection() as conn:
        with conn.cursor(row_factory=_dict_row()) as cur:
            cur.execute("SELECT * FROM documents WHERE id = %s", (record_id,))
            current = cur.fetchone()
            if current is None:
                raise KeyError(f"文档不存在: {record_id}")

            text = str(changes.get("text", current["text"])).strip()
            if not text:
                raise ValueError("text 不能为空")
            text_hash = str(changes["text_hash"])
            cur.execute(
                "SELECT id FROM documents WHERE text_hash = %s AND id <> %s",
                (text_hash, record_id),
            )
            if cur.fetchone():
                raise ValueError("已有相同文本，不能更新为重复内容")

            cur.execute(
                """
                UPDATE documents
                SET document_id = %s,
                    text_hash = %s,
                    text = %s,
                    category = %s,
                    tags = %s,
                    source = %s,
                    updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (
                    str(changes["document_id"]),
                    text_hash,
                    text,
                    str(changes.get("category", "")),
                    list(changes.get("tags") or []),
                    str(changes.get("source") or "api"),
                    record_id,
                ),
            )
            row = cur.fetchone()
            _set_vector_status(cur, str(row["document_id"]), current_vector_backend(), status="pending")
        conn.commit()
    return _doc_from_row(row)


def delete_documents(record_ids: Iterable[int]) -> int:
    ids = [int(item) for item in record_ids if int(item) > 0]
    if not ids:
        return 0
    ensure_schema()
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM documents WHERE id = ANY(%s)", (ids,))
            deleted = cur.rowcount
        conn.commit()
    return int(deleted)


def delete_document(record_id: int) -> bool:
    return delete_documents([record_id]) > 0


def clear_documents() -> None:
    ensure_schema()
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE TABLE documents RESTART IDENTITY CASCADE")
        conn.commit()


def save_search_log(entry: dict) -> None:
    ensure_schema()
    payload = {"ts": _iso(datetime.now(timezone.utc)), **entry}
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO search_logs (backend, query, payload, created_at)
                VALUES (%s, %s, %s::jsonb, now())
                """,
                (
                    str(entry.get("backend", "")),
                    str(entry.get("query", "")),
                    _json_value(payload),
                ),
            )
        conn.commit()


def save_error_log(entry: dict) -> None:
    ensure_schema()
    payload = {"ts": _iso(datetime.now(timezone.utc)), **entry}
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_errors (backend, operation, surface, error, payload, created_at)
                VALUES (%s, %s, %s, %s, %s::jsonb, now())
                """,
                (
                    str(entry.get("backend", "")),
                    str(entry.get("operation", "")),
                    str(entry.get("surface", "")),
                    str(entry.get("error", "")),
                    _json_value(payload),
                ),
            )
        conn.commit()


def recent_errors(limit: int = 10) -> list[dict]:
    ensure_schema()
    with _get_pool().connection() as conn:
        with conn.cursor(row_factory=_dict_row()) as cur:
            cur.execute(
                "SELECT payload FROM app_errors ORDER BY created_at DESC LIMIT %s",
                (min(max(limit, 1), 100),),
            )
            rows = cur.fetchall()
    return [dict(row["payload"]) for row in rows]


def save_import_job(summary: dict, errors: list[dict]) -> None:
    ensure_schema()
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO import_jobs (
                    job_id, source_filename, status, inserted, existing_count, skipped, failed,
                    failed_rows_download_url, summary, errors, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::timestamptz)
                ON CONFLICT (job_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    inserted = EXCLUDED.inserted,
                    existing_count = EXCLUDED.existing_count,
                    skipped = EXCLUDED.skipped,
                    failed = EXCLUDED.failed,
                    failed_rows_download_url = EXCLUDED.failed_rows_download_url,
                    summary = EXCLUDED.summary,
                    errors = EXCLUDED.errors
                """,
                (
                    str(summary["job_id"]),
                    str(summary.get("source_filename", "")),
                    str(summary.get("status", "")),
                    int(summary.get("inserted", 0)),
                    int(summary.get("existing_count", 0)),
                    int(summary.get("skipped", 0)),
                    int(summary.get("failed", 0)),
                    summary.get("failed_rows_download_url"),
                    _json_value(summary),
                    _json_value(errors),
                    summary.get("created_at"),
                ),
            )
        conn.commit()


def load_import_job(job_id: str) -> dict | None:
    ensure_schema()
    with _get_pool().connection() as conn:
        with conn.cursor(row_factory=_dict_row()) as cur:
            cur.execute("SELECT summary FROM import_jobs WHERE job_id = %s", (job_id,))
            row = cur.fetchone()
    return dict(row["summary"]) if row else None
