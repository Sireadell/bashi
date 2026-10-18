"""Customers most like this one, using FalkorDB's own vector index.

Every customer gets a 5-number credit profile (each number between 0 and 1),
stored on the customer in the graph. FalkorDB's vector index then finds the
customers whose profile is closest. No AI model and no outside service: the
numbers come straight from sales, payments and promises already in the graph.
This is information only. It never changes a YES or NO answer.

Write the profiles (safe to run again):  python lookalike.py [--graph NAME]
"""
import sys

PROFILE_FIELDS = ["debt vs limit", "broken promises", "unlinked payments",
                  "linked accounts", "sales fully paid"]
DIM = len(PROFILE_FIELDS)


def _clamp(x):
    return max(0.0, min(1.0, float(x)))


def build_profiles(graph):
    """{customer id: (profile list, open debt)} computed from the graph."""
    def rows(q):
        return graph.query(q).result_set

    base = {r[0]: r[1] for r in rows("MATCH (c:Customer) RETURN c.id, c.credit_limit")}
    trades = {r[0]: (r[1] or 0, r[2] or 0) for r in rows(
        "MATCH (c:Customer)-[:MADE]->(t:Trade) RETURN c.id, sum(t.amount), count(t)")}
    settled = {}
    for rel in ("SETTLES", "INFERRED_SETTLES"):
        for cid, amt in rows("MATCH (c:Customer)-[:MADE]->(t:Trade)<-[s:%s]-(:Payment) "
                             "RETURN c.id, sum(s.amount)" % rel):
            settled[cid] = settled.get(cid, 0) + (amt or 0)
    # a sale counts as fully paid when the payments linked to it cover it
    paid_sales = {}
    for cid, amt, got in rows(
            "MATCH (c:Customer)-[:MADE]->(t:Trade) "
            "OPTIONAL MATCH (:Payment)-[s:SETTLES|INFERRED_SETTLES]->(t) "
            "RETURN c.id, t.amount, sum(s.amount)"):
        if (got or 0) >= (amt or 0) and (amt or 0) > 0:
            paid_sales[cid] = paid_sales.get(cid, 0) + 1
    broken = {r[0]: r[1] for r in rows(
        "MATCH (c:Customer)-[:BROKE]->(p:Promise) RETURN c.id, count(p)")}
    unlinked = {r[0]: r[1] for r in rows(
        "MATCH (c:Customer)-[:PAID]->(p:Payment) WHERE NOT (p)-[:SETTLES]->() "
        "AND NOT (p)-[:INFERRED_SETTLES]->() RETURN c.id, count(p)")}
    accounts = {r[0]: r[1] for r in rows(
        "MATCH (b:Buyer)-[:BUYS_FOR]->(c:Customer) RETURN c.id, count(b)")}

    out = {}
    for cid, limit in base.items():
        total, n = trades.get(cid, (0, 0))
        debt = max(0, total - settled.get(cid, 0))
        ratio = _clamp(debt / limit) if limit else 1.0
        share = (paid_sales.get(cid, 0) / n) if n else 1.0
        out[cid] = ([ratio, _clamp(broken.get(cid, 0) / 3), _clamp(unlinked.get(cid, 0) / 3),
                     _clamp(accounts.get(cid, 0) / 3), _clamp(share)], int(debt))
    return out


def write_profiles(graph):
    """Store profiles and create the vector index. Safe to run again."""
    profiles = build_profiles(graph)
    batch = [{"id": cid, "v": [round(x, 4) for x in p], "debt": d}
             for cid, (p, d) in profiles.items()]
    graph.query("UNWIND $rows AS r MATCH (c:Customer {id:r.id}) "
                "SET c.profile = vecf32(r.v), c.profile_debt = r.debt", {"rows": batch})
    try:
        graph.query("CREATE VECTOR INDEX FOR (c:Customer) ON (c.profile) "
                    "OPTIONS {dimension:%d, similarityFunction:'euclidean'}" % DIM)
    except Exception as e:  # the index already exists on a second run
        if "already" not in str(e).lower() and "exist" not in str(e).lower():
            raise
    return len(batch)


def lookalike(graph, customer_id, k=3):
    """The k nearest other customers, or None if profiles are not written.

    Each item: {id, owed, answer} where answer is the latest saved answer for
    that customer (or None)."""
    try:
        mine = graph.query("MATCH (c:Customer {id:$c}) RETURN c.profile",
                           {"c": customer_id}).result_set
        if not mine or mine[0][0] is None:
            return None
        res = graph.query(
            "MATCH (me:Customer {id:$c}) "
            "CALL db.idx.vector.queryNodes('Customer','profile',$n,me.profile) "
            "YIELD node, score WHERE node.id <> $c "
            "RETURN node.id, node.profile_debt, score ORDER BY score, node.id LIMIT $k",
            {"c": customer_id, "n": k + 1, "k": k}).result_set
    except Exception:
        return None
    out = []
    for cid, debt, score in res:
        ans = None
        try:
            a = graph.query("MATCH (d:Decision {customer_id:$c}) RETURN d.verdict "
                            "ORDER BY d.id DESC LIMIT 1", {"c": cid}).result_set
            ans = a[0][0] if a else None
        except Exception:
            pass
        out.append({"id": cid, "owed": debt, "answer": ans, "distance": round(float(score), 3)})
    return out or None


if __name__ == "__main__":
    from db import get_db, resolve_graph_name
    db = get_db()
    args = sys.argv[1:]
    name = args[args.index("--graph") + 1] if "--graph" in args else None
    name = resolve_graph_name(db, name)
    print("wrote profiles for %d customers on %s" % (write_profiles(db.select_graph(name)), name))
