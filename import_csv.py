"""Load your own shop's records from CSV files into your own FalkorDB graph.

  python import_csv.py --dir examples/my_shop_csv --graph my_shop
  python import_csv.py --dir my_shop_csv --graph my_shop --replace   (rebuild a graph you made before)

Files in the folder (first line of each file is the column headings):
  customers.csv  id, name, credit_limit
  sales.csv      id, customer_id, amount, date, item
  payments.csv   id, customer_id, amount, date, sale_id (sale_id may be empty)
  promises.csv   id, customer_id, amount, date, due, kept   (this file is optional)

It builds the same graph the README describes, so rules.py, verify.py and the rest work on it.
A payment with a sale_id is a confirmed link. A payment without one is matched to the
customer's sales by linking.py and labelled inferred. Dates are YYYY-MM-DD, amounts are
whole naira. Every row is checked first. If any row is bad, every problem is printed with
its row number and nothing is written.

It never writes to the public demo graphs (shop_a, shop_own, shop_real).
"""
import argparse
import csv
import datetime
import os
import re
import sys
from decimal import Decimal, InvalidOperation

from db import get_db
from rules import RULES
from seed import LABELS

PROTECTED = ("shop_a", "shop_own", "shop_real")
PROTECTED_PREFIX = ("shop_a_whatif",)
SOURCE = "csv"

FILES = {
    "customers": (("id", "name", "credit_limit"), True),
    "sales": (("id", "customer_id", "amount", "date"), True),
    "payments": (("id", "customer_id", "amount", "date"), True),
    "promises": (("id", "customer_id", "amount", "date", "due", "kept"), False),
}
ID_OK = re.compile(r"^[A-Za-z0-9_.\-]{1,40}$")
NAME_OK = re.compile(r"^[A-Za-z0-9_\-]{1,60}$")
TRUE = {"true", "yes", "y", "1"}
FALSE = {"false", "no", "n", "0"}


class ImportProblems(Exception):
    def __init__(self, problems):
        super().__init__("%d problem(s)" % len(problems))
        self.problems = problems


def graph_name_problem(name):
    low = (name or "").lower()
    if low in PROTECTED or any(low.startswith(p) for p in PROTECTED_PREFIX):
        return ("The graph name '%s' belongs to the public demo and is never loaded from CSV. "
                "Pick your own name, for example my_shop." % name)
    if not NAME_OK.match(name or ""):
        return "The graph name may only use letters, numbers, _ and - (up to 60 characters)."
    return None


# ---------------------------------------------------------------- reading and checking

def _money(text, label, where, problems):
    t = (text or "").strip().replace(",", "")
    try:
        v = Decimal(t)
    except InvalidOperation:
        problems.append("%s: %s '%s' is not a number" % (where, label, text))
        return None
    if v < 0:
        problems.append("%s: %s '%s' is negative" % (where, label, text))
        return None
    if v != v.to_integral_value():
        problems.append("%s: %s '%s' is not a whole number of naira" % (where, label, text))
        return None
    return int(v)


def _date(text, label, where, problems):
    t = (text or "").strip()
    try:
        datetime.datetime.strptime(t, "%Y-%m-%d")
        return t
    except ValueError:
        problems.append("%s: %s '%s' is not a date (use YYYY-MM-DD, like 2026-08-14)" % (where, label, text))
        return None


def _rows(folder, kind, problems):
    """Rows of one file as (row number, dict). Row 1 is the headings."""
    required, must_exist = FILES[kind]
    path = os.path.join(folder, kind + ".csv")
    if not os.path.isfile(path):
        if must_exist:
            problems.append("%s.csv: file not found in %s" % (kind, folder))
        return []
    try:
        with open(path, newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            heads = [(h or "").strip().lower() for h in (reader.fieldnames or [])]
            missing = [c for c in required if c not in heads]
            if missing:
                problems.append("%s.csv: missing column(s): %s (found: %s)"
                                % (kind, ", ".join(missing), ", ".join(heads) or "nothing"))
                return []
            out = []
            for n, raw in enumerate(reader, start=2):
                row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items() if k}
                if raw.get(None):
                    problems.append("%s.csv row %d: too many values on this line" % (kind, n))
                if not any(row.values()):
                    continue
                out.append((n, row))
            return out
    except (OSError, UnicodeDecodeError, csv.Error) as e:
        problems.append("%s.csv: cannot read the file (%s)" % (kind, e))
        return []


