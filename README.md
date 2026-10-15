Live demo: https://bashi-vrfv.onrender.com (no sign-up)

# Bashi

I built Bashi for small shops that sell on credit. When a customer asks to buy on credit, Bashi answers yes or no, and it hands back a receipt that links the exact records it used: which sales, which payments, which broken promise. The answer comes from a fixed rule check over a FalkorDB graph, not from a guess, so anyone can look at the receipt and see why.

**All data in this project is synthetic.** Every customer name, phone number and amount is invented. No real shop or person is in here.

## Why this exists

On 17 July 2026 I ran an audit (read-only) on a real shop's records. It found 8 sales marked fully paid while the customer's account ledger still showed debt, N388,340 in total. The cause: one payment updates two separate records, the sale and the ledger, and one of them can lag or fail. Each screen looks right on its own, so nobody sees the gap. I fixed the cause afterwards.

I ran the same kind of check on the same shop on 15 October 2026 (494 sales, 46 credit accounts). 3 of the 46 accounts still had two records that differ, a total gap of N15,510.

Bashi does not repair that shop's data. It is built around the same problem. It decides from linked records instead of a stored balance, shows the exact records on a receipt, flags a payment that is not linked to a sale but matches a still-open sale amount as a "possible phantom debt", and says CANNOT TRACE instead of guessing. The demo shop below is synthetic.

## The 90-second path (no sign-up, nothing to install)

1. **Ask (about 15 seconds).** Open the live link. Tunde Adeyemi is already selected. Type 45000 and ask. The answer is NO.
2. **Open the receipt (about 20 seconds).** It lists the exact sales, payments and the broken promise PR001 behind the NO. Click any record to see it.
3. **Press what-if (about 20 seconds).** Next to PR001 press "What if this evidence did not exist". The answer flips to YES on a copy of the graph. The real data is never touched.
4. **Run the tamper test (about 30 seconds).** In a terminal, with the repo set up as in "Run it" below:

```powershell
python tamper.py T0002 50000
python verify.py        # FAIL, names Trade T0002
python tamper.py --restore
python verify.py        # PASS
```

## Tracks entered

- **Track 01, Agents That Act on Connected Data (lead).** The agent answers a credit question from linked records in the graph, saves the decision back into the graph, and the receipt shows the exact records it used.
- **Track 02, Agent Memory and Coordination.** Decisions and promises to pay are stored in the graph and survive restarts. A promise written in plain words ("Tunde promises N10,000 by Friday") becomes a node that the next decision for that customer reads. Stored decisions can be replayed later with `python verify.py`. The only hand-off is between the language step (picks lookups, words one sentence) and the fixed rule check, which makes the decision. It is not several agents talking to each other.

## How it works

- Customers, sales, payments and promises to pay live as a graph in FalkorDB.
- A payment is linked to the sale it settles, so a sale that was already paid is never counted twice.
- The rule: say no if what the customer owes plus the new request is over their limit, or if they broke a promise to pay.

A promise to pay that is still unkept after its due date counts as broken the next time Bashi checks that customer. The check runs before every decision and never touches a promise marked kept. A saved decision remembers the day it was made, so replaying it later does not change just because time passed.

## Where FalkorDB is needed

The answer is a walk over links, so the graph is the product:

- A payment is linked to the sale it settles `(Payment)-[:SETTLES]->(Trade)`. Open debt is the sales a customer made minus the payments linked to them. Without the link, a payment cannot be matched to the right sale.
- A customer is linked to the promises they made and the ones they broke `(Customer)-[:PROMISED]->(Promise)`, `(Customer)-[:BROKE]->(Promise)`.
- Every decision is saved as a node with `USED_EVIDENCE` links to the exact sales, payments and promises it read. The receipt page reads those links back and shows those records, nothing else.
- The what-if button uses FalkorDB's `GRAPH.COPY` to copy the whole graph, delete one record on the copy, ask again, and delete the copy.
- The receipt reads one customer's records in a single combined query (it used to be four).

Stop FalkorDB and Bashi answers nothing. There is no local copy of the data to fall back on.

## Graph data model

Graph name: `shop_a`. Every node has an `id` and an index on it.

```mermaid
graph LR
  C[Customer] -->|MADE| T[Trade]
  P[Payment] -->|SETTLES amount| T
  C -->|PROMISED| PR[Promise]
  C -->|BROKE since| PR
  D[Decision] -->|ABOUT| C
  D -->|USED_EVIDENCE| T
  D -->|USED_EVIDENCE| P
  D -->|USED_EVIDENCE| PR
  D -->|APPLIED_RULE| R[Rule]
```

