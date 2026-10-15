"""FalkorDB connection helpers. Credentials come from .env, never from code."""
import os

from dotenv import load_dotenv
from falkordb import FalkorDB

load_dotenv()

DEFAULT_GRAPH = "shop_a"
OWN_GRAPH = "shop_own"


def get_db():
    # FalkorDB Cloud free tier only answers with ssl=False (ssl=True times out).
    return FalkorDB(
        host=os.environ["FALKORDB_HOST"],
        port=int(os.environ["FALKORDB_PORT"]),
        username=os.environ.get("FALKORDB_USERNAME") or None,
        password=os.environ.get("FALKORDB_PASSWORD") or None,
        ssl=False,
        socket_timeout=30,
        socket_connect_timeout=30,
    )


def get_graph(name=DEFAULT_GRAPH):
    return get_db().select_graph(name)
