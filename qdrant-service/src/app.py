"""Web UI + REST API for Qdrant service.

启动：
    uvicorn src.app:app --reload --port 8888

访问：
    http://localhost:8888          搜索页面
    http://localhost:8888/ingest   写入页面
    http://localhost:8888/docs     Swagger API 文档
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from .config import COLLECTION_NAME, DATA_FILE, QDRANT_HOST, QDRANT_PORT
from .embedder import embed, embedding_dim, model_status
from .ingest import ensure_collection, upsert

# ─── 初始化 ────────────────────────────────────────────────────────────────────

_PROJECT_DIR = Path(__file__).resolve().parent.parent
_TEMPLATES_DIR = _PROJECT_DIR / "templates"
_ROOT_DIR = _PROJECT_DIR.parent
if str(_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(_ROOT_DIR))

from semantic_sandbox_common import (  # noqa: E402
    add_documents,
    append_audit_log,
    append_error_log,
    append_search_log,
    actor_from_request,
    available_categories,
    build_documents_from_rows,
    build_documents_from_texts,
    clear_documents,
    create_import_job,
    delete_document,
    delete_documents,
    document_lookup,
    document_matches_filters,
    enrich_search_hits,
    filter_payload,
    get_document,
    get_documents_by_ids,
    import_job_failed_rows_path,
    list_documents,
    list_audit_logs,
    list_error_logs,
    list_import_jobs,
    list_search_logs,
    load_import_job,
    load_documents,
    normalize_search_filters,
    parse_tags,
    parse_upload_rows,
    recent_errors,
    request_log_context,
    summarize_import_errors,
    truncate_text,
    update_document,
)
from semantic_sandbox_auth import install_api_key_auth  # noqa: E402
from semantic_sandbox_postgres import check_connection, postgres_enabled  # noqa: E402
from semantic_sandbox_web_auth import install_web_login_auth  # noqa: E402

BACKEND = "qdrant"

app = FastAPI(
    title="Qdrant Service API",
    description=(
        "向量数据库写入 & 语义搜索接口。\n\n"
        "- `POST /api/ingest`：文本 → PostgreSQL 元数据主库 → Qdrant 向量索引\n"
        "- `POST /api/search`：查询文本 → 向量 → 近邻检索 → 返回 Top-K 结果"
    ),
    version="1.0.0",
)
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
install_api_key_auth(app)
install_web_login_auth(app)


# ─── 工具函数 ──────────────────────────────────────────────────────────────────

def _get_client() -> QdrantClient:
    return QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)


_CONN_KEYWORDS = ("connection refused", "connect call failed", "timed out", "failed to connect", "errno 111", "unreachable")


def _fmt_exc(exc: Exception) -> str:
    msg = str(exc)
    if any(k in msg.lower() for k in _CONN_KEYWORDS):
        return "向量数据库未连接，请先在项目根目录执行 docker compose --profile qdrant up -d postgres qdrant"
    return msg


def _metadata_health() -> dict:
    if not postgres_enabled():
        return {"ok": True, "store": "json", "detail": "文件存储兼容模式"}
    try:
        info = check_connection()
        return {"ok": True, "store": "postgres", "database": info["database"], "detail": "PostgreSQL 连接正常"}
    except Exception as exc:
        return {"ok": False, "store": "postgres", "detail": str(exc)}


def _message_for_ingest(records: list[dict], existing: list[dict], failed: int = 0) -> str:
    parts = [f"成功写入 {len(records)} 条" if records else "没有新数据"]
    if existing:
        parts.append(f"已存在 {len(existing)} 条")
    if failed:
        parts.append(f"失败 {failed} 条")
    if records:
        parts.append(f"自动分配 ID：{[r['id'] for r in records]}")
    return "，".join(parts)


def _log_error(*, operation: str, surface: str, exc: Exception, **extra: object) -> None:
    append_error_log({
        "backend": BACKEND,
        "operation": operation,
        "surface": surface,
        "error": str(exc),
        **extra,
    })


def _log_audit(
    request: Request,
    *,
    event: str,
    level: str = "info",
    target_type: str = "",
    target_id: str | int = "",
    **metadata: object,
) -> None:
    append_audit_log({
        **request_log_context(request),
        "event": event,
        "level": level,
        "actor": actor_from_request(request),
        "backend": BACKEND,
        "target_type": target_type,
        "target_id": str(target_id or ""),
        "metadata": metadata,
    })


def _logs_snapshot(kind: str, limit: int) -> dict:
    limit = min(max(int(limit or 50), 1), 200)
    kind = kind if kind in {"audit", "search", "errors", "imports"} else "audit"
    return {
        "kind": kind,
        "limit": limit,
        "audit_logs": list_audit_logs(backend=BACKEND, limit=limit) if kind == "audit" else [],
        "search_logs": list_search_logs(backend=BACKEND, limit=limit) if kind == "search" else [],
        "error_logs": list_error_logs(backend=BACKEND, limit=limit) if kind == "errors" else [],
        "import_jobs": list_import_jobs(limit=limit) if kind == "imports" else [],
    }


def _parse_selected_ids(raw: str) -> list[int]:
    values: list[int] = []
    for item in str(raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            value = int(item)
        except ValueError:
            continue
        if value > 0 and value not in values:
            values.append(value)
    return values


def _search_candidate_limit(limit: int, filters: dict, doc_count: int) -> int:
    requested = min(max(limit, 1), 20)
    if not filter_payload(filters):
        return requested
    return min(max(requested * 15, 100), max(doc_count, requested), 500)


def _search_results(client: QdrantClient, *, query: str, limit: int, filters: dict) -> list[dict]:
    docs_by_id = document_lookup()
    [vector] = embed([query])
    hits = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=vector,
        limit=_search_candidate_limit(limit, filters, len(docs_by_id)),
        with_payload=True,
    )
    rows = [
        {
            "id": int(hit.id),
            "text": (hit.payload or {}).get("text", ""),
            "score": round(hit.score, 4),
        }
        for hit in hits
    ]
    filtered = [row for row in rows if document_matches_filters(docs_by_id.get(row["id"], {}), filters)]
    return enrich_search_hits(query, filtered[: min(max(limit, 1), 20)], docs_by_id=docs_by_id)


def _health_snapshot() -> dict:
    db_state = {"ok": False, "detail": "", "collection": COLLECTION_NAME}
    metadata_state = _metadata_health()
    vector_count = 0
    client = _get_client()
    try:
        client.get_collections()
        db_state["ok"] = True
        db_state["detail"] = "Qdrant 连接正常"
        vector_count = client.count(collection_name=COLLECTION_NAME, exact=True).count
    except Exception as exc:
        db_state["detail"] = _fmt_exc(exc)
    finally:
        client.close()

    errors = [item for item in recent_errors(limit=20) if item.get("backend") == BACKEND][:8]
    return {
        "backend": BACKEND,
        "db": db_state,
        "metadata": metadata_state,
        "model": model_status(),
        "metadata_count": len(load_documents()) if metadata_state["ok"] else 0,
        "vector_count": vector_count,
        "recent_errors": errors,
        "category_options": available_categories(),
    }


def _render_documents_page(
    request: Request,
    *,
    page: int = 1,
    page_size: int = 50,
    message: str | None = None,
    error: str | None = None,
):
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)
    docs, total = list_documents(offset=(page - 1) * page_size, limit=page_size)
    return templates.TemplateResponse(
        "documents.html",
        {
            "request": request,
            "documents": docs,
            "total": total,
            "model": model_status(),
            "page": page,
            "page_size": page_size,
            "message": message,
            "error": error,
        },
    )


# ─── Pydantic 模型 ──────────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    """写入请求体。texts 中每个字符串都会被独立向量化后写入向量库。"""

    texts: list[str]
    category: str = ""
    tags: list[str] = Field(default_factory=list)
    source: str = "api"

    model_config = {
        "json_schema_extra": {
            "example": {"texts": ["巴黎是法国的首都", "向量数据库用于语义检索"], "category": "geography"}
        }
    }


class IngestResponse(BaseModel):
    inserted: int
    ids: list[int]
    skipped: int = 0
    existing_count: int = 0
    existing: list[dict] = Field(default_factory=list)
    failed: int = 0
    errors: list[str] = Field(default_factory=list)
    job_id: str | None = None
    status: str | None = None
    failed_rows_download_url: str | None = None


class SearchRequest(BaseModel):
    """搜索请求体。支持多分类、标签和创建时间范围过滤。"""

    query: str
    limit: int = 5
    category: str | None = None
    categories: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    created_at_from: str | None = None
    created_at_to: str | None = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "query": "法国著名地标",
                "limit": 5,
                "categories": ["geography", "history"],
                "tags": ["travel"],
                "created_at_from": "2026-04-01T00:00:00+00:00",
            }
        }
    }


class SearchResult(BaseModel):
    id: int
    text: str
    score: float
    snippet: str = ""
    matched_terms: list[str] = Field(default_factory=list)
    score_explanation: str = ""
    category: str = ""
    tags: list[str] = Field(default_factory=list)
    source: str = ""
    created_at: str = ""
    updated_at: str = ""


class SearchResponse(BaseModel):
    query: str
    filter: dict = Field(default_factory=dict)
    results: list[SearchResult]


class DocumentUpdate(BaseModel):
    text: str
    category: str = ""
    tags: list[str] = Field(default_factory=list)
    source: str = "api"


class BatchDocumentRequest(BaseModel):
    record_ids: list[int] = Field(default_factory=list)


# ─── 健康检查 ─────────────────────────────────────────────────────────────────

@app.get("/health", include_in_schema=False)
async def health():
    try:
        client = _get_client()
        client.get_collections()
        metadata_state = _metadata_health()
        if not metadata_state["ok"]:
            raise HTTPException(status_code=503, detail=metadata_state["detail"])
        return {"status": "ok", "db": "qdrant", "metadata_store": metadata_state["store"]}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=_fmt_exc(exc))


# ─── REST API ──────────────────────────────────────────────────────────────────

@app.post(
    "/api/ingest",
    response_model=IngestResponse,
    summary="写入文本到向量库",
    description=(
        "将 `texts` 列表中的每条文本写入 PostgreSQL 元数据主库，再向量化写入 Qdrant。\n\n"
        "`document_id` / `text_hash` 由 PostgreSQL 唯一约束保证幂等；重复文本会跳过并计入 `skipped`。"
    ),
    tags=["数据写入"],
)
async def api_ingest(request: Request, req: IngestRequest) -> IngestResponse:
    new_records, existing = build_documents_from_texts(
        req.texts,
        seed_files=[DATA_FILE],
        source=req.source,
        category=req.category,
        tags=req.tags,
    )
    if not new_records:
        _log_audit(
            request,
            event="documents_ingest_skipped",
            target_type="documents",
            skipped=len(existing),
            source=req.source,
        )
        return IngestResponse(
            inserted=0,
            ids=[],
            skipped=len(existing),
            existing_count=len(existing),
            existing=existing,
        )
    client = _get_client()
    try:
        ensure_collection(client, embedding_dim())
        upsert(client, new_records)
        add_documents(new_records)
        _log_audit(
            request,
            event="documents_ingested",
            target_type="documents",
            inserted=len(new_records),
            skipped=len(existing),
            record_ids=[int(r["id"]) for r in new_records],
            source=req.source,
            category=req.category,
            tags=req.tags,
        )
        return IngestResponse(
            inserted=len(new_records),
            ids=[r["id"] for r in new_records],
            skipped=len(existing),
            existing_count=len(existing),
            existing=existing,
        )
    finally:
        client.close()


@app.post(
    "/api/upload",
    response_model=IngestResponse,
    summary="上传文件批量写入向量库",
    description=(
        "上传 JSON（`[{\"text\":\"...\"}]`）或 CSV（首行含 `text` 列）文件，批量向量化写入 Qdrant；"
        "支持 `UTF-8 BOM`，重复文本会跳过。"
    ),
    tags=["数据写入"],
)
async def api_upload(request: Request, file: UploadFile = File(...)) -> IngestResponse:
    content = await file.read()
    try:
        records_raw = parse_upload_rows(content, file.filename or "")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"文件解析失败：{exc}")
    new_records, existing, error_details = build_documents_from_rows(
        records_raw,
        seed_files=[DATA_FILE],
        default_source="upload",
    )
    errors = summarize_import_errors(error_details)
    if new_records:
        client = _get_client()
        try:
            ensure_collection(client, embedding_dim())
            upsert(client, new_records)
            add_documents(new_records)
        finally:
            client.close()
    job = create_import_job(
        source_filename=file.filename or "",
        inserted=len(new_records),
        existing=existing,
        errors=error_details,
    )
    _log_audit(
        request,
        event="documents_uploaded",
        target_type="import_job",
        target_id=job["job_id"],
        filename=file.filename or "",
        inserted=len(new_records),
        skipped=len(existing),
        failed=len(errors),
    )
    return IngestResponse(
        inserted=len(new_records),
        ids=[r["id"] for r in new_records],
        skipped=len(existing),
        existing_count=len(existing),
        existing=existing,
        failed=len(errors),
        errors=errors,
        job_id=job["job_id"],
        status=job["status"],
        failed_rows_download_url=job.get("failed_rows_download_url"),
    )


@app.post(
    "/api/search",
    response_model=SearchResponse,
    summary="语义搜索",
    description=(
        "将 `query` 向量化后在 Qdrant 里做近邻检索，并支持多分类、标签、时间范围过滤。\n\n"
        "`score` 为余弦相似度（-1 ~ 1），越接近 1 越相似；返回值包含匹配片段、高亮词和 score 解释。"
    ),
    tags=["语义搜索"],
)
async def api_search(req: SearchRequest) -> SearchResponse:
    client = _get_client()
    started = time.perf_counter()
    filters = normalize_search_filters(
        category=req.category,
        categories=req.categories,
        tags=req.tags,
        created_at_from=req.created_at_from,
        created_at_to=req.created_at_to,
    )
    try:
        results = [SearchResult(**item) for item in _search_results(client, query=req.query, limit=req.limit, filters=filters)]
        append_search_log({
            "backend": BACKEND,
            "query": req.query,
            "limit": min(req.limit, 20),
            "category": ",".join(filters["categories"]),
            "filter": filter_payload(filters),
            "result_count": len(results),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        })
        return SearchResponse(query=req.query, filter=filter_payload(filters), results=results)
    except Exception as exc:
        append_search_log({
            "backend": BACKEND,
            "query": req.query,
            "limit": min(req.limit, 20),
            "category": ",".join(filters["categories"]),
            "filter": filter_payload(filters),
            "result_count": 0,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error": str(exc),
        })
        _log_error(operation="search", surface="api", exc=exc, query=req.query, filter=filter_payload(filters))
        raise
    finally:
        client.close()


@app.get(
    "/api/count",
    summary="查询向量库中的记录总数",
    tags=["数据写入"],
)
async def api_count() -> dict:
    client = _get_client()
    try:
        result = client.count(collection_name=COLLECTION_NAME, exact=True)
        return {"count": result.count}
    except Exception:
        return {"count": 0}
    finally:
        client.close()


@app.delete(
    "/api/record/{record_id}",
    summary="删除指定 ID 的记录",
    tags=["数据写入"],
)
async def api_delete_record(request: Request, record_id: int) -> dict:
    client = _get_client()
    try:
        client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=qm.PointIdsList(points=[record_id]),
        )
        delete_document(record_id)
        _log_audit(request, event="document_deleted", target_type="document", target_id=record_id)
        return {"deleted": record_id}
    finally:
        client.close()


@app.delete(
    "/api/records",
    summary="清空向量库中所有记录（集合重建）",
    description="删除并重建当前 Qdrant collection，同时清空 PostgreSQL 文档元数据。",
    tags=["数据写入"],
)
async def api_clear_records(request: Request) -> dict:
    client = _get_client()
    try:
        client.delete_collection(collection_name=COLLECTION_NAME)
        ensure_collection(client, embedding_dim())
        clear_documents()
        _log_audit(request, event="documents_cleared", level="warning", target_type="documents", collection=COLLECTION_NAME)
        return {"cleared": True}
    finally:
        client.close()


@app.get(
    "/api/documents",
    summary="分页查看文档元数据",
    tags=["文档管理"],
)
async def api_documents(offset: int = 0, limit: int = 50) -> dict:
    docs, total = list_documents(offset=max(offset, 0), limit=min(max(limit, 1), 200))
    return {"total": total, "offset": offset, "limit": limit, "items": docs}


@app.get(
    "/api/documents/{record_id}",
    summary="查看单条文档",
    tags=["文档管理"],
)
async def api_document_detail(record_id: int) -> dict:
    doc = get_document(record_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="文档不存在")
    return doc


@app.put(
    "/api/documents/{record_id}",
    summary="更新文档并重建向量",
    tags=["文档管理"],
)
async def api_update_document(request: Request, record_id: int, req: DocumentUpdate) -> dict:
    client = _get_client()
    try:
        ensure_collection(client, embedding_dim())
        try:
            doc = update_document(record_id, req.model_dump())
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        upsert(client, [doc])
        _log_audit(
            request,
            event="document_updated",
            target_type="document",
            target_id=record_id,
            category=req.category,
            tags=req.tags,
            source=req.source,
            text_preview=truncate_text(req.text, 100),
        )
        return doc
    finally:
        client.close()


@app.delete(
    "/api/documents/{record_id}",
    summary="删除文档和向量",
    tags=["文档管理"],
)
async def api_delete_document(request: Request, record_id: int) -> dict:
    return await api_delete_record(request, record_id)


@app.post(
    "/api/documents/batch-delete",
    summary="批量删除文档和向量",
    tags=["文档管理"],
)
async def api_batch_delete_documents(request: Request, req: BatchDocumentRequest) -> dict:
    record_ids = sorted({int(item) for item in req.record_ids if int(item) > 0})
    if not record_ids:
        raise HTTPException(status_code=400, detail="请至少选择一条文档")
    client = _get_client()
    try:
        client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=qm.PointIdsList(points=record_ids),
        )
        deleted = delete_documents(record_ids)
        _log_audit(
            request,
            event="documents_batch_deleted",
            level="warning",
            target_type="documents",
            requested=len(record_ids),
            deleted=deleted,
            record_ids=record_ids,
        )
        return {"requested": len(record_ids), "deleted": deleted, "record_ids": record_ids}
    finally:
        client.close()


@app.post(
    "/api/documents/batch-reindex",
    summary="批量重建所选文档的向量",
    tags=["文档管理"],
)
async def api_batch_reindex_documents(request: Request, req: BatchDocumentRequest) -> dict:
    record_ids = sorted({int(item) for item in req.record_ids if int(item) > 0})
    if not record_ids:
        raise HTTPException(status_code=400, detail="请至少选择一条文档")
    docs = get_documents_by_ids(record_ids)
    if not docs:
        raise HTTPException(status_code=404, detail="未找到所选文档")
    client = _get_client()
    try:
        ensure_collection(client, embedding_dim())
        upsert(client, docs)
        _log_audit(
            request,
            event="documents_batch_reindexed",
            target_type="documents",
            requested=len(record_ids),
            reindexed=len(docs),
            record_ids=[int(doc["id"]) for doc in docs],
        )
        return {"requested": len(record_ids), "reindexed": len(docs), "record_ids": [int(doc["id"]) for doc in docs]}
    finally:
        client.close()


def _reindex_all(client: QdrantClient) -> int:
    docs = load_documents()
    try:
        client.delete_collection(collection_name=COLLECTION_NAME)
    except Exception:
        pass
    ensure_collection(client, embedding_dim())
    if docs:
        upsert(client, docs)
    return len(docs)


@app.post(
    "/api/reindex",
    summary="按 PostgreSQL 文档元数据重建当前向量库集合",
    tags=["文档管理"],
)
async def api_reindex(request: Request) -> dict:
    client = _get_client()
    try:
        indexed = _reindex_all(client)
        _log_audit(request, event="documents_reindexed", target_type="collection", target_id=COLLECTION_NAME, indexed=indexed)
        return {"indexed": indexed, "collection": COLLECTION_NAME}
    finally:
        client.close()


@app.get(
    "/api/model/status",
    summary="查看当前嵌入模型状态",
    tags=["模型"],
)
async def api_model_status() -> dict:
    return model_status()


@app.get(
    "/model/status",
    summary="兼容旧路径的模型状态接口",
    tags=["模型"],
)
async def model_status_alias() -> dict:
    return model_status()


@app.get(
    "/api/health/panel",
    summary="查看健康面板数据",
    tags=["模型"],
)
async def api_health_panel() -> dict:
    return _health_snapshot()


@app.get(
    "/api/import-jobs/{job_id}",
    summary="查看批量导入任务状态",
    tags=["数据写入"],
)
async def api_import_job_status(job_id: str) -> dict:
    job = load_import_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="导入任务不存在")
    return job


@app.get(
    "/api/import-jobs/{job_id}/failed-rows",
    summary="下载批量导入失败行",
    tags=["数据写入"],
)
async def api_import_job_failed_rows(job_id: str):
    job = load_import_job(job_id)
    path = import_job_failed_rows_path(job_id)
    if job is None or not path.exists():
        raise HTTPException(status_code=404, detail="失败行文件不存在")
    return FileResponse(path=path, media_type="text/csv", filename=f"{job_id}-failed-rows.csv")


# ─── 示例数据接口 ──────────────────────────────────────────────────────────────

_SAMPLE_FILES = {
    "en": _PROJECT_DIR.parent / "data" / "sample_en.json",
    "zh": _PROJECT_DIR.parent / "data" / "sample_zh.json",
}


@app.get(
    "/api/samples/{lang}",
    summary="获取示例数据文本列表",
    description="返回 sample_en.json 或 sample_zh.json 中的文本列表，供 Web UI 一键加载。",
    tags=["数据写入"],
)
async def api_samples(lang: str) -> dict:
    if lang not in _SAMPLE_FILES:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"lang 只支持 en 或 zh，收到 {lang!r}")
    data = json.loads(_SAMPLE_FILES[lang].read_text(encoding="utf-8"))
    return {"lang": lang, "texts": [r["text"] for r in data]}


# ─── Web 页面 ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def search_page(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "category_options": available_categories(),
            "selected_categories": [],
            "tags_text": "",
            "created_at_from": "",
            "created_at_to": "",
            "active_filter": {},
        },
    )


@app.post("/search", response_class=HTMLResponse, include_in_schema=False)
async def search_form(
    request: Request,
    query: Annotated[str, Form()],
    limit: Annotated[int, Form()] = 5,
    categories: Annotated[list[str], Form()] = [],
    tags: Annotated[str, Form()] = "",
    created_at_from: Annotated[str, Form()] = "",
    created_at_to: Annotated[str, Form()] = "",
):
    results, error = [], None
    client = _get_client()
    started = time.perf_counter()
    filters = normalize_search_filters(
        categories=categories,
        tags=parse_tags(tags),
        created_at_from=created_at_from,
        created_at_to=created_at_to,
    )
    try:
        results = _search_results(client, query=query, limit=limit, filters=filters)
        append_search_log({
            "backend": BACKEND,
            "query": query,
            "limit": min(limit, 20),
            "category": ",".join(filters["categories"]),
            "filter": filter_payload(filters),
            "result_count": len(results),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "surface": "web",
        })
    except Exception as exc:
        error = _fmt_exc(exc)
        append_search_log({
            "backend": BACKEND,
            "query": query,
            "limit": min(limit, 20),
            "category": ",".join(filters["categories"]),
            "filter": filter_payload(filters),
            "result_count": 0,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "surface": "web",
            "error": str(exc),
        })
        _log_error(operation="search", surface="web", exc=exc, query=query, filter=filter_payload(filters))
    finally:
        client.close()
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "query": query,
            "limit": limit,
            "results": results,
            "error": error,
            "category_options": available_categories(),
            "selected_categories": filters["categories"],
            "tags_text": ",".join(filters["tags"]),
            "created_at_from": filters["created_at_from"],
            "created_at_to": filters["created_at_to"],
            "active_filter": filter_payload(filters),
        },
    )


@app.get("/ingest", response_class=HTMLResponse, include_in_schema=False)
async def ingest_page(request: Request):
    return templates.TemplateResponse("ingest.html", {"request": request})


@app.get("/documents", response_class=HTMLResponse, include_in_schema=False)
async def documents_page(request: Request, page: int = 1, page_size: int = 50):
    return _render_documents_page(request, page=page, page_size=page_size)


@app.get("/health/panel", response_class=HTMLResponse, include_in_schema=False)
async def health_panel_page(request: Request):
    return templates.TemplateResponse(
        "health.html",
        {
            "request": request,
            "health": _health_snapshot(),
        },
    )


@app.get("/logs", response_class=HTMLResponse, include_in_schema=False)
async def logs_page(request: Request, kind: str = "audit", limit: int = 50):
    return templates.TemplateResponse(
        "logs.html",
        {
            "request": request,
            "backend": BACKEND,
            "logs": _logs_snapshot(kind, limit),
        },
    )


@app.post("/documents/{record_id}/update", response_class=HTMLResponse, include_in_schema=False)
async def update_document_form(
    request: Request,
    record_id: int,
    text: Annotated[str, Form()],
    category: Annotated[str, Form()] = "",
    tags: Annotated[str, Form()] = "",
    source: Annotated[str, Form()] = "web",
    page: Annotated[int, Form()] = 1,
    page_size: Annotated[int, Form()] = 50,
):
    message, error = None, None
    client = _get_client()
    try:
        ensure_collection(client, embedding_dim())
        doc = update_document(record_id, {
            "text": text,
            "category": category,
            "tags": parse_tags(tags),
            "source": source,
        })
        upsert(client, [doc])
        _log_audit(
            request,
            event="document_updated",
            target_type="document",
            target_id=record_id,
            category=category,
            tags=parse_tags(tags),
            source=source,
            text_preview=truncate_text(text, 100),
        )
        message = f"已更新文档 {record_id} 并重建向量"
    except Exception as exc:
        error = _fmt_exc(exc)
        _log_error(operation="update_document", surface="web", exc=exc, record_id=record_id)
    finally:
        client.close()
    return _render_documents_page(request, page=page, page_size=page_size, message=message, error=error)


@app.post("/documents/{record_id}/delete", response_class=HTMLResponse, include_in_schema=False)
async def delete_document_form(
    request: Request,
    record_id: int,
    page: Annotated[int, Form()] = 1,
    page_size: Annotated[int, Form()] = 50,
):
    message, error = None, None
    client = _get_client()
    try:
        client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=qm.PointIdsList(points=[record_id]),
        )
        delete_document(record_id)
        _log_audit(request, event="document_deleted", level="warning", target_type="document", target_id=record_id)
        message = f"已删除文档 {record_id}"
    except Exception as exc:
        error = _fmt_exc(exc)
        _log_error(operation="delete_document", surface="web", exc=exc, record_id=record_id)
    finally:
        client.close()
    return _render_documents_page(request, page=page, page_size=page_size, message=message, error=error)


@app.post("/documents/reindex", response_class=HTMLResponse, include_in_schema=False)
async def reindex_form(
    request: Request,
    page: Annotated[int, Form()] = 1,
    page_size: Annotated[int, Form()] = 50,
):
    message, error = None, None
    client = _get_client()
    try:
        indexed = _reindex_all(client)
        _log_audit(request, event="documents_reindexed", target_type="collection", target_id=COLLECTION_NAME, indexed=indexed)
        message = f"已重建集合 {COLLECTION_NAME}，写入 {indexed} 条文档"
    except Exception as exc:
        error = _fmt_exc(exc)
        _log_error(operation="reindex_all", surface="web", exc=exc)
    finally:
        client.close()
    return _render_documents_page(request, page=page, page_size=page_size, message=message, error=error)


@app.post("/documents/batch-delete", response_class=HTMLResponse, include_in_schema=False)
async def batch_delete_documents_form(
    request: Request,
    selected_ids: Annotated[str, Form()],
    page: Annotated[int, Form()] = 1,
    page_size: Annotated[int, Form()] = 50,
):
    record_ids = _parse_selected_ids(selected_ids)
    message, error = None, None
    if not record_ids:
        error = "请至少选择一条文档"
        return _render_documents_page(request, page=page, page_size=page_size, message=message, error=error)
    client = _get_client()
    try:
        client.delete(
            collection_name=COLLECTION_NAME,
            points_selector=qm.PointIdsList(points=record_ids),
        )
        deleted = delete_documents(record_ids)
        _log_audit(
            request,
            event="documents_batch_deleted",
            level="warning",
            target_type="documents",
            requested=len(record_ids),
            deleted=deleted,
            record_ids=record_ids,
        )
        message = f"已批量删除 {deleted} 条文档"
    except Exception as exc:
        error = _fmt_exc(exc)
        _log_error(operation="batch_delete", surface="web", exc=exc, record_ids=record_ids)
    finally:
        client.close()
    return _render_documents_page(request, page=page, page_size=page_size, message=message, error=error)


@app.post("/documents/batch-reindex", response_class=HTMLResponse, include_in_schema=False)
async def batch_reindex_documents_form(
    request: Request,
    selected_ids: Annotated[str, Form()],
    page: Annotated[int, Form()] = 1,
    page_size: Annotated[int, Form()] = 50,
):
    record_ids = _parse_selected_ids(selected_ids)
    message, error = None, None
    if not record_ids:
        error = "请至少选择一条文档"
        return _render_documents_page(request, page=page, page_size=page_size, message=message, error=error)
    docs = get_documents_by_ids(record_ids)
    if not docs:
        error = "未找到所选文档"
        return _render_documents_page(request, page=page, page_size=page_size, message=message, error=error)
    client = _get_client()
    try:
        ensure_collection(client, embedding_dim())
        upsert(client, docs)
        _log_audit(
            request,
            event="documents_batch_reindexed",
            target_type="documents",
            requested=len(record_ids),
            reindexed=len(docs),
            record_ids=[int(doc["id"]) for doc in docs],
        )
        message = f"已批量重建 {len(docs)} 条文档向量"
    except Exception as exc:
        error = _fmt_exc(exc)
        _log_error(operation="batch_reindex", surface="web", exc=exc, record_ids=record_ids)
    finally:
        client.close()
    return _render_documents_page(request, page=page, page_size=page_size, message=message, error=error)


@app.post("/ingest", response_class=HTMLResponse, include_in_schema=False)
async def ingest_form(
    request: Request,
    texts: Annotated[str, Form()],
):
    message, error = None, None
    try:
        lines = [t.strip() for t in texts.strip().splitlines() if t.strip()]
        if not lines:
            error = "请至少输入一行文本"
        else:
            new_records, existing = build_documents_from_texts(lines, seed_files=[DATA_FILE], source="web")
            if new_records:
                client = _get_client()
                try:
                    ensure_collection(client, embedding_dim())
                    if new_records:
                        upsert(client, new_records)
                        add_documents(new_records)
                finally:
                    client.close()
            _log_audit(
                request,
                event="documents_ingested",
                target_type="documents",
                inserted=len(new_records),
                skipped=len(existing),
                record_ids=[int(r["id"]) for r in new_records],
                source="web",
            )
            message = _message_for_ingest(new_records, existing)
    except Exception as exc:
        error = _fmt_exc(exc)
        _log_error(operation="ingest", surface="web", exc=exc)
    return templates.TemplateResponse(
        "ingest.html",
        {"request": request, "texts": texts if error else "", "message": message, "error": error},
    )


@app.post("/ingest/upload", response_class=HTMLResponse, include_in_schema=False)
async def upload_form(request: Request, file: UploadFile = File(...)):
    message, error, import_status = None, None, None
    try:
        content = await file.read()
        records_raw = parse_upload_rows(content, file.filename or "")
        new_records, existing, error_details = build_documents_from_rows(
            records_raw,
            seed_files=[DATA_FILE],
            default_source="upload",
        )
        errors = summarize_import_errors(error_details)
        if new_records:
            client = _get_client()
            try:
                ensure_collection(client, embedding_dim())
                upsert(client, new_records)
                add_documents(new_records)
            finally:
                client.close()
        import_status = create_import_job(
            source_filename=file.filename or "",
            inserted=len(new_records),
            existing=existing,
            errors=error_details,
        )
        _log_audit(
            request,
            event="documents_uploaded",
            target_type="import_job",
            target_id=import_status["job_id"],
            filename=file.filename or "",
            inserted=len(new_records),
            skipped=len(existing),
            failed=len(errors),
        )
        message = _message_for_ingest(new_records, existing, failed=len(errors))
    except Exception as exc:
        error = _fmt_exc(exc)
        _log_error(operation="upload", surface="web", exc=exc, filename=file.filename or "")
    return templates.TemplateResponse(
        "ingest.html",
        {"request": request, "message": message, "error": error, "import_status": import_status},
    )