| Node | What it is | Properties |
|---|---|---|
| Customer | a shop customer | id, name, phone, credit_limit, synthetic |
| Trade | one credit sale | id, amount, date, item |
| Payment | money received | id, amount, date |
| Promise | a promise to pay | id, date, due, amount, kept |
| Rule | one of the two rules | id, text |
| Decision | one saved yes or no | id, customer_id, request, verdict, reason, created, as_of, open_debt, fingerprint, rule_ids, snapshot |
| Counter | hands out the next D0001 or PR004 id | id, n |

| Link | Meaning | Link properties |
|---|---|---|
| `(Customer)-[:MADE]->(Trade)` | the customer bought on credit | none |
| `(Payment)-[:SETTLES]->(Trade)` | this payment paid all or part of this sale | `amount`: how much of the payment went to this sale |
| `(Customer)-[:PROMISED]->(Promise)` | the customer promised to pay | none |
| `(Customer)-[:BROKE]->(Promise)` | the promise is unkept and past its due date | `since`: the day the link was added (seeded ones have none) |
| `(Decision)-[:ABOUT]->(Customer)` | who the decision was for | none |
| `(Decision)-[:USED_EVIDENCE]->(Trade, Payment or Promise)` | a record the decision read | none |
| `(Decision)-[:APPLIED_RULE]->(Rule)` | the rules applied | none |

The seed (`seed.py`) builds 25 customers and 120 credit sales, 30 of them unpaid or part paid. One payment for customer C002 is left unlinked on purpose, to show the phantom-debt warning.

## Key Cypher queries

These are copied from the code. In plain words, "open debt" is all of a customer's sales minus the payment amounts linked to them.

**1. Open debt walk** (`rules.py`, `read_state`). One round trip gets the customer, their sales with the payments settling each (if any), their promises and their broken promises. The code then adds it up: open debt = sum of sale amounts minus sum of `SETTLES.amount` (`evaluate`, same file). The sales-and-payments part:

```cypher
MATCH (c:Customer {id:$cid})-[:MADE]->(t:Trade)
OPTIONAL MATCH (p:Payment)-[s:SETTLES]->(t)
RETURN t.id, t.amount, t.date, p.id, p.amount, p.date, s.amount
```

The same debt as one Cypher sum, used as a seed check for Tunde (`seed.py`, `main`):

```cypher
MATCH (:Customer {id:'C001'})-[:MADE]->(t:Trade)
OPTIONAL MATCH (:Payment)-[s:SETTLES]->(t)
WITH t, coalesce(sum(s.amount),0) AS paid RETURN sum(t.amount - paid)
```

**2. Broken promises** (`rules.py`, `mark_overdue_promises`). Links every customer to each promise that is unkept and past its due date. Running it twice changes nothing, and kept promises are never touched. The decision then reads the `BROKE` links in query 1.

```cypher
MATCH (c:Customer)-[:PROMISED]->(p:Promise)
WHERE p.kept = false AND p.due < $today
MERGE (c)-[b:BROKE]->(p) ON CREATE SET b.since = $today
```

**3. Evidence save** (`rules.py`, `_save`). Stores the decision, then one `USED_EVIDENCE` link for every sale, payment and promise it read (the label changes per record), then the rules it applied.

```cypher
MATCH (c:Customer {id:$cid})
CREATE (d:Decision {id:$did, customer_id:$cid, request:$req, verdict:$v, reason:$reason,
  created:$created, fingerprint:$fp, rule_ids:$rids, snapshot:$snap, open_debt:$debt, as_of:$as_of})
CREATE (d)-[:ABOUT]->(c)

MATCH (d:Decision {id:$did}), (e:Trade {id:$eid}) CREATE (d)-[:USED_EVIDENCE]->(e)
MATCH (d:Decision {id:$did}), (r:Rule {id:$rid}) CREATE (d)-[:APPLIED_RULE]->(r)
```

**4. Orphan payment check** (`rules.py`, `possible_phantoms`). Finds payments linked to no sale. If one has the same amount as a still-open sale, the receipt warns about a possible phantom debt. The debt is never changed.

```cypher
MATCH (p:Payment) WHERE NOT (p)-[:SETTLES]->() RETURN p.id, p.amount, p.date
```

**5. What-if** (`whatif.py`, `whatif`). Copies the whole graph with FalkorDB's `GRAPH.COPY` (called as `graph.copy(name)`), deletes the chosen record on the copy only, asks again on the copy, then deletes the copy.

```cypher
GRAPH.COPY shop_a shop_a_whatif_<decision id>_<time>_<random>
MATCH (n) WHERE n.id = $i AND (n:Trade OR n:Payment OR n:Promise) DETACH DELETE n   // on the copy
GRAPH.DELETE shop_a_whatif_<decision id>_<time>_<random>
```

