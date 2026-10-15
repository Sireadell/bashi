"""Wipe and rebuild the synthetic shop graph (shop_a). Run: python seed.py

All names, phone numbers and amounts are invented. Deterministic (seed 42).
"""
import datetime
import random

from db import DEFAULT_GRAPH, get_db

random.seed(42)

TODAY = datetime.date(2026, 10, 14)
LABELS = ["Customer", "Trade", "Payment", "Promise", "Rule", "Decision", "Counter"]

FIRST = ["Tunde", "Amaka", "Chidi", "Ngozi", "Bola", "Emeka", "Funke", "Ibrahim",
         "Halima", "Segun", "Yetunde", "Obinna", "Zainab", "Kunle", "Blessing",
         "Musa", "Adaeze", "Femi", "Ifeoma", "Sade", "Uche", "Rashida", "Tobi",
         "Chiamaka", "Dayo"]
LAST = ["Adeyemi", "Obi", "Okafor", "Eze", "Bello", "Nwosu", "Balogun", "Sani",
        "Lawal", "Okonkwo", "Abiola", "Danjuma", "Ogunleye", "Ikenna", "Yusuf",
        "Adebayo", "Nnamdi", "Ibe", "Salami", "Olawale", "Mohammed", "Chukwu",
        "Fashola", "Garba", "Onyeka"]
ITEMS = ["rice (50kg bag)", "vegetable oil (25L)", "sugar (carton)", "tomato paste (box)",
         "spaghetti (carton)", "beans (bag)", "garri (bag)", "indomie (carton)",
         "soap (carton)", "milk powder (tin)", "salt (bag)", "detergent (carton)"]


def d(days_ago):
    """ISO date days_ago before TODAY (negative means in the future)."""
    return (TODAY - datetime.timedelta(days=days_ago)).isoformat()


