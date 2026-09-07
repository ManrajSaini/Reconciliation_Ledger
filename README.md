# Reconciliation Ledger

## The problem

Two systems record the same trades: our own ledger, and a counterparty's
statement. They disagree — on amounts, on times, and on which transactions
happened at all — and until someone works out where and why, the books
cannot be closed.

The two systems were built independently and were never designed to agree.
They use different column names for the same field, write dates in
different formats, and use different vocabulary for the same value (one
side's `BUY` is the other's `B`). More sources may show up later in the same
shape of problem.

Not every difference is a real problem. Amounts drift slightly from
rounding and fees; recorded times drift slightly because two clocks are
never perfectly in sync. Small drift is normal — a large one means
something is actually wrong, and whoever is reviewing it needs to see
*which* field differs and *by how much*, not just a flag saying something
is off. Some rows have no counterpart on the other side at all, in either
direction. Cancelled transactions appear in both files but were never meant
to be compared.

Files keep arriving. Sometimes the same file is sent twice. Sometimes a new
file is a correction — most rows are unchanged, a few amounts are fixed, and
the fixed value is what counts going forward, though people still want to
know what a row used to say.

The process runs every morning. Between runs, people resolve what the
system couldn't: pairing two rows by hand, or accepting that a row genuinely
has no match. Whatever they decide has to still hold the next morning — an
automated rerun must not silently undo a human's decision.

**This project is the screen someone opens each morning to see what doesn't
match, and to resolve it.**

## The approach

- **One canonical transaction model, one adapter per source.** Column
  names, date formats, and vocabulary are a source-specific translation
  problem, isolated entirely inside each adapter. Nothing downstream —
  matching, comparison, storage, UI — ever needs to know which company sent
  a row, or that a third source format might show up tomorrow.

- **Two-tier matching.** Where both sides share an identifier, match on it
  directly — cheap and unambiguous. Everything left over is scored by
  proximity (instrument, side, quantity, price, time) and surfaced as
  ranked candidates, never auto-committed. A wrong automatic match is worse
  than an honest "no pair found," because it hides a real discrepancy behind
  a false match.

- **Field-by-field tolerance comparison, not a pass/fail flag.** Numeric
  fields are compared with a relative tolerance (percentage-based, since a
  fixed tolerance means different things at different trade sizes), with a
  small absolute floor for very small trades. Timestamps use a fixed time
  window instead, since clock drift isn't proportional to trade size. Every
  comparison stores the actual delta, so a reviewer sees the magnitude of a
  disagreement, not just its existence.

- **Cancelled rows are filtered out before matching**, symmetrically on
  both sides, since they were never meant to be compared at all.

- **Append-only, versioned storage.** Every ingested version of a row is
  kept. "Current" is the latest version; history answers "what did this used
  to say," and corrections never destroy the previous value.

- **Duplicate file submissions are detected by content hash** and treated as
  a no-op, so a resend is never mistaken for a correction.

- **A human's manual decision is its own authoritative record**, ranked
  above whatever the automated matcher produces. Each morning's run only
  acts on rows that don't already have a standing human decision — this is
  what makes "must still hold tomorrow" actually true rather than
  incidentally true. If a manually-matched row is later corrected, the
  pairing stands but the diff is recomputed against the new values —
  correction changes *agreement*, not *identity*.

- **Every run is a first-class, auditable record** — what came in, when,
  and the resulting counts (agree / differs / unmatched each side /
  excluded as cancelled).

**Guiding principle throughout:** deterministic before heuristic, heuristic
before automatic; never destroy state, only add to it; show magnitude, not
just a flag; when in doubt, leave something unresolved rather than guess.

## Deliberately out of scope

Multi-tenant auth, cross-currency conversion, validating prices against
external market data, and ML-based fuzzy matching — deterministic matching
plus simple scoring is sufficient here and far easier to audit.

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

- **Backend:** FastAPI. Chosen over Flask/Django for a modern, simple
  framework; used here purely for server-rendered Jinja2 pages, not its
  async/API-first features.
- **Database:** SQLite, accessed via SQLAlchemy Core (not the full ORM) —
  explicit, readable queries over relationship/lazy-loading magic, which
  matters for an append-only/versioned data model.
- **UI:** Server-rendered Jinja2 templates, plain HTML forms/links. No JS
  framework or build step by default; a little vanilla JS is added only
  where a plain page reload genuinely can't do the job (expected only in
  the manual-match screen, if at all). React would only be introduced if
  that specific interaction needs real client-side state — not expected.
- **Tests:** pytest.

## What's built so far, and what's next

**Built:** canonical transaction model; adapters for the ledger and
statement formats (column mapping, date parsing, vocabulary/status
normalization); a synthetic test dataset covering exact matches, in- and
out-of-tolerance price/time drift, unmatched rows on both sides, cancelled
rows, and a correction scenario.

**Next:** the matching engine (deterministic + heuristic candidates), the
tolerance-based comparison engine, database persistence (versioned
transactions, runs, manual decisions), run orchestration, and the UI
(run list, run detail, row diff view, manual match screen).

This section will be kept up to date as the build progresses.
