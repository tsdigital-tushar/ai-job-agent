"""Offline tests for Phase 0 + 1.

No network: adapters are tested against saved sample payloads, proving the
normalize -> dedup -> store flow end to end. Run with:  python -m pytest -q
"""

import json
import os
import tempfile

from src.sources.remotive import RemotiveSource
from src.sources.remoteok import RemoteOKSource
from src.db import Store
from src.pipeline import ingest_payloads

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    with open(os.path.join(HERE, "sample_data", name), encoding="utf-8") as fh:
        return json.load(fh)


def test_remotive_parse():
    jobs = RemotiveSource().parse(_load("remotive_sample.json"))
    assert len(jobs) == 3
    j = jobs[0]
    assert j.title == "Associate Product Manager"
    assert j.company == "Nimbus Labs"
    assert j.remote is True
    assert j.dedup_key == "remotive:1900001"
    assert j.salary_raw == "$60,000 - $80,000"


def test_remoteok_skips_legal_element():
    jobs = RemoteOKSource().parse(_load("remoteok_sample.json"))
    # 3 elements in payload, first is legal -> 2 jobs
    assert len(jobs) == 2
    titles = {j.title for j in jobs}
    assert titles == {"Product Analyst", "Backend Engineer"}


def test_remoteok_structured_salary():
    jobs = RemoteOKSource().parse(_load("remoteok_sample.json"))
    pa = next(j for j in jobs if j.title == "Product Analyst")
    assert pa.salary_min == 55000
    assert pa.salary_max == 75000
    assert pa.salary_currency == "USD"


def test_dedup_across_runs():
    payloads = {
        "remotive": _load("remotive_sample.json"),
        "remoteok": _load("remoteok_sample.json"),
    }
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "t.db")
        with Store(db_path) as store:
            first = ingest_payloads(payloads, store)
            # 3 remotive + 2 remoteok = 5 new on first run
            assert first["remotive"]["new"] == 3
            assert first["remoteok"]["new"] == 2
            assert store.count() == 5

            # Re-ingest identical payloads: everything already seen, zero new.
            second = ingest_payloads(payloads, store)
            assert second["remotive"]["new"] == 0
            assert second["remotive"]["seen"] == 3
            assert store.count() == 5


def test_dedup_key_stable_and_unique():
    jobs = RemotiveSource().parse(_load("remotive_sample.json"))
    keys = [j.dedup_key for j in jobs]
    assert len(keys) == len(set(keys))  # all unique


def test_adzuna_parse_and_currency():
    from src.sources.adzuna import AdzunaSource
    jobs = AdzunaSource(app_id="x", app_key="y").parse(_load("adzuna_sample.json"))
    assert len(jobs) == 3
    ba = next(j for j in jobs if "Business Analyst" in j.title)
    assert ba.company == "Infowave Consulting"
    assert ba.salary_currency == "INR"
    assert ba.salary_min == 900000
    apm = next(j for j in jobs if j.title == "Associate Product Manager")
    assert apm.remote is True   # "Remote - India" in location


def test_adzuna_pay_floor_inr_vs_usd():
    """INR salary must NOT be treated as USD (would wrongly 83x it)."""
    from src.sources.adzuna import AdzunaSource
    from src.scoring.rules import apply_rules
    from src.config import load_config
    cfg = load_config()
    jobs = AdzunaSource(app_id="x", app_key="y").parse(_load("adzuna_sample.json"))
    # Field Sales at 3 LPA (INR 300000) is below the 7 LPA floor -> flagged.
    sales = next(j for j in jobs if "Sales" in j.title)
    res = apply_rules(sales, cfg)
    assert "below-floor" in res.tags
    # BA at 9 LPA (INR 900000) is above floor -> not flagged below-floor.
    ba = next(j for j in jobs if "Business Analyst" in j.title)
    res2 = apply_rules(ba, cfg)
    assert "below-floor" not in res2.tags