def build():
    customers, trades, payments, settles = [], [], [], []
    promises, promised, broke = [], [], []

    def trade(cid, amount, days_ago, item):
        t = {"id": f"T{len(trades) + 1:04d}", "amount": amount, "date": d(days_ago),
             "item": item, "cid_ref": cid, "age": days_ago}
        trades.append(t)
        return t

    def pay(t, amount, days_after, link=True):
        p = {"id": f"P{len(payments) + 1:04d}", "amount": amount,
             "date": d(max(0, t["age"] - days_after))}
        payments.append(p)
        if link:
            settles.append({"pid": p["id"], "tid": t["id"], "amount": amount})
        return p

    def promise(cid, days_ago, due_days_ago, amount, kept):
        pr = {"id": f"PR{len(promises) + 1:03d}", "date": d(days_ago), "due": d(due_days_ago),
              "amount": amount, "kept": kept}
        promises.append(pr)
        promised.append({"cid": cid, "prid": pr["id"]})
        if not kept and due_days_ago > 0:
            broke.append({"cid": cid, "prid": pr["id"]})

    for i in range(1, 26):
        limit = 60000 if i == 1 else random.choice([30000, 40000, 50000, 80000, 100000])
        customers.append({"id": f"C{i:03d}", "name": f"{FIRST[i - 1]} {LAST[i - 1]}",
                          "phone": f"0800-555-{i:04d}", "credit_limit": limit})

    # Scene 1: Tunde (C001). Limit 60,000, open debt 10,000, one broken promise PR001.
    t = trade("C001", 30000, 120, "rice (50kg bag)")
    pay(t, 30000, 20)
    t = trade("C001", 20000, 70, "vegetable oil (25L)")
    pay(t, 10000, 25)                      # 10,000 still owed
    promise("C001", 55, 29, 10000, False)  # PR001, broken

    # Scene 2: phantom debt (C002). The payment exists but was never linked to the sale.
    t = trade("C002", 15000, 60, "sugar (carton)")
    pay(t, 15000, 5)
    ph = trade("C002", 12000, 40, "tomato paste (box)")
    pay(ph, 12000, 3, link=False)
    phantom = {"trade": ph["id"], "payment": payments[-1]["id"]}

    # Scene 3: clean YES customer (C003). Everything paid, promise kept.
    for amt, ago, item in [(18000, 110, "garri (bag)"), (22000, 80, "beans (bag)"),
                           (25000, 50, "milk powder (tin)"), (16000, 20, "salt (bag)")]:
        pay(trade("C003", amt, ago, item), amt, 4)
    promise("C003", 85, 60, 22000, True)

    # Everyone else fills up to exactly 120 trades.
    others = [f"C{i:03d}" for i in range(4, 26)]
    random_trades = []
    for k in range(120 - len(trades)):
        cid = others[k % len(others)] if k < len(others) else random.choice(others)
        random_trades.append(trade(cid, random.choice([6000, 8000, 10000, 12000, 15000, 20000, 25000]),
                                   random.randint(5, 150), random.choice(ITEMS)))
    # 30 unpaid or part-paid in total (25%): Tunde's, the phantom one, plus 28 here.
    pick = random.sample(random_trades, 28)
    partial = {x["id"] for x in pick[:8]}
    unpaid = {x["id"] for x in pick}
    for x in random_trades:
        if x["id"] in partial:
            pay(x, x["amount"] // 2, random.randint(2, 10))
        elif x["id"] not in unpaid:
            pay(x, x["amount"], random.randint(1, 12))

    promise("C004", 70, 40, 8000, True)
    promise("C005", 65, 35, 10000, False)
    promise("C006", 90, 30, 12000, True)
    promise("C007", 50, 20, 6000, False)
    promise("C008", 5, -10, 9000, False)   # due in the future, not broken yet

    rules = [
        {"id": "R_LIMIT", "text": "Say NO if open debt plus the new request is over the customer's credit limit."},
        {"id": "R_BROKEN_PROMISE", "text": "Say NO if the customer has broken a promise to pay."},
    ]
    return dict(customers=customers, trades=trades, payments=payments, settles=settles,
                promises=promises, promised=promised, broke=broke, rules=rules, phantom=phantom)


def load(g, s):
    for label in LABELS:
        g.query(f"CREATE INDEX FOR (n:{label}) ON (n.id)")
    g.query("UNWIND $rows AS r CREATE (:Customer {id:r.id, name:r.name, phone:r.phone, "
            "credit_limit:r.credit_limit, synthetic:true})", {"rows": s["customers"]})
    tr = [{k: t[k] for k in ("id", "amount", "date", "item", "cid_ref")} for t in s["trades"]]
    g.query("UNWIND $rows AS r MATCH (c:Customer {id:r.cid_ref}) "
            "CREATE (c)-[:MADE]->(:Trade {id:r.id, amount:r.amount, date:r.date, item:r.item})", {"rows": tr})
    g.query("UNWIND $rows AS r CREATE (:Payment {id:r.id, amount:r.amount, date:r.date})",
            {"rows": s["payments"]})
    g.query("UNWIND $rows AS r MATCH (p:Payment {id:r.pid}), (t:Trade {id:r.tid}) "
            "CREATE (p)-[:SETTLES {amount:r.amount}]->(t)", {"rows": s["settles"]})
    g.query("UNWIND $rows AS r CREATE (:Promise {id:r.id, date:r.date, due:r.due, "
            "amount:r.amount, kept:r.kept})", {"rows": s["promises"]})
    g.query("UNWIND $rows AS r MATCH (c:Customer {id:r.cid}), (p:Promise {id:r.prid}) "
            "CREATE (c)-[:PROMISED]->(p)", {"rows": s["promised"]})
    g.query("UNWIND $rows AS r MATCH (c:Customer {id:r.cid}), (p:Promise {id:r.prid}) "
            "CREATE (c)-[:BROKE]->(p)", {"rows": s["broke"]})
    g.query("UNWIND $rows AS r CREATE (:Rule {id:r.id, text:r.text})", {"rows": s["rules"]})
    # Id counters: the next Decision is D0001, the next new Promise follows the planted ones.
    g.query("CREATE (:Counter {id:'decision', n:0}), (:Counter {id:'promise', n:$n})",
            {"n": len(s["promises"])})
    # Labelled demo scene, left unlinked on purpose (never silently fixed).
    ph = s["phantom"]
    g.query("MATCH (t:Trade {id:$t}), (p:Payment {id:$p}) "
            "SET t.demo_scene='phantom_debt', p.demo_scene='phantom_debt'",
            {"t": ph["trade"], "p": ph["payment"]})


def count(g, q):
    return g.query(q).result_set[0][0]


def main():
    db = get_db()
    g = db.select_graph(DEFAULT_GRAPH)
    if DEFAULT_GRAPH in db.list_graphs():
        g.delete()
    g = db.select_graph(DEFAULT_GRAPH)
    s = build()
    load(g, s)

    expected = {
        "customers": len(s["customers"]), "trades": len(s["trades"]),
        "payments": len(s["payments"]), "settles": len(s["settles"]),
        "promises": len(s["promises"]), "broke": len(s["broke"]), "rules": len(s["rules"]),
    }
    queries = {
        "customers": "MATCH (n:Customer) RETURN count(n)",
        "trades": "MATCH (n:Trade) RETURN count(n)",
        "payments": "MATCH (n:Payment) RETURN count(n)",
        "settles": "MATCH ()-[r:SETTLES]->() RETURN count(r)",
        "promises": "MATCH (n:Promise) RETURN count(n)",
        "broke": "MATCH ()-[r:BROKE]->() RETURN count(r)",
        "rules": "MATCH (n:Rule) RETURN count(n)",
    }
    unpaid = count(g, "MATCH (t:Trade) OPTIONAL MATCH (:Payment)-[s:SETTLES]->(t) "
                      "WITH t, coalesce(sum(s.amount),0) AS paid WHERE paid < t.amount RETURN count(t)")
    tunde_debt = count(g, "MATCH (:Customer {id:'C001'})-[:MADE]->(t:Trade) "
                          "OPTIONAL MATCH (:Payment)-[s:SETTLES]->(t) "
                          "WITH t, coalesce(sum(s.amount),0) AS paid RETURN sum(t.amount - paid)")

    print("Seeded graph:", DEFAULT_GRAPH)
    for k, q in queries.items():
        actual = count(g, q)
        print(f"  {k:10s} expected {expected[k]:4d}  in graph {actual:4d}")
        assert expected[k] == actual, f"count mismatch for {k}"
    assert expected["customers"] == 25 and expected["trades"] == 120
    print(f"  unpaid or part-paid trades: {unpaid} of 120")
    assert unpaid == 30, unpaid
    assert tunde_debt == 10000, tunde_debt
    print("  Tunde (C001): open debt N10,000, limit N60,000, broken promise PR001")
    print("  Phantom debt scene (C002):", s["phantom"])
    print("OK: counts match.")


if __name__ == "__main__":
    main()
