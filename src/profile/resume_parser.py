"""Resume -> structured profile.

Reads a resume PDF once and produces the profile object the scoring phase will
measure every listing against. Kept intentionally simple and transparent:

  - contact details via regex,
  - skills by matching a known-skills vocabulary against the resume text
    (so we only record skills that actually appear), plus anything listed under
    an explicit SKILLS section,
  - target titles come from config, not guessed from the resume.

The output is plain JSON (data/profile.json) you can open and sanity-check.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, asdict

import pdfplumber

# A compact, domain-tuned vocabulary. Detection is case-insensitive and
# word-boundary aware. Extend freely — this is just the seed list.
SKILL_VOCAB = [
    # Product / BA
    "product management", "product roadmap", "product roadmapping", "roadmapping",
    "backlog grooming",
    "user stories", "sprint planning", "okrs", "kpis", "go-to-market", "go to market",
    "requirements gathering", "gap analysis", "functional specifications",
    "uat", "process mapping", "stakeholder management", "raci",
    "user story mapping", "feature prioritization", "release validation",
    "user research", "customer interviews", "acceptance criteria",
    "data driven decision making",
    # Product analytics / experimentation
    "product analytics", "data analytics", "a/b testing", "hypothesis testing",
    "funnel optimization", "funnel optimisation",
    # Methodologies / tools
    "agile", "scrum", "kanban", "waterfall", "safe", "jira", "confluence",
    "alm", "tdd",
    # AI / data
    "generative ai", "prompt engineering", "embeddings", "llm", "watsonx",
    "power bi", "sql", "excel", "data visualisation", "data visualization",
    "agentic ai", "rag", "claude api", "chain of thought", "tree of thought",
    # Engineering / stack
    "node.js", "rest apis", "git", "html", "css",
    # Enterprise / SAP
    "sap s/4hana", "sap s4hana", "sap ecc", "sap btp", "sap joule", "fico", "co-pa",
    "p2p", "o2c", "r2r", "erp",
]

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE_RE = re.compile(r"(?:\+?\d[\d\s-]{8,}\d)")


@dataclass
class Profile:
    name: str = ""
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    target_titles: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    pay_floor_lpa: float | None = None
    raw_text: str = ""

    def to_json(self, path: str) -> None:
        d = asdict(self)
        # raw_text is bulky; keep it but at the end.
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(d, fh, indent=2, ensure_ascii=False)


def extract_text(pdf_path: str) -> str:
    parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            parts.append(page.extract_text() or "")
    return "\n".join(parts)


def _detect_skills(text: str) -> list[str]:
    low = text.lower()
    found = []
    for skill in SKILL_VOCAB:
        pattern = r"(?<!\w)" + re.escape(skill.lower()) + r"(?!\w)"
        if re.search(pattern, low):
            found.append(skill)
    # De-dup while preserving order.
    seen, out = set(), []
    for s in found:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _guess_name(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line and len(line.split()) <= 5 and line.replace(" ", "").isalpha():
            return line.title()
    return ""


def build_profile(pdf_path: str, config: dict | None = None) -> Profile:
    config = config or {}
    text = extract_text(pdf_path)

    skills = _detect_skills(text)
    domains = [d for d in ("SAP", "ERP", "Finance", "AI", "Data") if any(
        k in " ".join(skills).upper() for k in _domain_signals(d)
    )]

    profile = Profile(
        name=_guess_name(text),
        emails=sorted(set(EMAIL_RE.findall(text))),
        phones=sorted(set(p.strip() for p in PHONE_RE.findall(text))),
        target_titles=list(config.get("target_titles", [])),
        skills=skills,
        domains=domains,
        # keywords = skills plus tags; scoring uses these for the cheap first pass.
        keywords=skills,
        pay_floor_lpa=config.get("pay_floor_lpa"),
        raw_text=text,
    )
    return profile


def _domain_signals(domain: str) -> list[str]:
    return {
        "SAP": ["SAP"],
        "ERP": ["ERP", "SAP"],
        "Finance": ["FICO", "CO-PA", "R2R", "O2C", "P2P"],
        "AI": ["AI", "LLM", "PROMPT", "WATSONX", "EMBEDDINGS"],
        "Data": ["POWER BI", "SQL", "DATA"],
    }[domain]
