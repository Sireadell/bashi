"""Load the own shop into its own graph (shop_own).

Run: python own_shop.py

The data is own_audit_seed.py: the 8 trades from the founder's audit of 17 July 2026
(source real_audit, names removed) plus invented filler customers (source invented).
It holds only codes, amounts and dates. This loader refuses data that has a name,
phone, address or note key, or any text longer than 20 characters.

Same model as seed.py (Customer, Trade, Payment, Promise, Rule, Counter), so the
same rules, receipts, what-if and tamper test work on it.
"""
import copy
import sys

from db import OWN_GRAPH, get_db
from seed import LABELS

LABEL_TEXT = "Real audit of 17 July 2026, names removed"
EXPLAINER = ("Real part: 8 credit sales from the founder's own shop audit of 17 July 2026. Each sale was "
             "recorded as paid, but the customer's ledger still showed the money as owed (N388,340 in "
             "total). Names, phones and notes are removed. Invented part: 16 made-up customers added so "
             "there is more to ask about. Each customer is tagged real or invented. Credit limits and "
             "payment dates are assumed.")
SOURCES = ("real_audit", "invented")
TAG = {"real_audit": "real", "invented": "invented"}
FORBIDDEN_KEYS = ("name", "phone", "address", "note")
MAX_TEXT = 20
MIN_LIMIT = 100000
LIMIT_STEP = 50000
DECISION_START = 1000   # decision ids start at D1001 so they never clash with shop_a's


def find_leaks(value, trail=""):
    """Every place in the data that could hold personal information."""
    bad = []
    if isinstance(value, dict):
        for k, v in value.items():
            if any(f in str(k).lower() for f in FORBIDDEN_KEYS):
                bad.append("key %s.%s" % (trail, k))
            bad.extend(find_leaks(v, "%s.%s" % (trail, k)))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            bad.extend(find_leaks(v, "%s[%d]" % (trail, i)))
    elif isinstance(value, str) and len(value) > MAX_TEXT:
        bad.append("long text at %s" % trail)
    return bad


