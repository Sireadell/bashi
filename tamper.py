"""Edit one Trade amount so verify.py visibly fails, then put it back.

  python tamper.py T0042 50000                      change the amount (live default shop)
  python tamper.py TR-2 300000 --graph shop_own     change it on a named graph
  python tamper.py --restore [--graph NAME]         put that graph's changed amounts back

The default graph is shop_own when it is loaded, else shop_a. The original amounts
are saved per graph, so changes on two graphs never mix.
"""
import json
import os
import sys

STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".tamper_state.json")


def _load_all():
    try:
        with open(STATE) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if data and all(isinstance(v, int) for v in data.values()):
        return {"shop_a": data}     # old file: one flat list, always from the practice shop
    return data


def _save_all(data):
    data = {g: v for g, v in data.items() if v}
    if not data:
        if os.path.exists(STATE):
            os.remove(STATE)
        return
    with open(STATE, "w") as f:
        json.dump(data, f)


def tamper(graph, trade_id, new_amount):
    rows = graph.query("MATCH (t:Trade {id:$id}) RETURN t.amount", {"id": trade_id}).result_set
    if not rows:
        raise SystemExit("No trade %s." % trade_id)
    data = _load_all()
    data.setdefault(graph.name, {}).setdefault(trade_id, rows[0][0])  # keep the first original
    _save_all(data)
    graph.query("MATCH (t:Trade {id:$id}) SET t.amount=$a", {"id": trade_id, "a": new_amount})
    return rows[0][0]


def restore(graph):
    data = _load_all()
    saved = data.pop(graph.name, {})
    for tid, amt in saved.items():
        graph.query("MATCH (t:Trade {id:$id}) SET t.amount=$a", {"id": tid, "a": amt})
    _save_all(data)
    return saved


def main(argv):
    from db import open_graph
    name, graph, rest = open_graph(argv[1:])
    flag = " --graph " + name
    if "--restore" in rest:
        saved = restore(graph)
        if not saved:
            print("Nothing to restore.")
        for tid, amt in saved.items():
            print("Restored Trade %s amount to N{:,}".format(amt) % tid)
        return 0
    args = [a for a in rest if not a.startswith("--")]
    if len(args) != 2 or not args[1].isdigit():
        print("usage: python tamper.py TRADE_ID 50000 [--graph NAME]   |   python tamper.py --restore [--graph NAME]")
        return 2
    old = tamper(graph, args[0], int(args[1]))
    print("Trade %s amount changed N{:,} -> N{:,}. Now run: python verify.py{}".format(old, int(args[1]), flag) % args[0])
    print("Undo with: python tamper.py --restore" + flag)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
