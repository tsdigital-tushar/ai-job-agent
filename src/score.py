"""Entrypoint — Phase 2 scoring.

Usage (after a discovery run has populated the DB):
    python -m src.score            # score everything, print the ranked top matches
    python -m src.score --tier core
    python -m src.score --top 25

Reads listings from the DB, scores each against your profile, writes the result
to the `scores` table, and prints the ranked list. Nothing is deleted; in the
default 'flag' mode nothing is even dropped — mismatches just rank low.
"""

from __future__ import annotations

import argparse
import json
import os

from .config import load_config
from .db import Store
from .scoring.rules import apply_rules
from .scoring.scorer import Scorer, make_backend
from .scoring.decide import decide


def load_profile(cfg: dict) -> dict:
    path = cfg.get("profile_out", "data/profile.json")
    if not os.path.exists(path):
        raise SystemExit(
            f"No profile at {path}. Run `python -m src.run` first to build it."
        )
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--tier", choices=["core", "stretch", "skip"])
    args = ap.parse_args()

    cfg = load_config()
    profile = load_profile(cfg)

    backend, note = make_backend(cfg)
    if note:
        print(f"[scorer] {note}")
    print(f"[scorer] backend: {backend.name}  ·  mode: "
          f"{cfg.get('scoring', {}).get('mode', 'flag')}")

    with Store(cfg.get("db_path", "data/jobs.db")) as store:
        scorer = Scorer(backend, profile, cfg)
        n = 0
        for job in store.iter_jobs():
            rules = apply_rules(job, cfg, already_applied=store.is_applied(job.dedup_key))
            base = scorer.base_score(job)
            store.save_score(decide(job, base, rules, cfg))
            n += 1
        store.commit()

        counts = store.tier_counts()
        print(f"\n[scored] {n} listings  ·  "
              f"core={counts.get('core',0)}  stretch={counts.get('stretch',0)}  "
              f"skip={counts.get('skip',0)}\n")

        rows = store.top_scored(limit=args.top, tier=args.tier)
        header = f"Top {len(rows)}" + (f" · tier={args.tier}" if args.tier else "")
        print(f"{header}\n" + "-" * 72)
        for r in rows:
            pay = r["salary_raw"] or "—"
            print(f"  {r['score']:5.1f}  [{r['tier']:7s}/{r['decision']:5s}]  "
                  f"{r['title'][:42]:42s}  @ {r['company'][:20]}")
            print(f"          reason: {r['reason']}   pay: {pay}")


if __name__ == "__main__":
    main()
