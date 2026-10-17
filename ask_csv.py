"""Ask for a credit decision on a graph you loaded with import_csv.py.

  python ask_csv.py --graph my_shop C001 45000

Prints the answer, the reasons and the records used. The decision is saved in your graph,
so `python verify.py --graph my_shop` can re-check it later. Same two fixed rules as
everywhere else; it will not write to the public demo graphs.
"""
import sys

from db import get_db, pop_graph_arg
from import_csv import graph_name_problem
from rules import decide, naira, read_state


def main(argv):
    name, rest = pop_graph_arg(argv[1:])
    if not name or len(rest) != 2 or not rest[1].isdigit():
        print("usage: python ask_csv.py --graph my_shop CUSTOMER_ID AMOUNT")
        return 2
    why = graph_name_problem(name)
    if why:
        print(why)
        return 2
    db = get_db()
    if name not in db.list_graphs():
        print("There is no graph called '%s'. Load it first: python import_csv.py --dir FOLDER --graph %s"
              % (name, name))
        return 2
    graph = db.select_graph(name)
    r = decide(rest[0], int(rest[1]), graph=graph)
    print("Answer:   %s" % r["verdict"].replace("_", " "))
    print("Reasons:  %s" % r["reason"])
    if r["open_debt"] is not None:
        print("Open debt %s, limit %s" % (naira(r["open_debt"]), naira(r["limit"])))
    if r["evidence"]:
        print("Records used: " + ", ".join("%s %s" % (e["label"], e["id"]) for e in r["evidence"]))
        state = read_state(graph, rest[0])
        for k, how in sorted(state["inferred"].items()):
            p, t = k.split(">")
            print("  inferred link: payment %s -> sale %s (%s)" % (p, t, how))
    if r["decision_id"]:
        print("Saved as %s. Re-check it: python verify.py --graph %s" % (r["decision_id"], name))
    return 0 if r["verdict"] in ("YES", "NO") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
