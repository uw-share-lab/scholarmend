---
name: refresh-cache
description: Populate or repair the committed tier-2 cache with live OpenReview, PMLR and PMC lookups. Use when adding records, after fixing a resolver that may have cached wrong answers, or when --offline reports misses.
---

# Refreshing the cache

`.scholarmend-cache/` is committed, and it is what makes "a rerun makes zero API
calls" true rather than aspirational. Treat it as an artifact of record.

## Before you fetch anything

**Fix the code first.** `Cache.fetch` returns a hit without retrying, so a bug
that produces an empty result poisons every entry it touches — permanently. This
has happened twice: OpenReview returning a Decision note with no `venueid`
cached 25 empties, and a `<h1>`-vs-`<h2>` mismatch cached 4 more. Populating
before fixing just commits the wrong answers.

## Budget

OpenReview allows **500 requests per rolling hour, per token**; the headers say
so (`ratelimit-policy: 500;w=3600`) and `http._respect_rate_limit` paces against
them. The whole corpus needs ~519 OpenReview lookups, which crosses that line and
will pause. The 112 hand-resolved records need ~97, which does not.

Decide which you are doing and say so before starting. Keep a delay between
calls; nothing here is urgent.

## Completeness trap

Volumes reachable **only through the PMC bridge** are easy to miss. PMC yields
its volume number at resolve time, not from a URL, so a script that collects
volumes from miner claims will not see 267, 287 or 297 — and the bridge then
dead-ends at a cache miss under `--offline`. Fetch the PMLR index page for every
volume any route can produce, not just the mined ones.

## After fetching

1. Verify against gold: every forum id in `openreview-venues.json` must match.
   **Report mismatches; never reconcile them.**
2. Confirm no entry is empty (`{}` or `title == ""`).
3. Scan before committing — the cache goes to a public repo. Check for the
   account email, the password, JWT-shaped strings, and any `token`/`password`
   key. An entry should be exactly `{"key": ..., "payload": ...}`.
4. Commit with a message saying what was fetched and why.

`scripts/repopulate.py` handles the repair case. Note its known hazard in
`BACKLOG.md` §3: it deletes poisoned entries before re-fetching and is unguarded,
so running it without credentials loses them until you re-run with credentials.
