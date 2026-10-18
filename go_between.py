"""Key go-between: the person who sits between the most linked accounts.

Uses FalkorDB's built-in Betweenness Centrality (CALL algo.betweenness). That algorithm follows
link direction, and the shop's links all point one way (person to account), so no path ever
runs through a person. So the people network around the asking customer (owner, buyer and
family links only) is copied into a tiny throwaway graph with every link going both ways,
the algorithm runs there, and the throwaway graph is deleted. The shop's own graph is only
read. Shown on the receipt as information; no yes or no rule reads it.
"""
import threading
import uuid

_CACHE = {}


def _drop(g):
    try:
        g.delete()
    except Exception:
        pass

EDGES = ("MATCH (a)-[r:OWNS|BUYS_FOR|FAMILY]->(b) "
         "RETURN labels(a)[0], a.id, coalesce(a.name, a.id), labels(b)[0], b.id, coalesce(b.name, b.id)")


def _component(rows, customer_id):
    adj = {}
    for la, a, na, lb, b, nb in rows:
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    seen, todo = {customer_id}, [customer_id]
    while todo:
        for m in adj.get(todo.pop(), ()):
            if m not in seen:
                seen.add(m)
                todo.append(m)
    return seen


def go_between(graph, customer_id):
    """{"name", "id", "touches", "score"} for the person with the highest betweenness among the
    people linked to this customer, or None when there is no such person."""
    rows = graph.query(EDGES).result_set
    comp = _component(rows, customer_id)
    rows = [r for r in rows if r[1] in comp]
    label = {}
    name = {}
    for la, a, na, lb, b, nb in rows:
        label[a], label[b], name[a], name[b] = la, lb, na, nb
    people = [n for n in comp if label.get(n) == "Buyer"]
    if len(people) < 1 or len(rows) < 2:
        return None
    touched = {p: set() for p in people}
    for la, a, na, lb, b, nb in rows:
        if la == "Buyer" and lb == "Customer":
            touched[a].add(b)
    key = repr(sorted(rows))
    if key in _CACHE:
        scores = _CACHE[key]
    else:
        db = getattr(graph, "client", None)
        if db is None:
            return None
        tmp = db.select_graph("gb_tmp_" + uuid.uuid4().hex[:10])
        try:
            both = [[a, b] for la, a, na, lb, b, nb in rows] + [[b, a] for la, a, na, lb, b, nb in rows]
            tmp.query("UNWIND $e AS r MERGE (a:N {id:r[0]}) MERGE (b:N {id:r[1]}) CREATE (a)-[:LINK]->(b)",
                      {"e": both})
            res = tmp.query("CALL algo.betweenness({relationshipTypes:['LINK']}) YIELD node, score "
                            "RETURN node.id, score").result_set
        finally:
            threading.Thread(target=_drop, args=(tmp,), daemon=True).start()
        scores = {nid: s for nid, s in res}
        if len(_CACHE) > 200:
            _CACHE.clear()
        _CACHE[key] = scores
    scores = {n: v for n, v in scores.items() if label.get(n) == "Buyer"}
    best = None
    for p in sorted(scores):
        if scores[p] > 0 and (best is None or scores[p] > scores[best]):
            best = p
    if best is None:
        return None
    return {"id": best, "name": name[best], "touches": len(touched[best]), "score": scores[best]}
