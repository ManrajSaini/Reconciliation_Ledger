# Reconciliation Ledger

A daily reconciliation screen: loads two disagreeing systems' trade files,
matches rows across them, compares matched rows within tolerance, and lets a
human resolve what the automated pass couldn't.

See `taskDetails.md` for the original assignment brief, `solution.md` for the
reasoning behind the approach, `architecture.md` for the concrete design,
`plan.md` for the phase-by-phase build plan, `constitution.md` for the
ground rules governing how this gets built, and `mistakes.md` for problems
hit along the way and how they were resolved.

**Status:** Phase 0 (scaffolding) — not yet functional beyond a placeholder
page. This README will be filled in as later phases land.

---

## How to run it

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

uvicorn reconciliation.app:app --reload --app-dir src
```

Then open http://127.0.0.1:8000/.

## How to run the tests

```bash
pytest
```

---

## Stack, and why

- **Backend:** FastAPI. Chosen over Flask/Django per user preference for a
  modern, simple framework; used here purely for server-rendered Jinja2
  pages, not its async/API-first features.
- **Database:** SQLite, accessed via SQLAlchemy Core (not the full ORM) —
  explicit, readable queries over relationship/lazy-loading magic, which
  matters for an append-only/versioned data model (see `architecture.md`
  #3).
- **UI:** Server-rendered Jinja2 templates, plain HTML forms/links. No JS
  framework or build step by default; a little vanilla JS is added only
  where a plain page reload genuinely can't do the job (expected only in
  the manual-match screen, if at all). React would only be introduced if
  that specific interaction needs real client-side state — not expected.
- **Tests:** pytest.

Full rationale for every non-obvious decision lives in `architecture.md`
§7 (Decisions Log) as it grows; this section will summarize the final state
once the build is further along.

## What was left out, and what's next

Tracked in `plan.md` (phase status) and `solution.md` §5 (explicitly
out-of-scope items). Updated as phases complete.
