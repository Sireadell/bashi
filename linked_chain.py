"""Shortest link chain from an account to the largest debt in its linked group,
using FalkorDB's built-in shortest path (algo.SPpaths). Information only: it never
feeds the YES/NO decision. Read-only."""
from linked_group import GROUP_QUERY, DEBT_QUERY

PATH_QUERY = (
    "MATCH (a:Customer {id:$a}), (b:Customer {id:$b}) "
    "CALL algo.SPpaths({sourceNode:a, targetNode:b, "
    "relTypes:['OWNS','COLLECTED','BUYS_FOR','MADE','PAID','FAMILY'], relDirection:'both', pathCount:1}) "
    # A family tie runs through the shared Family node (two edges); count it as
    # one link, the same way the family network check does.
    "YIELD path RETURN length(path) - size([n IN nodes(path) WHERE 'Family' IN labels(n)])")


def linked_chain(graph, customer_id):
    """{'to': account id, 'owed': naira, 'links': N} for the biggest debt among the
    other accounts joined to this one, or None when there is none."""
    try:
        for _comp, ids in graph.query(GROUP_QUERY).result_set:
            if customer_id not in ids:
                continue
            others = [i for i in ids if i != customer_id]
            if not others:
                return None
            rows = graph.query(DEBT_QUERY, {"ids": others}).result_set
            owing = [(owed, i) for i, owed in rows if owed and owed > 0]
            if not owing:
                return None
            owed, target = max(owing)
            res = graph.query(PATH_QUERY, {"a": customer_id, "b": target}).result_set
            if not res:
                return None
            return {"to": target, "owed": int(owed), "links": int(res[0][0])}
    except Exception:
        return None
    return None
