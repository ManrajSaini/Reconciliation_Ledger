# The Reconciliation Problem — Assignment Brief

This document captures the assignment exactly as given: the problem statement,
requirements, deliverables, and example data. (For the proposed solution
approach, see `reconciliation-solution.md`.)

---

## Stack

Any Python web framework, any database, any way of building the UI.

## Data

Make up your own.

## Anything unclear

Decide for yourself and record the decision in the README.

---

## The Problem

Two systems recorded the same transactions. Your own ledger says one thing.
The other company's statement says another. They disagree on amounts, on
times, and on which transactions happened at all. Until someone works out
where and why, the accounts cannot be closed.

The two systems were built by different companies and were never designed to
agree. They use different column names for the same field, write dates in
different formats, and use different words for the same value, so where one
says `BUY` the other says `B`. Tomorrow there may be a third company sending a
third format.

Not every difference is a real problem. Amounts drift apart slightly because
of rounding and fees, and recorded times drift apart slightly because two
clocks are never quite the same. A tiny difference is normal. A large one
means something is wrong, and the person looking at it needs to know which
fields differ and by how much. Some rows will have nothing matching them on
the other side at all, and this happens in both directions. Cancelled
transactions also appear in the files, and these were never meant to be
compared at all.

Files keep arriving. Sometimes the same file is sent twice. Sometimes a file
is a correction, where most rows are unchanged but a few amounts have been
fixed, and the fixed values are the ones that count from then on, although
people will still ask what the row used to say.

The process runs every morning, and between runs people resolve things by
hand. They match two rows the system could not match, or they accept that a
row genuinely has no pair. Whatever they decide must still hold tomorrow.

**Build the screen someone opens each morning to find what does not match, and
to resolve it.**

---

## What to Build

- **Database.** Design the tables.
- **Backend.** Loading the files, matching, and comparing. The comparison
  logic should be testable without a database and without a browser.
- **UI.** Enough to be usable: start a run, see the results, inspect what
  differs on a row that does not agree, and match an unmatched row by hand.
  Plain server-rendered pages are fine.
- **Tests.** Cover the logic that matters.
- **README.** How to run it, what you decided and why, what you left out, and
  what you would do next.

---

## Example Data (for illustration only — make your own, and more of it)

### Your own ledger

```csv
trade_id,traded_at,instrument,side,quantity,price,gross_amount,state
T-1001,2025-07-01T09:15:00Z,BTC-USD,BUY,0.50,62000.00,31000.00,SETTLED
T-1011,2025-07-04T10:15:00Z,ETH-USD,BUY,10.00,3400.00,34000.00,SETTLED
T-1015,2025-07-05T10:00:00Z,SOL-USD,SELL,300.00,146.00,43800.00,SETTLED
T-1016,2025-07-06T09:00:00Z,BTC-USD,BUY,0.20,63200.00,12640.00,SETTLED
T-1018,2025-07-06T15:00:00Z,SOL-USD,BUY,100.00,149.00,14900.00,CANCELLED
```

### The other company's statement (same period)

```csv
reference,executed_at,symbol,direction,qty,unit_price,total,status
T-1001,2025-07-01 09:15:00,BTC-USD,B,0.5,62000,31000.00,SETTLED
T-1011,2025-07-04 10:15:00,ETH-USD,B,10,3417,34170.00,SETTLED
T-1015,2025-07-05 10:40:00,SOL-USD,S,300,146,43800.00,SETTLED
C-9001,2025-07-06 11:20:00,BTC-USD,B,0.15,63100,9465.00,SETTLED
```

> Note: column names, date formats, and vocabulary (`BUY` vs `B`, `SELL` vs
> `S`) differ deliberately between the two files. `Create data of your own
> that covers the rest.`

---

## Field Mapping Observed Between the Two Sample Formats

| Concept | Ledger column | Statement column |
|---|---|---|
| Trade identifier | `trade_id` | `reference` |
| Timestamp | `traded_at` (ISO 8601, `Z` suffix) | `executed_at` (space-separated, no timezone marker) |
| Instrument | `instrument` | `symbol` |
| Side | `side` (`BUY` / `SELL`) | `direction` (`B` / `S`) |
| Quantity | `quantity` | `qty` |
| Price | `price` | `unit_price` |
| Total value | `gross_amount` | `total` |
| Status | `state` | `status` |

---

## Observations Embedded in the Sample Rows

- `T-1001` — identical on both sides (id, time, quantity, price, total all
  match exactly).
- `T-1011` — same id and time; price differs (`3400.00` vs `3417`), which
  cascades into a differing total (`34000.00` vs `34170.00`).
- `T-1015` — same id, quantity, price, and total; only the time differs
  (`10:00:00` vs `10:40:00`), a 40-minute gap.
- `T-1016` — present only in the ledger; no counterpart row appears in the
  statement at all.
- `T-1018` — present only in the ledger, marked `CANCELLED`.
- `C-9001` — present only in the statement, with an identifier format
  (`C-` prefix) unlike the ledger's `T-` prefix; quantity, price, and total
  all differ from the ledger's nearby `T-1016` row, so it is not obviously the
  same trade under a different id.