"""Daily controller — runs the full pipeline end to end.

Executes discovery -> scoring -> notify in sequence. Each stage is isolated in
its own try/except: if one stage raises, the traceback is logged and the
controller moves on to the next stage instead of aborting the whole run. A
summary of which stages succeeded or failed prints at the end.

Notify runs in send-only mode: it pushes the new roles and exits, without the
interactive ~2-minute listen loop, so an unattended daily run never blocks.

Usage:
    python -m src.daily
"""

from __future__ import annotations

import sys
import traceback

from . import run, score
from . import notify

# (label, callable, argv) — order matters: discovery feeds scoring feeds notify.
# argv is the argument list each stage's argparse should see. Setting it
# per-stage keeps daily's own CLI args from leaking into the sub-commands and
# lets us force notify into --send-only.
STAGES = [
    ("discovery", run.main, []),
    ("scoring", score.main, []),
    ("notify", notify.main, ["--send-only"]),
]


def _run_stage(fn, argv: list[str]) -> None:
    """Call a stage's main() with a controlled sys.argv, then restore it."""
    saved = sys.argv
    sys.argv = [saved[0], *argv]
    try:
        fn()
    finally:
        sys.argv = saved


def main() -> None:
    results: dict[str, str] = {}

    for name, fn, argv in STAGES:
        print(f"\n{'=' * 72}\n[daily] starting: {name}\n{'=' * 72}")
        try:
            _run_stage(fn, argv)
            results[name] = "ok"
        except Exception:
            results[name] = "FAILED"
            print(f"[daily] stage {name!r} raised — continuing to next stage:")
            traceback.print_exc()

    print(f"\n{'=' * 72}\n[daily] run summary\n{'=' * 72}")
    for name, _, _ in STAGES:
        print(f"  {name:12s} {results[name]}")


if __name__ == "__main__":
    main()
