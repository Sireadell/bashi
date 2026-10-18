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
    limit = state["customer"]["limit"]
    worst = max(rows, key=lambda r: r["balance"]) if rows else None
    person = None
    if worst and isinstance(limit, int):
        person = "YES" if max(worst["balance"], 0) + request <= limit else "NO"
    return {"people": rows, "different": len(different),
            "collected_by": dict(info["collected"]), "paid_by": dict(info["paid"]),
            "names": names, "person_answer": person,
            "person_name": worst["name"] if worst else None,
            "person_debt": worst["balance"] if worst else None,
            "wrong": bool(person and verdict in ("YES", "NO") and person != verdict)}
