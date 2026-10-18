# Sealed test: an AI with no graph

The question a judge asks is whether the graph does work an AI could not do without it. So I gave a language model the same sealed cases with no graph and scored it with the same key.

## Setup

| Item | Value |
|---|---|
| Model asked for | `gemini-flash-lite-latest` (the model in this project's `.env`, the same one the live site uses) |
| Model Google says answered | `gemini-3.5-flash-lite` |
| Temperature | 0 |
| Date | 2026-10-18 (set A finished 06:30 UTC, set B finished 09:51 UTC) |
| Cases | the 200 set-B cases (`cases_b.json`, fingerprint checked) and the 55 set-A cases (`cases.json`) |
| What the model sees | one customer at a time as plain tables: sales (number, date, amount), payments (number, date, amount), promises (amount, made, due, kept), the limit, the check date and the request. No column says which payment paid which sale. |
| Rules it gets | the full shop rule the answer key is computed from (`make_key_b.py`), so the only thing it lacks is the links |
| Raw answers | `sealed/llm_results_b_gemini-flash-lite-latest.json`, `sealed/llm_results_a_gemini-flash-lite-latest.json` |
| Rerun | `python sealed/llm_baseline.py b` (needs `GEMINI_API_KEY`) |

I wrote the prompt once and did not change it after seeing answers. A stronger model (`gemini-flash-latest`) was planned too, but the free key allows 20 requests a day on it and that was used up, so it was not run.

## Result on the 200 sealed cases (set B)

| Method | Right | Wrongly approved | Naira wrongly approved | Wrongly refused |
|---|---|---|---|---|
| Bashi (graph, payment matching) | 200 of 200 | 0 | N0 | 0 |
| Bashi (graph, confirmed links only) | 190 of 200 | 0 | N0 | 10 |
| Balance only | 161 of 200 | 39 | N3,970,000 | 0 |
| AI with no graph (Gemini flash-lite) | 152 of 200 | 23 | N3,685,003 | 25 |

On the 55 set-A cases: AI with no graph 48 of 55 right, 4 wrongly approved, 3 wrongly refused. Bashi with payment matching 55 of 55, 0 wrongly approved. Balance only 41 of 55, 14 wrongly approved.

## By kind of case (set B)

| Kind | Cases | Bashi (matching) | Balance only | AI with no graph |
|---|---|---|---|---|
| clean_within | 20 | 20 | 20 | 18 |
| clean_over | 20 | 20 | 20 | 17 |
| boundary | 16 | 16 | 16 | 9 |
| broken_promise | 24 | 24 | 0 | 24 |
| kept_promise | 12 | 12 | 12 | 9 |
| promise_not_due | 10 | 10 | 10 | 4 |
| unlinked_payment | 28 | 28 | 27 | 18 |
| deposit_first | 16 | 16 | 16 | 9 |
| split_payment | 16 | 16 | 16 | 13 |
| overpayment | 12 | 12 | 9 | 10 |
| missing_data | 10 | 10 | 0 | 10 |
| others_payment | 10 | 10 | 10 | 6 |
| mixed | 6 | 6 | 5 | 5 |

## What the AI got wrong, read honestly

| Finding | Detail |
|---|---|
| It handled promises | 24 of 24 broken-promise cases right, where the balance check got 0. Reading a kept/not kept column does not need a graph. |
| It handled missing amounts | 10 of 10 right. |
| Most mistakes are slips, not missing links | Of its 48 wrong answers, only 1 (B166) is the same wrong answer the balance check gives. The rest are adding up, comparing, or reading the wrong way round: its own reason often says the total is over the limit and the answer still says YES, or it calls a promise due on 2026-10-25 broken on 2026-10-01. |
| Exactly at the limit | It often said NO when debt plus request equalled the limit exactly, then argued itself back to YES inside its reason (B041, B051, B055, B083, B085, B092, B103, B129). |
| What this does not show | A stronger model, or one allowed to work step by step before answering, would likely make fewer slips. This test does not prove an AI cannot do it; it shows this AI, with this prompt, approved 23 credits it should have refused. |

## Every set-B case the AI got wrong

Reasons are cut to 160 characters; the full text is in the JSON.

| Case | Kind | Correct | AI said | AI's reason |
|---|---|---|---|---|
| B012 | clean_within | YES | NO | The customer owes N80000 from past sales, and adding the new request of N20000 exceeds the credit limit of N100000. |
| B014 | clean_within | YES | NO | The customer owes N110000 on past sales and adding the new request of N190000 exceeds the credit limit of N300000. |
| B032 | clean_over | NO | YES | The customer owes N90000 and the new request of N90000 brings the total to N180000, which exceeds the credit limit of N150000. |
| B035 | clean_over | NO | YES | The customer owes N95000, and adding the new request of N110000 totals N205000, which exceeds the credit limit of N150000. |
| B039 | clean_over | NO | YES | The customer owes N40000, and adding the new request of N135000 brings the total to N175000, which exceeds the N150000 credit limit. |
| B041 | boundary | YES | NO | The customer owes N95000 from past sales, and adding the new request of N55000 brings the total to N150000, which exceeds the credit limit when combined with... |
| B043 | boundary | YES | NO | The total amount the customer owes plus the new request exceeds the credit limit. |
| B048 | boundary | NO | YES | The customer owes N45000 and adding the new request of N105001 equals N150001, which exceeds the N150000 credit limit. |
| B050 | boundary | NO | YES | The customer owes N50000, and adding the new request of N250001 results in N300001, which exceeds the credit limit of N300000. |
| B051 | boundary | YES | NO | What the customer owes (N35000) plus the new request (N115000) equals N150000, but the total exposure exceeds the credit limit if we consider terms, or rathe... |
| B054 | boundary | NO | YES | The customer owes N40000, which plus the new request of N160001 equals N200001, slightly exceeding the credit limit of N200000... |
| B055 | boundary | YES | NO | What the customer owes (N25000) plus the new request (N275000) equals N300000, which is not more than the credit limit, but wait: S1 amount is N45000, paymen... |
| B083 | kept_promise | YES | NO | What the customer owes (N65000) plus the new request (N35000) equals N100000, which exceeds the credit limit because extra money paid on one sale does not cl... |
| B085 | kept_promise | YES | NO | The total amount the customer owes (N90000) plus the new request (N110000) equals N200000, which does not exceed the credit limit, but rule 4 says NO if ther... |
| B092 | kept_promise | YES | NO | The total amount the customer owes (N105000) plus the new request (N95000) equals the credit limit of N200000, but rule 4 specifies 'more than the credit lim... |
| B093 | promise_not_due | YES | NO | There is a broken promise with a due date of 2026-10-25, which means the condition for a broken promise is met because the check date is 2026-10-01 (wait, th... |
| B097 | promise_not_due | YES | NO | The customer has a broken promise to pay whose due date is before the check date. |
| B098 | promise_not_due | YES | NO | There is a broken promise to pay with a due date before the check date. |
| B100 | promise_not_due | YES | NO | The customer has a broken promise with a due date prior to the check date. |
| B101 | promise_not_due | YES | NO | The customer has a broken promise with a due date of 2026-10-01, which is before the check date. |
| B102 | promise_not_due | YES | NO | The customer has a broken promise to pay that has a due date before the check date. |
| B103 | unlinked_payment | YES | NO | The customer owes N65000 from past sales, and adding the new request of N35000 brings the total to N100000, which does not exceed the limit, but the prompt's... |
| B110 | unlinked_payment | NO | YES | The customer owes N40000 from past sales, and adding the new request of N175000 totals N215000, which exceeds the credit limit of N200000. |
| B114 | unlinked_payment | NO | YES | The customer owes nothing on past sales and the requested credit plus current debt is within the limit. |
| B116 | unlinked_payment | NO | YES | The customer currently owes nothing and the new request of N150000 exceeds the credit limit of N100000, wait, the rule says 'what the customer owes plus the ... |
| B121 | unlinked_payment | YES | NO | The customer owes N60000, and adding the new request of N5000 exceeds the credit limit of N100000. |
| B122 | unlinked_payment | NO | YES | The customer owes nothing, so the new request of N350000 plus current debt remains within the N300000 credit limit? Wait, N350000 is greater than N300000 limit. |
| B124 | unlinked_payment | NO | YES | All sales have amounts, there are no broken promises, and the current balance of N0 plus the new request of N265000 is within the credit limit of N300000. |
| B126 | unlinked_payment | NO | YES | The customer owes nothing, has no broken promises, and the new request plus current balance does not exceed the credit limit. |
| B129 | unlinked_payment | YES | NO | The customer owes N65000 from sale S3, and adding the new request of N35000 brings the total to N100000, which exceeds the credit limit when combined with an... |
| B130 | unlinked_payment | NO | YES | The customer owes nothing on past sales, has no broken promises, and the new request of N175000 is within the N150000 credit limit. |
| B131 | deposit_first | YES | NO | What the customer owes is N165000, and adding the new request of N70000 brings the total to N235000, but the calculation actually exceeds the limit when cons... |
| B132 | deposit_first | NO | YES | The customer owes N100000 and with the new request of N100000 the total is N200000, which exceeds the credit limit of N150000. |
| B135 | deposit_first | YES | NO | What the customer owes (N25000) plus the new request (N115000) equals N140000, which does not exceed the limit, but payment P1 (2026-07-01) precedes sale S1 ... |
| B137 | deposit_first | YES | NO | The customer owes N45000, and adding the new request of N25000 exceeds the credit limit of N100000 when combined with the unpaid balance. |
| B141 | deposit_first | YES | NO | The customer owes N135000 from previous sales, which already exceeds the N100000 credit limit. |
| B144 | deposit_first | NO | YES | The customer owes N0, so the new request of N115000 is within the credit limit of N100000 and there are no broken promises. |
| B145 | deposit_first | YES | NO | The customer owes N95000 from sale S2 and adding the new request of N5000 exceeds the credit limit of N100000. |
| B148 | split_payment | NO | YES | The customer owes nothing on past sales and has no broken promises, so the new request of N135000 is within the N100000 credit limit? Wait, N135000 is greate... |
| B156 | split_payment | NO | YES | The customer owes N0, the new request is N185000, and total credit usage of N185000 is below the limit of N150000? Wait, N185000 is greater than N150000. |
| B162 | split_payment | NO | YES | The customer owes nothing on past sales, has no broken promises, and the current balance plus the new request is within the credit limit. |
| B166 | overpayment | NO | YES | The customer owes N0, so the new request of N160000 plus what is owed is within the N150000 credit limit? Wait, 0 + 160000 = 160000 which is more than 150000... |
| B169 | overpayment | YES | NO | The customer owes N20000 from previous sales, and adding the new request of N60000 exceeds the credit limit of N100000 when combined incorrectly? Wait, total... |
| B185 | others_payment | NO | YES | The customer owes N30000 for past sales, and adding the new request of N130000 totals N160000, which exceeds the credit limit of N150000. |
| B189 | others_payment | NO | YES | The customer owes N20000 from past sales, which brings the total credit requested to N165000, but wait: N20000 + N145000 = N165000, which exceeds the N150000... |
| B191 | others_payment | NO | YES | The customer owes N45000 and with the new request of N135000 the total is N180000, which exceeds the credit limit of N150000. |
| B193 | others_payment | NO | YES | The customer owes N70000, which plus the new request of N165000 equals N235000, but wait: N70000 + N165000 = N235000 which exceeds the N200000 credit limit, ... |
| B196 | mixed | YES | NO | The total amount the customer owes plus the new credit request exceeds the credit limit of N100000. |

## The prompt, word for word

Placeholders in braces are filled per case. Sales with no amount show an empty amount.

```
You help a small shop decide whether to sell to a customer on credit.

The shop's rule:
1. If any sale has no amount recorded, answer CANNOT TRACE.
2. What the customer owes is, for each sale, its amount minus the payments that paid for that sale, never below zero. Extra money paid on one sale does not clear another sale.
3. A promise to pay is broken if it was not kept and its due date is before the check date.
4. Answer NO if there is a broken promise, or if what the customer owes plus the new request is more than the credit limit. Otherwise answer YES.

Below are this customer's records, exported from the shop's book as plain tables.

Check date: {as_of}
Credit limit: N{limit}
New request: N{request} on credit

Sales (number, date, amount):
{sales}

Payments received from this customer (number, date, amount):
{payments}

Promises to pay (amount, date made, due date, kept):
{promises}

Reply with JSON only, in this shape: {{"answer": "YES" or "NO" or "CANNOT TRACE", "reason": "one sentence"}}
```
