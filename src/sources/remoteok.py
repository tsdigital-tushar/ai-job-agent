"""RemoteOK adapter.

RemoteOK's API (https://remoteok.com/api) returns a JSON *list*. The first
element is a legal/notice object, not a job — it has no `position` and usually
carries a `legal` key — so we skip it. Remaining elements are listings with
structured `salary_min` / `salary_max` integers when available (USD).
"""

from __future__ import annotations

from .base import BaseSource
from ..models import Job


class RemoteOKSource(BaseSource):
    name = "remoteok"
    endpoint = "https://remoteok.com/api"

    def parse(self, payload) -> list[Job]:
        jobs = []
        for r in payload or []:
            # Skip the leading legal/metadata element.
            if not isinstance(r, dict) or "position" not in r:
                continue

            smin = r.get("salary_min")
            smax = r.get("salary_max")
            jobs.append(
                Job(
                    source=self.name,
                    source_id=str(r.get("id", r.get("slug", ""))),
                    url=self._clean(r.get("url") or r.get("apply_url")),
                    title=self._clean(r.get("position")),
                    company=self._clean(r.get("company")),
                    location=self._clean(r.get("location")),
                    remote=True,
                    salary_min=float(smin) if smin else None,
                    salary_max=float(smax) if smax else None,
                    salary_currency="USD" if (smin or smax) else None,
                    posted_at=self._clean(r.get("date")),
                    tags=[t for t in (r.get("tags") or []) if t],
                    description=self._clean(r.get("description")),
                    raw=r,
                )
            )
        return jobs
