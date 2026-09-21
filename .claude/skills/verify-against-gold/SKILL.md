---
name: verify-against-gold
description: Re-run every ground-truth check against the Trust-Evals-LitReview corpus — venueids, workshop verdicts, the 112 hand-resolved records, the merge list and the overrides. Use before a release, after any resolver or precedence change, and whenever a documented figure is in doubt.
---

# Verifying against the reviewers' ground truth

This package's claims are claims about someone's systematic review. They were
established on 2026-09-20 by two researchers resolving 112 records by hand over
a day, and everything here exists to reproduce that work rather than to assert
it.

The gold data lives in `../Trust-Evals-LitReview/verification/` and is
**read-only**. Never write to it, and never edit a value to make a check pass.

## What to verify, in order of how much it matters

**1. The 90 OpenReview venueids.** For every forum id in
`openreview-venues.json`, the cached venueid must equal the gold value exactly.
This is the strongest claim the project makes — 90 automated determinations
agreeing with 90 human ones, record by record.

**2. Workshop verdicts, per record.** Compare the predicted workshop-or-main
call against `review-bucket-resolutions.json`, one record at a time. Aggregate
counts are necessary but never sufficient: two errors in opposite directions
still sum to 73/17.

**3. The merge list, in the projected RIS.** All ten titles in
`merge-titles-2026-09-20.csv` must collapse to a single year in the output of
`emit.project_ris` — not merely in the ledger. Covidence and `venuetriage` read
only the RIS, so a year that resolves but is not written is not delivered. This
distinction hid a Critical defect through eleven passing reviews.

**4. The seven overrides.** `overrides-2026-09-20.csv` records individually
adjudicated records. Not yet covered by a committed test (see `BACKLOG.md` §2).

**5. The PMLR and PMC routes.** Ten PMLR volumes and three PMC-bridged records
were verified by hand at merge time and are still not asserted by the suite
(`BACKLOG.md` §1). v267 must resolve to ICML 2025; v287 (CHIL) and v297 (ML4H)
must retrieve their titles and decline to name a venue.

## Rules

Run everything offline, from the committed cache. If a check needs a lookup the
cache lacks, that is itself a finding — the cache is supposed to back these.

Report measured against claimed for every figure. **A mismatch is a finding, not
a number to update.** Say which side you believe is wrong and why, and let a
human decide. Seven defects in this codebase were found exactly this way.
