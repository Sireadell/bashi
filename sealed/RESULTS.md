# Sealed test results

This is a test I wrote. The 55 cases and their correct answers were fixed, hashed and pushed (commit 977f5bd) before any system was run on them. Fingerprint (sha256): `d1eefd0fdebf5bf97957be205d72adb0077444c43d3a9af99526808cb218bfcc`. `python sealed/run_sealed.py` re-checks that fingerprint and refuses to run if it differs.

I chose the cases to cover the situations Bashi was built for, so this shows what it does there. It is not a measure of accuracy on real shops. I also wrote Bashi, so I was not blind to how it behaves.

## Result

| Method | Right | Wrongly approved | Naira wrongly approved | Wrongly refused | Other wrong |
|---|---|---|---|---|---|
| Bashi, confirmed links only | 47 of 55 | 0 | N0 | 8 | 0 |
| Bashi with payment matching | 55 of 55 | 0 | N0 | 0 | 0 |
| Balance only | 41 of 55 | 14 | N258,001 | 0 | 0 |

## By kind of case

| Kind | Cases | Bashi, confirmed links only | Bashi with payment matching | Balance only |
|---|---|---|---|---|
| clean_within | 6 | 6 | 6 | 6 |
| clean_over | 5 | 5 | 5 | 5 |
| boundary | 4 | 4 | 4 | 4 |
| broken_promise | 7 | 7 | 7 | 0 |
| kept_promise | 4 | 4 | 4 | 4 |
| promise_not_due | 3 | 3 | 3 | 3 |
| unlinked_payment | 8 | 4 | 8 | 7 |
| deposit_first | 4 | 0 | 4 | 4 |
| split_payment | 4 | 4 | 4 | 4 |
| overpayment | 3 | 3 | 3 | 1 |
| missing_data | 4 | 4 | 4 | 0 |
| others_payment | 3 | 3 | 3 | 3 |

## Every case a method got wrong

| Case | Kind | Story | Correct | Bashi, confirmed links only | Bashi with payment matching | Balance only |
|---|---|---|---|---|---|---|
| Q16 | broken_promise | Broken promise, no debt | NO | NO | NO | YES (wrong) |
| Q17 | broken_promise | Broken promise, sale paid | NO | NO | NO | YES (wrong) |
| Q18 | broken_promise | Broken promise, small unpaid sale | NO | NO | NO | YES (wrong) |
| Q19 | broken_promise | Promise broken yesterday | NO | NO | NO | YES (wrong) |
| Q20 | broken_promise | One kept promise, one broken | NO | NO | NO | YES (wrong) |
| Q21 | broken_promise | Very old broken promise | NO | NO | NO | YES (wrong) |
| Q22 | broken_promise | Part paid sale and a broken promise | NO | NO | NO | YES (wrong) |
| Q30 | unlinked_payment | Paid 60,000, never tied to the sale | YES | NO (wrong) | YES | YES |
| Q31 | unlinked_payment | Paid 45,000, never tied | YES | NO (wrong) | YES | YES |
| Q32 | unlinked_payment | Two same-size sales, one paid, not tied | YES | NO (wrong) | YES | YES |
| Q33 | unlinked_payment | Big limit, paid 200,000, not tied | YES | NO (wrong) | YES | YES |
| Q36 | unlinked_payment | Paid, not tied, but a broken promise | NO | NO | NO | YES (wrong) |
| Q38 | deposit_first | Deposit of 50,000 before the sale | YES | NO (wrong) | YES | YES |
| Q39 | deposit_first | Deposit of 40,000 before the sale | YES | NO (wrong) | YES | YES |
| Q40 | deposit_first | Deposit of 30,000 on a 70,000 sale | YES | NO (wrong) | YES | YES |
| Q41 | deposit_first | Deposit of 20,000 before the sale | YES | NO (wrong) | YES | YES |
| Q47 | overpayment | Same, asks one naira over the limit | NO | NO | NO | YES (wrong) |
| Q48 | overpayment | Extra on one sale does not clear the other | NO | NO | NO | YES (wrong) |
| Q49 | missing_data | Only sale has no amount | REFUSE | REFUSE | REFUSE | YES (wrong) |
| Q50 | missing_data | One of two sales has no amount | REFUSE | REFUSE | REFUSE | YES (wrong) |
| Q51 | missing_data | No-amount sale and a payment | REFUSE | REFUSE | REFUSE | YES (wrong) |
| Q52 | missing_data | Paid sale plus a no-amount sale | REFUSE | REFUSE | REFUSE | YES (wrong) |

## What is not covered

- Sales that were reversed or refunded: Bashi has no way to record a reversal yet, so there are no such cases.
- The cases are small and tidy. Real records are messier, which is why the whole-shop view marks every matched link as inferred.
