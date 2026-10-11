#!/usr/bin/env python3
"""HTTP sidecar: warm ApiRetriever for CADAM (or any agent) prompt slices.

Endpoints:
  GET  /health
  POST /retrieve  JSON body → { markdown, hit_ids, reasons, ... }

Examples:
  python scripts/serve_api_retrieval.py --host 127.0.0.1 --port 8765
  curl -s http://127.0.0.1:8765/health
  curl -s -X POST http://127.0.0.1:8765/retrieve \\
    -H "Content-Type: application/json" \\
    -d "{\"query\":\"make a mug, height 100mm\"}"
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Importing ``simplecadapi.retrieval`` normally executes the public package's
# eager ``simplecadapi.__init__`` first, which loads the complete OCP CAD
# runtime. The retrieval service needs only the pure-Python retrieval package
# and NumPy. Register a namespace parent for this process so Python can resolve
# the retrieval subpackage without loading OCP or its native system libraries.
if "simplecadapi" not in sys.modules:
    simplecadapi_namespace = types.ModuleType("simplecadapi")
    simplecadapi_namespace.__path__ = [str(SRC / "simplecadapi")]
    simplecadapi_namespace.__package__ = "simplecadapi"
    sys.modules["simplecadapi"] = simplecadapi_namespace

from simplecadapi.retrieval import (  # noqa: E402
    RETRIEVE_TOP_K,
    ApiRetriever,
    format_api_prompt_slice,
    select_core_hits,
)
from simplecadapi.retrieval.catalog_io import load_catalog  # noqa: E402
from simplecadapi.retrieval.embed import (  # noqa: E402
    default_embeddings_path,
    load_embeddings,
    resolve_api_key,
)
from simplecadapi.retrieval.load_md import attach_bodies  # noqa: E402

logger = logging.getLogger("serve_api_retrieval")

# Process-global warm engine (set in main before serving).
_ENGINE: ApiRetriever | None = None
_USE_VECTOR_DEFAULT = False
_EMBEDDINGS_LOADED = False


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length_raw = handler.headers.get("Content-Length") or "0"
    try:
        length = int(length_raw)
    except ValueError as exc:
        raise ValueError("invalid Content-Length") from exc
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    if not raw:
        return {}
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")
    return data


def build_engine(
    *,
    catalog_path: Path,
    embeddings_path: Path,
    repo_root: Path,
) -> tuple[ApiRetriever, bool, bool]:
    """Load catalog once; load embeddings if present else zeros (BM25-only)."""
    catalog = load_catalog(catalog_path)
    embeddings_loaded = False
    if embeddings_path.is_file():
        embeddings = load_embeddings(embeddings_path)
        embeddings_loaded = True
    else:
        logger.warning(
            "embeddings not found at %s; starting BM25-only with zero matrix",
            embeddings_path,
        )
        embeddings = np.zeros((len(catalog), 1), dtype=np.float32)

    engine = ApiRetriever(
        catalog=catalog,
        embeddings=embeddings,
        repo_root=repo_root,
        catalog_path=catalog_path,
        embeddings_path=embeddings_path,
    )
    use_vector_default = embeddings_loaded and resolve_api_key() is not None
    if embeddings_loaded and not use_vector_default:
        logger.warning(
            "no EMBEDDING_API_KEY/ZENMUX_API_KEY/OPENAI_API_KEY; "
            "defaulting requests to BM25-only (pass use_vector=true only if key set)"
        )
    return engine, use_vector_default, embeddings_loaded


def handle_retrieve(body: dict[str, Any]) -> dict[str, Any]:
    assert _ENGINE is not None
    core_only = bool(body.get("core_only"))
    query = body.get("query")
    if query is None:
        query = ""
    if not isinstance(query, str):
        raise ValueError("query must be a string")

    top_k = body.get("top_k", RETRIEVE_TOP_K)
    if not isinstance(top_k, int) or top_k < 1:
        raise ValueError("top_k must be a positive integer")

    operation = body.get("operation")
    if operation is not None and not isinstance(operation, str):
        raise ValueError("operation must be a string or null")
    if isinstance(operation, str) and not operation.strip():
        operation = None

    exclude_ids = body.get("exclude_ids", [])
    if not isinstance(exclude_ids, list) or not all(
        isinstance(api_id, str) and api_id.strip() for api_id in exclude_ids
    ):
        raise ValueError("exclude_ids must be an array of non-empty strings")
    exclude_ids = tuple(dict.fromkeys(exclude_ids))

    use_vector = body.get("use_vector")
    if use_vector is None:
        use_vector = _USE_VECTOR_DEFAULT
    elif not isinstance(use_vector, bool):
        raise ValueError("use_vector must be a boolean")
    if use_vector and resolve_api_key() is None:
        logger.info("use_vector requested but no API key; forcing BM25-only")
        use_vector = False

    load_bodies = body.get("load_bodies", True)
    if not isinstance(load_bodies, bool):
        raise ValueError("load_bodies must be a boolean")

    # Empty query or explicit core_only → core pack only (CADAM downtime fallback).
    if core_only or not query.strip():
        hits = [
            hit
            for hit in select_core_hits(_ENGINE.catalog)
            if hit.id not in exclude_ids
        ]
        if load_bodies:
            hits = attach_bodies(hits, repo_root=_ENGINE.repo_root)
        mode = "core_only"
    else:
        hits = _ENGINE.retrieve(
            query.strip(),
            top_k=top_k,
            load_bodies=load_bodies,
            use_vector=use_vector,
            operation=operation,
            exclude_ids=exclude_ids,
        )
        mode = "hybrid"

    markdown = format_api_prompt_slice(hits, include_body=load_bodies)
    return {
        "ok": True,
        "mode": mode,
        "query": query.strip(),
        "top_k": top_k if mode == "hybrid" else len(hits),
        "use_vector": use_vector if mode == "hybrid" else False,
        "operation": operation,
        "exclude_ids": list(exclude_ids),
        "hit_ids": [h.id for h in hits],
        "reasons": [h.reason for h in hits],
        "markdown": markdown,
    }


class RetrievalHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/health":
            assert _ENGINE is not None
            _json_response(
                self,
                200,
                {
                    "ok": True,
                    "doc_count": len(_ENGINE.catalog),
                    "use_vector_default": _USE_VECTOR_DEFAULT,
                    "embeddings_loaded": _EMBEDDINGS_LOADED,
                    "top_k_default": RETRIEVE_TOP_K,
                },
            )
            return
        _json_response(self, 404, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/retrieve":
            _json_response(self, 404, {"ok": False, "error": "not found"})
            return
        try:
            body = _read_json_body(self)
            payload = handle_retrieve(body)
            _json_response(self, 200, payload)
        except json.JSONDecodeError:
            _json_response(self, 400, {"ok": False, "error": "invalid JSON"})
        except ValueError as exc:
            _json_response(self, 400, {"ok": False, "error": str(exc)})
        except Exception as exc:  # noqa: BLE001 — surface to client for local dev
            logger.exception("retrieve failed")
            _json_response(self, 500, {"ok": False, "error": str(exc)})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Warm HTTP sidecar for SimpleCADAPI hybrid API retrieval.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--catalog",
        type=Path,
        default=PROJECT_ROOT / "retrieval" / "catalog.jsonl",
    )
    parser.add_argument(
        "--embeddings",
        type=Path,
        default=default_embeddings_path(),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=PROJECT_ROOT,
        help="Root used to resolve docs/api/*.md paths from catalog",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="DEBUG logging",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    global _ENGINE, _USE_VECTOR_DEFAULT, _EMBEDDINGS_LOADED
    _ENGINE, _USE_VECTOR_DEFAULT, _EMBEDDINGS_LOADED = build_engine(
        catalog_path=args.catalog,
        embeddings_path=args.embeddings,
        repo_root=args.repo_root,
    )
    logger.info(
        "ApiRetriever ready: docs=%d embeddings_loaded=%s use_vector_default=%s",
        len(_ENGINE.catalog),
        _EMBEDDINGS_LOADED,
        _USE_VECTOR_DEFAULT,
    )

    server = ThreadingHTTPServer((args.host, args.port), RetrievalHandler)
    logger.info("listening on http://%s:%d", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("shutting down")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
