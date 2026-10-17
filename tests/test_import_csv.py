"""Tests for import_csv.py. Graph tests use a unique throwaway graph name and delete it afterwards.
They never touch shop_a, shop_own or shop_real."""
import shutil
import uuid
from pathlib import Path

import pytest

import import_csv
from db import get_db
from rules import decide

SAMPLE = Path(__file__).resolve().parent.parent / "examples" / "my_shop_csv"


def throwaway():
    return "csvtest_" + uuid.uuid4().hex[:10]


def copy_sample(tmp_path):
    dst = tmp_path / "shop"
    shutil.copytree(SAMPLE, dst)
    return dst


def edit(folder, name, old, new):
    p = Path(folder) / name
    text = p.read_text(encoding="utf-8")
    assert old in text
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def graph_exists(name):
    return name in get_db().list_graphs()


def cleanup(name):
    try:
        if graph_exists(name):
            get_db().select_graph(name).delete()
    except Exception:
        pass


def problems_for(folder):
    with pytest.raises(import_csv.ImportProblems) as e:
        import_csv.read_csv_folder(str(folder))
    return e.value.problems


# ---------------------------------------------------------------- checks, no database

def test_sample_files_pass_the_checks():
    rows = import_csv.read_csv_folder(str(SAMPLE))
    assert (len(rows["customers"]), len(rows["sales"]), len(rows["payments"]),
            len(rows["promises"])) == (4, 8, 6, 2)
    assert len(rows["settles"]) == 5


@pytest.mark.parametrize("file,old,new,words", [
    ("sales.csv", "30000,2026-06-01", "abc,2026-06-01", "not a number"),
    ("sales.csv", "30000,2026-06-01", "-5,2026-06-01", "negative"),
    ("sales.csv", "30000,2026-06-01", "300.5,2026-06-01", "whole number"),
    ("sales.csv", "2026-06-01", "01/06/2026", "not a date"),
    ("sales.csv", "S002,C001", "S001,C001", "already used"),
    ("sales.csv", "S003,C002", "S003,C999", "not in customers.csv"),
    ("payments.csv", "P002,C001", "P002,C999", "not in customers.csv"),
    ("payments.csv", "30000,2026-06-20,S001", "30000,2026-06-20,S777", "not in sales.csv"),
    ("payments.csv", "15000,2026-07-12,S003", "15000,2026-07-12,S001", "belongs to customer"),
    ("payments.csv", "10000,2026-07-25,S002", "50000,2026-07-25,S002", "more than the sale"),
    ("customers.csv", "60000", "lots", "not a number"),
    ("promises.csv", ",no", ",maybe", "yes or no"),
    ("promises.csv", "2026-08-20", "tomorrow", "not a date"),
])
def test_each_kind_of_bad_row_is_named_with_its_row(tmp_path, file, old, new, words):
    folder = copy_sample(tmp_path)
    edit(folder, file, old, new)
    found = problems_for(folder)
    assert any(words in p and "row" in p for p in found), found


def test_missing_column_and_missing_file(tmp_path):
    folder = copy_sample(tmp_path)
    edit(folder, "sales.csv", "id,customer_id,amount,date,item", "id,customer_id,amount,item")
    assert any("missing column" in p and "date" in p for p in problems_for(folder))
    (folder / "payments.csv").unlink()
    assert any("payments.csv: file not found" in p for p in problems_for(folder))


def test_every_problem_is_reported_not_just_the_first(tmp_path):
    folder = copy_sample(tmp_path)
    edit(folder, "sales.csv", "30000,2026-06-01", "abc,2026-06-01")
    edit(folder, "payments.csv", "18000,2026-07-30", "-1,2026-07-30")
    assert len(problems_for(folder)) >= 2


@pytest.mark.parametrize("name", ["shop_a", "shop_own", "shop_real", "SHOP_A", "shop_a_whatif_1", "shop_a_whatifX"])
def test_public_graph_names_are_refused_before_anything_happens(name):
    with pytest.raises(ValueError, match="public demo"):
        import_csv.load_csv_dir(str(SAMPLE), name, replace=True)