Also in `rules.py`: `allocate_id` bumps the id counter in the graph with `MATCH (k:Counter {id:$k}) SET k.n = k.n + 1 RETURN k.n`, so two requests never get the same id. `agent.py` `record_promise` writes the promise from plain words:

```cypher
MATCH (c:Customer {id:$cid})
CREATE (c)-[:PROMISED]->(:Promise {id:$pid, date:$d, due:$due, amount:$amt, kept:false})
```

## What this is not

- **Not tamper-proof.** The replay is tamper-evident. If something changes a sale, a payment or a decision, the replay shows it. But anyone who can write to the database can rewrite a decision and its fingerprint together, and the replay would pass.
- **Not a smart credit score.** The yes or no comes from a fixed rule, two lines long, simple on purpose: say no if the debt plus the request is over the limit, or if there is a broken promise. No model decides it.
- **Not an AI that decides.** The AI only picks which lookups to run and words one sentence. Every number and name in that sentence is checked against the records, and if the check fails, a plain template answers instead.
- **Not far more accurate than a balance check.** On the scorecard below, Bashi gives the same answer as a balance-only check on 37 of 40 questions and a different one on 3. The gain is the receipt and the trace, not a bigger accuracy number.
- **Not real data.** Every customer, amount and phone number is invented, so nothing here is advice about a real person or a real debt.

## Run it

You need Python 3 (the hosted site uses 3.13) and a FalkorDB instance. I use the free FalkorDB Cloud one. To run FalkorDB on your own machine instead, start FalkorDB's standard Docker image (`docker run -p 6379:6379 falkordb/falkordb`) and use host `localhost`, port `6379` and no username or password below.

```powershell
git clone https://github.com/Sireadell/bashi
cd bashi
pip install -r requirements.txt
```

Copy `.env.example` to `.env`, fill in your connection details (never commit it). The two AI keys are optional: without one, the plain-words box uses a built-in parser and fixed wording, and every reply says which mode answered. If both are set, Claude is used first.

```
FALKORDB_HOST=your-host
FALKORDB_PORT=your-port
FALKORDB_USERNAME=your-username
FALKORDB_PASSWORD=your-password
ANTHROPIC_API_KEY=optional
GEMINI_API_KEY=optional
```

Build the demo shop (wipes and rebuilds the graph `shop_a`, takes a few seconds):

```powershell
python seed.py
```

Ask from the command line. Tunde asks for N45,000 and gets a NO because of one broken promise:

```powershell
python rules.py C001 45000
```

Start the site and open http://127.0.0.1:5000. Press "Try the Tunde demo":

```powershell
python app.py
```

`verify.py` and the tamper test need at least one saved decision. On a fresh graph, ask once first (`python rules.py C001 45000`, or press the demo button), then run the tamper test above. Hosting steps are in `DEPLOY.md`.

## Honest edge cases

To replay every saved decision at any time, run `python verify.py`.

If removing the evidence changes nothing, the page says so instead of pretending it mattered. If an amount cannot be traced to a sale and a payment, Bashi says it cannot trace it and gives no number.

## Scorecard

Bashi against a plain "balance only" answer (all sales minus all payments, plus the request, against the limit; it ignores which sale a payment settles and ignores broken promises). 40 questions on the seeded shop: every one of the 25 customers once, 15 repeats, amounts spread between 30% and 130% of each limit (seed 42), plus Tunde at N45,000. Nothing is saved to the graph.

| | Count |
|---|---|
| Questions | 40 |
| Same answer | 37 |
| Different | 3 |

| Customer | Request | Bashi | Balance only | Why |
|---|---|---|---|---|
| C001 Tunde Adeyemi | N45,000 | NO | YES | broken promise PR001 |
| C002 Amaka Obi | N24,000 | NO | YES | a N12,000 payment was never linked to its sale |
| C007 Funke Balogun | N30,000 | NO | YES | broken promise PR006 |

The data is synthetic and only 3 of 40 differ, so this is a small gap. It is the gap Bashi is built for: the balance says yes where a broken promise or an unlinked payment says otherwise. Re-run it with `python scorecard.py` (writes `scorecard_results.json`).

## Tests

```powershell
python -m pytest
```

The tests run against a copy of the graph and delete it afterwards.

## AI tools used

- **Claude Code (Anthropic)** was used to build this project: the code, tests and documentation.
- **At run time, Claude (a Haiku model) or Gemini**, only if you set a key, and only for two jobs: choosing which lookups to run and wording one short sentence. They never make the yes or no. The rule check (`rules.py`) contains no AI, and a model sentence that fails the check against the records is replaced by fixed wording.
