"""Source registry.

Maps config names to adapter classes. Most adapters need no config, but Adzuna
needs credentials + the list of title queries, so `build_source` optionally
takes the loaded config and wires those in.
"""

from __future__ import annotations

from .remotive import RemotiveSource
from .remoteok import RemoteOKSource
from .adzuna import AdzunaSource
from .greenhouse import GreenhouseSource

REGISTRY = {
    RemotiveSource.name: RemotiveSource,
    RemoteOKSource.name: RemoteOKSource,
    AdzunaSource.name: AdzunaSource,
    GreenhouseSource.name: GreenhouseSource,
}


def build_source(name: str, cfg: dict | None = None):
    if name not in REGISTRY:
        raise KeyError(f"Unknown source '{name}'. Known: {sorted(REGISTRY)}")

    if name == "adzuna":
        cfg = cfg or {}
        s = (cfg.get("sources", {}) or {}).get("adzuna", {}) or {}
        # Query Adzuna once per target title so the pool is pre-biased to your roles.
        queries = cfg.get("target_titles", []) or [""]
        return AdzunaSource(
            app_id=s.get("app_id", ""),
            app_key=s.get("app_key", ""),
            country=s.get("country", "in"),
            queries=queries,
            results_per_page=s.get("results_per_page", 50),
        )

    if name == "greenhouse":
        cfg = cfg or {}
        s = (cfg.get("sources", {}) or {}).get("greenhouse", {}) or {}
        return GreenhouseSource(companies=s.get("companies", []) or [])

    return REGISTRY[name]()
