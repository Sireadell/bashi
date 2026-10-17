# Tamper sweep

Run with `python tamper_sweep.py` on a throwaway copy of the practice shop (`shop_a`), which is deleted afterwards. For each edit: change one thing, replay the saved decision (it must fail), undo the change, replay again (it must pass).

| # | Edit | Caught and restored | What verify said |
|---|---|---|---|
| 1 | Change a sale amount (T0001) | yes | Trade T0001 amount changed N30,000 -> N31,000 |
| 2 | Change a different sale amount (T0002) | yes | Trade T0002 amount changed N20,000 -> N40,000 |
| 3 | Change a payment amount (P0001) | yes | Payment P0001 amount changed N30,000 -> N30,500 |
| 4 | Change a sale date (T0001) | yes | Trade T0001 date changed 2026-06-16 -> 2020-01-01 |
| 5 | Mark a promise as kept (PR001) | yes | Promise PR001 kept changed False -> True |
| 6 | Change a promise amount (PR001) | yes | Promise PR001 amount changed N10,000 -> N10,700 |
| 7 | Raise the customer's credit limit | yes | Customer C001 limit changed N60,000 -> N160,000 |
| 8 | Edit the saved decision's yes or no | yes | Decision D0033 itself was edited (its fingerprint no longer matches) |
| 9 | Edit the saved decision's fingerprint | yes | Decision D0033 itself was edited (its fingerprint no longer matches) |
| 10 | Edit the decision's saved copy of its records | yes | Decision D0033 itself was edited (its fingerprint no longer matches) |
| 11 | Remove a record from the decision's evidence (T0002) | yes | Trade T0002 is no longer linked to this decision |

**11 of 11 edits caught.**
