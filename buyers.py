"""One shop, many buyers.

A shop can have several people who collect goods and pay for it. The graph says who:

  (:Buyer {id, name})-[:BUYS_FOR]->(:Customer)     the person acts for this shop
  (:Buyer)-[:COLLECTED]->(:Trade)                  this person took the goods
  (:Buyer)-[:PAID]->(:Payment)                     this person handed over the money

The credit decision is still made per Customer (the shop), and rules.py never reads
these links, so a graph with no Buyer nodes gives exactly the same answers and the
same fingerprints as before. Matching a payment to a sale already works on every
payment of the shop, whoever made it. This file only adds the "who" for the receipt,
and the wrong answer a per-person balance would have given.
"""


def read_buyers(graph, customer_id):
    """Everything known about the buyers of one shop. None if the shop has none.

    {"buyers": {id: {"name"}}, "collected": {trade: buyer}, "paid": {payment: buyer}}"""
    rows = graph.query(
        "MATCH (b:Buyer)-[:BUYS_FOR]->(:Customer {id:$cid}) "
        "RETURN 'B' AS k, b.id AS a, b.name AS b "
        "UNION ALL "
        "MATCH (b:Buyer)-[:BUYS_FOR]->(:Customer {id:$cid}) MATCH (b)-[:COLLECTED]->(t:Trade) "
        "RETURN 'T' AS k, t.id AS a, b.id AS b "
        "UNION ALL "
        "MATCH (b:Buyer)-[:BUYS_FOR]->(:Customer {id:$cid}) MATCH (b)-[:PAID]->(p:Payment) "
        "RETURN 'P' AS k, p.id AS a, b.id AS b", {"cid": customer_id}).result_set
    buyers = {a: {"name": b or a} for k, a, b in rows if k == "B"}
    if not buyers:
        return None
    return {"buyers": buyers,
            "collected": {a: b for k, a, b in rows if k == "T"},
            "paid": {a: b for k, a, b in rows if k == "P"}}


def buyer_view(info, state, request, verdict):
    """Plain facts for the receipt, built from read_buyers and the shop's state.

    people:  one row per buyer, with what they collected, what they paid and the
             balance a per-person check would show (collected minus paid).
    person_answer: what that per-person check says for the buyer owing the most.
    different: payments that settle a sale collected by someone else."""
    if not info:
        return None
    names = {b: v["name"] for b, v in info["buyers"].items()}
    people = {b: {"id": b, "name": n, "collected": 0, "paid": 0, "trades": 0, "payments": 0}
              for b, n in names.items()}
    for tid, b in info["collected"].items():
        if tid in state["trades"] and b in people:
            people[b]["collected"] += state["trades"][tid]["amount"]
            people[b]["trades"] += 1
    for pid, b in info["paid"].items():
        if pid in state["payments"] and b in people:
            people[b]["paid"] += state["payments"][pid]["amount"]
            people[b]["payments"] += 1
    rows = sorted(people.values(), key=lambda r: r["id"])
    for r in rows:
        r["balance"] = r["collected"] - r["paid"]
    different = set()
    for key in state["settles"]:
        pid, tid = key.split(">")
        payer, taker = info["paid"].get(pid), info["collected"].get(tid)
        if payer and taker and payer != taker:
            different.add(pid)
    has_payers = bool(info["paid"])
    limit = state["customer"]["limit"]
    worst = max(rows, key=lambda r: r["balance"]) if rows else None
    person = None
    if has_payers and worst and isinstance(limit, int):
        person = "YES" if max(worst["balance"], 0) + request <= limit else "NO"
    return {"has_payers": has_payers, "people": rows, "different": len(different),
            "collected_by": dict(info["collected"]), "paid_by": dict(info["paid"]),
            "names": names, "person_answer": person,
            "person_name": worst["name"] if worst else None,
            "person_debt": worst["balance"] if worst else None,
            "wrong": bool(person and verdict in ("YES", "NO") and person != verdict)}


def read_exposure(graph, customer_id):
    """For a personal account: the other accounts its owner also collects goods for.

    (:Buyer)-[:OWNS]->(:Customer) says whose account this is. Any other account where
    that person collected sales is listed with what it owes. Shown on the receipt only;
    the yes or no rule never reads it. Returns [] when there is none."""
    from rules import evaluate, read_state
    rows = graph.query(
        "MATCH (b:Buyer)-[:OWNS]->(:Customer {id:$cid}) "
        "MATCH (b)-[:COLLECTED]->(t:Trade)<-[:MADE]-(o:Customer) WHERE o.id <> $cid "
        "RETURN b.name AS who, o.id AS acct, count(t) AS n", {"cid": customer_id}).result_set
    out = []
    for who, acct, n in sorted(rows, key=lambda r: (r[1], r[0])):
        st = read_state(graph, acct, network=False)
        debt = evaluate(st, 1)["open_debt"] if st else None
        out.append({"who": who, "account": acct, "sales": n, "debt": debt})
    return out


def family_view(state, result, request):
    """The family network for the receipt: each account reached, how, what it owes, the total,
    and a small tree to draw (one box per person or account, one line per link). None if none."""
    net = state.get("network")
    if not net:
        return None
    rows = sorted(({"account": a, "debt": v["debt"], "hops": v["hops"], "steps": v["steps"]}
                   for a, v in net.items()), key=lambda r: (r["hops"], r["account"]))
    own = state["customer"]["id"]
    parent, names, text, kind = {}, {own: own}, {}, {own: "Customer"}
    for r in rows:
        for st in r["steps"]:
            names[st["from"]], names[st["to"]] = st["from_name"], st["to_name"]
            if st["to"] not in parent and st["to"] != own:
                parent[st["to"]], text[st["to"]] = st["from"], ("family" if st["link"] else "")
    debts = {r["account"]: r["debt"] for r in rows}
    kids = {}
    for child, par in parent.items():
        kids.setdefault(par, []).append(child)
    nodes, col = [], [0]

    def place(n, depth):
        ks = sorted(kids.get(n, []), key=lambda k: (k not in debts, k))
        x0 = col[0]
        for k in ks:
            place(k, depth + 1)
        if not ks:
            col[0] += 1
        nodes.append({"id": n, "name": names[n], "depth": depth, "col": (x0 + col[0] - 1) / 2.0,
                      "account": n in debts or n == own, "debt": debts.get(n),
                      "parent": parent.get(n), "family": text.get(n) == "family"})
    place(own, 0)
    cols = max(col[0], 1)
    links = [x for r in rows for x in r["steps"] if x["link"]]
    total = result.get("network_debt")
    return {"rows": rows, "total": total, "own": result.get("open_debt"),
            "hops": max(r["hops"] for r in rows), "accounts": len(rows),
            "nodes": nodes, "cols": cols, "depth": max(n["depth"] for n in nodes),
            "links": sorted({x["link"] for x in links}),
            "over": isinstance(total, int) and total + request > (result.get("limit") or 0)}
