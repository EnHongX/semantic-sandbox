"""Smoke test a running semantic search API service.

This script exercises the public health endpoint and the API-key-protected REST
surface. It expects the target API and its vector backend to be running.
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import Any

import requests


def _request(method: str, url: str, *, headers: dict[str, str], **kwargs: Any) -> requests.Response:
    res = requests.request(method, url, headers=headers, timeout=120, **kwargs)
    if res.status_code >= 400:
        raise RuntimeError(f"{method} {url} failed: {res.status_code} {res.text}")
    return res


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8888")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--api-key-header", default="X-API-Key")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    headers = {args.api_key_header: args.api_key} if args.api_key else {}
    marker = f"smoke test {int(time.time())}"

    health = _request("GET", f"{base_url}/health", headers={}).json()
    print(f"health ok: {health}")

    unauthorized = requests.get(f"{base_url}/api/documents", timeout=30)
    if args.api_key and unauthorized.status_code != 401:
        raise RuntimeError(f"expected 401 without API key, got {unauthorized.status_code}")

    ingest = _request(
        "POST",
        f"{base_url}/api/ingest",
        headers=headers,
        json={"texts": [marker], "category": "smoke", "tags": ["api"], "source": "smoke"},
    ).json()
    print(f"ingest ok: inserted={ingest.get('inserted')} skipped={ingest.get('skipped')}")

    docs = _request("GET", f"{base_url}/api/documents", headers=headers).json()
    print(f"documents ok: total={docs.get('total')}")

    search = _request(
        "POST",
        f"{base_url}/api/search",
        headers=headers,
        json={"query": marker, "limit": 3, "categories": ["smoke"]},
    ).json()
    print(f"search ok: results={len(search.get('results', []))}")

    reindex = _request("POST", f"{base_url}/api/reindex", headers=headers).json()
    print(f"reindex ok: indexed={reindex.get('indexed')}")

    cleared = _request("DELETE", f"{base_url}/api/records", headers=headers).json()
    print(f"clear ok: {cleared}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
