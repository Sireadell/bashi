"""What if the unlinked payments were linked to their sales?

Works on a throwaway copy of the graph. The live graph is only read, and the
copy is always deleted. Nothing is written to sealed/.
"""
import time
import uuid

import whatif as _w
from rules import decide, possible_phantoms, read_state


def matching_links(g, state):
    """One payment per open sale, one sale per payment, from possible_phantoms."""
    used_t, used_p, out = set(), set(), []
    for ph in possible_phantoms(g, state):
        if ph["trade"] in used_t or ph["payment"] in used_p:
            continue
        used_t.add(ph["trade"])
        used_p.add(ph["payment"])
        out.append(ph)
    return out


def phantom_whatif(decision_id, graph_name):
    """Before and after on a copy where each matching unlinked payment is linked."""
    main = _w.get_graph(graph_name)
    dec = _w.load_decision(decision_id, main)
    if dec is None:
        raise LookupError("unknown decision")
    state = read_state(main, dec["customer_id"], as_of=dec["as_of"])
    links = matching_links(main, state) if state else []
    if not links:
        raise ValueError("no unlinked payment matches a still-open sale here")
    before = decide(dec["customer_id"], dec["request"], graph=main, save=False, as_of=dec["as_of"])
    db = _w.get_db()
    _w.sweep_stale_copies(db)
    name = "shop_a_whatif_%s_%d_%s" % (decision_id, int(time.time()), uuid.uuid4().hex[:6])
    out = {"decision_id": decision_id, "copy_deleted": False}
    try:
        main.copy(name)
        cg = db.select_graph(name)
        for ln in links:
            cg.query("MATCH (p:Payment {id:$p}), (t:Trade {id:$t}) "
                     "CREATE (p)-[:SETTLES {amount:$a}]->(t)",
                     {"p": ln["payment"], "t": ln["trade"], "a": ln["amount"]})
        after = decide(dec["customer_id"], dec["request"], graph=cg, save=False, as_of=dec["as_of"])
    finally:
        try:
            db.select_graph(name).delete()
            out["copy_deleted"] = True
        except Exception:
            pass
    out.update({
        "links": links,
        "before": {"answer": before["verdict"], "owed": before.get("open_debt")},
        "after": {"answer": after["verdict"], "owed": after.get("open_debt")},
        "changed": before["verdict"] != after["verdict"] or before.get("open_debt") != after.get("open_debt"),
        "real_graph_untouched": True,
    })
    return out
