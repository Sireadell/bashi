# Bashi

I built Bashi for small shops that sell on credit. When a customer asks to buy on credit, Bashi answers yes or no, and it hands back a receipt that links the exact records it used: which sales, which payments, which broken promise. The answer comes from a fixed rule check over a FalkorDB graph, not from a guess, so anyone can look at the receipt and see why.

**All data in this project is synthetic.** Every customer name, phone number and amount is invented. No real shop or person is in here.

## How it works

- Customers, sales, payments and promises to pay live as a graph in FalkorDB.
- A payment is linked to the sale it settles, so a sale that was already paid is never counted twice.
- The rule: say no if what the customer owes plus the new request is over their limit, or if they broke a promise to pay.

## Run it

You need Python 3 and a FalkorDB instance (I use the free FalkorDB Cloud one).

```powershell
pip install falkordb python-dotenv
```

Put your connection details in a `.env` file (never commit it):

```
FALKORDB_HOST=your-host
FALKORDB_PORT=your-port
FALKORDB_USERNAME=your-username
FALKORDB_PASSWORD=your-password
```

Build the demo shop (wipes and rebuilds the graph `shop_a`, takes a few seconds):

```powershell
python seed.py
```

It prints the counts it loaded and checks them against what it expected.

## AI tools used

- Claude Code (Anthropic) helped write the code in this repo.
