"""Shared metadata helpers for the vector database services.

This keeps product-facing state outside the vector DB so each backend can be
rebuilt from the same document metadata.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
DOCUMENTS_FILE = DATA_DIR / "documents.json"
USER_DATA_FILE = DATA_DIR / "user_data.json"
SEARCH_LOG_FILE = DATA_DIR / "search_logs.jsonl"
ERROR_LOG_FILE = DATA_DIR / "app_errors.jsonl"
IMPORT_REPORT_DIR = DATA_DIR / "import_reports"
DEFAULT_CATEGORY_OPTIONS = [
    "technology",
    "science",
    "geography",
    "history",
    "food",
    "sports",
    "art",
    "nature",
]
_TERM_SPLIT_RE = re.compile(r"[\s,，。.!?！？;；:：、'\"“”‘’()\[\]{}<>《》【】]+")


def _postgres_enabled() -> bool:
    from semantic_sandbox_postgres import postgres_enabled

    return postgres_enabled()


def _pg():
    import semantic_sandbox_postgres

    return semantic_sandbox_postgres


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_text(text: str) -> str:
    return " ".join(str(text).strip().split())


def text_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def make_document_id(hash_value: str) -> str:
    return f"doc_{hash_value[:16]}"


def parse_tags(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_tags = value
    else:
        raw_tags = str(value).replace("，", ",").split(",")
    tags: list[str] = []
    for raw in raw_tags:
        tag = str(raw).strip()
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def _parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            dt = datetime.fromisoformat(f"{normalized}T00:00:00")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def document_summary(doc: dict) -> dict:
    return {
        "id": int(doc.get("id", 0)),
        "document_id": str(doc.get("document_id", "")),
        "text_hash": str(doc.get("text_hash", "")),
        "text": str(doc.get("text", "")),
        "category": str(doc.get("category", "")),
        "tags": parse_tags(doc.get("tags")),
        "source": str(doc.get("source", "")),
        "created_at": str(doc.get("created_at", "")),
        "updated_at": str(doc.get("updated_at", "")),
    }


def document_lookup() -> dict[int, dict]:
    return {int(doc.get("id", 0)): doc for doc in load_documents() if int(doc.get("id", 0)) > 0}


def get_documents_by_ids(record_ids: Iterable[int]) -> list[dict]:
    if _postgres_enabled():
        return _pg().get_documents_by_ids(record_ids)
    wanted = {int(value) for value in record_ids}
    return [doc for doc in load_documents() if int(doc.get("id", 0)) in wanted]


def delete_documents(record_ids: Iterable[int]) -> int:
    if _postgres_enabled():
        return _pg().delete_documents(record_ids)
    wanted = {int(value) for value in record_ids}
    if not wanted:
        return 0
    docs = load_documents()
    remaining = [doc for doc in docs if int(doc.get("id", 0)) not in wanted]
    deleted = len(docs) - len(remaining)
    if deleted:
        save_documents(remaining)
    return deleted


def available_categories() -> list[str]:
    discovered = {str(doc.get("category", "")).strip() for doc in load_documents()}
    values = [item for item in DEFAULT_CATEGORY_OPTIONS if item]
    for category in sorted(discovered):
        if category and category not in values:
            values.append(category)
    return values


def normalize_search_filters(
    *,
    category: str | None = None,
    categories: Iterable[str] | None = None,
    tags: Iterable[str] | None = None,
    created_at_from: str | None = None,
    created_at_to: str | None = None,
) -> dict:
    category_values = [str(item).strip() for item in (categories or []) if str(item).strip()]
    single = str(category or "").strip()
    if single and single not in category_values:
        category_values.append(single)
    tag_values = parse_tags(list(tags or []))
    return {
        "categories": category_values,
        "tags": tag_values,
        "created_at_from": str(created_at_from or "").strip(),
        "created_at_to": str(created_at_to or "").strip(),
    }


def filter_payload(filters: dict) -> dict:
    payload: dict[str, Any] = {}
    if filters.get("categories"):
        payload["categories"] = list(filters["categories"])
    if filters.get("tags"):
        payload["tags"] = list(filters["tags"])
    if filters.get("created_at_from"):
        payload["created_at_from"] = filters["created_at_from"]
    if filters.get("created_at_to"):
        payload["created_at_to"] = filters["created_at_to"]
    return payload


def document_matches_filters(doc: dict, filters: dict | None = None) -> bool:
    filters = filters or {}
    categories = list(filters.get("categories") or [])
    tags = parse_tags(filters.get("tags") or [])
    created_at_from = _parse_datetime(filters.get("created_at_from"))
    created_at_to = _parse_datetime(filters.get("created_at_to"))

    if categories and str(doc.get("category", "")).strip() not in categories:
        return False

    if tags:
        doc_tags = set(parse_tags(doc.get("tags")))
        if not doc_tags.intersection(tags):
            return False

    if created_at_from or created_at_to:
        doc_dt = _parse_datetime(doc.get("created_at") or doc.get("updated_at"))
        if doc_dt is None:
            return False
        if created_at_from and doc_dt < created_at_from:
            return False
        if created_at_to and doc_dt > created_at_to:
            return False

    return True


def filter_documents(docs: Iterable[dict], filters: dict | None = None) -> list[dict]:
    return [doc for doc in docs if document_matches_filters(doc, filters)]


def append_error_log(entry: dict) -> None:
    if _postgres_enabled():
        _pg().save_error_log(entry)
        return
    ERROR_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": utc_now(), **entry}
    with ERROR_LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def recent_errors(limit: int = 10) -> list[dict]:
    if _postgres_enabled():
        return _pg().recent_errors(limit)
    if not ERROR_LOG_FILE.exists():
        return []
    rows: list[dict] = []
    for line in ERROR_LOG_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return list(reversed(rows[-limit:]))


def query_terms(query: str, text: str = "") -> list[str]:
    normalized_query = str(query or "").strip()
    lower_text = str(text or "").lower()
    if not normalized_query:
        return []

    terms: set[str] = set()

    def add(term: str) -> None:
        value = term.strip()
        if len(value) < 2:
            return
        if lower_text and value.lower() not in lower_text:
            return
        terms.add(value)

    add(normalized_query)
    for item in _TERM_SPLIT_RE.split(normalized_query):
        add(item)

    if not terms and lower_text:
        max_len = min(len(normalized_query), 8)
        for length in range(max_len, 1, -1):
            for idx in range(0, len(normalized_query) - length + 1):
                add(normalized_query[idx: idx + length])
            if terms:
                break

    return sorted(terms, key=lambda item: (-len(item), item.lower()))


def extract_snippet(text: str, terms: Iterable[str], *, radius: int = 48, max_chars: int = 160) -> str:
    content = normalize_text(text)
    if not content:
        return ""

    lower = content.lower()
    first_start = None
    first_end = None
    for term in terms:
        index = lower.find(str(term).lower())
        if index != -1:
            first_start = index
            first_end = index + len(term)
            break

    if first_start is None:
        return content[:max_chars] + ("..." if len(content) > max_chars else "")

    start = max(0, first_start - radius)
    end = min(len(content), first_end + radius)
    snippet = content[start:end]
    if start > 0:
        snippet = "..." + snippet.lstrip()
    if end < len(content):
        snippet = snippet.rstrip() + "..."
    if len(snippet) > max_chars + 6:
        snippet = snippet[:max_chars].rstrip() + "..."
    return snippet


def explain_score(score: float) -> str:
    value = float(score)
    if value >= 0.85:
        band = "高度相关"
    elif value >= 0.65:
        band = "相关性较强"
    elif value >= 0.45:
        band = "部分相关"
    else:
        band = "相关性较弱"
    return f"{band}，score={value:.4f}，越接近 1 越相似。"


def enrich_search_hits(query: str, hits: Iterable[dict], *, docs_by_id: dict[int, dict] | None = None) -> list[dict]:
    index = docs_by_id or document_lookup()
    enriched: list[dict] = []
    for item in hits:
        record_id = int(item.get("id", 0))
        doc = index.get(record_id, {})
        text = str(item.get("text") or doc.get("text", ""))
        matched_terms = query_terms(query, text)
        enriched.append({
            **item,
            "snippet": extract_snippet(text, matched_terms),
            "matched_terms": matched_terms[:6],
            "score_explanation": explain_score(float(item.get("score", 0))),
            "category": str(doc.get("category", "")),
            "tags": parse_tags(doc.get("tags")),
            "source": str(doc.get("source", "")),
            "created_at": str(doc.get("created_at", "")),
            "updated_at": str(doc.get("updated_at", "")),
        })
    return enriched


def _read_json_list(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, ValueError):
        return []
    return data if isinstance(data, list) else []


def _write_json(path: Path, data: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _legacy_documents() -> list[dict]:
    docs: list[dict] = []
    for item in _read_json_list(USER_DATA_FILE):
        text = normalize_text(str(item.get("text", "")))
        if not text:
            continue
        hash_value = str(item.get("text_hash") or text_hash(text))
        now = str(item.get("created_at") or utc_now())
        docs.append({
            "id": int(item.get("id", 0)),
            "document_id": str(item.get("document_id") or make_document_id(hash_value)),
            "text_hash": hash_value,
            "text": text,
            "category": str(item.get("category", "")),
            "tags": parse_tags(item.get("tags")),
            "source": str(item.get("source", "web")),
            "created_at": now,
            "updated_at": str(item.get("updated_at") or now),
        })
    return [doc for doc in docs if doc["id"] > 0]


def load_documents() -> list[dict]:
    if _postgres_enabled():
        return _pg().load_documents()
    docs = _read_json_list(DOCUMENTS_FILE)
    if docs:
        return docs
    legacy = _legacy_documents()
    if legacy:
        save_documents(legacy)
    return legacy


def save_documents(docs: list[dict]) -> None:
    if _postgres_enabled():
        _pg().replace_documents(docs)
        return
    docs_sorted = sorted(docs, key=lambda item: int(item.get("id", 0)))
    _write_json(DOCUMENTS_FILE, docs_sorted)
    _write_json(USER_DATA_FILE, docs_sorted)


def next_record_id(seed_files: Iterable[Path]) -> int:
    ids: list[int] = []
    for path in seed_files:
        for item in _read_json_list(path):
            value = item.get("id")
            if isinstance(value, int):
                ids.append(value)
    for item in load_documents():
        value = item.get("id")
        if isinstance(value, int):
            ids.append(value)
    return max(ids, default=0) + 1


def _existing_hashes(docs: list[dict]) -> set[str]:
    return {str(item.get("text_hash", "")) for item in docs if item.get("text_hash")}


def _document_indexes(docs: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    hash_index: dict[str, dict] = {}
    document_id_index: dict[str, dict] = {}
    for doc in docs:
        hash_value = str(doc.get("text_hash", ""))
        document_id = str(doc.get("document_id", ""))
        if hash_value:
            hash_index[hash_value] = doc
        if document_id:
            document_id_index[document_id] = doc
    return hash_index, document_id_index


def _existing_hit(
    doc: dict,
    *,
    reason: str,
    row_number: int | None = None,
    input_index: int | None = None,
) -> dict:
    hit = document_summary(doc)
    hit["reason"] = reason
    if row_number is not None:
        hit["row_number"] = row_number
    if input_index is not None:
        hit["input_index"] = input_index
    return hit


def build_documents_from_texts(
    texts: Iterable[str],
    *,
    seed_files: Iterable[Path],
    source: str = "api",
    category: str = "",
    tags: list[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    if _postgres_enabled():
        return _build_documents_from_texts_postgres(
            texts,
            source=source,
            category=category,
            tags=tags,
        )
    docs = load_documents()
    existing_by_hash, existing_by_document_id = _document_indexes(docs)
    next_id = next_record_id(seed_files)
    records: list[dict] = []
    existing_hits: list[dict] = []
    seen_by_hash: dict[str, dict] = {}
    seen_by_document_id: dict[str, dict] = {}
    now = utc_now()

    for input_index, raw_text in enumerate(texts, start=1):
        text = normalize_text(raw_text)
        if not text:
            continue
        hash_value = text_hash(text)
        document_id = make_document_id(hash_value)
        if hash_value in existing_by_hash:
            existing_hits.append(
                _existing_hit(existing_by_hash[hash_value], reason="text_hash", input_index=input_index)
            )
            continue
        if document_id in existing_by_document_id:
            existing_hits.append(
                _existing_hit(existing_by_document_id[document_id], reason="document_id", input_index=input_index)
            )
            continue
        record = {
            "id": next_id,
            "document_id": document_id,
            "text_hash": hash_value,
            "text": text,
            "category": category,
            "tags": tags or [],
            "source": source,
            "created_at": now,
            "updated_at": now,
        }
        records.append(record)
        existing_by_hash[hash_value] = record
        existing_by_document_id[document_id] = record
        next_id += 1

    return records, existing_hits


def _build_documents_from_texts_postgres(
    texts: Iterable[str],
    *,
    source: str = "api",
    category: str = "",
    tags: list[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    records: list[dict] = []
    existing_hits: list[dict] = []
    seen_by_hash: dict[str, dict] = {}
    seen_by_document_id: dict[str, dict] = {}
    now = utc_now()

    for input_index, raw_text in enumerate(texts, start=1):
        text = normalize_text(raw_text)
        if not text:
            continue
        hash_value = text_hash(text)
        document_id = make_document_id(hash_value)
        if hash_value in seen_by_hash:
            existing_hits.append(_existing_hit(seen_by_hash[hash_value], reason="text_hash", input_index=input_index))
            continue
        if document_id in seen_by_document_id:
            existing_hits.append(
                _existing_hit(seen_by_document_id[document_id], reason="document_id", input_index=input_index)
            )
            continue
        record = {
            "document_id": document_id,
            "text_hash": hash_value,
            "text": text,
            "category": category,
            "tags": tags or [],
            "source": source,
            "created_at": now,
            "updated_at": now,
        }
        reason, doc = _pg().insert_document(record)
        if reason == "inserted":
            records.append(doc)
            seen_by_hash[hash_value] = doc
            seen_by_document_id[document_id] = doc
        else:
            existing_hits.append(_existing_hit(doc, reason=reason, input_index=input_index))

    return records, existing_hits


def build_documents_from_rows(
    rows: Iterable[dict],
    *,
    seed_files: Iterable[Path],
    default_source: str,
) -> tuple[list[dict], list[dict], list[dict]]:
    if _postgres_enabled():
        return _build_documents_from_rows_postgres(rows, default_source=default_source)
    docs = load_documents()
    existing_by_hash, existing_by_document_id = _document_indexes(docs)
    next_id = next_record_id(seed_files)
    records: list[dict] = []
    existing_hits: list[dict] = []
    errors: list[dict] = []
    seen_by_hash: dict[str, dict] = {}
    seen_by_document_id: dict[str, dict] = {}

    for idx, row in enumerate(rows, start=1):
        text = normalize_text(str(row.get("text", "")))
        if not text:
            errors.append({"row_number": idx, "error": "缺少 text", "row": row})
            continue
        hash_value = text_hash(text)
        document_id = str(row.get("document_id") or make_document_id(hash_value)).strip()

        existing_doc = existing_by_document_id.get(document_id)
        if existing_doc is not None:
            if str(existing_doc.get("text_hash", "")) != hash_value:
                errors.append({
                    "row_number": idx,
                    "error": f"document_id 已存在但文本不同: {document_id}",
                    "row": row,
                })
                continue
            existing_hits.append(_existing_hit(existing_doc, reason="document_id", row_number=idx))
            continue

        existing_doc = existing_by_hash.get(hash_value)
        if existing_doc is not None:
            existing_hits.append(_existing_hit(existing_doc, reason="text_hash", row_number=idx))
            continue

        now = utc_now()
        record = {
            "id": next_id,
            "document_id": document_id,
            "text_hash": hash_value,
            "text": text,
            "category": str(row.get("category", "")),
            "tags": parse_tags(row.get("tags")),
            "source": str(row.get("source") or default_source),
            "created_at": now,
            "updated_at": now,
        }
        records.append(record)
        existing_by_hash[hash_value] = record
        existing_by_document_id[document_id] = record
        next_id += 1

    return records, existing_hits, errors


def _build_documents_from_rows_postgres(
    rows: Iterable[dict],
    *,
    default_source: str,
) -> tuple[list[dict], list[dict], list[dict]]:
    records: list[dict] = []
    existing_hits: list[dict] = []
    errors: list[dict] = []
    seen_by_hash: dict[str, dict] = {}
    seen_by_document_id: dict[str, dict] = {}

    for idx, row in enumerate(rows, start=1):
        text = normalize_text(str(row.get("text", "")))
        if not text:
            errors.append({"row_number": idx, "error": "缺少 text", "row": row})
            continue
        hash_value = text_hash(text)
        document_id = str(row.get("document_id") or make_document_id(hash_value)).strip()
        if document_id in seen_by_document_id:
            existing_hits.append(_existing_hit(seen_by_document_id[document_id], reason="document_id", row_number=idx))
            continue
        if hash_value in seen_by_hash:
            existing_hits.append(_existing_hit(seen_by_hash[hash_value], reason="text_hash", row_number=idx))
            continue
        now = utc_now()
        record = {
            "document_id": document_id,
            "text_hash": hash_value,
            "text": text,
            "category": str(row.get("category", "")),
            "tags": parse_tags(row.get("tags")),
            "source": str(row.get("source") or default_source),
            "created_at": now,
            "updated_at": now,
        }
        try:
            reason, doc = _pg().insert_document(record)
        except ValueError as exc:
            errors.append({"row_number": idx, "error": str(exc), "row": row})
            continue
        if reason == "inserted":
            records.append(doc)
            seen_by_hash[hash_value] = doc
            seen_by_document_id[document_id] = doc
        else:
            existing_hits.append(_existing_hit(doc, reason=reason, row_number=idx))

    return records, existing_hits, errors


def add_documents(records: list[dict]) -> None:
    if not records:
        return
    if _postgres_enabled():
        _pg().mark_documents_indexed(records)
        return
    docs = load_documents()
    docs.extend(records)
    save_documents(docs)


def list_documents(offset: int = 0, limit: int = 50) -> tuple[list[dict], int]:
    if _postgres_enabled():
        return _pg().list_documents(offset=offset, limit=limit)
    docs = load_documents()
    total = len(docs)
    return docs[offset: offset + limit], total


def get_document(record_id: int) -> dict | None:
    if _postgres_enabled():
        return _pg().get_document(record_id)
    for doc in load_documents():
        if int(doc.get("id", 0)) == record_id:
            return doc
    return None


def update_document(record_id: int, changes: dict) -> dict:
    if _postgres_enabled():
        current = get_document(record_id)
        if current is None:
            raise KeyError(f"文档不存在: {record_id}")
        new_text = normalize_text(str(changes.get("text", current.get("text", ""))))
        if not new_text:
            raise ValueError("text 不能为空")
        new_hash = text_hash(new_text)
        payload = {
            "document_id": str(changes.get("document_id") or current.get("document_id") or make_document_id(new_hash)),
            "text_hash": new_hash,
            "text": new_text,
            "category": str(changes.get("category", current.get("category", ""))),
            "tags": parse_tags(changes.get("tags", current.get("tags", []))),
            "source": str(changes.get("source", current.get("source", "api"))),
        }
        return _pg().update_document(record_id, payload)
    docs = load_documents()
    target: dict | None = None
    for doc in docs:
        if int(doc.get("id", 0)) == record_id:
            target = doc
            break
    if target is None:
        raise KeyError(f"文档不存在: {record_id}")

    new_text = normalize_text(str(changes.get("text", target.get("text", ""))))
    if not new_text:
        raise ValueError("text 不能为空")
    new_hash = text_hash(new_text)
    for doc in docs:
        if int(doc.get("id", 0)) != record_id and doc.get("text_hash") == new_hash:
            raise ValueError("已有相同文本，不能更新为重复内容")

    target["text"] = new_text
    target["text_hash"] = new_hash
    target["document_id"] = str(changes.get("document_id") or target.get("document_id") or make_document_id(new_hash))
    target["category"] = str(changes.get("category", target.get("category", "")))
    target["tags"] = parse_tags(changes.get("tags", target.get("tags", [])))
    target["source"] = str(changes.get("source", target.get("source", "api")))
    target["updated_at"] = utc_now()
    save_documents(docs)
    return target


def delete_document(record_id: int) -> bool:
    if _postgres_enabled():
        return _pg().delete_document(record_id)
    docs = load_documents()
    remaining = [doc for doc in docs if int(doc.get("id", 0)) != record_id]
    if len(remaining) == len(docs):
        return False
    save_documents(remaining)
    return True


def clear_documents() -> None:
    if _postgres_enabled():
        _pg().clear_documents()
        return
    save_documents([])


def parse_upload_rows(content: bytes, filename: str) -> list[dict]:
    decoded = content.decode("utf-8-sig")
    if filename.lower().endswith(".csv"):
        import csv
        import io

        return list(csv.DictReader(io.StringIO(decoded)))
    data = json.loads(decoded)
    if not isinstance(data, list):
        raise ValueError("JSON 顶层必须是数组")
    return data


def append_search_log(entry: dict) -> None:
    if _postgres_enabled():
        _pg().save_search_log(entry)
        return
    SEARCH_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"ts": utc_now(), **entry}
    with SEARCH_LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def summarize_import_errors(errors: list[dict]) -> list[str]:
    return [f"第 {int(item.get('row_number', 0))} 行：{item.get('error', '')}" for item in errors]


def create_import_job(
    *,
    source_filename: str,
    inserted: int,
    existing: list[dict],
    errors: list[dict],
) -> dict:
    job_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{secrets.token_hex(4)}"
    IMPORT_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    summary = {
        "job_id": job_id,
        "source_filename": source_filename,
        "status": "completed",
        "inserted": inserted,
        "existing_count": len(existing),
        "skipped": len(existing),
        "failed": len(errors),
        "created_at": utc_now(),
    }
    if errors:
        csv_path = import_job_failed_rows_path(job_id)
        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "row_number",
                    "error",
                    "text",
                    "document_id",
                    "category",
                    "tags",
                    "source",
                    "row_json",
                ],
            )
            writer.writeheader()
            for item in errors:
                row = item.get("row") if isinstance(item.get("row"), dict) else {}
                writer.writerow({
                    "row_number": item.get("row_number", ""),
                    "error": item.get("error", ""),
                    "text": row.get("text", ""),
                    "document_id": row.get("document_id", ""),
                    "category": row.get("category", ""),
                    "tags": json.dumps(parse_tags(row.get("tags")), ensure_ascii=False),
                    "source": row.get("source", ""),
                    "row_json": json.dumps(row, ensure_ascii=False),
                })
        summary["failed_rows_download_url"] = f"/api/import-jobs/{job_id}/failed-rows"
    if _postgres_enabled():
        _pg().save_import_job(summary, errors)
        return summary
    _write_json(IMPORT_REPORT_DIR / f"{job_id}.json", [summary])
    return summary


def load_import_job(job_id: str) -> dict | None:
    if _postgres_enabled():
        return _pg().load_import_job(job_id)
    data = _read_json_list(IMPORT_REPORT_DIR / f"{job_id}.json")
    return data[0] if data else None


def import_job_failed_rows_path(job_id: str) -> Path:
    return IMPORT_REPORT_DIR / f"{job_id}-failed-rows.csv"
