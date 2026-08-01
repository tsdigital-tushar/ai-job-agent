"""Remotive adapter.

Remotive exposes a public listings API (https://remotive.com/api/remote-jobs)
that returns `{"jobs": [ {...}, ... ]}`. It's a remote-only board, so every
listing is treated as remote. Salary is a free-text field when present and
often absent — we keep the raw text and leave parsing of it to the scoring
phase.
"""

from __future__ import annotations

from .base import BaseSource
from ..models import Job


class RemotiveSource(BaseSource):
    name = "remotive"
    endpoint = "https://remotive.com/api/remote-jobs"

    def parse(self, payload) -> list[Job]:
        jobs = []
        for r in (payload or {}).get("jobs", []):
            jobs.append(
                Job(
                    source=self.name,
                    source_id=str(r.get("id", "")),
                    url=self._clean(r.get("url")),
                    title=self._clean(r.get("title")),
                    company=self._clean(r.get("company_name")),
                    location=self._clean(r.get("candidate_required_location")),
                    remote=True,
                    salary_raw=self._clean(r.get("salary")),
                    posted_at=self._clean(r.get("publication_date")),
                    tags=[t for t in (r.get("tags") or []) if t],
                    description=self._clean(r.get("description")),
                    raw=r,
                )
            )
        return jobs
