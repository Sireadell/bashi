"""Load the whole real shop into its own graph (shop_real).

Run: python real_shop.py [path-to-export.json]

The export holds codes, amounts, dates and a sale type only: no names, phones,
addresses or notes. Every record is tagged source "real_shop". Credit limits are
assumed (the shop keeps none), the same way own_shop.py assumes them.
The loader refuses anything that looks like personal data (same check as own_shop.py).
"""
import json
import sys

import own_shop
from db import get_db

REAL_GRAPH = "shop_real"
SOURCE = "real_shop"
DEFAULT_EXPORT = "own_shop_export.json"

# Teach the shared loader and the pages about the new source, once, when this module loads.
if SOURCE not in own_shop.SOURCES:
    own_shop.SOURCES = own_shop.SOURCES + (SOURCE,)
own_shop.TAG[SOURCE] = "real"


def tagged(data):
    out = {}
    for key in ("customers", "sales", "payments", "promises"):
        out[key] = [dict(row, source=SOURCE) for row in data.get(key, [])]
    return out


def load_real(db, data, graph_name=REAL_GRAPH):
    counts = own_shop.load_seed(db, data=tagged(data), graph_name=graph_name)
    # The export says which customer made each payment. Keep that as a link, so a
    # payment can be matched to that customer's sales later (see linking.py).
    paid = [{"cid": p["customer"], "pid": p["id"]} for p in data.get("payments", [])]
    db.select_graph(graph_name).query(
        "UNWIND $rows AS r MATCH (c:Customer {id:r.cid}), (p:Payment {id:r.pid}) "
        "CREATE (c)-[:PAID]->(p)", {"rows": paid})
    counts["paid_links"] = len(paid)
    return counts


def main(argv):
    path = argv[1] if len(argv) > 1 else DEFAULT_EXPORT
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    counts = load_real(get_db(), data)
    print("Loaded graph %s: %s" % (REAL_GRAPH, ", ".join("%d %s" % (n, k) for k, n in counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
