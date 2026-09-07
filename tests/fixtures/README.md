# Synthetic Test Fixtures

These CSVs are the shared dataset reused across phases (per plan.md Phase 1).
Each trade id encodes the scenario it exercises so tests stay traceable.

## day1_ledger.csv / day1_statement.csv

| id (ledger / statement) | scenario |
|---|---|
| T-2001 | exact match: id, time, qty, price, total all agree |
| T-2002 | price drift within tolerance (rounding-level, e.g. bps-level) |
| T-2003 | price drift outside tolerance (real discrepancy) |
| T-2004 | time drift within tolerance (small clock skew, e.g. seconds) |
| T-2005 | time drift outside tolerance (large gap, e.g. 40+ minutes) |
| T-2006 | ledger-only; no counterpart row in statement at all |
| C-3001 | statement-only; no counterpart row in ledger at all, non-`T-` id prefix |
| T-2007 | present both sides but CANCELLED on the ledger side |
| C-3002 | present both sides but CANCELLED on the statement side |
| T-2008 | exact match on day 1; gets corrected in day2_statement_correction.csv |

## day2_statement_correction.csv

Same rows as day1_statement.csv, except T-2008's price/total are fixed to a
new value. Simulates "a later file repeats most rows unchanged but fixes a
few amounts" (brief, and solution.md #2.5).

## day2_ledger_duplicate.csv

Byte-identical resend of day1_ledger.csv. Simulates "the same file sent
twice" (brief, and solution.md #2.6) — used in Phase 3 for content-hash
dedup tests, not needed by Phase 1's adapter-only tests.
