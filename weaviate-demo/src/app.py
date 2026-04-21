"""Web UI + REST API for Weaviate demo.

启动：
    uvicorn src.app:app --reload --port 8889

访问：
    http://localhost:8889          搜索页面
    http://localhost:8889/ingest   写入页面
    http://localhost:8889/docs     Swagger API 文档
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import weaviate
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from weaviate.classes.config import Configure, DataType, Property
from weaviate.classes.data import DataObject
from weaviate.classes.query import MetadataQuery
from weaviate.util import generate_uuid5

from .config import (
    COLLECTION_NAME,
    DATA_FILE,
    WEAVIATE_GRPC_PORT,
    WEAVIATE_HOST,
    WEAVIATE_HTTP_PORT,
)
from .embedder import embed, embedding_dim

# ─── 初始化 ────────────────────────────────────────────────────────────────────

_PROJECT_DIR = Path(__file__).resolve().parent.parent
_TEMPLATES_DIR = _PROJECT_DIR / "templates"
_USER_DATA_FILE = _PROJECT_DIR.parent / "data" / "user_data.json"

app = FastAPI(
    title="Weaviate Demo API",
    description=(
        "向量数据库写入 & 语义搜索接口。\n\n"
        "- `POST /api/ingest`：文本 → 向量 → 写入 Weaviate，同时追加到 `data/user_data.json`\n"
        "- `POST /api/search`：查询文本 → 向量 → 近邻检索 → 返回 Top-K 结果"
    ),
    version="1.0.0",
)
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


# ─── 工具函数 ──────────────────────────────────────────────────────────────────

def _connect() -> weaviate.WeaviateClient:
    return weaviate.connect_to_local(
        host=WEAVIATE_HOST,
        port=WEAVIATE_HTTP_PORT,
        grpc_port=WEAVIATE_GRPC_PORT,
    )


def _ensure_collection(client: weaviate.WeaviateClient) -> None:
    """集合不存在才建；已有集合直接复用，不删除已有数据。"""
    if client.collections.exists(COLLECTION_NAME):
        return
    client.collections.create(
        name=COLLECTION_NAME,
        properties=[
            Property(name="doc_id",   data_type=DataType.INT),
            Property(name="text",     data_type=DataType.TEXT),
            Property(name="category", data_type=DataType.TEXT),
        ],
        vectorizer_config=Configure.Vectorizer.none(),
        vector_index_config=Configure.VectorIndex.hnsw(
            distance_metric=weaviate.classes.config.VectorDistances.COSINE,
        ),
    )


def _upsert_records(client: weaviate.WeaviateClient, records: list[dict]) -> int:
    """返回实际写入成功的条数。"""
    texts = [r["text"] for r in records]
    vectors = embed(texts)
    collection = client.collections.get(COLLECTION_NAME)
    objects = [
        DataObject(
            properties={"doc_id": r["id"], "text": r["text"], "category": r.get("category", "")},
            uuid=generate_uuid5(str(r["id"])),
            vector=vec,
        )
        for r, vec in zip(records, vectors)
    ]
    result = collection.data.insert_many(objects)
    if result.has_errors:
        msgs = "; ".join(e.message for e in result.errors.values())
        raise RuntimeError(f"部分数据写入失败：{msgs}")
    return len(objects)


def _load_user_data() -> list[dict]:
    if _USER_DATA_FILE.exists():
        return json.loads(_USER_DATA_FILE.read_text(encoding="utf-8"))
    return []


def _save_user_data(records: list[dict]) -> None:
    _USER_DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    _USER_DATA_FILE.write_text(
        json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _next_id() -> int:
    ids: list[int] = []
    for f in [DATA_FILE, _USER_DATA_FILE]:
        if f.exists():
            data = json.loads(f.read_text(encoding="utf-8"))
            ids.extend(int(r.get("id", 0)) for r in data if isinstance(r.get("id"), int))
    return max(ids, default=0) + 1


# ─── Pydantic 模型 ─────────────────────────────────────────────────────────────

class IngestRequest(BaseModel):
    """写入请求体。texts 中每个字符串都会被独立向量化后写入向量库。"""

    texts: list[str]

    model_config = {
        "json_schema_extra": {
            "example": {"texts": ["巴黎是法国的首都", "向量数据库用于语义检索"]}
        }
    }


class IngestResponse(BaseModel):
    inserted: int
    ids: list[int]


class SearchRequest(BaseModel):
    """搜索请求体。query 是查询文本，limit 控制返回条数（默认 5，最大 20）。"""

    query: str
    limit: int = 5

    model_config = {
        "json_schema_extra": {
            "example": {"query": "法国著名地标", "limit": 5}
        }
    }


class SearchResult(BaseModel):
    id: int
    text: str
    score: float


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]


# ─── REST API ──────────────────────────────────────────────────────────────────

@app.post(
    "/api/ingest",
    response_model=IngestResponse,
    summary="写入文本到向量库",
    description=(
        "将 `texts` 列表中的每条文本向量化后写入 Weaviate，并追加保存到 `data/user_data.json`。\n\n"
        "ID 自动从现有数据的最大 id + 1 开始递增。每条记录用 `generate_uuid5(str(id))` 生成稳定 UUID，重复提交不会产生重复数据。"
    ),
    tags=["数据写入"],
)
async def api_ingest(req: IngestRequest) -> IngestResponse:
    client = _connect()
    try:
        _ensure_collection(client)
        start_id = _next_id()
        new_records = [
            {"id": start_id + i, "text": t.strip()}
            for i, t in enumerate(req.texts)
            if t.strip()
        ]
        if not new_records:
            return IngestResponse(inserted=0, ids=[])

        _upsert_records(client, new_records)
        existing = _load_user_data()
        existing.extend(new_records)
        _save_user_data(existing)
        return IngestResponse(inserted=len(new_records), ids=[r["id"] for r in new_records])
    finally:
        client.close()


@app.post(
    "/api/search",
    response_model=SearchResponse,
    summary="语义搜索",
    description=(
        "将 `query` 向量化后在 Weaviate 里做近邻检索，返回最相近的 `limit` 条结果。\n\n"
        "`score` 为余弦相似度（= 1 − cosine distance），范围 0 ~ 1，越接近 1 越相似。"
    ),
    tags=["语义搜索"],
)
async def api_search(req: SearchRequest) -> SearchResponse:
    client = _connect()
    try:
        [vector] = embed([req.query])
        collection = client.collections.get(COLLECTION_NAME)
        res = collection.query.near_vector(
            near_vector=vector,
            limit=min(req.limit, 20),
            return_metadata=MetadataQuery(distance=True),
        )
        results = []
        for obj in res.objects:
            distance = obj.metadata.distance if obj.metadata else None
            score = round(1 - distance, 4) if distance is not None else 0.0
            props = obj.properties or {}
            results.append(SearchResult(
                id=int(props.get("doc_id", 0)),
                text=props.get("text", ""),
                score=score,
            ))
        return SearchResponse(query=req.query, results=results)
    finally:
        client.close()


# ─── Web 页面 ──────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def search_page(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/search", response_class=HTMLResponse, include_in_schema=False)
async def search_form(
    request: Request,
    query: Annotated[str, Form()],
    limit: Annotated[int, Form()] = 5,
):
    results, error = [], None
    client = _connect()
    try:
        [vector] = embed([query])
        collection = client.collections.get(COLLECTION_NAME)
        res = collection.query.near_vector(
            near_vector=vector,
            limit=min(limit, 20),
            return_metadata=MetadataQuery(distance=True),
        )
        for obj in res.objects:
            distance = obj.metadata.distance if obj.metadata else None
            score = round(1 - distance, 4) if distance is not None else 0.0
            props = obj.properties or {}
            results.append({"id": int(props.get("doc_id", 0)), "text": props.get("text", ""), "score": score})
    except Exception as exc:
        error = str(exc)
    finally:
        client.close()
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "query": query, "limit": limit, "results": results, "error": error},
    )


@app.get("/ingest", response_class=HTMLResponse, include_in_schema=False)
async def ingest_page(request: Request):
    return templates.TemplateResponse("ingest.html", {"request": request})


@app.post("/ingest", response_class=HTMLResponse, include_in_schema=False)
async def ingest_form(
    request: Request,
    texts: Annotated[str, Form()],
):
    message, error = None, None
    client = _connect()
    try:
        lines = [t.strip() for t in texts.strip().splitlines() if t.strip()]
        if not lines:
            error = "请至少输入一行文本"
        else:
            _ensure_collection(client)
            start_id = _next_id()
            new_records = [{"id": start_id + i, "text": t} for i, t in enumerate(lines)]
            _upsert_records(client, new_records)
            existing = _load_user_data()
            existing.extend(new_records)
            _save_user_data(existing)
            ids = [r["id"] for r in new_records]
            message = f"成功写入 {len(new_records)} 条，自动分配 ID：{ids}"
    except Exception as exc:
        error = str(exc)
    finally:
        client.close()
    return templates.TemplateResponse(
        "ingest.html",
        {"request": request, "texts": texts if error else "", "message": message, "error": error},
    )
