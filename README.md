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

---

## How to run it

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

uvicorn reconciliation.app:app --reload --app-dir src
```

Then open <http://127.0.0.1:8000/>. Sample multi-scenario CSV files (both
sources, plus a correction file and a duplicate-resend file) are in
`tests/fixtures/` — upload `day1_ledger.csv` and `day1_statement.csv` on the
run list page to see a populated run immediately.

**Golden path to try by hand:**
1. Upload both `day1_*.csv` files and start a run.
2. Open the run — see 4 agreeing pairs, 2 differing pairs, 1 unmatched row
   on each side, 2 excluded-as-cancelled rows.
3. Click a differing pair (e.g. `T-2003`) to see the field-by-field diff
   with deltas.
4. Click "Resolve" on the unmatched ledger row (`T-2006`) to see its ranked
   candidate (`C-3001`) and confirm the match, or declare it has no pair.
5. Start a second run with no new files — the resolution you just made
   still holds.
6. Upload `day2_statement_correction.csv` and start another run — a
   corrected row's diff updates, but any manual pairing on it is preserved.

## How to run the tests

```bash
pytest
```

70 tests cover the logic that matters: source adapters (column mapping,
date parsing, vocabulary normalization), the matching engine (deterministic
+ heuristic, including boundary and asymmetric-cancellation cases), the
tolerance comparison engine (including exact tolerance-boundary values), the
persistence layer (versioning, duplicate detection, manual decisions), full
orchestration, and the UI routes end-to-end via `TestClient` against an
isolated in-memory database.

---

## What was decided, and why

### Stack
- **Backend — FastAPI.** Chosen over Flask/Django for a modern, simple
  framework; used here purely for server-rendered Jinja2 pages, not its
  async/API-first features.
- **Database — SQLite via SQLAlchemy Core** (not the full ORM). Explicit,
  readable queries over relationship/lazy-loading magic, which matters for
  an append-only/versioned data model where every write needs to be
  obviously correct.
- **UI — server-rendered Jinja2 templates**, plain HTML forms and links.
  No JS framework or build step anywhere in the app — every interaction
  (including manual match resolution) turned out to be doable with a form
  POST and a redirect, so the JS/React escalation path outlined at the
  start was never actually needed.
- **Tests — pytest.**

### The reconciliation design

- **One canonical transaction model, one adapter per source.** Column
  names, date formats, and vocabulary are a source-specific translation
  problem, isolated entirely inside each adapter (`src/reconciliation/adapters/`).
  Nothing downstream — matching, comparison, storage, UI — ever needs to
  know which company sent a row, or that a third source format might show
  up tomorrow. Adding a third source is one new adapter module.

- **Two-tier matching.** Where both sides share an identifier, match on it
  directly — cheap and unambiguous. Everything left over is scored by
  proximity (instrument, side must match exactly; quantity/price/time then
  rank the rest) and surfaced as ranked candidates, never auto-committed. A
  wrong automatic match is worse than an honest "no pair found," because it
  hides a real discrepancy behind a false match. On the resolve screen, a
  human can also pick any other unmatched row by hand, not just the ranked
  candidates — a reviewer may recognize a pairing the scorer didn't rank.

- **Same external_id, cancelled on one side only.** If one system cancels a
  trade the other hasn't caught up on, the still-active side is *not*
  matched against its cancelled counterpart — it surfaces as genuinely
  unmatched, since that mismatch is itself a real discrepancy worth a
  human's attention, not something to quietly drop.

- **Field-by-field tolerance comparison, not a pass/fail flag.**
  - Numeric fields (quantity, price, gross amount): **10 basis points
    (0.10%) relative tolerance, OR within a $0.01 absolute floor** —
    whichever passes. The floor exists so near-zero-value trades aren't
    flagged on trivial noise; the relative tolerance dominates above that.
  - Timestamps: a **fixed 2-minute window**, not a percentage — clock drift
    isn't proportional to trade size.
  - Every comparison stores the actual absolute and relative delta, so a
    reviewer sees the magnitude of a disagreement, not just its existence.

- **Cancelled rows are filtered out before matching**, symmetrically on
  both sides, since they were never meant to be compared at all.

- **Append-only, versioned storage.** Every ingested version of a row is
  kept (`transaction_versions`, keyed on source + external id + version
  number). "Current" is the latest version; history answers "what did this
  used to say," and corrections never destroy the previous value.

- **Duplicate file submissions are detected by content hash** and treated
  as a no-op, so a resend is never mistaken for a correction.

- **A human's manual decision is its own authoritative record**
  (`manual_decisions`, keyed on the stable source+external-id pair, not on
  any specific version), ranked above whatever the automated matcher
  produces. Each morning's run only acts on rows that don't already have a
  standing human decision — this is what makes "must still hold tomorrow"
  actually true rather than incidentally true. If a manually-matched row is
  later corrected, the pairing stands but the diff is recomputed against
  the new values — a correction changes *agreement*, not *identity*. A
  confirmed "no pair" decision is treated as **resolved**, not as still
  "unmatched" — a human already settled it, so the unmatched count reflects
  what still needs attention.

- **Every run is a first-class, auditable record** — what came in, when,
  and the resulting counts (agree / differs / unmatched each side /
  excluded as cancelled). Viewing any past run's detail page always
  reflects *current* state (including later corrections or manual
  decisions), not a frozen snapshot of what that run originally saw —
  otherwise "view run #3" could contradict a correction made in run #5.

**Guiding principle throughout:** deterministic before heuristic, heuristic
before automatic; never destroy state, only add to it; show magnitude, not
just a flag; when in doubt, leave something unresolved rather than guess.

### Other decisions made along the way

| Decision | Why |
|---|---|
| Naive/no-timezone counterparty timestamps assumed UTC | Removes silent ambiguity; easy to change later if wrong |
| File intake is via upload on the run-list page, not a fixed drop-folder | Matches "start a run" as a literal, directly demoable UI action |
| Canonical model is a frozen `dataclass`, not pydantic | Adapters already do explicit parsing/coercion; no extra validation layer was needed |
| SQLite datetimes stored as naive UTC, converted at the repository boundary | SQLite silently drops tzinfo on round-trip — converting at one boundary keeps every other layer working in tz-aware UTC without knowing about the storage quirk |
| DB engine provided via FastAPI dependency injection, not a module-level singleton | A module-level engine touched the real on-disk database just from importing the app module — dependency injection lets tests use an isolated in-memory database instead |

---

## Deliberately out of scope

Multi-tenant access control / authentication, cross-currency conversion,
validating trade prices against external market data, and ML-based fuzzy
matching — deterministic matching plus simple scoring is sufficient here and
far easier to audit than a model whose confidence can't be explained to a
reviewer.

## What's built, and what's next

**Built (all phases complete):**
- Canonical transaction model and adapters for both sample formats.
- Matching engine (deterministic exact-id + heuristic scoring, with ranked
  candidates never auto-committed).
- Tolerance-based comparison engine reporting actual deltas.
- Full persistence layer: versioned transactions, run history, match
  candidates, manual decisions, cached comparison results.
- Run orchestration wiring ingest → adapt → match → compare → persist.
- A server-rendered UI: run list (upload + trigger), run detail (5
  buckets), row detail (field diff + both-side version history), and a
  manual resolution screen (confirm a match or declare no pair).
- 70 tests covering adapters, matching, comparison, persistence,
  orchestration, and the UI end-to-end.

**What would come next, given more time:**
- Support for a third source format, to prove out the "one new adapter"
  claim against a real (not hypothetical) third shape.
- A dedicated "resolved as no-pair" view, distinct from both the unmatched
  and matched-agree buckets, so a reviewer can audit past no-pair decisions.
- Pagination/filtering on the run list and bucket tables once run history
  or transaction volume grows past what fits on one page.
- Configurable tolerance values (currently constants in
  `src/reconciliation/comparison.py`) exposed as run-time settings rather
  than requiring a code change.
- Authentication and an audit trail of *who* made each manual decision, if
  this were to move beyond a single-user tool.
