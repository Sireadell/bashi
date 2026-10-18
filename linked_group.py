"""Linked group: how many accounts are joined to this one through shared buyers,
and how many of those owe money.

This uses FalkorDB's built-in connected-components algorithm (algo.WCC), which
walks the graph itself instead of a hand-written path query. Information only:
it never feeds the YES/NO decision. Read-only."""

GROUP_QUERY = (
    "CALL algo.WCC({nodeLabels:['Customer','Buyer','Trade','Payment'], "
    "relationshipTypes:['OWNS','COLLECTED','MADE','PAID','FAMILY']}) "
    "YIELD node, componentId "
    "WITH componentId AS comp, [x IN collect(node) WHERE 'Customer' IN labels(x) | x.id] AS ids "
    "RETURN comp, ids")

DEBT_QUERY = (
    "UNWIND $ids AS cid MATCH (c:Customer {id:cid}) "
    "OPTIONAL MATCH (c)-[:MADE]->(t:Trade) "
    "OPTIONAL MATCH (p:Payment)-[s:SETTLES|INFERRED_SETTLES]->(t) "
    "WITH c, t, coalesce(sum(s.amount), 0) AS paid "
    "WITH c, sum(coalesce(t.amount, 0) - paid) AS owed "
    "RETURN c.id, owed")


def linked_group(graph, customer_id):
    """(other_accounts, owing) for the accounts joined to `customer_id`.
    Returns None when the customer is not found or the algorithm is unavailable."""
    try:
        for _comp, ids in graph.query(GROUP_QUERY).result_set:
            if customer_id in ids:
                others = [i for i in ids if i != customer_id]
                if not others:
                    return {"others": 0, "owing": 0}
                rows = graph.query(DEBT_QUERY, {"ids": others}).result_set
                return {"others": len(others), "owing": sum(1 for _i, owed in rows if owed and owed > 0)}
    except Exception:
        return None
    return None