def _ids(rows, kind, problems):
    seen = {}
    for n, row in rows:
        where = "%s.csv row %d" % (kind, n)
        rid = row.get("id", "")
        if not ID_OK.match(rid):
            problems.append("%s: id '%s' is empty or uses odd characters (use letters, numbers, - _ .)" % (where, rid))
        elif rid in seen:
            problems.append("%s: id '%s' is already used on row %d" % (where, rid, seen[rid]))
        else:
            seen[rid] = n
    return seen


def read_csv_folder(folder):
    """Check every file. Returns the rows ready for the graph, or raises ImportProblems."""
    problems = []
    if not os.path.isdir(folder):
        raise ImportProblems(["The folder '%s' does not exist" % folder])
    raw = {k: _rows(folder, k, problems) for k in FILES}
    for kind in FILES:
        _ids(raw[kind], kind, problems)

    customers, known = [], set()
    for n, r in raw["customers"]:
        where = "customers.csv row %d" % n
        limit = _money(r["credit_limit"], "credit_limit", where, problems)
        if ID_OK.match(r["id"]):
            known.add(r["id"])
        customers.append({"id": r["id"], "name": r["name"] or r["id"], "credit_limit": limit})
    if not raw["customers"] and not any("customers.csv" in p for p in problems):
        problems.append("customers.csv: no customers in the file")

    sales, sale_owner, sale_amount = [], {}, {}
    for n, r in raw["sales"]:
        where = "sales.csv row %d" % n
        amt = _money(r["amount"], "amount", where, problems)
        dt = _date(r["date"], "date", where, problems)
        if r["customer_id"] not in known:
            problems.append("%s: customer '%s' is not in customers.csv" % (where, r["customer_id"]))
        sales.append({"id": r["id"], "cid": r["customer_id"], "amount": amt, "date": dt,
                      "item": r.get("item", "")})
        sale_owner.setdefault(r["id"], r["customer_id"])
        sale_amount.setdefault(r["id"], amt)

    payments, settles, paid_on_sale = [], [], {}
    for n, r in raw["payments"]:
        where = "payments.csv row %d" % n
        amt = _money(r["amount"], "amount", where, problems)
        dt = _date(r["date"], "date", where, problems)
        if r["customer_id"] not in known:
            problems.append("%s: customer '%s' is not in customers.csv" % (where, r["customer_id"]))
        payments.append({"id": r["id"], "cid": r["customer_id"], "amount": amt, "date": dt})
        sid = r.get("sale_id", "")
        if sid:
            if sid not in sale_owner:
                problems.append("%s: sale_id '%s' is not in sales.csv" % (where, sid))
            elif sale_owner[sid] != r["customer_id"]:
                problems.append("%s: sale '%s' belongs to customer %s, not %s"
                                % (where, sid, sale_owner[sid], r["customer_id"]))
            elif amt is not None and sale_amount[sid] is not None:
                paid_on_sale[sid] = paid_on_sale.get(sid, 0) + amt
                if amt > sale_amount[sid] or paid_on_sale[sid] > sale_amount[sid]:
                    problems.append("%s: payments named for sale '%s' add up to more than the sale "
                                    "(N%s). Leave sale_id empty and Bashi will match the extra money."
                                    % (where, sid, "{:,}".format(sale_amount[sid])))
                else:
                    settles.append({"pid": r["id"], "tid": sid, "amount": amt})

    promises = []
    for n, r in raw["promises"]:
        where = "promises.csv row %d" % n
        amt = _money(r["amount"], "amount", where, problems)
        dt = _date(r["date"], "date", where, problems)
        due = _date(r["due"], "due", where, problems)
        k = r["kept"].lower()
        if k not in TRUE | FALSE:
            problems.append("%s: kept '%s' must be yes or no" % (where, r["kept"]))
        if r["customer_id"] not in known:
            problems.append("%s: customer '%s' is not in customers.csv" % (where, r["customer_id"]))
        promises.append({"id": r["id"], "cid": r["customer_id"], "amount": amt, "date": dt,
                         "due": due, "kept": k in TRUE})

    if problems:
        raise ImportProblems(problems)
    return dict(customers=customers, sales=sales, payments=payments, settles=settles,
                promises=promises)


# ---------------------------------------------------------------- writing

