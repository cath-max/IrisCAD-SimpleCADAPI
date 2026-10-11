#!/usr/bin/env python3
"""CLI: user utterance → exactly 20 practical SimpleCADAPI docs.

Examples:
  python scripts/retrieve_apis.py "make a mug, height 100mm"
  python scripts/retrieve_apis.py "boolean cut a hole" --no-body
  python scripts/retrieve_apis.py "flange" --out-md retrieval/last_slice.md
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from simplecadapi.retrieval import (  # noqa: E402
    RETRIEVE_TOP_K,
    format_api_prompt_slice,
    retrieve_apis,
)
from simplecadapi.retrieval.embed import resolve_api_key  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Retrieve top-K SimpleCADAPI docs for an agent prompt.",
    )
    parser.add_argument("query", help="User utterance / CAD intent")
    parser.add_argument(
        "--top-k",
        type=int,
        default=RETRIEVE_TOP_K,
        help=f"Final list length (default {RETRIEVE_TOP_K})",
    )
    parser.add_argument(
        "--no-body",
        action="store_true",
        help="Skip reading docs/api/*.md bodies (faster listing)",
    )
    parser.add_argument(
        "--bm25-only",
        action="store_true",
        help="Skip query embedding (no API key required)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show related-API expansion diagnostics on stderr",
    )
    parser.add_argument(
        "--operation",
        default=None,
        help="Force-include this API id (ErrorGuidance hook)",
    )
    parser.add_argument(
        "--out-md",
        type=Path,
        default=None,
        help="Write assembled prompt slice markdown to this path",
    )
    parser.add_argument(
        "--out-json",
        type=Path,
        default=None,
        help="Write hit list JSON (without full bodies unless bodies loaded)",
    )
    parser.add_argument(
        "--catalog",
        type=Path,
        default=PROJECT_ROOT / "retrieval" / "catalog.jsonl",
    )
    parser.add_argument(
        "--embeddings",
        type=Path,
        default=PROJECT_ROOT / "retrieval" / "embeddings.npy",
    )
    args = parser.parse_args(argv)
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")

    use_vector = not args.bm25_only
    if use_vector and resolve_api_key() is None:
        print(
            "warning: no EMBEDDING_API_KEY/ZENMUX_API_KEY; "
            "falling back to --bm25-only",
            file=sys.stderr,
        )
        use_vector = False

    hits = retrieve_apis(
        args.query,
        top_k=args.top_k,
        load_bodies=not args.no_body,
        catalog_path=args.catalog,
        embeddings_path=args.embeddings,
        repo_root=PROJECT_ROOT,
        use_vector=use_vector,
        operation=args.operation,
    )

    print(f"query={args.query!r}  hits={len(hits)}  vector={use_vector}")
    for i, hit in enumerate(hits, start=1):
        tags = ",".join(hit.capability_tags[:4])
        print(
            f"{i:2d}. {hit.score:7.4f}  [{hit.reason}]  "
            f"{hit.agent_priority:6}  {hit.id}  {tags}"
        )

    if args.out_md is not None:
        slice_md = format_api_prompt_slice(hits, include_body=not args.no_body)
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(slice_md, encoding="utf-8")
        print(f"wrote prompt slice -> {args.out_md}")

    if args.out_json is not None:
        payload = []
        for hit in hits:
            row = hit.to_dict()
            if args.no_body:
                row.pop("body_markdown", None)
            else:
                # Keep JSON smaller in default dumps unless bodies requested.
                body = row.get("body_markdown") or ""
                if len(body) > 2000:
                    row["body_markdown"] = body[:2000] + "…"
            payload.append(row)
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"wrote json -> {args.out_json}")

    return 0 if len(hits) == args.top_k else 1


if __name__ == "__main__":
    raise SystemExit(main())
