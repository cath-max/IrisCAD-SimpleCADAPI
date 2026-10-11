#!/usr/bin/env python3
"""Build retrieval/embeddings.npy from catalog.jsonl via ZenMux/OpenAI embeddings.

Reads atomic catalog rows, assembles embedding_text with
embedding_text_from_record (not stored in jsonl), calls the embedding API,
and writes:
  - retrieval/embeddings.npy  (float32, shape [N, D], row-aligned with catalog)
  - retrieval/meta.json
  - retrieval/embedding_state.json  (per-id content_sha256 + row index for incremental)

Environment:
  EMBEDDING_API_KEY   (required; falls back to ZENMUX_API_KEY / OPENAI_API_KEY)
  EMBEDDING_BASE_URL  (default https://zenmux.ai/api/v1)
  EMBEDDING_MODEL     (default openai/text-embedding-3-small)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from build_api_catalog import embedding_text_from_record  # noqa: E402

DEFAULT_CATALOG = PROJECT_ROOT / "retrieval" / "catalog.jsonl"
DEFAULT_EMBEDDINGS = PROJECT_ROOT / "retrieval" / "embeddings.npy"
DEFAULT_META = PROJECT_ROOT / "retrieval" / "meta.json"
DEFAULT_STATE = PROJECT_ROOT / "retrieval" / "embedding_state.json"

DEFAULT_BASE_URL = "https://zenmux.ai/api/v1"
DEFAULT_MODEL = "openai/text-embedding-3-small"


def _api_key() -> str:
    for name in ("EMBEDDING_API_KEY", "ZENMUX_API_KEY", "OPENAI_API_KEY"):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    raise SystemExit(
        "Missing embedding API key. Set EMBEDDING_API_KEY "
        "(or ZENMUX_API_KEY / OPENAI_API_KEY)."
    )


def _base_url() -> str:
    raw = (os.environ.get("EMBEDDING_BASE_URL") or DEFAULT_BASE_URL).strip()
    return raw.rstrip("/")


def _model() -> str:
    return (os.environ.get("EMBEDDING_MODEL") or DEFAULT_MODEL).strip()


def load_catalog(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
    if not rows:
        raise SystemExit(f"Catalog is empty: {path}")
    return rows


def load_state(path: Path) -> dict:
    if not path.is_file():
        return {"model": None, "ids": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"model": None, "ids": {}}


def embedding_text_sha256(text: str) -> str:
    """Fingerprint the exact text submitted for one document embedding."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_meta(path: Path, *, stats: dict, catalog_path: Path) -> None:
    """Write retrieval/meta.json for the embeddings artifact.

    Consumers (retrieve / serve) load embeddings.npy + catalog.jsonl directly;
    meta.json is the human/CI-facing sidecar describing how the matrix was built.
    Schema matches the existing retrieval/meta.json layout.
    """
    meta = {
        "model": stats["model"],
        "base_url": stats["base_url"],
        "dimensions": stats["dimensions"],
        "doc_count": stats["doc_count"],
        "reused": stats["reused"],
        "embedded": stats["embedded"],
        "catalog": catalog_path.resolve().as_posix(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dtype": "float32",
        "layout": "row i of embeddings.npy aligns with line i of catalog.jsonl",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def embed_batch(
    *,
    texts: list[str],
    api_key: str,
    base_url: str,
    model: str,
    timeout_s: float = 120.0,
) -> list[list[float]]:
    """POST /embeddings; returns vectors in the same order as texts."""
    if not texts:
        return []
    url = f"{base_url}/embeddings"
    payload = {
        "model": model,
        "input": texts if len(texts) > 1 else texts[0],
        "encoding_format": "float",
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"Embedding HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Embedding request failed: {exc}") from exc

    data = body.get("data")
    if not isinstance(data, list) or len(data) != len(texts):
        raise SystemExit(
            f"Unexpected embedding response size: got {type(data)} "
            f"len={len(data) if isinstance(data, list) else 'n/a'}, "
            f"expected {len(texts)}"
        )
    ordered = sorted(data, key=lambda item: item.get("index", 0))
    vectors: list[list[float]] = []
    for item in ordered:
        emb = item.get("embedding")
        if not isinstance(emb, list) or not emb:
            raise SystemExit("Embedding response missing vector data")
        vectors.append(emb)
    return vectors


def build_embeddings(
    *,
    catalog: list[dict],
    api_key: str,
    base_url: str,
    model: str,
    state: dict,
    old_matrix: np.ndarray | None,
    batch_size: int,
    force: bool,
) -> tuple[np.ndarray, dict, dict]:
    """Return (matrix, new_state, stats)."""
    old_ids: dict = state.get("ids") or {}
    same_model = (state.get("model") == model) and not force

    # Map old id -> vector row (only reusable when model unchanged).
    old_vectors: dict[str, np.ndarray] = {}
    if (
        same_model
        and old_matrix is not None
        and old_matrix.ndim == 2
        and old_matrix.shape[0] > 0
    ):
        for entry_id, meta in old_ids.items():
            idx = meta.get("row")
            sha = meta.get("content_sha256")
            if not isinstance(idx, int):
                continue
            if idx < 0 or idx >= old_matrix.shape[0]:
                continue
            old_vectors[entry_id] = old_matrix[idx]

    reused = 0
    to_embed: list[tuple[int, str]] = []  # (catalog_index, text)
    pending_vectors: list[np.ndarray | None] = [None] * len(catalog)

    for i, row in enumerate(catalog):
        entry_id = row["id"]
        sha = row.get("content_sha256")
        embedding_text = embedding_text_from_record(row)
        embedding_sha = embedding_text_sha256(embedding_text)
        prev = old_ids.get(entry_id) if same_model else None
        legacy_unchanged = (
            prev
            and "embedding_text_sha256" not in prev
            and prev.get("content_sha256") == sha
        )
        if (
            prev
            and entry_id in old_vectors
            and (
                prev.get("embedding_text_sha256") == embedding_sha
                or legacy_unchanged
            )
        ):
            pending_vectors[i] = old_vectors[entry_id]
            reused += 1
        else:
            to_embed.append((i, embedding_text))

    embedded = 0
    dim: int | None = None
    if old_matrix is not None and old_matrix.ndim == 2 and old_matrix.shape[1] > 0:
        dim = int(old_matrix.shape[1])

    for start in range(0, len(to_embed), batch_size):
        chunk = to_embed[start : start + batch_size]
        texts = [text for _, text in chunk]
        vectors = embed_batch(
            texts=texts,
            api_key=api_key,
            base_url=base_url,
            model=model,
            )
        for (catalog_index, _), vector in zip(chunk, vectors):
            arr = np.asarray(vector, dtype=np.float32)
            if dim is None:
                dim = int(arr.shape[0])
            elif arr.shape[0] != dim:
                raise SystemExit(
                    f"Embedding dimension mismatch: got {arr.shape[0]}, expected {dim}"
                )
            pending_vectors[catalog_index] = arr
            embedded += 1
        print(f"  embedded batch {start // batch_size + 1}: {len(chunk)} vectors")

    if dim is None:
        raise SystemExit("No embedding dimensions available (empty catalog?)")

    matrix = np.zeros((len(catalog), dim), dtype=np.float32)
    new_ids: dict[str, dict] = {}
    for i, row in enumerate(catalog):
        vec = pending_vectors[i]
        if vec is None:
            raise SystemExit(f"Internal error: missing vector for {row.get('id')}")
        matrix[i] = vec
        new_ids[row["id"]] = {
            "row": i,
            "content_sha256": row.get("content_sha256"),
            "embedding_text_sha256": embedding_text_sha256(
                embedding_text_from_record(row)
            ),
        }

    new_state = {
        "model": model,
        "base_url": base_url,
        "dimensions": dim,
        "doc_count": len(catalog),
        "ids": new_ids,
    }
    stats = {
        "doc_count": len(catalog),
        "reused": reused,
        "embedded": embedded,
        "dimensions": dim,
        "model": model,
        "base_url": base_url,
    }
    return matrix, new_state, stats


def cosine_top_k(
    query_vec: np.ndarray,
    matrix: np.ndarray,
    catalog: list[dict],
    k: int = 5,
) -> list[tuple[float, dict]]:
    """Return top-k (score, row) by cosine similarity."""
    q = query_vec.astype(np.float32)
    q_norm = float(np.linalg.norm(q))
    if q_norm < 1e-12:
        raise SystemExit("Query embedding is a zero vector")
    q = q / q_norm
    doc_norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    doc_norms = np.maximum(doc_norms, 1e-12)
    normalized = matrix / doc_norms
    scores = normalized @ q
    k = min(k, len(catalog))
    top_idx = np.argsort(-scores)[:k]
    return [(float(scores[i]), catalog[int(i)]) for i in top_idx]


def run_smoke_queries(
    *,
    catalog: list[dict],
    matrix: np.ndarray,
    api_key: str,
    base_url: str,
    model: str,
    queries: list[str],
    k: int = 5,
) -> list[dict]:
    """Embed each query and print / return Top-k catalog hits."""
    reports: list[dict] = []
    print(f"\n=== Smoke query (top-{k}) ===")
    print(f"Matrix shape={matrix.shape}, catalog={len(catalog)}")
    for query in queries:
        vectors = embed_batch(
            texts=[query],
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
        q = np.asarray(vectors[0], dtype=np.float32)
        hits = cosine_top_k(q, matrix, catalog, k=k)
        print(f"\nQuery: {query!r}")
        hit_rows = []
        for rank, (score, row) in enumerate(hits, start=1):
            tags = ",".join(row.get("capability_tags") or [])
            line = (
                f"  {rank}. {score:.4f}  {row['id']}"
                f"  [{row.get('agent_priority')}]"
                f"  {row.get('doc_category')}"
                f"  tags={tags}"
            )
            print(line)
            hit_rows.append(
                {
                    "rank": rank,
                    "score": score,
                    "id": row["id"],
                    "symbol": row.get("symbol"),
                    "agent_priority": row.get("agent_priority"),
                    "doc_category": row.get("doc_category"),
                    "capability_tags": row.get("capability_tags") or [],
                }
            )
        reports.append({"query": query, "hits": hit_rows})
    return reports


DEFAULT_SMOKE_QUERIES = [
    "flange with bolt holes",
    "boolean cut a hole",
    "fillet round edges on a solid",
    "revolve a profile to make a cup",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Embed API catalog rows via ZenMux/OpenAI-compatible API.",
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--out", type=Path, default=DEFAULT_EMBEDDINGS)
    parser.add_argument("--meta", type=Path, default=DEFAULT_META)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-embed every row even if content_sha256 matches.",
    )
    parser.add_argument(
        "--smoke-query",
        action="store_true",
        help=(
            "Only run cosine Top-5 smoke tests against existing embeddings.npy "
            "(does not rebuild the matrix unless --force-rebuild is also passed)."
        ),
    )
    parser.add_argument(
        "--smoke-only",
        action="store_true",
        help=argparse.SUPPRESS,  # alias
    )
    parser.add_argument(
        "--query",
        action="append",
        default=None,
        help="Custom smoke query (repeatable). Defaults to built-in industrial probes.",
    )
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args(argv)
    smoke_only = args.smoke_query or args.smoke_only

    catalog_path = args.catalog.resolve()
    out_path = args.out.resolve()
    meta_path = args.meta.resolve()
    state_path = args.state.resolve()

    api_key = _api_key()
    base_url = _base_url()
    model = _model()
    catalog = load_catalog(catalog_path)

    if smoke_only:
        if not out_path.is_file():
            raise SystemExit(
                f"Missing {out_path}. Run without --smoke-query first to build embeddings."
            )
        matrix = np.load(out_path)
        if matrix.shape[0] != len(catalog):
            raise SystemExit(
                f"Row mismatch: embeddings {matrix.shape[0]} vs catalog {len(catalog)}. "
                "Rebuild embeddings."
            )
        queries = args.query if args.query else list(DEFAULT_SMOKE_QUERIES)
        reports = run_smoke_queries(
            catalog=catalog,
            matrix=matrix,
            api_key=api_key,
            base_url=base_url,
            model=model,
            queries=queries,
            k=max(1, args.top_k),
        )
        report_path = PROJECT_ROOT / "retrieval" / "smoke_query_report.json"
        report_path.write_text(
            json.dumps(
                {
                    "model": model,
                    "base_url": base_url,
                    "embeddings": out_path.as_posix(),
                    "top_k": args.top_k,
                    "results": reports,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"\nWrote {report_path}")
        return 0

    state = load_state(state_path)
    old_matrix = None
    if out_path.is_file():
        try:
            old_matrix = np.load(out_path)
        except Exception as exc:  # noqa: BLE001
            print(f"Warning: could not load existing {out_path}: {exc}")

    print(f"Catalog: {catalog_path} ({len(catalog)} rows)")
    print(f"Model: {model}")
    print(f"Base URL: {base_url}")
    print(f"Force: {args.force}")

    matrix, new_state, stats = build_embeddings(
        catalog=catalog,
        api_key=api_key,
        base_url=base_url,
        model=model,
        state=state,
        old_matrix=old_matrix,
        batch_size=max(1, args.batch_size),
        force=args.force,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(out_path, matrix)
    state_path.write_text(
        json.dumps(new_state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    write_meta(meta_path, stats=stats, catalog_path=catalog_path)

    print(
        f"Wrote {out_path} shape={matrix.shape} "
        f"(reused={stats['reused']}, embedded={stats['embedded']})"
    )
    print(f"Wrote {meta_path}")
    print(f"Wrote {state_path}")

    if args.query:
        run_smoke_queries(
            catalog=catalog,
            matrix=matrix,
            api_key=api_key,
            base_url=base_url,
            model=model,
            queries=args.query,
            k=max(1, args.top_k),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
