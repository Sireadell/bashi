"""Key go-between line: FalkorDB's built-in betweenness picks the person between the most accounts.
Information only: the answer and the fingerprint must not change."""
import uuid

import app as webapp
import own_shop
import whatif
from db import get_db
from go_between import go_between
from own_audit_seed import SEED
from rules import decide

COOKIE = {"Cookie": f"{webapp.SHOP_COOKIE}=demo"}


def _graph():
    db = get_db()
    name = "shop_own_test_" + uuid.uuid4().hex[:8]
    own_shop.load_seed(db, SEED, graph_name=name)
    return db.select_graph(name)


def test_receipt_shows_the_go_between_line_and_nothing_else_changes(monkeypatch):
    g = _graph()
    try:
        monkeypatch.setattr(webapp, "get_graph", lambda name="shop_a": g)
        monkeypatch.setattr(whatif, "get_graph", lambda name="shop_a": g)
        webapp.reset_limits()
        found = go_between(g, "CUST-17")
        assert found and found["name"] == "Buyer 8" and found["touches"] >= 1
        r = decide("CUST-17", 40000, graph=g)
        assert r["verdict"] == "NO"
        html = webapp.app.test_client().get("/receipt/" + r["decision_id"], headers=COOKIE).get_data(as_text=True)
        assert "Key go-between (FalkorDB built-in betweenness): Buyer 8 sits between the most linked accounts" in html
        assert go_between(g, "CUST-13") is None
        webapp.reset_limits()
    finally:
        g.delete()
