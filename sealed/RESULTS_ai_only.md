# Sealed test: plain AI model, no graph (A set)

The same 55 cases as the main sealed test (fingerprint `d1eefd0fdebf5bf97957be205d72adb0077444c43d3a9af99526808cb218bfcc`, checked before scoring). Model: Claude Sonnet 5.5 (no graph). It was given the shop's rule in words and a text ledger per customer (`ai_prompt_a.txt`), with payments marked as tied to a sale only where the shop tied them. It had no graph and none of Bashi's code, one try per case. Answers are in `results_ai_only.json`.

| Method | Right | Wrongly approved | Naira wrongly approved | Wrongly refused | Other wrong |
|---|---|---|---|---|---|
| Plain AI model | 55 of 55 | 0 | N0 | 0 | 0 |

## By kind of case

| Kind | Cases | Right |
|---|---|---|
| clean_within | 6 | 6 |
| clean_over | 5 | 5 |
| boundary | 4 | 4 |
| broken_promise | 7 | 7 |
| kept_promise | 4 | 4 |
| promise_not_due | 3 | 3 |
| unlinked_payment | 8 | 8 |
| deposit_first | 4 | 4 |
| split_payment | 4 | 4 |
| overpayment | 3 | 3 |
| missing_data | 4 | 4 |
| others_payment | 3 | 3 |

## Every case it got wrong

| Case | Kind | Story | Correct | AI said |
|---|---|---|---|---|

One model, one prompt, one run. A different model or prompt could score differently.