def credit_limit(biggest_sale):
    """The shop's own data has no credit limit, so one is assumed: the larger of
    N100,000 and the customer's biggest sale rounded up to the next N50,000."""
    rounded = -(-biggest_sale // LIMIT_STEP) * LIMIT_STEP
    return max(MIN_LIMIT, rounded)


def prepare(data):
    """Turn the export into rows for the graph. Raises ValueError on a bad file."""
    leaks = find_leaks(data)
    if leaks:
        raise ValueError("export is not anonymous (%d problem(s), first: %s)" % (len(leaks), leaks[0]))
    cust_ids = [c["id"] for c in data.get("customers", [])]
    if len(set(cust_ids)) != len(cust_ids):
        raise ValueError("duplicate customer codes")
    known = set(cust_ids)
    sales, pays, proms = data.get("sales", []), data.get("payments", []), data.get("promises", [])
    for row in sales + pays + proms:
        if row["customer"] not in known:
            raise ValueError("unknown customer code %s" % row["customer"])
        if not isinstance(row["amount"], int) or isinstance(row["amount"], bool) or row["amount"] < 0:
            raise ValueError("bad amount on %s" % row["id"])
    sale_ids = {s["id"] for s in sales}
    biggest = {c: 0 for c in cust_ids}
    for s in sales:
        biggest[s["customer"]] = max(biggest[s["customer"]], s["amount"])
    for row in data.get("customers", []) + sales + pays + proms:
        if row.get("source") not in SOURCES:
            raise ValueError("record %s has no valid source" % row["id"])
    customers = [{"id": c["id"], "name": c["id"], "source": c["source"],
                  "credit_limit": credit_limit(biggest[c["id"]])} for c in data["customers"]]
    buyers = [{"id": b["id"], "name": b["label"], "cid": b["customer"]} for b in data.get("buyers", [])]
    bids = {b["id"]: b["cid"] for b in buyers}
    for row in sales + pays:
        if row.get("buyer") and bids.get(row["buyer"]) != row["customer"]:
            raise ValueError("record %s names a buyer who does not act for that shop" % row["id"])
    owns = [{"bid": b["id"], "cid": c} for b in data.get("buyers", []) for c in b.get("owns", [])]
    for o in owns:
        if o["cid"] not in known:
            raise ValueError("buyer %s owns unknown account %s" % (o["bid"], o["cid"]))
    collected = [{"bid": s["buyer"], "id": s["id"]} for s in sales if s.get("buyer")]
    paid_by = [{"bid": p["buyer"], "id": p["id"]} for p in pays if p.get("buyer")]
    # What each buyer does for their shop, in plain words, for the family network on the receipt.
    takes, gives = {c["bid"] for c in collected}, {p["bid"] for p in paid_by}
    for b in buyers:
        b["role"] = ("collects and pays for" if b["id"] in takes and b["id"] in gives else
                     "pays for" if b["id"] in gives else "collects goods for")
    family = []
    for f in data.get("family", []):
        if f.get("source") not in SOURCES:
            raise ValueError("record %s has no valid source" % f["id"])
        if f["a"] not in bids or f["b"] not in bids or f["a"] == f["b"]:
            raise ValueError("family link %s must join two different known buyers" % f["id"])
        family.append({"id": f["id"], "a": f["a"], "b": f["b"], "source": f["source"]})
    trades = [{"id": s["id"], "amount": s["amount"], "date": s["date"], "cid": s["customer"],
               "kind": s.get("kind", "sale"), "marked_paid": s.get("paid", 0),
               "source": s["source"]} for s in sales]
    payments = [{"id": p["id"], "amount": p["amount"], "date": p["date"], "source": p["source"]}
                for p in pays]
    settles = []
    for p in pays:
        if p.get("settles"):
            if p["settles"] not in sale_ids:
                raise ValueError("payment %s settles unknown sale" % p["id"])
            settles.append({"pid": p["id"], "tid": p["settles"],
                            "amount": p.get("applied", p["amount"])})
    promises = [{"id": r["id"], "date": r["date"], "due": r["due"], "amount": r["amount"],
                 "kept": bool(r["kept"]), "source": r["source"]} for r in proms]
    promised = [{"cid": r["customer"], "prid": r["id"]} for r in proms]
    return dict(customers=customers, trades=trades, payments=payments, settles=settles,
                promises=promises, promised=promised,
                buyers=buyers, owns=owns, collected=collected, paid_by=paid_by, family=family)


def load(g, rows):
    for label in LABELS:
        g.query("CREATE INDEX FOR (n:%s) ON (n.id)" % label)
    g.query("UNWIND $rows AS r CREATE (:Customer {id:r.id, name:r.name, "
            "credit_limit:r.credit_limit, synthetic:(r.source = 'invented'), own_shop:true, "
            "limit_assumed:true, source:r.source})",
            {"rows": rows["customers"]})
    g.query("UNWIND $rows AS r MATCH (c:Customer {id:r.cid}) "
            "CREATE (c)-[:MADE]->(:Trade {id:r.id, amount:r.amount, date:r.date, "
            "kind:r.kind, marked_paid:r.marked_paid, source:r.source})", {"rows": rows["trades"]})
    g.query("UNWIND $rows AS r CREATE (:Payment {id:r.id, amount:r.amount, date:r.date, source:r.source})",
            {"rows": rows["payments"]})
    g.query("UNWIND $rows AS r MATCH (p:Payment {id:r.pid}), (t:Trade {id:r.tid}) "
            "CREATE (p)-[:SETTLES {amount:r.amount}]->(t)", {"rows": rows["settles"]})
    g.query("UNWIND $rows AS r CREATE (:Promise {id:r.id, date:r.date, due:r.due, "
            "amount:r.amount, kept:r.kept, source:r.source})", {"rows": rows["promises"]})
    g.query("UNWIND $rows AS r MATCH (c:Customer {id:r.cid}), (p:Promise {id:r.prid}) "
            "CREATE (c)-[:PROMISED]->(p)", {"rows": rows["promised"]})
    if rows.get("buyers"):
        g.query("CREATE INDEX FOR (n:Buyer) ON (n.id)")
        g.query("UNWIND $rows AS r MATCH (c:Customer {id:r.cid}) "
                "CREATE (:Buyer {id:r.id, name:r.name})-[:BUYS_FOR {role:r.role}]->(c)", {"rows": rows["buyers"]})
        g.query("UNWIND $rows AS r MATCH (b:Buyer {id:r.bid}), (c:Customer {id:r.cid}) "
                "CREATE (b)-[:OWNS]->(c)", {"rows": rows["owns"]})
        g.query("UNWIND $rows AS r MATCH (b:Buyer {id:r.bid}), (t:Trade {id:r.id}) "
                "CREATE (b)-[:COLLECTED]->(t)", {"rows": rows["collected"]})
        g.query("UNWIND $rows AS r MATCH (b:Buyer {id:r.bid}), (p:Payment {id:r.id}) "
                "CREATE (b)-[:PAID]->(p)", {"rows": rows["paid_by"]})
    if rows.get("family"):
        # Two people who are family: (:Buyer)-[:FAMILY]->(:Family)<-[:FAMILY]-(:Buyer). The link is a
        # node with an id so a receipt can use it as evidence and the what-if can remove it.
        g.query("CREATE INDEX FOR (n:Family) ON (n.id)")
        g.query("UNWIND $rows AS r MATCH (a:Buyer {id:r.a}), (b:Buyer {id:r.b}) "
                "CREATE (a)-[:FAMILY]->(:Family {id:r.id, source:r.source})<-[:FAMILY]-(b)",
                {"rows": rows["family"]})
    g.query("CREATE (:Counter {id:'decision', n:$d}), (:Counter {id:'promise', n:$p})",
            {"d": DECISION_START, "p": len(rows["promises"])})


def load_seed(db, data=None, graph_name=OWN_GRAPH):
    """Wipe and rebuild the graph from the seed (or from `data`, for tests). Returns row counts."""
    if data is None:
        from own_audit_seed import SEED
        data = SEED
    rows = prepare(data)      # checks first, so bad data never touches the graph
    if graph_name in db.list_graphs():
        db.select_graph(graph_name).delete()
    g = db.select_graph(graph_name)
    load(g, rows)
    return {k: len(v) for k, v in rows.items()}


def needs_load(db, graph_name=OWN_GRAPH):
    """True when the graph is missing, empty, or was built before records carried a source tag."""
    if graph_name not in db.list_graphs():
        return True
    g = db.select_graph(graph_name)
    n = g.query("MATCH (c:Customer {own_shop:true}) RETURN count(c)").result_set[0][0]
    if n == 0:
        return True
    return g.query("MATCH (c:Customer) WHERE c.source IS NULL RETURN count(c)").result_set[0][0] > 0


DEMO_AMOUNTS = (45000, 20000, 10000, 60000, 90000, 5000)
MAX_SEARCH = 80


def _without(state, rid):
    """A copy of the state with one record removed, as the what-if does on its graph copy."""
    st = copy.deepcopy(state)
    for key in ("trades", "payments", "promises"):
        st[key].pop(rid, None)
    st["settles"] = {k: v for k, v in st["settles"].items() if rid not in k.split(">")}
    used = {k.split(">")[0] for k in st["settles"]}
    st["payments"] = {k: v for k, v in st["payments"].items() if k in used}
    return st


def find_demo_case(graph, only_source=None):
    """Search a shop for a case worth showing: a customer and amount where the answer is NO,
    and removing ONE record (a broken promise first, else a sale) flips it to YES.

    Reads the graph at run time, so it adapts to whatever data was loaded.
    only_source limits the search to customers with that source tag (the invented ones for
    the demo button). Returns {"customer", "amount", "remove", "kind"}, or None."""
    from rules import evaluate, mark_overdue_promises, possible_phantoms, read_state
    mark_overdue_promises(graph)
    phantoms = {}
    ids = [r[0] for r in graph.query(
        "MATCH (c:Customer) WHERE $s IS NULL OR c.source = $s RETURN c.id ORDER BY c.id",
        {"s": only_source}).result_set]
    best = None
    for cid in ids[:MAX_SEARCH]:
        state = read_state(graph, cid)
        if not state:
            continue
        size = len(state["trades"]) + len(state["payments"]) + len(state["promises"])
        removals = ([(0, "promise", p) for p, v in sorted(state["promises"].items()) if v["broke"]] +
                    [(1, "sale", t) for t in sorted(state["trades"])])
        for amount in DEMO_AMOUNTS:
            if evaluate(state, amount)["verdict"] != "NO":
                continue
            for rank, kind, rid in removals:
                if evaluate(_without(state, rid), amount)["verdict"] != "YES":
                    continue
                case = {"customer": cid, "amount": amount, "remove": rid, "kind": kind}
                if kind == "sale":
                    # A sale that an unlinked payment of the same size probably paid: the NO
                    # rests on a payment nobody linked, a case one step deeper than a broken promise.
                    if cid not in phantoms:
                        phantoms[cid] = {p["trade"]: p["payment"]
                                         for p in possible_phantoms(graph, state)}
                    if rid in phantoms[cid]:
                        rank = -1
                        case["payment"] = phantoms[cid][rid]
                key = (rank, size, cid, DEMO_AMOUNTS.index(amount))
                if best is None or key < best[0]:
                    best = (key, case)
                break
            else:
                continue
            break
    return best[1] if best else None


REAL_REQUEST = 10000


def find_real_case(graph):
    """The real-audit customer with the most money showing as owed. Returns
    {"customer", "amount"} (a small request, answered NO because of the phantom debt) or None."""
    from rules import evaluate, read_state
    best = None
    for (cid,) in graph.query("MATCH (c:Customer {source:'real_audit'}) RETURN c.id ORDER BY c.id").result_set:
        state = read_state(graph, cid)
        if not state:
            continue
        debt = evaluate(state, REAL_REQUEST).get("open_debt")
        if isinstance(debt, int) and (best is None or debt > best[0]):
            best = (debt, cid)
    return {"customer": best[1], "amount": REAL_REQUEST} if best and best[0] > 0 else None


def main(argv):
    counts = load_seed(get_db())
    print("Loaded graph %s: %s" % (OWN_GRAPH, ", ".join("%d %s" % (n, k) for k, n in counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
