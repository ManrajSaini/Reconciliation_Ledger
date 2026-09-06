# The Reconciliation Problem — Solution Approach

This document lays out the reasoning and the chosen solution for each sub-problem
embedded in the reconciliation exercise. It is intentionally implementation-agnostic —
no schema, no code — it exists to record *what* we are solving, *why*, and *the
approach that best satisfies the requirements*, so that the eventual build has a
clear rationale to point back to.

---

## 1. What problem this actually is

Two independent systems (our ledger, the counterparty's statement) each claim to
record the same set of trades. Before books can be closed, every trade must be
proven to agree, or every disagreement must be explained. This is standard
**trade/transaction reconciliation** — the daily operational problem every broker,
bank, and exchange solves. The exercise is not really "write a matcher" — it's
"build a small but honest version of a system that has to stay correct over many
days, many file formats, and many human interventions."

The requirements are dense; nearly every sentence in the brief encodes a distinct
sub-problem. Below, each is pulled out and paired with the approach that best
satisfies it.

---

## 2. Sub-problems and chosen solutions

### 2.1 Multiple, evolving file formats
**Problem:** Column names, date formats, and vocabulary (`BUY` vs `B`) differ
between sources, and a third source format may appear later.

**Solution:** Introduce one **canonical transaction model** — a fixed internal
representation (external id, timestamp, instrument, side, quantity, price, gross
amount, status) — and one **adapter per source** whose only responsibility is
translating that source's native shape into the canonical model (field renaming,
date parsing into a single timezone-aware type, vocabulary normalization like
`BUY`/`B` → one enum value).

**Why this is the right shape:** it isolates volatility. Adding a third company
later means writing one new adapter; nothing in matching, comparison, storage, or
the UI needs to know a third format exists. Any design where matching/comparison
logic has to branch on "which company sent this" has coupled the wrong layers
together and will not survive "tomorrow there may be a third format."

---

### 2.2 Deciding which rows on each side are "the same trade"
**Problem:** Rows must be paired across the two sources. Sometimes a shared
identifier exists; sometimes it doesn't (one side's `C-9001` has no counterpart id
at all, and the other side's `T-1016` has no counterpart id either).

**Solution:** A two-tier matching strategy —
1. **Deterministic match**: wherever both sides expose a shared external
   identifier, join on it directly. Cheap, unambiguous, no judgment involved.
2. **Heuristic candidate scoring** for everything left unmatched: score
   remaining rows against each other using instrument, side, quantity/price
   proximity, and timestamp proximity. Produce **ranked candidates**, not
   silent auto-matches.

**Why this is the right approach:** in reconciliation, a false match is worse
than an honest "no pair found," because a wrong match hides a real discrepancy
behind a green checkmark. So the system should never auto-bind a low-confidence
guess — it should surface candidates and let a human confirm. Only exact-key
matches are trusted automatically; everything else stays provisional until a
person accepts it. This also directly satisfies the brief's requirement that
some rows on *both* sides may have no counterpart at all — "unmatched" must be a
legitimate, stable outcome, not something the system keeps trying to force.

---

### 2.3 Deciding whether two matched rows actually agree
**Problem:** Amounts drift slightly from rounding/fees; timestamps drift slightly
from clock skew. Small drift is normal; large drift means something is wrong —
and the person reviewing needs to know *which* fields differ and *by how much*.

**Solution:** Field-by-field tolerance comparison, not a single pass/fail flag:
- **Numeric fields (quantity, price, gross amount):** relative (percentage)
  tolerance, since a fixed absolute tolerance is meaningless across trade sizes
  (a $1 tolerance is nothing on a $40,000 trade and huge on a $10 one). A small
  basis-point-level tolerance, with a small absolute floor for very small
  trades, is a defensible default.
- **Timestamps:** a fixed time window rather than a percentage, since clock
  drift isn't proportional to trade size.
- **Every comparison result stores the actual delta** (absolute and %), not
  just a boolean, so the person reviewing sees exactly which field diverged and
  by how much, not merely that "something" is off.

**Why this is the right approach:** the brief explicitly distinguishes "a tiny
difference is normal" from "a large one means something is wrong" and states the
reviewer needs magnitude, not just direction. A single global epsilon or a
plain equality check would fail both halves of that requirement.

---

### 2.4 Cancelled transactions
**Problem:** Cancelled rows appear in both files but were never meant to be
compared at all.

**Solution:** Filter cancelled rows out **before** matching, at the adapter
layer, using each source's own status vocabulary mapped into the canonical
model's status field.

**Why this is the right approach:** filtering after matching would either
surface cancelled rows as false "unmatched" noise, or worse, let them get
matched and diffed against something they were never supposed to be compared
to. Exclusion has to be symmetric — cancelled rows can appear on either side,
so the filter must be applied per source, not just to our own ledger.

---

### 2.5 Corrections that arrive later
**Problem:** A later file may repeat most rows unchanged but fix a few amounts.
The fixed values are authoritative going forward, but people will still ask
what the row used to say.

