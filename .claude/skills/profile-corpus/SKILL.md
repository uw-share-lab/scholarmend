---
name: profile-corpus
description: Measure scholarmend's runtime and allocation over the full 2,413-record corpus, find hot paths, and check a change has not made the offline path slow. Use after touching parse, miners, ledger or emit.
---

# Profiling against the corpus

The whole corpus resolves offline in about **0.6 seconds** and the full test
suite runs in about **0.6 seconds**. Both numbers matter: the first is what
makes re-deriving a headline figure a casual act rather than a chore, and the
second is what keeps test-driven work pleasant.

Treat a regression in either as a real finding.

## Measure, do not guess

```bash
python -X importtime -c "import scholarmend" 2>&1 | tail -15
python -m cProfile -s cumtime -m scholarmend.cli \
  --input ../Trust-Evals-LitReview/corpus --out /tmp/prof --cache .scholarmend-cache --offline \
  2>/dev/null | head -30
```

Time the phases separately — parsing, mining, ledger resolution, projection,
JSON emission — because they have very different shapes. Parsing is regex over
40,833 lines; mining is regex per URL; the ledger is a small nested loop per
field; emission writes an 11 MB JSON document, which is usually the largest
single cost.

## Known, deliberate inefficiencies

`Ledger.resolve` is O(precedence × claims) rather than a dict keyed by source
(`BACKLOG.md` §7). At this scale it is invisible. Confirm that with a
measurement before optimising it — a faster resolve that scatters precedence out
of its single table would trade a real invariant for an imaginary gain.

## Rules

- **Correctness first.** Never trade the round-trip guarantee, the out-of-scope
  guard or precedence-as-data for speed. Re-run `verify-against-gold` after any
  optimisation.
- Profile the offline path. Tier 2 timings measure someone else's server.
- Report before and after with the command you ran. A speedup you cannot
  reproduce is a story, not a result.
