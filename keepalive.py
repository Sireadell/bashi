"""Keep the free FalkorDB Cloud graph and the live site awake.

The free cloud tier stops after 1 idle day and deletes after 7 with no backup.
Run once:        python keepalive.py
Run every hour:  python keepalive.py --loop
Needs BASHI_URL (live site address) for the site ping. FalkorDB settings come
from .env. If the graph has gone, it is rebuilt with the seed.
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
    from db import get_graph
    return get_graph().query("MATCH (c:Customer) RETURN count(c)").result_set[0][0]


def once():
    url = os.environ.get("BASHI_URL")
    if url:
        try:
            print("site /health:", ping_site(url))
        except Exception as e:
            print("site /health failed:", type(e).__name__)
    try:
        print("database customers:", tiny_read())
    except Exception as e:
        print("database read failed:", type(e).__name__)
        return 1
    return 0


if __name__ == "__main__":
    if "--loop" in sys.argv:
        while True:
            once()
            time.sleep(INTERVAL)
    sys.exit(once())
