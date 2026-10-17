# Five-minute path for judges

Live site: https://bashi-vrfv.onrender.com (no sign-up). The free host sleeps when idle, so the first visit can show a "waking up" screen for about 25 seconds.

| Minutes | What to do | What you should see |
|---|---|---|
| 0:00 | Open the live site. | It opens on my own shop view. The page says Bashi answers yes or no for credit and shows the records behind it. FalkorDB is named in the footer. |
| 0:30 | Press "See the real audit case". | A receipt for a real customer. The 8 real audit sales are flagged as possible phantom debts (N388,340 in total). The fingerprint shows "Verified". |
| 1:30 | In the shop list at the bottom, pick "My whole shop (real records, names removed)". Press "See the account with the most money paid before the sale". | The receipt of one real account. Every payment matched to a sale is marked "inferred" with the rule that made it. A note shows N111,500 that was paid before the sales it was applied to, treated as deposits. |
| 2:30 | Go back, pick "Practice shop", press "Try the Tunde demo", open the receipt, then press "What if this evidence did not exist" next to the broken promise. | The answer flips from NO to YES on a copy of the graph. The real data is never touched. |
| 3:30 | Open `/mcp` or read AGENTS.md. | The agent routes and the MCP tools another AI tool can call. |
| 4:00 | In a terminal, run the four tamper commands in "The 90-second path" in the README. | `verify.py` fails and names the changed record, then passes after the restore. |

The sealed tests: 55 cases, then 200 new ones whose answers were locked before running (`python sealed/run_sealed.py b`). Bashi never wrongly approves; a plain balance check wrongly approves 53. A plain AI model also gets all 255 right on these tidy cases, and the README says so. See README, "Sealed test".

## What is real and what is not

- Real: my own shop's records, with names removed. Two views: the 8 audit sales, and the whole shop (45 customers, 544 credit sales, 543 payments).
- Invented: the practice shop and the 12 filler customers in the audit view.
- Assumed: credit limits, and the dates of the 8 audit payments.
- Inferred: in the whole-shop view, which payment cleared which sale. It is a rule, not a fact, and every such link says so on the receipt.

## Where FalkorDB does the work

- The answer is a walk from customer to sales to payments to promises. A flat table cannot tell which sale a payment cleared.
- Inferred links are saved as their own link type, so a link a person confirmed is never mixed with one a rule proposed.
- The what-if button copies the graph (`GRAPH.COPY`), removes one record on the copy, and re-asks.
- Every decision is saved back into the graph with a fingerprint, and replay shows if anything changed later.

The README lists each claim with the click or command that checks it.
