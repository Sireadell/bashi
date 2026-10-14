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


def ensure_seeded():
    """Return True if it had to seed, False if the data was already there."""
    if graph_is_populated(get_db()):
        print("startup: shop_a already has data, leaving it alone")
        return False
    print("startup: shop_a missing or empty, seeding the demo shop")
    import seed
    seed.main()
    return True


def main():
    ensure_seeded()
    port = os.environ.get("PORT", "10000")
    os.execvp(sys.executable, [sys.executable, "-m", "gunicorn", "app:app",
                               "--bind", "0.0.0.0:" + port, "--workers", "1",
                               "--threads", "4", "--timeout", "120"])


if __name__ == "__main__":
    main()
