"""Load doc embeddings + embed a query via ZenMux/OpenAI-compatible API."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Sequence

import numpy as np

DEFAULT_BASE_URL = "https://zenmux.ai/api/v1"
DEFAULT_MODEL = "openai/text-embedding-3-small"


def default_embeddings_path() -> Path:
    return Path(__file__).resolve().parents[3] / "retrieval" / "embeddings.npy"


def resolve_api_key() -> str | None:
    for name in ("EMBEDDING_API_KEY", "ZENMUX_API_KEY", "OPENAI_API_KEY"):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return None


def resolve_base_url() -> str:
    raw = (os.environ.get("EMBEDDING_BASE_URL") or DEFAULT_BASE_URL).strip()
    return raw.rstrip("/")


def resolve_model() -> str:
    return (os.environ.get("EMBEDDING_MODEL") or DEFAULT_MODEL).strip()


def load_embeddings(path: Path | None = None) -> np.ndarray:
    emb_path = path or default_embeddings_path()
    if not emb_path.is_file():
        raise FileNotFoundError(f"Embeddings not found: {emb_path}")
    matrix = np.load(emb_path)
    if matrix.ndim != 2:
        raise ValueError(f"Expected 2-D embeddings, got shape {matrix.shape}")
    return matrix.astype(np.float32, copy=False)


def cosine_similarities(matrix: np.ndarray, query_vec: Sequence[float]) -> np.ndarray:
    """Row-wise cosine similarity; returns shape [N]."""
    q = np.asarray(query_vec, dtype=np.float32)
    q_norm = float(np.linalg.norm(q))
    if q_norm < 1e-12:
        return np.zeros(matrix.shape[0], dtype=np.float32)
    q = q / q_norm
    norms = np.linalg.norm(matrix, axis=1)
    norms = np.maximum(norms, 1e-12)
    return (matrix @ q) / norms


def embed_texts(
    texts: list[str],
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    timeout_s: float = 60.0,
) -> list[list[float]]:
    """POST /embeddings; returns vectors in the same order as texts."""
    if not texts:
        return []
    key = api_key if api_key is not None else resolve_api_key()
    if not key:
        raise RuntimeError(
            "Missing embedding API key. Set EMBEDDING_API_KEY "
            "(or ZENMUX_API_KEY / OPENAI_API_KEY)."
        )
    url = f"{(base_url or resolve_base_url()).rstrip('/')}/embeddings"
    payload = {
        "model": model or resolve_model(),
        "input": texts if len(texts) > 1 else texts[0],
        "encoding_format": "float",
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Embedding HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Embedding request failed: {exc}") from exc

    data = body.get("data")
    if not isinstance(data, list) or len(data) != len(texts):
        raise RuntimeError(
            f"Unexpected embedding response size: expected {len(texts)}, "
            f"got {len(data) if isinstance(data, list) else type(data)}"
        )
    ordered = sorted(data, key=lambda item: item.get("index", 0))
    vectors: list[list[float]] = []
    for item in ordered:
        emb = item.get("embedding")
        if not isinstance(emb, list) or not emb:
            raise RuntimeError("Embedding response missing vector data")
        vectors.append(emb)
    return vectors


def embed_query(query: str, **kwargs) -> list[float]:
    return embed_texts([query], **kwargs)[0]
