"""Rules gate — the cheap first pass (no AI).

Runs before any embedding work, on plain title/salary text, so we never spend
compute deeply analyzing an obvious mismatch. Produces tags, a penalty, and
(in filter mode) a drop flag. In the default 'flag' mode nothing is dropped —
mismatches are just tagged and penalized so they sink in the ranking.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..models import Job


@dataclass
class RuleResult:
    dropped: bool = False
    penalty: float = 0.0            # points subtracted from the 0-100 score
    boost: float = 0.0              # points added (preferred roles)
    tags: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    hard_mismatch: bool = False     # seniority/domain/pay -> can't be 'core'


# ---- role preference (defaults; overridable in config.scoring) -------------
# Built from Tushar's actual Naukri apply history: Product + Data/Analytics are
# the core; analyst/consulting is the entry tier; SAP/systems sinks but stays
# applyable (never dropped) as an income / industry-entry option.
DEFAULT_PREFERRED = [
    # product core
    "product manager", "product owner", "associate product", "product analyst",
    "apm", "group product", "product lead", "product delivery", "product",
    # data / analytics core
    "data analyst", "analytics", "business intelligence", "bi analyst",
    "data & analytics", "insights",
    # startup / growth
    "founding", "startup", "growth", "strategy",
]
# Titles that name AI/ML in a product/data context get an extra bump — these
# are the roles Tushar actively chased (AI-PM at Platinus, highlevel).
DEFAULT_AI_TERMS = ["ai", "a.i", "ml", "machine learning", "genai", "llm"]

# Middle tier — real but secondary; small boost, not the top.
DEFAULT_ENTRY = [
    "business analyst", "consultant", "associate consultant", "analyst",
    "program manager", "project manager",
]

DEFAULT_SYSTEMS = [
    "sap", "s/4hana", "s4hana", "erp", "functional consultant", "ewm",
    "abap", "basis", "netweaver", "mm consultant", "pp consultant",
    "sd consultant", "fico", "techno functional", "systems analyst",
]


# ---- salary parsing -------------------------------------------------------

_NUM = re.compile(r"(\d[\d,]*)(k)?", re.I)


def _annual_amount(raw: str, smin, smax):
    """Return (amount, is_structured). Structured salaries carry their own
    currency on the Job; free-text is assumed USD (remote boards)."""
    if smin or smax:
        vals = [v for v in (smin, smax) if v]
        return (min(vals) if vals else None), True
    if not raw:
        return None, False
    nums = []
    for m in _NUM.finditer(raw):
        n = float(m.group(1).replace(",", ""))
        if m.group(2):            # a trailing 'k'
            n *= 1000
        nums.append(n)
    nums = [n for n in nums if n >= 1000]   # ignore stray small numbers
    return (min(nums) if nums else None), False


def _to_lpa(amount: float, currency: str | None, usd_to_inr: float) -> float:
    """Convert an annual figure to INR lakhs/year, respecting currency.
    INR stays as-is; anything else (or unknown free-text) treated as USD."""
    inr = amount if currency == "INR" else amount * usd_to_inr
    return inr / 100_000.0


# ---- the gate -------------------------------------------------------------

def apply_rules(job: Job, cfg: dict, already_applied: bool = False) -> RuleResult:
    sc = cfg.get("scoring", {}) or {}
    mode = sc.get("mode", "flag")
    pen = sc.get("penalties", {}) or {}
    res = RuleResult()
    title_l = (job.title or "").lower()

    # Detect a core-preferred (product / data / analytics) title up front, so it
    # can override the domain guard — e.g. "Marketing Data & Analytics Manager"
    # is a data role Tushar wants, not a marketing role to block.
    prefs = sc.get("preferred_titles", DEFAULT_PREFERRED)
    is_core_pref = any(k.lower() in title_l for k in prefs)

    def flag(tag, reason, penalty, hard=True):
        res.tags.append(tag)
        res.reasons.append(reason)
        res.penalty += float(penalty)
        if hard:
            res.hard_mismatch = True
        if mode == "filter":
            res.dropped = True

    # already applied -> always skip, regardless of mode
    if already_applied:
        res.dropped = True
        res.tags.append("already-applied")
        res.reasons.append("already applied")
        return res

    # seniority guard (title-level, not a years-of-experience filter)
    for kw in cfg.get("seniority_block", []):
        if kw.lower() in title_l:
            flag("seniority-mismatch", f"seniority mismatch ({kw})",
                 pen.get("seniority", 35))
            break

    # domain guard (skipped when the title is a core product/data role)
    if not is_core_pref:
        for kw in cfg.get("domain_block", []):
            if kw.lower() in title_l:
                flag("domain-mismatch", f"wrong field ({kw})",
                     pen.get("domain", 40))
                break

    # pay floor (only when we can actually read a number)
    floor = cfg.get("pay_floor_lpa")
    if floor:
        amount, _structured = _annual_amount(job.salary_raw, job.salary_min, job.salary_max)
        if amount is not None:
            lpa = _to_lpa(amount, job.salary_currency, sc.get("usd_to_inr", 83))
            if lpa < floor:
                flag("below-floor", f"pay ~{lpa:.1f} LPA below {floor}",
                     pen.get("below_floor", 30))
        else:
            res.tags.append("no-salary-listed")   # neutral, no penalty

    # ---- role preference reweighting (tiered, from real apply history) ----
    # Core: product + data/analytics -> strong boost, float to top.
    if is_core_pref:
        res.boost += float(sc.get("preferred_boost", 20))
        res.tags.append("preferred-role")
        # extra bump when it's an AI/ML product/data role (his top target)
        ai_terms = sc.get("ai_terms", DEFAULT_AI_TERMS)
        if any(re.search(r"(?<!\w)" + re.escape(a) + r"(?!\w)", title_l) for a in ai_terms):
            res.boost += float(sc.get("ai_boost", 8))
            res.tags.append("ai-role")

    # Entry tier: analyst/consulting -> small boost only (secondary), and only
    # if it wasn't already counted as core.
    if not is_core_pref:
        entry = sc.get("entry_titles", DEFAULT_ENTRY)
        if any(k.lower() in title_l for k in entry):
            res.boost += float(sc.get("entry_boost", 8))
            res.tags.append("entry-role")

    # Systems/SAP -> SOFT penalty: sinks below everything above but never
    # dropped, never a hard mismatch. Stays applyable as income/entry option.
    systems = sc.get("deprioritize_systems", DEFAULT_SYSTEMS)
    if any(k.lower() in title_l for k in systems):
        res.penalty += float(sc.get("systems_penalty", 22))
        res.tags.append("systems-role")
        res.reasons.append("systems/SAP — deprioritized (entry/income option)")

    return res