def _write(g, rows):
    for label in LABELS:
        g.query("CREATE INDEX FOR (n:%s) ON (n.id)" % label)
    g.query("UNWIND $rows AS r CREATE (:Customer {id:r.id, name:r.name, credit_limit:r.credit_limit, "
            "synthetic:false, source:$src})", {"rows": rows["customers"], "src": SOURCE})
    g.query("UNWIND $rows AS r MATCH (c:Customer {id:r.cid}) "
            "CREATE (c)-[:MADE]->(:Trade {id:r.id, amount:r.amount, date:r.date, item:r.item, source:$src})",
            {"rows": rows["sales"], "src": SOURCE})
    g.query("UNWIND $rows AS r CREATE (:Payment {id:r.id, amount:r.amount, date:r.date, source:$src})",
            {"rows": rows["payments"], "src": SOURCE})
    # Same as real_shop.py: tie every payment to its customer, so linking.py can match loose ones.
    g.query("UNWIND $rows AS r MATCH (c:Customer {id:r.cid}), (p:Payment {id:r.id}) "
            "CREATE (c)-[:PAID]->(p)", {"rows": rows["payments"]})
    if rows["settles"]:
        g.query("UNWIND $rows AS r MATCH (p:Payment {id:r.pid}), (t:Trade {id:r.tid}) "
                "CREATE (p)-[:SETTLES {amount:r.amount}]->(t)", {"rows": rows["settles"]})
    if rows["promises"]:
        g.query("UNWIND $rows AS r CREATE (:Promise {id:r.id, date:r.date, due:r.due, "
                "amount:r.amount, kept:r.kept, source:$src})", {"rows": rows["promises"], "src": SOURCE})
        g.query("UNWIND $rows AS r MATCH (c:Customer {id:r.cid}), (p:Promise {id:r.id}) "
                "CREATE (c)-[:PROMISED]->(p)", {"rows": rows["promises"]})
    for rid, text in RULES.items():
        g.query("CREATE (:Rule {id:$id, text:$text})", {"id": rid, "text": text})
    g.query("CREATE (:Counter {id:'decision', n:0}), (:Counter {id:'promise', n:$n})",
            {"n": len(rows["promises"])})


def load_csv_dir(folder, graph_name, replace=False, db=None):
    """Check the files, then build the graph. Returns the counts.
    Raises ImportProblems (nothing written) or ValueError (bad graph name or graph already exists)."""
    why = graph_name_problem(graph_name)
    if why:
        raise ValueError(why)
    rows = read_csv_folder(folder)          # all checks happen before the database is touched
    db = db or get_db()
    exists = graph_name in db.list_graphs()
    if exists and not replace:
        raise ValueError("The graph '%s' already exists. Pick a new name, or add --replace to rebuild it."
                         % graph_name)
    if exists:
        db.select_graph(graph_name).delete()
    g = db.select_graph(graph_name)
    try:
        _write(g, rows)
        import linking
        res = linking.infer_all(g)
    except Exception:
        try:
            g.delete()                      # never leave a half-built graph behind
        except Exception:
            pass
        raise
    loose = sum(1 for p in rows["payments"]) - len(rows["settles"])
    return {"customers": len(rows["customers"]), "sales": len(rows["sales"]),
            "payments": len(rows["payments"]), "promises": len(rows["promises"]),
            "confirmed_links": len(rows["settles"]), "inferred_links": res["links"],
            "loose_payments": loose}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Load your shop's CSV files into your own FalkorDB graph.")
    ap.add_argument("--dir", required=True, help="folder with customers.csv, sales.csv, payments.csv")
    ap.add_argument("--graph", required=True, help="name for your new graph, for example my_shop")
    ap.add_argument("--replace", action="store_true", help="rebuild a graph you made before")
    a = ap.parse_args(argv)
    try:
        c = load_csv_dir(a.dir, a.graph, replace=a.replace)
    except ImportProblems as e:
        print("Nothing was loaded. Fix these %d problem(s) and run it again:" % len(e.problems))
        for p in e.problems:
            print("  - " + p)
        return 1
    except ValueError as e:
        print("Nothing was loaded. " + str(e))
        return 1
    print("Loaded into your graph '%s':" % a.graph)
    print("  %d customers, %d sales, %d payments, %d promises" %
          (c["customers"], c["sales"], c["payments"], c["promises"]))
    print("  %d links: %d confirmed by you (sale_id), %d inferred by Bashi (%d payment(s) had no sale_id)"
          % (c["confirmed_links"] + c["inferred_links"], c["confirmed_links"], c["inferred_links"],
             c["loose_payments"]))
    print("Ask:     python ask_csv.py --graph %s CUSTOMER_ID AMOUNT" % a.graph)
    print("Re-check: python verify.py --graph %s" % a.graph)
    return 0


if __name__ == "__main__":
    sys.exit(main())
