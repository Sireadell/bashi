"""What-if: remove evidence on a COPY of the graph and re-run the rule.

The real graph (shop_a) is only ever read. The copy is always deleted.
"""
import threading
import time
import uuid

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
        "d.fingerprint, d.rule_ids, c.name, c.credit_limit, d.as_of, d.snapshot", {"d": decision_id})
    if not r.result_set:
        return None
    row = r.result_set[0]
    keys = ["id", "customer_id", "request", "verdict", "reason", "created",
            "fingerprint", "rule_ids", "customer_name", "limit"]
    out = dict(zip(keys, row))
    out["as_of"] = row[10] or (out["created"] or "")[:10] or None
    out["snapshot"] = row[11]
    return out


STALE_AFTER = 300      # seconds before a leftover copy counts as a crash leftover
SWEEP_EVERY = 60
_sweep = {"at": 0.0}
_sweep_lock = threading.Lock()


def sweep_stale_copies(db, now=None):
    """Delete shop_a_whatif_* copies left behind by a crash. The copy name carries
    the time it was made; a name without one is an old-style leftover."""
    now = time.time() if now is None else now
    with _sweep_lock:
        if now - _sweep["at"] < SWEEP_EVERY:
            return []
        _sweep["at"] = now
    removed = []
    try:
        names = db.list_graphs()
    except Exception:
        return removed
    for name in names:
        if not name.startswith(MAIN + "_whatif_"):
            continue
        parts = name.split("_")
        stamp = parts[-2] if len(parts) >= 5 and parts[-2].isdigit() else None
        if stamp is not None and now - int(stamp) < STALE_AFTER:
            continue
        try:
            db.select_graph(name).delete()
            removed.append(name)
        except Exception:
            pass
    return removed


def whatif(decision_id, remove, graph_name=MAIN):
    """Return original vs new verdict after deleting `remove` (record ids) on a copy."""
    remove = [x for x in (remove or []) if x]
    main = get_graph(graph_name)
    dec = load_decision(decision_id, main)
    if dec is None:
        raise ValueError("unknown decision " + str(decision_id))
    db = get_db()
    sweep_stale_copies(db)
    # Every call gets its own copy, so two runs on one receipt never touch each other.
    copy_name = "%s_whatif_%s_%d_%s" % (MAIN, decision_id, int(time.time()), uuid.uuid4().hex[:6])
    try:
        main.copy(copy_name)
        cg = db.select_graph(copy_name)
        for rid in remove:
            cg.query("MATCH (n) WHERE n.id = $i AND (n:Trade OR n:Payment OR n:Promise OR n:Family) "
                     "DETACH DELETE n", {"i": rid})
        # Read the copy as it stood on the decision's day, so the baseline is the
        # same data the original decision used and only the removal changes it.
        new = decide(dec["customer_id"], dec["request"], graph=cg, save=False,
                     as_of=dec["as_of"])
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
