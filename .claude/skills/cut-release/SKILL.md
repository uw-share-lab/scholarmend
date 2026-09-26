---
name: cut-release
description: Prepare a scholarmend release — version bump, gold verification, doc figure check, secret scan, changelog and tag. Use when publishing to PyPI or tagging a version.
---

# Cutting a release

## Gates, in order

1. `pytest` green, `ruff check src tests` clean, `mypy src` clean.
2. Run the `verify-against-gold` skill. Every ground-truth check must pass
   against the committed cache. This package's value is that it reproduces
   someone's manual work; shipping without re-checking that is shipping a claim
   you have not tested.
3. Run the `corpus-measurer` agent. Every figure in `README.md`, the design
   document and `BACKLOG.md` must match what the code now measures. A README has
   already published 21 where its own adjacent test asserted 17.
4. **Secret scan, working tree and full history.** This repo is public and the
   committed cache was produced with real credentials:

   ```bash
   set -a; . ./.env; set +a
   for s in "$SCHOLARMEND_OPENREVIEW_PASSWORD" "$SCHOLARMEND_S2_KEY"; do
     git grep -I -l -F -- "$s" || echo clean
     git rev-list --all | while read c; do
       git grep -I -F -- "$s" "$c" 2>/dev/null
     done | head
   done
   git grep -I -E 'eyJ[A-Za-z0-9_-]{20,}\.' || echo "no JWTs"
   git ls-files --error-unmatch .env 2>/dev/null && echo "*** .env TRACKED ***"
   ```

   A secret removed in a later commit still sits in history forever.

## Version and changelog

Bump `src/scholarmend/_version.py`. Write the changelog entry in terms of what
changed for a user of the tool — "resolved years now reach the RIS for the 331
records that carry no PY line" beats "fixed emit.py".

If a headline figure moved, say so and say why. Those numbers end up in a
methods section.

## Honesty check

Before tagging, re-read the README's "What 'settled' does and does not mean" and
the "What it does not recover" paragraph. Both exist because a claim was found to
be overstated. Confirm they still describe what the code does — and that the
figures in them match the suite, not a hand-run script.
