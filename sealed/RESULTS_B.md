# Sealed test results

This is a test I wrote. The 200 cases and their correct answers were fixed, hashed and pushed (commit a5e2bd8) before any system was run on them. Fingerprint (sha256): `9915a63d879de640203689dab2e7b1927dc49a771396b2083881c4fe559d0763`. `python sealed/run_sealed.py b` re-checks that fingerprint and refuses to run if it differs.

I chose the cases to cover the situations Bashi was built for, so this shows what it does there. It is not a measure of accuracy on real shops. I also wrote Bashi, so I was not blind to how it behaves.

## Result

| Method | Right | Wrongly approved | Naira wrongly approved | Wrongly refused | Other wrong |
|---|---|---|---|---|---|
| Bashi, confirmed links only | 190 of 200 | 0 | N0 | 10 | 0 |
| Bashi with payment matching | 200 of 200 | 0 | N0 | 0 | 0 |
| Balance only | 161 of 200 | 39 | N3,970,000 | 0 | 0 |

## By kind of case

| Kind | Cases | Bashi, confirmed links only | Bashi with payment matching | Balance only |
|---|---|---|---|---|
| clean_within | 20 | 20 | 20 | 20 |
| clean_over | 20 | 20 | 20 | 20 |
| boundary | 16 | 16 | 16 | 16 |
| broken_promise | 24 | 24 | 24 | 0 |
| kept_promise | 12 | 12 | 12 | 12 |
| promise_not_due | 10 | 10 | 10 | 10 |
| unlinked_payment | 28 | 24 | 28 | 27 |
| deposit_first | 16 | 11 | 16 | 16 |
| split_payment | 16 | 16 | 16 | 16 |
| overpayment | 12 | 12 | 12 | 9 |
| missing_data | 10 | 10 | 10 | 0 |
| others_payment | 10 | 10 | 10 | 10 |
| mixed | 6 | 5 | 6 | 5 |

## Every case a method got wrong

| Case | Kind | Story | Correct | Bashi, confirmed links only | Bashi with payment matching | Balance only |
|---|---|---|---|---|---|---|
| B057 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B058 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B059 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B060 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B061 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B062 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B063 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B064 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B065 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B066 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B067 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B068 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B069 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B070 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B071 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B072 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B073 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B074 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B075 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B076 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B077 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B078 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B079 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B080 | broken_promise | Broken promise, small ask | NO | NO | NO | YES (wrong) |
| B103 | unlinked_payment | Payments recorded but not tied to sales | YES | NO (wrong) | YES | YES |
| B104 | unlinked_payment | Payments recorded but not tied to sales | NO | NO | NO | YES (wrong) |
| B117 | unlinked_payment | Payments recorded but not tied to sales | YES | NO (wrong) | YES | YES |
| B123 | unlinked_payment | Payments recorded but not tied to sales | YES | NO (wrong) | YES | YES |
| B129 | unlinked_payment | Payments recorded but not tied to sales | YES | NO (wrong) | YES | YES |
| B133 | deposit_first | Money paid before the sale | YES | NO (wrong) | YES | YES |
| B137 | deposit_first | Money paid before the sale | YES | NO (wrong) | YES | YES |
| B139 | deposit_first | Money paid before the sale | YES | NO (wrong) | YES | YES |
| B141 | deposit_first | Money paid before the sale | YES | NO (wrong) | YES | YES |
| B145 | deposit_first | Money paid before the sale | YES | NO (wrong) | YES | YES |
| B166 | overpayment | Paid more than the sale | NO | NO | NO | YES (wrong) |
| B170 | overpayment | Paid more than the sale | NO | NO | NO | YES (wrong) |
| B174 | overpayment | Paid more than the sale | NO | NO | NO | YES (wrong) |
| B175 | missing_data | A sale has no amount | REFUSE | REFUSE | REFUSE | YES (wrong) |
| B176 | missing_data | A sale has no amount | REFUSE | REFUSE | REFUSE | YES (wrong) |
| B177 | missing_data | A sale has no amount | REFUSE | REFUSE | REFUSE | YES (wrong) |
| B178 | missing_data | A sale has no amount | REFUSE | REFUSE | REFUSE | YES (wrong) |
| B179 | missing_data | A sale has no amount | REFUSE | REFUSE | REFUSE | YES (wrong) |
| B180 | missing_data | A sale has no amount | REFUSE | REFUSE | REFUSE | YES (wrong) |
| B181 | missing_data | A sale has no amount | REFUSE | REFUSE | REFUSE | YES (wrong) |
| B182 | missing_data | A sale has no amount | REFUSE | REFUSE | REFUSE | YES (wrong) |
| B183 | missing_data | A sale has no amount | REFUSE | REFUSE | REFUSE | YES (wrong) |
| B184 | missing_data | A sale has no amount | REFUSE | REFUSE | REFUSE | YES (wrong) |
| B196 | mixed | Several sales, mixed payment situations | YES | NO (wrong) | YES | YES |
| B197 | mixed | Several sales, mixed payment situations | NO | NO | NO | YES (wrong) |

## What is not covered

- Sales that were reversed or refunded: Bashi has no way to record a reversal yet, so there are no such cases.
- The cases are small and tidy. Real records are messier, which is why the whole-shop view marks every matched link as inferred.
