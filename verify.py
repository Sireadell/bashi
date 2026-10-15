"""Replay every stored decision and check it still holds.

For each Decision: rebuild its fingerprint from what it recorded, compare every
linked record with what was recorded, re-run the rule on today's records.
Prints PASS or FAIL per decision. Exit code 1 if any FAIL.

  python verify.py                  the live default shop (shop_own if loaded, else shop_a)
  python verify.py --graph shop_a   a named graph
"""
import json
import sys

from rules import evaluate, fingerprint, read_state, snapshot_of, naira


def _label(key):
    return key.split(":", 1)


def _describe(v):
    return "N{:,}".format(v) if isinstance(v, int) and not isinstance(v, bool) else str(v)


def diff_snapshots(old, new):
    """Return plain sentences naming each changed record and field."""
    msgs = []
    for key in sorted(old):
        label, rid = _label(key)
        name = "%s %s" % (label if label != "Settles" else "Payment link", rid)
        if key not in new:
            msgs.append("%s is missing now" % name)
            continue
        for f in sorted(old[key]):
            a, b = old[key][f], new[key].get(f)
            if a != b:
                if f in ("amount", "limit"):
                    a, b = _describe(a), _describe(b)
                msgs.append("%s %s changed %s -> %s" % (name, f, a, b))
    return msgs


def verify_decision(graph, d, state=None):
    """d = (id, customer_id, request, verdict, fingerprint, snapshot_json).
    state: records the caller already read for this decision's day (as_of), so
    they are not read twice. Returns (ok, [problems])."""
    did, cid, request, verdict, fp, snap_json = d
    problems = []
    try:
        old = json.loads(snap_json)
    except (TypeError, ValueError):
        return False, ["Decision %s has no readable record of what it used" % did]
    if fingerprint(old, verdict, request) != fp:
        problems.append("Decision %s itself was edited (its fingerprint no longer matches)" % did)
    # Read the records as they stood on the day of the decision, so a promise
    # that fell overdue later does not make an old decision look tampered with.
    if state is None:
        meta = graph.query("MATCH (d:Decision {id:$did}) RETURN d.as_of, d.created",
                           {"did": did}).result_set
        as_of = None
        if meta:
            as_of = meta[0][0] or (meta[0][1] or "")[:10] or None
        state = read_state(graph, cid, as_of=as_of)
    if state is None:
        return False, problems + ["Customer %s is missing now" % cid]
    # Only compare records this decision actually used.
    linked = graph.query(
        "MATCH (:Decision {id:$did})-[:USED_EVIDENCE]->(e) RETURN labels(e)[0], e.id",
        {"did": did}).result_set
    now_all = snapshot_of(state)
    used = {"Customer:%s" % cid}
    for lab, eid in linked:
        used.add("%s:%s" % (lab, eid))
    for key in old:
        if key.startswith("Settles:"):
            used.add(key)
    now = {k: v for k, v in now_all.items() if k in used}
    for lab, eid in [_label(k) for k in old if not k.startswith(("Customer", "Settles"))]:
        if "%s:%s" % (lab, eid) not in {"%s:%s" % (a, b) for a, b in linked}:
            problems.append("%s %s is no longer linked to this decision" % (lab, eid))
    problems += diff_snapshots(old, now)
    # Re-run the rule on today's records.
    replay = evaluate(state, request)
    if replay["verdict"] != verdict:
        problems.append("Re-running the rule now gives %s, the decision said %s"
                        % (replay["verdict"], verdict))
    return (not problems), problems


def main(argv=None):
    from db import open_graph
    _, graph, _ = open_graph(sys.argv[1:] if argv is None else argv)
    rows = graph.query(
        "MATCH (d:Decision) RETURN d.id, d.customer_id, d.request, d.verdict, "
        "d.fingerprint, d.snapshot ORDER BY d.id").result_set
    if not rows:
        print("No decisions stored yet.")
        return 0
    fails = 0
    for d in rows:
        ok, problems = verify_decision(graph, d)
        print("%s  %s  customer %s  request %s  %s"
              % ("PASS" if ok else "FAIL", d[0], d[1], naira(d[2]), d[3]))
        for p in problems:
            print("      - " + p)
        fails += 0 if ok else 1
    print("\n%d decision(s) checked, %d failed." % (len(rows), fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
