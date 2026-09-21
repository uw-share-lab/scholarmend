# OpenReview authentication spike

**Question:** does an OpenReview login token clear the CAPTCHA/challenge that
blocks anonymous reads of `api2.openreview.net/notes`?

**Answer: yes.**

## Steps and results

1. **Anonymous baseline** — `GET /notes?forum=0GgFeojE4a&limit=1` with no
   auth header still returns `403`. The anonymous challenge is unchanged.

2. **Obtaining a token** — `POST /login` with `{"id": <email>, "password":
   <password>}` (`Content-Type: application/json`) returns a JSON body with
   two top-level keys: `token` and `user`. `token` is a JWT.

3. **Using the token** — a request to the endpoint that matters, with header

   ```
   Authorization: Bearer <token>
   ```

   returns `200` (not `403`) for forum id `0GgFeojE4a`, which is the same
   forum blocked in step 1. This confirms the token clears the challenge.

## JSON path to venueid — confirmed, no correction needed

The brief's assumed path is correct:

```
notes[0].content.venueid.value
```

For forum `0GgFeojE4a` this returned `ICML.cc/2026/Workshop/AI4GOOD`, which
matches the gold value in
`../Trust-Evals-LitReview/verification/openreview-venues.json` for that
forum id.

Other fields present alongside `venueid` in `content` (for reference, not
needed by Task 7): `title`, `authors`, `authorids`, `keywords`, `TLDR`,
`abstract`, `pdf`, `email_sharing`, `data_release`, `venue`, `_bibtex`,
`paperhash`.

## Rate-limit behaviour (10 calls, 1s delay between each)

All 10 calls against distinct forum ids returned `200`. Response headers
exposed both a legacy and a standard rate-limit header set (values agreed
in every response):

- `ratelimit-policy: 500;w=3600` — **500 requests per 3600-second (1 hour)
  rolling window**, per authenticated token/user.
- `ratelimit-remaining` decremented by exactly 1 per call (497 → 488 across
  the 10 calls), consistent with the stated policy.
- No throttling, no `429`, and no slowdown in response latency (each call
  completed in ~0.09–0.13s) across the 10-call sample.

**Implication for tier 2:** the 527 calls tier 2 needs exceed the 500/hour
budget by 27 calls. A single unbroken run will hit the limit near the end.
Tier 2 should either (a) pace calls so the run spans slightly over an hour
(e.g. resume after the window resets, using `ratelimit-reset`, which the
response gives as seconds until the window rolls over), or (b) split the
527 calls into two batches separated by a wait for the window to reset.
Either is a small addition to the existing 1-second-delay loop in the
brief's Step 4 script.

## Token lifetime

The JWT's decoded claims (`user`, `iat`, `exp`, `iss` — decoded locally to
inspect timing only, never printed in full or committed) show:

- **`exp - iat` = 86400 seconds = 24 hours.**

A token obtained once is valid for the full 527-call run and does not need
mid-run refresh, as long as the run completes within 24 hours of login.

## Conclusion

Authentication via `POST /login` + `Authorization: Bearer <token>` clears
the challenge that blocks anonymous reads. Task 7 does **not** need the
one-time authenticated-browser-capture fallback: it can call `/login` once
per run (or once per 24h), reuse the token for all reads, and must budget
calls to the 500-requests/hour limit (pace or split runs of >500 calls).
