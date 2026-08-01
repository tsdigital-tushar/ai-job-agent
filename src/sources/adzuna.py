"""Adzuna adapter — the source that actually carries your roles.

Unlike the remote-only boards, Adzuna aggregates India-wide listings (BA, APM,
SAP, consulting, analyst) and exposes salary data. It's a keyword search API, so
instead of pulling one firehose we query it once per target title and merge the
results — meaning the pool is pre-biased toward roles you actually want.

Needs free credentials (app_id + app_key) from developer.adzuna.com, set in
config under sources.adzuna. Salaries for the 'in' region come back in INR/year,
so we tag currency accordingly for the pay-floor check.
"""

from __future__ import annotations

import requests

from .base import BaseSource, _UA, _TIMEOUT
from ..models import Job

_BASE = "https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"


class AdzunaSource(BaseSource):
    name = "adzuna"

    def __init__(self, app_id: str, app_key: str, country: str = "in",
                 queries: list[str] | None = None, results_per_page: int = 50):
        self.app_id = app_id
        self.app_key = app_key
        self.country = country
        self.queries = queries or []
        self.results_per_page = min(results_per_page, 50)

    def fetch(self) -> list[Job]:
        if not self.app_id or not self.app_key:
            raise RuntimeError(
                "Adzuna needs app_id and app_key in config (sources.adzuna). "
                "Get free keys at developer.adzuna.com."
            )
        seen, jobs = set(), []
        for term in (self.queries or [""]):
            url = _BASE.format(country=self.country, page=1)
            params = {
                "app_id": self.app_id,
                "app_key": self.app_key,
                "results_per_page": self.results_per_page,
                "what": term,
                "content-type": "application/json",
            }
            resp = requests.get(url, params=params,
                                headers={"User-Agent": _UA}, timeout=_TIMEOUT)
            resp.raise_for_status()
            for job in self.parse(resp.json()):
                if job.dedup_key not in seen:
                    seen.add(job.dedup_key)
                    jobs.append(job)
        return jobs

    def parse(self, payload) -> list[Job]:
        jobs = []
        for r in (payload or {}).get("results", []):
            loc = ((r.get("location") or {}).get("display_name")) or ""
            title = self._clean(r.get("title"))
            is_remote = "remote" in (title + " " + loc).lower()
            smin = r.get("salary_min")
            smax = r.get("salary_max")
            jobs.append(
                Job(
                    source=self.name,
                    source_id=str(r.get("id", "")),
                    url=self._clean(r.get("redirect_url")),
                    title=title,
                    company=self._clean((r.get("company") or {}).get("display_name")),
                    location=self._clean(loc),
                    remote=is_remote,
                    salary_min=float(smin) if smin else None,
                    salary_max=float(smax) if smax else None,
                    salary_currency="INR" if (smin or smax) else None,
                    posted_at=self._clean(r.get("created")),
                    tags=[(r.get("category") or {}).get("label", "")] if r.get("category") else [],
                    description=self._clean(r.get("description")),
                    raw=r,
                )
            )
        return jobs
