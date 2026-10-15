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


def resolve_graph_name(db, name=None):
    """The graph a command line tool should use: the one asked for, else the live default
    (shop_own when it exists and holds own-shop customers), else the practice shop."""
    if name:
        return name
    try:
        if OWN_GRAPH in db.list_graphs():
            n = db.select_graph(OWN_GRAPH).query(
                "MATCH (c:Customer {own_shop:true}) RETURN count(c)").result_set[0][0]
            if n > 0:
                return OWN_GRAPH
    except Exception:
        pass
    return DEFAULT_GRAPH


def pop_graph_arg(argv):
    """Take `--graph NAME` (or `--graph=NAME`) out of an argument list.
    Returns (name or None, the remaining arguments)."""
    rest, name, i = [], None, 0
    while i < len(argv):
        a = argv[i]
        if a == "--graph" and i + 1 < len(argv):
            name, i = argv[i + 1], i + 2
            continue
        if a.startswith("--graph="):
            name = a.split("=", 1)[1]
        else:
            rest.append(a)
        i += 1
    return name, rest


def open_graph(argv):
    """For command line tools: pick the graph from `--graph`, print which one, and return
    (graph name, graph, the remaining arguments)."""
    name, rest = pop_graph_arg(argv)
    db = get_db()
    name = resolve_graph_name(db, name)
    print("Graph: %s" % name)
    return name, db.select_graph(name), rest
