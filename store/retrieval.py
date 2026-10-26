"""A small, dependency-free BM25 (Okapi) index.

Hand-rolled so every line can be explained: tokenize, count term
frequencies per document, and score with the standard BM25 formula
    idf(t) * tf * (k1 + 1) / (tf + k1 * (1 - b + b * len(d) / avg_len))
summed over query terms. No embeddings, no external service.
"""

from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORD_TEXT = (
    "a an and are as at be but by can do does for from how i if in is it its me my "
    "of on or our so that the this to was we what when where which who will with you your"
)
_STOPWORDS = frozenset(_STOPWORD_TEXT.split())


def tokenize(text: str) -> list[str]:
    tokens = [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS]
    # crude plural folding so "returns" matches "return"
    return [t[:-1] if len(t) > 3 and t.endswith("s") and not t.endswith("ss") else t
            for t in tokens]


class BM25Index:
    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.doc_tokens = [tokenize(d) for d in documents]
        self.term_freqs = [Counter(toks) for toks in self.doc_tokens]
        self.avg_len = sum(len(t) for t in self.doc_tokens) / max(len(self.doc_tokens), 1)
        doc_freq: Counter[str] = Counter()
        for tf in self.term_freqs:
            doc_freq.update(tf.keys())
        n = len(documents)
        self.idf = {t: math.log(1 + (n - df + 0.5) / (df + 0.5)) for t, df in doc_freq.items()}

    def score(self, query_tokens: list[str], index: int) -> float:
        tf, length = self.term_freqs[index], len(self.doc_tokens[index])
        total = 0.0
        for term in query_tokens:
            if term not in tf:
                continue
            freq = tf[term]
            norm = freq + self.k1 * (1 - self.b + self.b * length / self.avg_len)
            total += self.idf[term] * freq * (self.k1 + 1) / norm
        return total

    def search(self, query: str, k: int) -> list[tuple[int, float]]:
        """Return up to k (doc_index, score) pairs with score > 0, best first."""
        q = tokenize(query)
        scored = [(i, self.score(q, i)) for i in range(len(self.doc_tokens))]
        scored = [(i, s) for i, s in scored if s > 0]
        scored.sort(key=lambda pair: (-pair[1], pair[0]))
        return scored[:k]
