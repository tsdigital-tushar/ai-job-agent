"""Common data model.

Every source adapter, no matter how different its raw payload, converts its
listings into a `Job`. Everything downstream (dedup, scoring, notifications)
only ever touches `Job` — never a source's raw shape. That single normalized
schema is what keeps the rest of the system simple.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Job:
    # --- provenance ---
    source: str                      # e.g. "remotive"
    source_id: str                   # the id this source assigns the listing
    url: str                         # where a human applies

    # --- core fields ---
    title: str
    company: str
    location: str = ""
    remote: bool = False

    # --- pay (any of these may be missing; most listings omit salary) ---
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    salary_raw: str = ""             # the original salary text, kept for auditing

    # --- extras ---
    posted_at: str = ""              # ISO date string if the source gives one
    tags: list[str] = field(default_factory=list)
    description: str = ""
    raw: dict = field(default_factory=dict)   # untouched source record, for debugging

    @property
    def dedup_key(self) -> str:
        """Stable identity for a listing, used to avoid applying twice.

        Prefer source + source_id. If a source gives no usable id, fall back to
        a hash of the fields that identify a posting to a human.
        """
        if self.source_id:
            return f"{self.source}:{self.source_id}"
        basis = f"{self.title}|{self.company}|{self.url}".lower()
        digest = hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]
        return f"{self.source}:h:{digest}"

    def to_row(self) -> dict:
        """Flatten to a dict ready for the DB layer (lists/dicts -> JSON text)."""
        d = asdict(self)
        d["tags"] = json.dumps(self.tags, ensure_ascii=False)
        d["raw"] = json.dumps(self.raw, ensure_ascii=False)
        d["remote"] = 1 if self.remote else 0
        d["dedup_key"] = self.dedup_key
        return d
