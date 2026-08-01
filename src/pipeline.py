"""Ingestion pipeline (Phase 1: discovery).

Ties the pieces together: for each enabled source, fetch listings, normalize
them to `Job`s, and upsert into the store (which handles dedup + history).
Scoring and notifications are later phases; this stage's only job is to build a
clean, de-duplicated pool of listings.

`ingest_live()` hits the network (run on your machine). `ingest_payloads()`
takes pre-fetched payloads and is what the tests use.
"""

from __future__ import annotations

from .db import Store
from .sources import build_source


def ingest_payloads(payloads: dict[str, object], store: Store) -> dict:
    """payloads: {source_name: raw_payload}. Returns a per-source summary."""
    summary = {}
    for name, payload in payloads.items():
        source = build_source(name)
        jobs = source.parse(payload)
        result = store.upsert_many(jobs)
        result["parsed"] = len(jobs)
        summary[name] = result
    return summary


def ingest_live(source_names: list[str], store: Store, cfg: dict | None = None) -> dict:
    """Hit each source's live API. For use on the user's machine."""
    summary = {}
    for name in source_names:
        source = build_source(name, cfg)
        try:
            jobs = source.fetch()
        except Exception as exc:  # a dead source shouldn't kill the whole run
            summary[name] = {"error": str(exc)}
            continue
        result = store.upsert_many(jobs)
        result["parsed"] = len(jobs)
        summary[name] = result
    return summary
