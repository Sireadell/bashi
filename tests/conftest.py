import os
import sys
import time
import uuid

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import get_db  # noqa: E402


def _copy_of_shop(db, name):
    """Copy shop_a, retrying if it is being reseeded at that moment."""
    for _ in range(6):
        src = db.select_graph("shop_a")
        try:
            if src.query("MATCH (c:Customer) RETURN count(c)").result_set[0][0] == 25:
                src.copy(name)
                return db.select_graph(name)
        except Exception:
            pass
        time.sleep(5)
    pytest.fail("shop_a is empty or unavailable; run python seed.py first")


@pytest.fixture()
def graph():
    """A private copy of the seeded shop, deleted afterwards."""
    db = get_db()
    name = "shop_a_test_" + uuid.uuid4().hex[:8]
    g = _copy_of_shop(db, name)
    g.query("MATCH (d:Decision) DETACH DELETE d")
    yield g
    try:
        g.delete()
    except Exception:
        pass
