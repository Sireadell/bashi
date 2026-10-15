# Bashi

I built Bashi for small shops that sell on credit. When a customer asks to buy on credit, Bashi answers yes or no, and it hands back a receipt that links the exact records it used: which sales, which payments, which broken promise. The answer comes from a fixed rule check over a FalkorDB graph, not from a guess, so anyone can look at the receipt and see why.

**All data in this project is synthetic.** Every customer name, phone number and amount is invented. No real shop or person is in here.

## How it works

- Customers, sales, payments and promises to pay live as a graph in FalkorDB.
- A payment is linked to the sale it settles, so a sale that was already paid is never counted twice.
- The rule: say no if what the customer owes plus the new request is over their limit, or if they broke a promise to pay.

A promise to pay that is still unkept after its due date counts as broken the next time Bashi checks that customer. The check runs before every decision and never touches a promise marked kept. A saved decision remembers the day it was made, so replaying it later does not change just because time passed.

## What this is not

- The receipt replay is tamper-evident, not tamper-proof. If something changes a sale, a payment or a decision, the replay shows it. But anyone who can write to the database can rewrite a decision and its fingerprint together, and the replay would pass.
- The data is synthetic. Every customer, amount and phone number is invented, so nothing here is advice about a real person or a real debt.
- The yes or no comes from a fixed rule, two lines long. No model decides it.
- The AI only picks which lookups to run and words one sentence. Every number and name in that sentence is checked against the records, and if the check fails, a plain template answers instead.

## Run it

You need Python 3 and a FalkorDB instance (I use the free FalkorDB Cloud one).

```powershell
pip install -r requirements.txt
```

Put your connection details in a `.env` file (never commit it). `ANTHROPIC_API_KEY` is optional: without it the plain-words box uses a built-in parser and fixed wording, and every reply says which mode answered.

```
FALKORDB_HOST=your-host
FALKORDB_PORT=your-port
FALKORDB_USERNAME=your-username
FALKORDB_PASSWORD=your-password
ANTHROPIC_API_KEY=optional
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

## The one-minute proof

1. Ask for Tunde (C001) and N45,000. The answer is NO, and the receipt lists the exact sales, payments and the broken promise PR001 behind it.
2. On the receipt press "What if this evidence did not exist" next to PR001. Bashi copies the graph, removes that record on the copy, runs the rule again and shows the answer flip to YES. The real data is never touched.
3. Replay every saved decision:

```powershell
python verify.py
```

4. Change one sale by hand, then replay again. The replay fails and names the record that changed:

```powershell
python tamper.py T0002 50000
python verify.py
python tamper.py --restore
```

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

- Claude Code (Anthropic) helped write the code in this repo.
