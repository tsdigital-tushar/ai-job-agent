"""Entrypoint — Phase 1 discovery run.

Usage (on your machine, with network access):
    python -m src.run                 # build profile if missing, then poll sources

It loads config, ensures the resume profile exists, polls every enabled source
live, stores new listings, and prints a short digest. Later phases add scoring
and the Telegram loop after this step.
"""

from __future__ import annotations

import argparse
import os

from .config import load_config, enabled_sources
from .db import Store
from .pipeline import ingest_live
from .profile.resume_parser import build_profile


def ensure_profile(cfg: dict, force: bool = False) -> None:
    out = cfg.get("profile_out", "data/profile.json")
    resume = cfg.get("resume_path")
    if os.path.exists(out) and not force:
        return
    if resume and os.path.exists(resume):
        prof = build_profile(resume, cfg)
        prof.to_json(out)
        print(f"[profile] {'rebuilt' if force else 'built'} from {resume} -> {out} "
              f"({len(prof.skills)} skills detected)")
    else:
        print(f"[profile] no resume at {resume!r}; skipping profile build")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh-profile", action="store_true",
                    help="rebuild the profile from the resume PDF even if "
                         "data/profile.json already exists (ignore the cache)")
    args = ap.parse_args()

    cfg = load_config()
    os.makedirs("data", exist_ok=True)
    ensure_profile(cfg, force=args.refresh_profile)

    sources = enabled_sources(cfg)
    db_path = cfg.get("db_path", "data/jobs.db")
    with Store(db_path) as store:
        summary = ingest_live(sources, store, cfg)
        print("\n[discovery] run complete")
        for name, res in summary.items():
            if "error" in res:
                print(f"  {name:12s} ERROR: {res['error']}")
            else:
                print(f"  {name:12s} parsed={res['parsed']:4d} "
                      f"new={res['new']:4d} seen={res['seen']:4d}")
        print(f"\n  total listings in db: {store.count()}")


if __name__ == "__main__":
    main()
