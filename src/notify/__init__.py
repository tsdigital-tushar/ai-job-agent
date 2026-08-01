"""Entrypoint — Phase 3 Telegram push.

Usage (from job-agent folder, venv active):
    python -m src.notify --whoami        # print your chat_id (run once, after messaging your bot)
    python -m src.notify                 # push top roles, then listen ~2 min for taps
    python -m src.notify --send-only     # push and exit (no listening)
    python -m src.notify --top 10 --tier core

Reads token + chat_id from config.telegram. Pushes the top unsent, non-skip
roles as cards with Apply/Draft/Skip buttons; taps are logged to the DB so the
same role never gets pushed twice.
"""

from __future__ import annotations

import argparse

from ..config import load_config
from ..db import Store
from .telegram import Telegram


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=None)
    ap.add_argument("--tier", default=None, help="core|stretch (default: config or core)")
    ap.add_argument("--send-only", action="store_true", help="don't listen for taps")
    ap.add_argument("--listen", type=int, default=None, help="seconds to listen for taps")
    ap.add_argument("--whoami", action="store_true", help="print your chat_id and exit")
    ap.add_argument("--collect", action="store_true",
                    help="don't push cards; poll pending taps, record them, and exit")
    args = ap.parse_args()

    cfg = load_config()
    tg_cfg = cfg.get("telegram", {}) or {}
    token = tg_cfg.get("token", "")

    # --whoami only needs the token
    if args.whoami:
        tg = Telegram(token, chat_id="whoami-placeholder")
        print(tg.get_chat_id_hint())
        return

    tg = Telegram(token, tg_cfg.get("chat_id", ""))

    # --collect: don't push anything. Drain the taps already sitting in
    # Telegram's update queue, record each to the applications table, and exit.
    # Reuses poll_updates, which both answers each callback and advances the
    # getUpdates offset so collected taps are acknowledged (not re-processed).
    if args.collect:
        collect_secs = args.listen if args.listen is not None else 3
        tally = {"apply": 0, "draft": 0, "skip": 0, "other": 0}
        with Store(cfg.get("db_path", "data/jobs.db")) as store:
            def on_tap(action, key):
                store.record_application(key, status=action, channel="telegram")
                tally[action if action in tally else "other"] += 1
                print(f"   • {action:6s} -> {key}")

            print(f"[notify] collecting pending taps (polling up to {collect_secs}s)…")
            try:
                n = tg.poll_updates(collect_secs, on_tap)
            except KeyboardInterrupt:
                n = sum(tally.values())
                print("\n[notify] interrupted — taps so far are saved.")
        print(f"[notify] collected {n} tap(s)  ·  apply={tally['apply']} "
              f"draft={tally['draft']} skip={tally['skip']}"
              + (f" other={tally['other']}" if tally['other'] else ""))
        return

    top = args.top or tg_cfg.get("push_top", 20)
    tier = args.tier or tg_cfg.get("push_tier", "core")
    listen_secs = args.listen if args.listen is not None else tg_cfg.get("listen_seconds", 120)

    with Store(cfg.get("db_path", "data/jobs.db")) as store:
        rows = store.unsent_top(limit=top, tier=tier)
        if not rows:
            tg.send_text("No new roles to review right now. ✅")
            print("[notify] nothing new to push.")
            return

        tg.send_text(f"📋 {len(rows)} new roles to review — tap Apply / Draft / Skip:")
        for r in rows:
            tg.send_role(r["dedup_key"], r["title"], r["company"],
                         r["score"], r["reason"], r["url"])
        print(f"[notify] pushed {len(rows)} roles to Telegram.")

        if args.send_only:
            return

        print(f"[notify] listening {listen_secs}s for your taps… (Ctrl-C to stop)")

        def on_tap(action, key):
            store.record_application(key, status=action, channel="telegram")
            print(f"   • {action:6s} -> {key}")

        try:
            n = tg.poll_updates(listen_secs, on_tap)
            print(f"[notify] recorded {n} taps.")
        except KeyboardInterrupt:
            print("\n[notify] stopped listening. Taps so far are saved.")


if __name__ == "__main__":
    main()
