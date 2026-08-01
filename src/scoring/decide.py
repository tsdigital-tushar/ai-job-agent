"""Decision — turn a score + rule flags into a label you can act on.

Combines the embedding score with the rule penalties, then maps to:
  tier   : core | stretch | skip
  action : apply | draft | skip
  reason : one line explaining the placement

Thresholds live in config and are advisory — the ranking (sort by final score)
is the robust part; thresholds just label bands within it.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Job
from .rules import RuleResult


@dataclass
class Decision:
    dedup_key: str
    score: float           # final 0-100 after penalties
    tier: str
    action: str
    reason: str


def decide(job: Job, base: float, rules: RuleResult, cfg: dict) -> Decision:
    sc = cfg.get("scoring", {}) or {}
    th = sc.get("thresholds", {}) or {}
    core_t = th.get("core", 45)
    stretch_t = th.get("stretch", 28)

    final = max(0.0, min(100.0, base - rules.penalty + rules.boost))

    if rules.dropped:
        tier, action = "skip", "skip"
        reason = "; ".join(rules.reasons) or "filtered by rules"
    elif rules.hard_mismatch:
        # A hard mismatch can't be 'core' no matter how the text reads.
        tier = "stretch" if final >= stretch_t else "skip"
        action = "draft" if tier == "stretch" else "skip"
        reason = "; ".join(rules.reasons)
    elif final >= core_t:
        tier, action = "core", "apply"
        reason = _fit_reason(job, final, strong=True)
    elif final >= stretch_t:
        tier, action = "stretch", "draft"
        reason = _fit_reason(job, final, strong=False)
    else:
        tier, action = "skip", "skip"
        reason = f"low fit ({final:.0f})"

    # annotate preference so the list reads clearly
    if "preferred-role" in rules.tags and tier != "skip":
        reason = "★ " + reason
    if "systems-role" in rules.tags and tier != "skip":
        reason += " · [SAP/entry]"
    if "no-salary-listed" in rules.tags and tier != "skip":
        reason += " · pay not listed"

    return Decision(job.dedup_key, round(final, 1), tier, action, reason)


def _fit_reason(job: Job, score: float, strong: bool) -> str:
    lead = "strong match" if strong else "possible fit"
    return f"{lead} ({score:.0f}) · {job.title}"
