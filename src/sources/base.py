"""Base class for source adapters.

Each source (Remotive, RemoteOK, Adzuna, ...) subclasses this. The split is
deliberate:

  - `parse(payload)` is pure: raw dict in, list[Job] out. No network. This is
    what the tests hit, so adapters are verifiable offline against saved
    sample payloads.
  - `fetch()` does the actual HTTP, then calls `parse()`.

That separation is why the whole discovery layer can be developed and tested
without ever touching the live APIs.
"""

from __future__ import annotations

import requests

from ..models import Job

_UA = "job-agent/0.1 (personal project)"
_TIMEOUT = 20


class BaseSource:
    name: str = "base"
    endpoint: str = ""

    def parse(self, payload) -> list[Job]:
        raise NotImplementedError

    def fetch(self) -> list[Job]:
        """Live call. Runs on the user's machine, not in tests."""
        resp = requests.get(
            self.endpoint, headers={"User-Agent": _UA, "Accept": "application/json"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        return self.parse(resp.json())

    # -- small shared helpers --
    @staticmethod
    def _clean(text) -> str:
        return (text or "").strip()