**Solution:** Store data **append-only and versioned** — every ingested version
of a given (source, external id) is kept, tagged with the file/run it arrived
in. "Current" is simply the latest version. All comparisons use the current
value; a history view can answer "what did this used to say."

**Why this is the right approach:** overwriting a value in place would satisfy
"the fixed value counts from now on" but destroys the ability to answer "what
did it used to say" — the brief asks for both, so the storage model has to
retain history rather than mutate state destructively.

---

### 2.6 The same file arriving twice
**Problem:** A resend of an identical file must not be mistaken for a
correction.

**Solution:** Detect duplicate submissions by content (e.g., a hash of the
file), and treat an exact resend as a no-op rather than creating a new "version"
of every row.

**Why this is the right approach:** without this, a benign resend gets
recorded as a correction with identical values, which is harmless in outcome
but pollutes the history/audit trail with fake "changes" that never actually
changed anything.

---

### 2.7 Manual resolutions must survive the next morning's run
**Problem:** People resolve unmatched or ambiguous rows by hand between runs.
Whatever they decide must still hold the next time the process runs.

**Solution:** Treat a human decision (these two rows are a pair / this row
genuinely has no pair) as its **own authoritative record**, separate from and
outranking the automated matcher's output. Each morning's run only operates on
rows that do not already have a standing human decision attached.

**Why this is the right approach — and the sharpest requirement in the whole
brief:** if "matched" were just a mutable flag recomputed by the matcher each
run, an automated rerun could silently overwrite or contradict a human's
decision from the day before. Making the human decision its own record, which
the automated pass must check and defer to, is the only way to guarantee "must
still hold tomorrow" is actually true rather than accidentally true.

A related edge case worth deciding explicitly: if a row that is already part of
a manual match later arrives in a correction file with new values, the pairing
(a decision about *identity*) should stand, but the diff should be recomputed
against the new values (a decision about *agreement*), since a correction
changes what the numbers say, not which two rows represent the same trade.

---

### 2.8 The daily run itself
**Problem:** The process runs every morning; someone needs to open a screen and
understand what happened.

**Solution:** Treat each run as a first-class, auditable unit of work — what
files were pulled in, when, and the resulting counts (matched & agree, matched &
differs, unmatched on each side, excluded as cancelled).

**Why this is the right approach:** a tool whose entire purpose is explaining
disagreements should be able to explain its own history too — "why did this
look different yesterday" is exactly the kind of question it exists to answer
about the underlying trades, and the same discipline should apply to itself.

---

## 3. Guiding principles behind these choices

- **Deterministic before heuristic, heuristic before automatic.** Certainty is
  used where it exists (shared IDs); scoring is used where it doesn't, but
  scoring produces candidates for a human, not silent decisions.
- **Never destroy state, only add to it.** Corrections, resends, and manual
  decisions are all additive records, not in-place overwrites — this is what
  makes "what did it used to say" and "must still hold tomorrow" both possible
  simultaneously.
- **Show magnitude, not just a flag.** Every disagreement is reported as a
  delta a human can judge, not a boolean a human has to trust blindly.
- **Isolate volatility at the edges.** Source-specific format quirks live only
  in adapters; the core matching/comparison logic never needs to change when a
  new source appears.
- **Conservative by default.** When in doubt, leave a row unmatched or
  unresolved rather than guess — a wrong automatic decision in reconciliation
  is more dangerous than an honest "still needs review."

---

## 4. Ambiguities deliberately resolved (and why)

| Ambiguity | Decision | Reasoning |
|---|---|---|
| Exact tolerance for amount agreement | Small relative (basis-point) tolerance, with a small absolute floor | Percentage scales correctly across trade sizes; a floor avoids flagging trivial noise on very small trades |
| Exact tolerance for time agreement | Fixed window (a few minutes) | Clock drift isn't proportional to trade size, so a fixed window fits better than a percentage |
| Timezone of naive-looking counterparty timestamps | Assumed UTC, stated explicitly | Removes silent ambiguity; easy to change later if wrong |
| Should a confirmed "no pair" decision ever be reopened automatically | No — sticky until a human undoes it | Consistent with treating human decisions as authoritative, not advisory |
| Should a correction to an already-matched pair reopen the match for review, or silently re-diff | Re-diff silently, keep the pairing | The correction changes agreement, not identity — reopening the *match* would be re-litigating a decision nobody actually reversed |
| How confident does a heuristic candidate need to be before matching | No fixed auto-accept cutoff — always surfaced as a ranked, human-confirmed suggestion | Simpler to defend than tuning a threshold, and safer by construction |

---

## 5. Deliberately out of scope

- Multi-tenant access control / authentication
- Currency conversion across differently-denominated statements
- Validating trade prices against external market data
- ML-based fuzzy matching (deterministic + simple scoring is sufficient here
  and far easier to audit)
- Supporting more than two sources in the UI simultaneously (though the
  ingestion layer is built so a third source could be added without changing
  core logic)

These are named explicitly rather than silently omitted, since a take-home like
this rewards showing *where* the line was drawn as much as what's inside it.