# Five-minute path for judges

**Judged track: Track 01, Agents That Act on Connected Data.** The graph work a balance check cannot do: it follows customer, sales, payments and promises. Wrongly approved on the 255 sealed cases: Bashi 0, balance check 53. Plus 30 locked family-network cases with chains up to 22 links: Bashi 30 of 30; checking the asking account alone wrongly approves 11 (`sealed/RESULTS_FAMILY.md`, `sealed/RESULTS_FAMILY_G.md`).

The practice shop (invented) also has an older broken-promise case, Tunde (customer C001): pick it in the shop list and the button reads "Try the Tunde demo". It is optional.

**Bashi runs on a real shop's books:** my whole shop, names removed, 45 customers, 544 credit sales, 543 payments. Press "Open my real shop's books" on the home page.

Ways to use Bashi (website, MCP, Claude Desktop, web API, your own shop): see the "Ways to use Bashi" box in [README.md](README.md).

Live site: https://bashi-vrfv.onrender.com (no sign-up). The free host sleeps when idle, so the first visit can show a "waking up" screen for about 25 seconds.

| Minutes | What to do | What you should see |
|---|---|---|
| 0:00 | Open the live site. | It opens on my own shop view. The page says Bashi answers yes or no for credit and shows the records behind it. FalkorDB is named in the footer. |
| 0:30 | Press "See the real audit case". | A receipt for a real customer. The 8 real audit sales are flagged as possible phantom debts (N388,340 in total). The fingerprint shows "Verified". |
| 1:30 | In the shop list at the bottom, pick "My whole shop (real records, names removed)". Press "See the account with the most money paid before the sale". | The receipt of one real account. Every payment matched to a sale is marked "inferred" with the rule that made it. A note shows N111,500 that was paid before the sales it was applied to, treated as deposits. |
| 2:30 | Go back and press "Try the demo" (N90,000 for invented customer CUST-02), open the receipt, then press "What if this evidence did not exist" next to sale TI-005. | The answer is NO because TI-005 looks unpaid while payment PY-005 of the same amount was never linked to it. It flips to YES (owed N0) on a copy of the graph. The real data is never touched. |
| 3:00 | In the same shop, ask CUST-17 for N40,000 (invented data) and open the receipt. | CUST-17 alone owes N0 and a plain balance check says YES. Bashi says NO: this account and 5 linked accounts owe N100,000, plus N40,000 is N140,000, above the limit N100,000. The path is 7 links deep. Press the what-if on family link FAM-1 and it flips to YES (2 accounts, N70,000). |
| 3:30 | Open `/mcp` or read AGENTS.md. | The agent routes and the MCP tools another AI tool can call. |
| 4:00 | In a terminal, run the four tamper commands in "The 90-second path" in the README. | `verify.py` fails and names the changed record, then passes after the restore. |

The sealed tests: 55 cases, then 200 new ones whose answers were locked before running (`python sealed/run_sealed.py b`). Bashi never wrongly approves; a plain balance check wrongly approves 53. The 30 family-network cases (sets F and G, chains up to 22 links) are locked the same way: Bashi 30 of 30. See README, "Sealed test".

## What is real and what is not

- Real: my own shop's records, with names removed. Two views: the 8 audit sales, and the whole shop (45 customers, 544 credit sales, 543 payments).
- Invented: the practice shop and the 16 invented customers (CUST-01 to CUST-16) in the audit view.
- Assumed: credit limits, and the dates of the 8 audit payments.
- Inferred: in the whole-shop view, which payment cleared which sale. It is a rule, not a fact, and every such link says so on the receipt.

## Where FalkorDB does the work

- The answer is a walk from customer to sales to payments to promises. A flat table cannot tell which sale a payment cleared.
- Inferred links are saved as their own link type, so a link a person confirmed is never mixed with one a rule proposed.
- The what-if button copies the graph (`GRAPH.COPY`), removes one record on the copy, and re-asks.
- The family network rule walks up to 20 links in one Cypher variable-length query.
- Receipt lines from FalkorDB's own algorithms: the linked group (`algo.WCC`, `linked_group.py`) and the shortest link chain to the largest linked debt (`algo.SPpaths`, `linked_chain.py`). Information only.
- "Customers most like this one" uses FalkorDB's vector index on a 5-number credit profile (`lookalike.py`). No AI model. Information only.
- Every decision is saved back into the graph with a fingerprint, and replay shows if anything changed later.

The README lists each claim with the click or command that checks it. Its "Track entered" section quotes each track's focus areas from the [track page](https://wemakedevs.org/hackathons/falkordb) and says where Bashi does each one.