def test_odd_graph_name_is_refused():
    with pytest.raises(ValueError, match="letters"):
        import_csv.load_csv_dir(str(SAMPLE), "my shop; drop")


# ---------------------------------------------------------------- the database

def test_good_load_counts_decision_verify_and_cleanup(tmp_path):
    name = throwaway()
    try:
        c = import_csv.load_csv_dir(str(SAMPLE), name)
        assert c == {"customers": 4, "sales": 8, "payments": 6, "promises": 2,
                     "confirmed_links": 5, "inferred_links": 1, "loose_payments": 1}
        g = get_db().select_graph(name)
        for q, n in [("MATCH (n:Customer) RETURN count(n)", 4), ("MATCH (n:Trade) RETURN count(n)", 8),
                     ("MATCH (n:Payment) RETURN count(n)", 6), ("MATCH (n:Promise) RETURN count(n)", 2),
                     ("MATCH (n:Rule) RETURN count(n)", 2), ("MATCH (n:Counter) RETURN count(n)", 2),
                     ("MATCH ()-[r:MADE]->() RETURN count(r)", 8),
                     ("MATCH ()-[r:PROMISED]->() RETURN count(r)", 2),
                     ("MATCH ()-[r:SETTLES]->() RETURN count(r)", 5),
                     ("MATCH ()-[r:INFERRED_SETTLES]->() RETURN count(r)", 1)]:
            assert g.query(q).result_set[0][0] == n, q
        broken = decide("C001", 45000, graph=g)
        assert broken["verdict"] == "NO" and broken["broken_promises"] == ["PR001"]
        clean = decide("C003", 10000, graph=g)
        assert clean["verdict"] == "YES"
        import verify
        assert verify.main(["--graph", name]) == 0
    finally:
        cleanup(name)


def test_loose_payment_is_linked_and_labelled_inferred():
    name = throwaway()
    try:
        import_csv.load_csv_dir(str(SAMPLE), name)
        g = get_db().select_graph(name)
        rows = g.query("MATCH (p:Payment)-[r:INFERRED_SETTLES]->(t:Trade) "
                       "RETURN p.id, t.id, r.amount, r.method").result_set
        assert rows == [["P004", "S004", 12000, "exact"]]
        from rules import read_state
        assert read_state(g, "C002")["inferred"] == {"P004>S004": "exact"}
        assert decide("C002", 20000, graph=g, save=False)["open_debt"] == 0
    finally:
        cleanup(name)


def test_bad_rows_write_nothing(tmp_path):
    name = throwaway()
    folder = copy_sample(tmp_path)
    edit(folder, "sales.csv", "30000,2026-06-01", "abc,2026-06-01")
    try:
        with pytest.raises(import_csv.ImportProblems):
            import_csv.load_csv_dir(str(folder), name)
        assert not graph_exists(name)
    finally:
        cleanup(name)


def test_existing_graph_needs_replace():
    name = throwaway()
    try:
        import_csv.load_csv_dir(str(SAMPLE), name)
        with pytest.raises(ValueError, match="already exists"):
            import_csv.load_csv_dir(str(SAMPLE), name)
        c = import_csv.load_csv_dir(str(SAMPLE), name, replace=True)
        assert c["customers"] == 4
    finally:
        cleanup(name)


def test_bad_rows_do_not_touch_an_existing_graph_even_with_replace(tmp_path):
    name = throwaway()
    folder = copy_sample(tmp_path)
    edit(folder, "customers.csv", "60000", "-1")
    try:
        import_csv.load_csv_dir(str(SAMPLE), name)
        with pytest.raises(import_csv.ImportProblems):
            import_csv.load_csv_dir(str(folder), name, replace=True)
        g = get_db().select_graph(name)
        assert g.query("MATCH (n:Customer) RETURN count(n)").result_set[0][0] == 4
    finally:
        cleanup(name)
