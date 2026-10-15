"""Keep the free FalkorDB Cloud graph and the live site awake.

The free cloud tier stops after 1 idle day and deletes after 7 with no backup.
Run once:        python keepalive.py
Run every hour:  python keepalive.py --loop
Needs BASHI_URL (live site address) for the site ping. FalkorDB settings come
from .env. If the graph is gone or has no customers, startup.ensure_seeded()
rebuilds it with the seed. Exit code is 1 when the database cannot be read or
the graph could not be repaired.
"""
import os
import sys
import time
import urllib.request

INTERVAL = 3600


def ping_site(url):
    with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=90) as r:
        return r.status


def tiny_read():
    """Customer count in shop_a, or 0 if the graph is not there."""
    from db import DEFAULT_GRAPH, get_db
    db = get_db()
    if DEFAULT_GRAPH not in db.list_graphs():
        return 0
    return db.select_graph(DEFAULT_GRAPH).query("MATCH (c:Customer) RETURN count(c)").result_set[0][0]


def once():
    url = os.environ.get("BASHI_URL")
    if url:
        try:
            print("site /health:", ping_site(url))
        except Exception as e:
            print("site /health failed:", type(e).__name__)
    try:
        n = tiny_read()
        if n == 0:
            print("database: shop_a is missing or empty, rebuilding it")
            import startup
            startup.ensure_seeded()
            n = tiny_read()
            if n == 0:
                print("database: rebuild did not bring the customers back")
                return 1
        print("database customers:", n)
    except Exception as e:
        print("database read or rebuild failed:", type(e).__name__)
        return 1
    return 0


if __name__ == "__main__":
    if "--loop" in sys.argv:
        while True:
            once()
            time.sleep(INTERVAL)
    sys.exit(once())
