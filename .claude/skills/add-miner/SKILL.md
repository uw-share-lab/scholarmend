---
name: add-miner
description: Add a URL miner to src/scholarmend/miners/ — host matching, claim emission, registry wiring, and the corpus measurement that justifies it. Use when a new publisher host appears in a corpus.
---

# Adding a miner

A miner is a pure function `mine(url: str) -> list[Claim]`. No network, no
state, no I/O. That is the whole interface, and it is why 99% of this package is
testable in milliseconds with no fixtures beyond a URL string.

## Measure before you write

Count the host's occurrences in the corpus first and put the number in the
module docstring. A miner for a host that appears zero times is forward-looking
at best; two such already exist (`papers.nips.cc`, bare `mlr.press`) and both are
noted in `BACKLOG.md` §6. Knowing the count tells the next reader whether the
code is load-bearing.

## Match the host exactly

Use set or dict membership against full hostnames. **Never `endswith` on a
domain** — `endswith("ncbi.nlm.nih.gov")` accepts `notncbi.nlm.nih.gov` and
`evilncbi.nlm.nih.gov`, which shipped once and was caught in review. These URLs
arrive via Google Scholar, not from a trusted source.

Parse with `urlparse` and match against `parsed.path`, never the raw string: one
real corpus URL carries `?utm_source=chatgpt.com`, having been round-tripped
through a chatbot before Scholar saw it.

## Keys versus answers

Decide which you are emitting. `proceedings.py` emits answers — venue, year,
track. `openreview.py` emits only a `forum_id`, because OpenReview hosts
workshop submissions and main-track papers at indistinguishable URLs and only
the tier-2 `venueid` separates them. **Do not helpfully emit a `version` you
cannot justify**; guessing `proceedings` there would misclassify 73 workshop
papers in the dangerous direction.

Any field you emit must exist in `ledger.PRECEDENCE`, with your `source` string
spelled identically. A mismatch makes the claim unreachable while every test
still passes.

## Fail loudly on the unrecognised

If the URL grammar has a closed vocabulary, raise on a value outside it rather
than defaulting — `proceedings.py` raises `UnknownTrack`. A new track silently
treated as main track is a false keep wearing a confident face.

## Finish

Register in `miners/__init__.py`, check your host cannot also match another
miner, and add both positive tests (asserting exact extracted values, not mere
non-emptiness) and negative ones. Then re-run the corpus count and confirm the
no-miner figure moved by what you expect.
