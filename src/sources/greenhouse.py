"""Greenhouse adapter — pull roles straight from company career boards.

Many companies host careers on Greenhouse and expose a public, key-free
job-board API:

    https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true

`{company}` is the board token in a careers URL (boards.greenhouse.io/<token>).
Each board belongs to one company, so — like the Adzuna adapter — we make one
request per configured token and merge the results, de-duplicating as we go.

Configure the boards in config under sources.greenhouse.companies (a list of
board tokens). No credentials required.
"""

from __future__ import annotations

import requests

from .base import BaseSource, _UA, _TIMEOUT
from ..models import Job

_BASE = "https://boards-api.greenhouse.io/v1/boards/{company}/jobs"


class GreenhouseSource(BaseSource):
    name = "greenhouse"

    def __init__(self, companies: list[str] | None = None):
        # Board tokens, e.g. ["stripe", "gitlab"].
        self.companies = [c for c in (companies or []) if c]

    def fetch(self) -> list[Job]:
        if not self.companies:
            raise RuntimeError(
                "Greenhouse needs at least one board token in config "
                "(sources.greenhouse.companies). Find it in a company's careers "
                "URL: boards.greenhouse.io/<token>."
            )
        seen, jobs = set(), []
        for company in self.companies:
            url = _BASE.format(company=company)
            try:
                resp = requests.get(
                    url, params={"content": "true"},
                    headers={"User-Agent": _UA, "Accept": "application/json"},
                    timeout=_TIMEOUT,
                )
                resp.raise_for_status()
            except requests.RequestException as e:
                # One dead/typo'd board shouldn't sink the others — skip and warn.
                print(f"[greenhouse] board '{company}' failed, skipping: {e}")
                continue
            for job in self.parse(resp.json(), company=company):
                if job.dedup_key not in seen:
                    seen.add(job.dedup_key)
                    jobs.append(job)
        return jobs

    def parse(self, payload, company: str = "") -> list[Job]:
        jobs = []
        for r in (payload or {}).get("jobs", []):
            loc = (r.get("location") or {}).get("name") or ""
            title = self._clean(r.get("title"))
            # Board API rarely echoes the company name per job, so fall back to
            # the board token we queried.
            company_name = self._clean(r.get("company_name")) or self._clean(company)
            is_remote = "remote" in (title + " " + loc).lower()
            departments = [
                d.get("name", "") for d in (r.get("departments") or []) if d.get("name")
            ]
            jobs.append(
                Job(
                    source=self.name,
                    source_id=str(r.get("id", "")),
                    url=self._clean(r.get("absolute_url")),
                    title=title,
                    company=company_name,
                    location=self._clean(loc),
                    remote=is_remote,
                    posted_at=self._clean(r.get("updated_at")),
                    tags=departments,
                    description=self._clean(r.get("content")),
                    raw=r,
                )
            )
        return jobs
