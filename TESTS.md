# Test runs

Every test runs against the hosted FalkorDB database, on a throwaway copy of the graph that is deleted afterwards. The model keys are blanked during the run, so no test depends on an AI model.

| Date | Code | What ran | Result | Time |
|---|---|---|---|---|
| 18 Oct 2026 | commit 911cea7 | Full suite, `python -m pytest tests -q` | 187 passed, 0 failed | 27 min 49 s |
| 18 Oct 2026 | commit 9bae6c1 | `tests/test_bashi.py` and the new `tests/test_evidence_graph.py` (receipt graph picture, real-shop banner) | 20 passed, 0 failed | 3 min 12 s |

193 tests are collected today: the 187 above plus 6 for the receipt graph picture.

Run them yourself:

```
python -m pytest tests -q
```

It takes about 25 minutes because each test talks to the hosted database.
