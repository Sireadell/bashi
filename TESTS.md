# Quick check (under 2 seconds, no database)

Two test files run on invented data held in memory, with no database, no network and no keys:

```
python -m pytest tests/test_fast_rules.py tests/test_demo_cache.py -q
```

Expected: `44 passed`. They cover the two credit rules (limit and broken promise), the CANNOT TRACE refusals, the fingerprint changing when any record changes, the what-if on a copy, the payment matching, and the demo-case cache (reuse, reset, expiry after ten minutes, fallback to the Tunde case). On 18 Oct 2026 this ran in a fresh clone with a new virtual environment and no `.env`: 44 passed in 1.85 s.

The same command runs on every push in `.github/workflows/fast-tests.yml`.

# Test runs

Every test runs against the hosted FalkorDB database, on a throwaway copy of the graph that is deleted afterwards. The model keys are blanked during the run, so no test depends on an AI model.

| Date | Code | What ran | Result | Time |
|---|---|---|---|---|
| 18 Oct 2026 | commit 8458c53 | Full suite, `python -m pytest tests -q` (237 collected, includes the 44 quick tests) | 236 passed, 1 setup error (a network name lookup to the hosted database failed once); that test passed when re-run alone (1 passed, 14 s) | 32 min 12 s |
| 18 Oct 2026 | commit 911cea7 | Full suite, `python -m pytest tests -q` | 187 passed, 0 failed | 27 min 49 s |
| 18 Oct 2026 | commit 9bae6c1 | `tests/test_bashi.py` and the new `tests/test_evidence_graph.py` (receipt graph picture, real-shop banner) | 20 passed, 0 failed | 3 min 12 s |

296 tests are collected today (the full run at commit 8458c53 collected 237; later commits added more).

Run them yourself:

```
python -m pytest tests -q
```

It takes about 25 minutes because each test talks to the hosted database.
