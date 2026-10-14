"""Edit one Trade amount so verify.py visibly fails, then put it back.

  python tamper.py T0042 50000     change the amount
  python tamper.py --restore       put every changed amount back
"""
import json
import os
import sys

STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tamper_state.json")


def _load():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def tamper(graph, trade_id, new_amount):
    rows = graph.query("MATCH (t:Trade {id:$id}) RETURN t.amount", {"id": trade_id}).result_set
    if not rows:
        raise SystemExit("No trade %s." % trade_id)
    saved = _load()
    saved.setdefault(trade_id, rows[0][0])  # keep the first original
    with open(STATE, "w") as f:
        json.dump(saved, f)
    graph.query("MATCH (t:Trade {id:$id}) SET t.amount=$a", {"id": trade_id, "a": new_amount})
    return rows[0][0]


def restore(graph):
    saved = _load()
    for tid, amt in saved.items():
        graph.query("MATCH (t:Trade {id:$id}) SET t.amount=$a", {"id": tid, "a": amt})
    if os.path.exists(STATE):
        os.remove(STATE)
    return saved


def main(argv):
    from db import get_graph
    graph = get_graph()
    if "--restore" in argv:
        saved = restore(graph)
        if not saved:
            print("Nothing to restore.")
        for tid, amt in saved.items():
            print("Restored Trade %s amount to N{:,}".format(amt) % tid)
        return 0
    args = [a for a in argv[1:] if not a.startswith("--")]
    if len(args) != 2 or not args[1].isdigit():
        print("usage: python tamper.py T0042 50000   |   python tamper.py --restore")
        return 2
    old = tamper(graph, args[0], int(args[1]))
    print("Trade %s amount changed N{:,} -> N{:,}. Now run: python verify.py".format(old, int(args[1])) % args[0])
    print("Undo with: python tamper.py --restore")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
