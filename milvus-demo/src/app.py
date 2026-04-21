"""Web UI + REST API for Milvus demo.

启动：
    uvicorn src.app:app --reload --port 8890

访问：
    http://localhost:8890          搜索页面
    http://localhost:8890/ingest   写入页面
    http://localhost:8890/docs     Swagger API 文档
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pymilvus import MilvusClient

from .config import COLLECTION_NAME, DATA_FILE, MILVUS_URI
from .embedder import embed, embedding_dim
from .ingest import ensure_collection, upsert

# ─── 初始化 ────────────────────────────────────────────────────────────────────

_PROJECT_DIR = Path(__file__).resolve().parent.parent
_TEMPLATES_DIR = _PROJECT_DIR / "templates"
_USER_DATA_FILE = _PROJECT_DIR.parent / "data" / "user_data.json"

app = FastAPI(
    title="Milvus Demo API",
    description=(
        "向量数据库写入 & 语义搜索接口。\n\n"
        "- `POST /api/ingest`：文本 → 向量 → 写入 Milvus，同时追加到 `data/user_data.json`\n"
        "- `POST /api/search`：查询文本 → 向量 → 近邻检索 → 返回 Top-K 结果"
    ),
    version="1.0.0",
)
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


# ─── 工具函数 ──────────────────────────────────────────────────────────────────

def _get_client() -> MilvusClient:
    return MilvusClient(uri=MILVUS_URI)


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
        "将 `texts` 列表中的每条文本向量化后 upsert 到 Milvus，并追加保存到 `data/user_data.json`。\n\n"
        "ID 自动从现有数据的最大 id + 1 开始递增。使用 `upsert` 语义：相同 id 的记录会被覆盖，不产生重复数据。"
    ),
    tags=["数据写入"],
)
async def api_ingest(req: IngestRequest) -> IngestResponse:
    client = _get_client()
    ensure_collection(client, embedding_dim())

    start_id = _next_id()
    new_records = [
        {"id": start_id + i, "text": t.strip()}
        for i, t in enumerate(req.texts)
        if t.strip()
    ]
    if not new_records:
        return IngestResponse(inserted=0, ids=[])

    upsert(client, new_records)
    existing = _load_user_data()
    existing.extend(new_records)
    _save_user_data(existing)
    return IngestResponse(inserted=len(new_records), ids=[r["id"] for r in new_records])


@app.post(
    "/api/search",
    response_model=SearchResponse,
    summary="语义搜索",
    description=(
        "将 `query` 向量化后在 Milvus 里做近邻检索，返回最相近的 `limit` 条结果。\n\n"
        "`score` 为 COSINE 相似度（-1 ~ 1），越接近 1 越相似。"
        "注意：Milvus COSINE 指标下 `search` 返回的 `distance` 字段实际是相似度（不是距离），这里直接使用。"
    ),
    tags=["语义搜索"],
)
async def api_search(req: SearchRequest) -> SearchResponse:
    client = _get_client()
    client.load_collection(collection_name=COLLECTION_NAME)
    [vector] = embed([req.query])
    results_raw = client.search(
        collection_name=COLLECTION_NAME,
        data=[vector],
        limit=min(req.limit, 20),
        output_fields=["text"],
        search_params={"metric_type": "COSINE"},
    )
    hits = results_raw[0] if results_raw else []
    results = [
        SearchResult(
            id=int(h["id"]),
            text=h.get("entity", {}).get("text", ""),
            score=round(float(h.get("distance", 0)), 4),
        )
        for h in hits
    ]
    return SearchResponse(query=req.query, results=results)


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
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/search", response_class=HTMLResponse, include_in_schema=False)
async def search_form(
    request: Request,
    query: Annotated[str, Form()],
    limit: Annotated[int, Form()] = 5,
):
    results, error = [], None
    try:
        client = _get_client()
        client.load_collection(collection_name=COLLECTION_NAME)
        [vector] = embed([query])
        results_raw = client.search(
            collection_name=COLLECTION_NAME,
            data=[vector],
            limit=min(limit, 20),
            output_fields=["text"],
            search_params={"metric_type": "COSINE"},
        )
        hits = results_raw[0] if results_raw else []
        results = [
            {"id": int(h["id"]), "text": h.get("entity", {}).get("text", ""), "score": round(float(h.get("distance", 0)), 4)}
            for h in hits
        ]
    except Exception as exc:
        error = str(exc)
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
    try:
        lines = [t.strip() for t in texts.strip().splitlines() if t.strip()]
        if not lines:
            error = "请至少输入一行文本"
        else:
            client = _get_client()
            ensure_collection(client, embedding_dim())
            start_id = _next_id()
            new_records = [{"id": start_id + i, "text": t} for i, t in enumerate(lines)]
            upsert(client, new_records)
            existing = _load_user_data()
            existing.extend(new_records)
            _save_user_data(existing)
            ids = [r["id"] for r in new_records]
            message = f"成功写入 {len(new_records)} 条，自动分配 ID：{ids}"
    except Exception as exc:
        error = str(exc)
    return templates.TemplateResponse(
        "ingest.html",
        {"request": request, "texts": texts if error else "", "message": message, "error": error},
    )
