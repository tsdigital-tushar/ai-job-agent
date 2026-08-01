"""Config loading.

All tunable knobs live in `config.yaml` at the repo root so filters can change
without editing code. This module just reads that file and hands back a plain
dict, with a couple of convenience accessors.
"""

from __future__ import annotations

import os
import yaml

_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml"
)


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge `override` into `base` (in place). Nested dicts merge
    key-by-key, so a local secret overrides one field without wiping its
    siblings; any non-dict value replaces the base value."""
    for key, val in (override or {}).items():
        if isinstance(val, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], val)
        else:
            base[key] = val
    return base


def load_config(path: str | None = None) -> dict:
    path = path or _DEFAULT_PATH
    with open(path, "r", encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    # Layer real secrets from config.local.yaml (gitignored) over the committed
    # placeholders, so nothing sensitive lives in the tracked config.yaml.
    local_path = os.path.join(os.path.dirname(path), "config.local.yaml")
    if os.path.exists(local_path):
        with open(local_path, "r", encoding="utf-8") as fh:
            local = yaml.safe_load(fh) or {}
        _deep_merge(cfg, local)
    return cfg


def enabled_sources(cfg: dict) -> list[str]:
    """Names of sources with `enabled: true` in config."""
    sources = cfg.get("sources", {}) or {}
    return [name for name, s in sources.items() if (s or {}).get("enabled")]
