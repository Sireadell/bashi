"""What-if: remove evidence on a COPY of the graph and re-run the rule.

The real graph (shop_a) is only ever read. The copy is always deleted.
"""
import db as _db

_cached = {}


def get_db():
    """One shared connection per process (a new one costs about 2 seconds)."""
    if "db" not in _cached:
        _cached["db"] = _db.get_db()
    return _cached["db"]


def get_graph(name="shop_a"):
    return get_db().select_graph(name)

MAIN = "shop_a"

from rules import decide


def load_decision(decision_id, graph=None):
    g = graph or get_graph(MAIN)
    r = g.query(
        "MATCH (d:Decision {id:$d})-[:ABOUT]->(c:Customer) "
        "RETURN d.id, d.customer_id, d.request, d.verdict, d.reason, d.created, "
        "d.fingerprint, d.rule_ids, c.name, c.credit_limit", {"d": decision_id})
    if not r.result_set:
        return None
    row = r.result_set[0]
    keys = ["id", "customer_id", "request", "verdict", "reason", "created",
            "fingerprint", "rule_ids", "customer_name", "limit"]
    return dict(zip(keys, row))


def whatif(decision_id, remove):
    """Return original vs new verdict after deleting `remove` (record ids) on a copy."""
    remove = [x for x in (remove or []) if x]
    main = get_graph(MAIN)
    dec = load_decision(decision_id, main)
    if dec is None:
        raise ValueError("unknown decision " + str(decision_id))
    copy_name = "%s_whatif_%s" % (MAIN, decision_id)
    db = get_db()
    # clear any leftover from an earlier crash
    try:
        db.select_graph(copy_name).delete()
    except Exception:
        pass
    try:
        main.copy(copy_name)
        cg = db.select_graph(copy_name)
        for rid in remove:
            cg.query("MATCH (n) WHERE n.id = $i AND (n:Trade OR n:Payment OR n:Promise) "
                     "DETACH DELETE n", {"i": rid})
        new = decide(dec["customer_id"], dec["request"], graph=cg, save=False)
    finally:
        try:
            db.select_graph(copy_name).delete()
        except Exception:
            pass
    changed = new["verdict"] != dec["verdict"]
    return {
        "decision_id": decision_id,
        "removed": remove,
        "original_verdict": dec["verdict"],
        "new_verdict": new["verdict"],
        "new_reason": new.get("reason"),
        "new_open_debt": new.get("open_debt"),
        "changed": changed,
        "note": None if changed else "EVIDENCE DID NOT MATTER",
        "real_graph_untouched": True,
    }
