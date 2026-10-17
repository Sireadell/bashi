# Bashi for agents and other tools

Bashi answers one question for a shop: can this customer take this amount on credit? It says YES, NO or CANNOT TRACE, and gives a receipt that links the exact sales, payments and promises it used. Anyone can re-check a receipt later.

Any AI app or program can ask Bashi through plain web addresses or through MCP (a standard way for AI tools to plug into other tools). The answer comes from two fixed rules, not from an AI guess:

1. Say NO if open debt plus the new request is above the credit limit.
2. Say NO if the customer has any broken promise to pay.

Everything below works on the demo shop (all invented data) and, when it is loaded, the founder's own shop (real audit, names removed). Pass `"shop": "shop_a"` for the demo shop or `"shop": "shop_own"` for the own shop. Leave it out to get the same shop the website shows.

In the examples, replace `$BASHI` with the site address, for example `BASHI=https://bashi-vrfv.onrender.com`.

## The web addresses

| Address | What it does |
|---|---|
| `POST /api/decide` | Ask: can customer X take N naira on credit? Saves the decision. |
| `GET /api/receipt/<id>` | The full receipt as data. |
| `GET /api/verify/<id>` | Re-check one saved decision. Returns `verified` true or false. |
| `GET /api/whatif/<id>?remove=<record id>` | What would the answer be if that record had never existed? |
| `GET /api/customers` | The customer ids you can ask about. |
| `POST /mcp` | The MCP address. `GET /mcp` describes it. |

### Ask for a decision

```
curl -s -X POST $BASHI/api/decide -H "Content-Type: application/json" \
  -d '{"customer": "C001", "amount": 45000, "shop": "shop_a"}'
```

You get back `answer`, `reasons` (in plain words), `decision_id`, `receipt_url`, `verify_url`, `fingerprint` (a code that changes if any record or the answer changes) and `evidence_ids` (the records used).

### Read the receipt

```
curl -s $BASHI/api/receipt/D0001
```

### Re-check it

```
curl -s $BASHI/api/verify/D0001
```

Returns `{"id": "D0001", "verified": true, "detail": "..."}`. It is false if any record used was changed afterwards, or if running the rule again now gives a different answer.

### Ask "what if"

```
curl -s "$BASHI/api/whatif/D0001?remove=PR001"
```

Bashi makes a throwaway copy of the shop, removes that record, runs the rule again, and deletes the copy. The real shop is never changed. You can only remove records the decision used (they are listed in `evidence_ids`).

### List customers

```
curl -s $BASHI/api/customers
```

## Use it from Claude Desktop or Cursor

Bashi has five MCP tools: `decide_credit`, `get_receipt`, `verify_decision`, `what_if_remove_evidence` and `list_customers`.

Claude Desktop runs Bashi on your own computer (stdio). Add this to its config file, with the full path to `mcp_stdio.py`. The folder needs a `.env` file with the database settings (see `.env.example`).

```json
{
  "mcpServers": {
    "bashi": {
      "command": "python",
      "args": ["C:\\path\\to\\bashi\\mcp_stdio.py"]
    }
  }
}
```

Cursor can connect to the site address directly. Add this to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "bashi": {
      "url": "https://bashi-vrfv.onrender.com/mcp"
    }
  }
}
```

A raw MCP call, to see it work:

```
curl -s -X POST $BASHI/mcp -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"decide_credit","arguments":{"customer":"C001","amount":45000,"shop":"shop_a"}}}'
```

## What Bashi will refuse

| It refuses | Why |
|---|---|
| An amount that is zero, negative, not a whole number of naira, or above N1,000,000,000,000 | It will not guess. You get a 400 error. |
| A customer id that does not exist | 404. Use `list_customers`. |
| Records that do not add up (a payment bigger than what it paid, a missing limit, a missing amount) | It says CANNOT TRACE and gives no number. Nothing is saved. |
| A what-if that removes a record the decision did not use | 400, with the list of records it did use. |
| An unknown or expired decision id | 404. Only the most recent 300 decisions are kept. |
| Too many requests | 429. Asking for a decision or a what-if is limited to 20 per 10 minutes per visitor, and 200 per 10 minutes for the whole site. Reading is limited more lightly. |
| Changing the shop's records | There is no way to add, edit or delete a sale, payment or promise through this door. |
| Using an AI model to decide | The answer is the two fixed rules above, every time. |

## Honest limits

The demo shop is invented. The own shop is a real audit with names removed, and some of its payments, dates and limits were rebuilt or assumed. Every receipt carries a `data_label` that says which it is.
