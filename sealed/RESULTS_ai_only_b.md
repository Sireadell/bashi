# Sealed test: plain AI model, no graph (B set)

The same 200 cases as the main sealed test (fingerprint `9915a63d879de640203689dab2e7b1927dc49a771396b2083881c4fe559d0763`, checked before scoring). Model: Claude Sonnet 5.5 (no graph). It was given the shop's rule in words and a text ledger per customer (`ai_prompt_b.txt`), with payments marked as tied to a sale only where the shop tied them. It had no graph and none of Bashi's code, one try per case. Answers are in `results_ai_only_b.json`.

| Method | Right | Wrongly approved | Naira wrongly approved | Wrongly refused | Other wrong |
|---|---|---|---|---|---|
| Plain AI model | 200 of 200 | 0 | N0 | 0 | 0 |

## By kind of case

| Kind | Cases | Right |
|---|---|---|
| clean_within | 20 | 20 |
| clean_over | 20 | 20 |
| boundary | 16 | 16 |
| broken_promise | 24 | 24 |
| kept_promise | 12 | 12 |
| promise_not_due | 10 | 10 |
| unlinked_payment | 28 | 28 |
| deposit_first | 16 | 16 |
| split_payment | 16 | 16 |
| overpayment | 12 | 12 |
| missing_data | 10 | 10 |
| others_payment | 10 | 10 |
| mixed | 6 | 6 |

## Every case it got wrong

| Case | Kind | Story | Correct | AI said |
|---|---|---|---|---|

One model, one prompt, one run. A different model or prompt could score differently.
