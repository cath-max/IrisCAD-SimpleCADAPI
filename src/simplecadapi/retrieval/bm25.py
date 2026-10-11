"""In-memory BM25 over catalog search_text (built once at startup)."""

from __future__ import annotations

import math
import re
from typing import Mapping, Sequence

from .search_text import search_text_from_record

_TOKEN_RE = re.compile(r"[a-z0-9_]+", re.I)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if len(t) > 1]


class Bm25Index:
    """Okapi BM25 scores for a fixed catalog (row-aligned)."""

    def __init__(
        self,
        catalog: Sequence[Mapping],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.k1 = k1
        self.b = b
        self.n = len(catalog)
        self._docs_tok = [tokenize(search_text_from_record(row)) for row in catalog]
        self._df: dict[str, int] = {}
        for toks in self._docs_tok:
            for term in set(toks):
                self._df[term] = self._df.get(term, 0) + 1
        total_len = sum(len(toks) for toks in self._docs_tok)
        self._avgdl = (total_len / self.n) if self.n else 1.0

    def scores(self, query: str) -> list[float]:
        q_terms = tokenize(query)
        if not q_terms or self.n == 0:
            return [0.0] * self.n

        out: list[float] = []
        k1, b, n, avgdl = self.k1, self.b, self.n, self._avgdl
        df = self._df
        for toks in self._docs_tok:
            tf: dict[str, int] = {}
            for t in toks:
                tf[t] = tf.get(t, 0) + 1
            score = 0.0
            dl = len(toks) or 1
            for term in q_terms:
                if term not in tf:
                    continue
                n_df = df.get(term, 0)
                idf = math.log(1 + (n - n_df + 0.5) / (n_df + 0.5))
                freq = tf[term]
                score += idf * (freq * (k1 + 1)) / (
                    freq + k1 * (1 - b + b * dl / avgdl)
                )
            out.append(score)
        return out
