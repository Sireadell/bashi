"""Start Bashi on a host. Run: python startup.py

Seeds the demo shop only when the graph is missing or empty. A graph that
already has customers is never touched. Then starts the web server.
"""
import os
import sys

from db import DEFAULT_GRAPH, get_db


def graph_is_populated(db):
    if DEFAULT_GRAPH not in db.list_graphs():
        return False
    rows = db.select_graph(DEFAULT_GRAPH).query("MATCH (c:Customer) RETURN count(c)").result_set
    return bool(rows) and rows[0][0] > 0


def ensure_indexes(db):
    """Make sure every label has an index on id. Safe to run on every start."""
    from seed import LABELS
    g = db.select_graph(DEFAULT_GRAPH)
    have = {row[0] for row in g.query("CALL db.indexes()").result_set}
    for label in LABELS:
        if label not in have:
            g.query("CREATE INDEX FOR (n:%s) ON (n.id)" % label)
            print("startup: added missing index on %s.id" % label)


def ensure_seeded():
    """Return True if it had to seed, False if the data was already there."""
    if graph_is_populated(get_db()):
        print("startup: shop_a already has data, leaving it alone")
        return False
    print("startup: shop_a missing or empty, seeding the demo shop")
    import seed
    seed.main()
    return True


def ensure_own_shop():
    """Load the own shop when its graph is missing or empty. Safe to run on every start."""
    import own_shop
    db = get_db()
    if not own_shop.needs_load(db):
        return False
    print("startup: loading the own shop (real audit plus invented filler)")
    own_shop.load_seed(db)
    return True


def main():
    ensure_seeded()
    try:
        ensure_own_shop()
    except Exception as e:  # the demo shop must still start if this fails
        print("startup: own shop skipped (%s)" % type(e).__name__)
    try:
        ensure_indexes(get_db())
    except Exception as e:  # indexes only speed things up, never block the start
        print("startup: index check skipped (%s)" % type(e).__name__)
    port = os.environ.get("PORT", "10000")
    os.execvp(sys.executable, [sys.executable, "-m", "gunicorn", "app:app",
                               "--bind", "0.0.0.0:" + port, "--workers", "1",
                               "--threads", "4", "--timeout", "120"])


if __name__ == "__main__":
    main()
