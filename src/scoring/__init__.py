"""Phase 2 — scoring.

Turns the raw pool of discovered listings into a ranked apply/draft/skip list.
Two layers, cheap-first:

  rules.py   - fast text checks (pay floor, seniority, domain, already-applied).
  scorer.py  - embedding "meaning match" of a job against your profile.
  decide.py  - combine score + rule flags into a tier, an action, and a reason.

Nothing here deletes listings. In the default 'flag' mode it only tags and
ranks; 'filter' mode drops hard mismatches instead.
"""
