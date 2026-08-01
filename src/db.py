"""Storage layer (SQLite).

This is the system's memory. It does three jobs:
  1. Dedup   - never surface or apply to the same listing twice.
  2. History - keep every listing seen, when, and (later) what we did about it.
  3. Audit   - one place to answer "why did the agent do X?"

Phase 1 only writes the `jobs` table. The `scores` and `applications` tables
are created now so the schema is stable; later phases fill them in.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Iterable

from .models import Job

_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    dedup_key       TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    source_id       TEXT,
    title           TEXT NOT NULL,
    company         TEXT,
    location        TEXT,
    remote          INTEGER DEFAULT 0,
    url             TEXT,
    salary_min      REAL,
    salary_max      REAL,
    salary_currency TEXT,
    salary_raw      TEXT,
    posted_at       TEXT,
    tags            TEXT,
    description     TEXT,
    raw             TEXT,
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS scores (
    dedup_key   TEXT PRIMARY KEY REFERENCES jobs(dedup_key),
    score       REAL,
    tier        TEXT,          -- core | stretch | skip
    decision    TEXT,          -- auto | draft | skip
    reason      TEXT,
    scored_at   TEXT
);

CREATE TABLE IF NOT EXISTS applications (
    dedup_key    TEXT PRIMARY KEY REFERENCES jobs(dedup_key),
    status       TEXT,         -- pending | approved | submitted | skipped
    channel      TEXT,         -- auto | telegram | assisted
    resume_ver   TEXT,
    acted_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_source   ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_jobs_seen      ON jobs(first_seen);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str = "data/jobs.db"):
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- context manager sugar --
    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def has_seen(self, dedup_key: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM jobs WHERE dedup_key = ? LIMIT 1", (dedup_key,)
        )
        return cur.fetchone() is not None

    def upsert(self, job: Job) -> bool:
        """Insert a listing, or refresh last_seen if we've seen it.

        Returns True if this listing is NEW (worth scoring/surfacing),
        False if it was already known.
        """
        row = job.to_row()
        now = _now()
        is_new = not self.has_seen(row["dedup_key"])
        if is_new:
            cols = [
                "dedup_key", "source", "source_id", "title", "company",
                "location", "remote", "url", "salary_min", "salary_max",
                "salary_currency", "salary_raw", "posted_at", "tags",
                "description", "raw",
            ]
            placeholders = ", ".join("?" for _ in cols) + ", ?, ?"
            sql = (
                f"INSERT INTO jobs ({', '.join(cols)}, first_seen, last_seen) "
                f"VALUES ({placeholders})"
            )
            self.conn.execute(sql, [row[c] for c in cols] + [now, now])
        else:
            self.conn.execute(
                "UPDATE jobs SET last_seen = ? WHERE dedup_key = ?",
                (now, row["dedup_key"]),
            )
        self.conn.commit()
        return is_new

    def upsert_many(self, jobs: Iterable[Job]) -> dict:
        """Bulk upsert. Returns {'new': n, 'seen': n}."""
        new_count = seen_count = 0
        for job in jobs:
            if self.upsert(job):
                new_count += 1
            else:
                seen_count += 1
        return {"new": new_count, "seen": seen_count}

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]

    # -- Phase 2: scoring --

    def iter_jobs(self):
        """Yield every stored listing as a Job, for scoring."""
        from .models import Job
        import json as _json
        for r in self.conn.execute("SELECT * FROM jobs"):
            yield Job(
                source=r["source"], source_id=r["source_id"] or "",
                url=r["url"] or "", title=r["title"] or "",
                company=r["company"] or "", location=r["location"] or "",
                remote=bool(r["remote"]),
                salary_min=r["salary_min"], salary_max=r["salary_max"],
                salary_currency=r["salary_currency"], salary_raw=r["salary_raw"] or "",
                posted_at=r["posted_at"] or "",
                tags=_json.loads(r["tags"]) if r["tags"] else [],
                description=r["description"] or "",
            )

    def is_applied(self, dedup_key: str) -> bool:
        row = self.conn.execute(
            "SELECT status FROM applications WHERE dedup_key = ?", (dedup_key,)
        ).fetchone()
        return bool(row and row["status"] == "submitted")

    def save_score(self, dec) -> None:
        self.conn.execute(
            "INSERT INTO scores (dedup_key, score, tier, decision, reason, scored_at) "
            "VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(dedup_key) DO UPDATE SET "
            "score=excluded.score, tier=excluded.tier, decision=excluded.decision, "
            "reason=excluded.reason, scored_at=excluded.scored_at",
            (dec.dedup_key, dec.score, dec.tier, dec.action, dec.reason, _now()),
        )

    def commit(self) -> None:
        self.conn.commit()

    def top_scored(self, limit: int = 15, tier: str | None = None):
        q = (
            "SELECT j.title, j.company, j.url, j.salary_raw, s.score, s.tier, "
            "s.decision, s.reason "
            "FROM scores s JOIN jobs j ON j.dedup_key = s.dedup_key "
        )
        params = []
        if tier:
            q += "WHERE s.tier = ? "
            params.append(tier)
        q += "ORDER BY s.score DESC LIMIT ?"
        params.append(limit)
        return self.conn.execute(q, params).fetchall()

    def tier_counts(self) -> dict:
        rows = self.conn.execute(
            "SELECT tier, COUNT(*) c FROM scores GROUP BY tier"
        ).fetchall()
        return {r["tier"]: r["c"] for r in rows}

    # -- Phase 3: applications (Telegram taps) --

    def record_application(self, dedup_key: str, status: str,
                           channel: str = "telegram") -> None:
        """Log a tap: status in apply|draft|skip -> applications table."""
        self.conn.execute(
            "INSERT INTO applications (dedup_key, status, channel, acted_at) "
            "VALUES (?,?,?,?) "
            "ON CONFLICT(dedup_key) DO UPDATE SET "
            "status=excluded.status, channel=excluded.channel, "
            "acted_at=excluded.acted_at",
            (dedup_key, status, channel, _now()),
        )
        self.conn.commit()

    def unsent_top(self, limit: int, tier: str | None = "core"):
        """Top scored roles NOT already acted on (no applications row yet)."""
        q = (
            "SELECT j.dedup_key, j.title, j.company, j.url, j.salary_raw, "
            "s.score, s.tier, s.reason "
            "FROM scores s JOIN jobs j ON j.dedup_key = s.dedup_key "
            "LEFT JOIN applications a ON a.dedup_key = s.dedup_key "
            "WHERE a.dedup_key IS NULL AND s.decision != 'skip' "
        )
        params = []
        if tier:
            q += "AND s.tier = ? "
            params.append(tier)
        q += "ORDER BY s.score DESC LIMIT ?"
        params.append(limit)
        return self.conn.execute(q, params).fetchall()
