"""Scorer — the AI 'meaning match'.

Compares a job's text to your profile by meaning, not keywords, so a BA role
that describes requirements-gathering and functional specs scores high even if
it never says "SAP".

Backend is pluggable:
  - SentenceTransformerBackend: real semantic embeddings (default on your
    machine). Lazily imported so the model is only loaded if selected.
  - LexicalBackend: a dependency-free bag-of-words cosine fallback. Runs with no
    model download, so the pipeline never hard-fails and tests run offline.

If the sentence-transformers import/model load fails, we fall back to lexical
automatically and note it, rather than crashing a run.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from ..models import Job

_HTML = re.compile(r"<[^>]+>")
_WORD = re.compile(r"[a-z0-9][a-z0-9+/#.-]*")
_STOP = {
    "the", "and", "for", "with", "you", "our", "your", "are", "will", "have",
    "this", "that", "job", "role", "work", "team", "years", "year", "experience",
    "a", "an", "to", "of", "in", "on", "as", "at", "is", "be", "or", "we",
}


def clean_text(text: str) -> str:
    return _HTML.sub(" ", text or "")


def tokens(text: str) -> list[str]:
    return [w for w in _WORD.findall(clean_text(text).lower())
            if w not in _STOP and len(w) > 1]


def profile_reference(profile: dict, cfg: dict | None = None) -> str:
    """Build the reference text we match every job against.

    We prepend a small set of preference anchors (product / data / analytics)
    so the embedding match itself leans toward the roles Tushar actually wants,
    rather than relying only on after-the-fact rule penalties. Anchors are
    overridable via config.scoring.profile_anchors.
    """
    cfg = cfg or {}
    anchors = (cfg.get("scoring", {}) or {}).get("profile_anchors", [
        "product management", "product owner", "product roadmap",
        "product analytics", "data analytics", "business intelligence",
        "AI product", "stakeholder management", "user stories", "go-to-market",
    ])
    parts = list(anchors)                       # anchors first (weighted)
    parts += profile.get("target_titles", [])
    parts += profile.get("skills", [])
    parts += profile.get("domains", [])
    return " . ".join(p for p in parts if p)


def job_reference(job: Job) -> str:
    """Weight the title (repeat it) since it carries the most signal."""
    title = job.title or ""
    tags = " ".join(job.tags or [])
    desc = clean_text(job.description or "")[:2000]
    return f"{title} . {title} . {tags} . {desc}"


# ---- backends -------------------------------------------------------------

class LexicalBackend:
    name = "lexical"

    def encode(self, text: str) -> Counter:
        return Counter(tokens(text))

    def similarity(self, a: Counter, b: Counter) -> float:
        if not a or not b:
            return 0.0
        common = set(a) & set(b)
        dot = sum(a[t] * b[t] for t in common)
        na = math.sqrt(sum(v * v for v in a.values()))
        nb = math.sqrt(sum(v * v for v in b.values()))
        return dot / (na * nb) if na and nb else 0.0


class SentenceTransformerBackend:
    name = "sentence-transformers"

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer  # lazy
        self._model = SentenceTransformer(model_name)

    def encode(self, text: str):
        return self._model.encode(text, normalize_embeddings=True)

    def similarity(self, a, b) -> float:
        return float(sum(x * y for x, y in zip(a, b)))   # both normalized


def make_backend(cfg: dict):
    """Return the configured backend, falling back to lexical on any failure."""
    sc = cfg.get("scoring", {}) or {}
    want = sc.get("backend", "sentence-transformers")
    if want == "lexical":
        return LexicalBackend(), None
    try:
        return SentenceTransformerBackend(sc.get("model", "all-MiniLM-L6-v2")), None
    except Exception as exc:
        return LexicalBackend(), f"sentence-transformers unavailable ({exc}); using lexical fallback"


class Scorer:
    """Encodes the profile once, then scores many jobs against it."""

    def __init__(self, backend, profile: dict, cfg: dict | None = None):
        self.backend = backend
        self._pref_vec = backend.encode(profile_reference(profile, cfg))

    def base_score(self, job: Job) -> float:
        """0-100 meaning-match score, before rule penalties."""
        jvec = self.backend.encode(job_reference(job))
        sim = self.backend.similarity(self._pref_vec, jvec)
        return max(0.0, min(1.0, sim)) * 100.0
