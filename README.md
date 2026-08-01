# AI Job-Application Agent

An automated pipeline that discovers job listings from multiple sources, scores each one against my résumé using sentence-embedding similarity, and pushes the strongest matches to Telegram as one-tap cards — collapsing a daily job hunt into a short, ranked shortlist on my phone.

Built as a hands-on project in agentic / AI-assisted development.

## What it does

- **Aggregates** listings from several job boards behind a common adapter interface.
- **Normalizes** every source's raw payload into one `Job` schema, then de-duplicates and stores in SQLite.
- **Scores** each listing 0–100 against a résumé-derived profile using semantic similarity, with rule-based penalties (seniority mismatch, wrong domain, below pay floor).
- **Recommends** only high-confidence matches (configurable score cutoff) and pushes them to Telegram with Apply / Draft / Skip buttons.
- **Runs daily** via cron; taps are recorded so the same role is never surfaced twice.

> The agent surfaces and pre-scores roles — it does **not** auto-submit applications. Applying is manual, by design.

## Architecture

```
   Remotive ─┐   each adapter: parse() + fetch()
   RemoteOK ─┤        │
   Adzuna   ─┼────────►  normalize → Job schema
   Greenhouse┘        │
                      ▼
              dedup + store (SQLite)
                      │
                      ▼
           scoring: embeddings + rules  →  score 0–100, tier bands
                      │  (≥ cutoff)
                      ▼
           Telegram push (Apply / Draft / Skip)
```

- **Sources** (`src/sources/`) — one adapter per board. `parse()` is pure (raw dict → `list[Job]`, no network, unit-tested offline); `fetch()` does the HTTP then calls `parse()`.
- **Model** (`src/models.py`) — the single `Job` dataclass every source normalizes into, with a stable `dedup_key`.
- **Storage** (`src/db.py`) — SQLite with dedup + history; `scores` and `applications` tables.
- **Scoring** (`src/scoring/`) — sentence-transformers similarity + a rules gate → tier (`core` / `stretch` / `skip`).
- **Notify** (`src/notify/`) — Telegram Bot API push + tap collection.
- **Controller** (`src/daily.py`) — runs discovery → scoring → notify in sequence, resilient to per-stage failure.

## Tech stack

Python · SQLite · sentence-transformers (all-MiniLM-L6-v2) · pdfplumber · Telegram Bot API · requests · PyYAML

## Setup

```bash
# 1. clone + virtualenv
git clone <this-repo> && cd job-agent
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. secrets: copy the template, fill in your keys
cp config.example.yaml config.local.yaml
#    edit config.local.yaml — Adzuna app_id/app_key, Telegram token/chat_id

# 3. add your résumé PDF (path set in config.yaml: resume_path), then:
python -m src.run       # discover + build résumé profile
python -m src.score     # score listings against your profile
python -m src.notify    # push top matches to Telegram
```

**Configuration files**
- `config.yaml` — all non-secret knobs (target titles, filters, score cutoff, sources). Committed.
- `config.local.yaml` — your real secrets. **Gitignored, never committed.** Overrides the placeholders in `config.yaml` at runtime.
- `config.example.yaml` — template to copy into `config.local.yaml`.

### Deploying on a server

Instead of shipping `config.local.yaml`, set the secrets as environment
variables — they take precedence over both YAML files:

| Env var | Overrides |
|---|---|
| `ADZUNA_APP_ID`    | `sources.adzuna.app_id`  |
| `ADZUNA_APP_KEY`   | `sources.adzuna.app_key` |
| `TELEGRAM_TOKEN`   | `telegram.token`         |
| `TELEGRAM_CHAT_ID` | `telegram.chat_id`       |

Resolution order per secret: **environment variable → `config.local.yaml` →
`config.yaml` placeholder** — same code runs locally (YAML) and on a server
(env vars) with no changes.

## Usage

| Command | What it does |
|---|---|
| `python -m src.run` | Discover listings from all enabled sources; build the profile if missing (`--refresh-profile` forces a rebuild). |
| `python -m src.score` | Score every stored listing against the profile. |
| `python -m src.notify` | Push top core roles to Telegram (`--send-only`, or `--collect` to just record pending taps). |
| `python -m src.daily` | Full pipeline: discover → score → notify (send-only). |

## Tests

```bash
python -m pytest -q
```

Tests run fully offline against saved sample payloads — proving parse → dedup → store works end to end without touching the network.

## Project layout

```
config.yaml            committed config (no secrets)
config.example.yaml    secrets template → copy to config.local.yaml
src/
  models.py            Job schema + dedup key
  config.py            config loader (merges config.local.yaml over placeholders)
  db.py                SQLite: dedup + history
  pipeline.py          poll → normalize → dedup → store
  run.py               discovery entrypoint
  score.py             scoring entrypoint
  daily.py             daily controller
  profile/             résumé PDF → profile.json
  sources/             board adapters (remotive, remoteok, adzuna, greenhouse)
  scoring/             embeddings + rules + decision
  notify/              Telegram push + tap collection
tests/                 offline tests + sample payloads
```

## Status & roadmap

**Working today:** multi-source discovery, semantic scoring with a configurable cutoff, Telegram push with one-tap triage, daily scheduling.

**Planned:** safe auto-submit for structured boards (Greenhouse / Lever), assisted human-in-the-loop apply for others, LLM triage on top-ranked roles.
# ai-job-agent
