"""Source data for the own shop (graph shop_own). Codes, amounts and dates only.

Two parts, each record tagged with a source:

  real_audit  The 8 trades from the founder's own audit of 17 July 2026. Each sale was
              recorded as paid in full, but the customer's credit ledger still showed the
              amount as owed (N388,340 in total). Amounts and sale dates come from the
              audit log. Customers are CUST-A to CUST-D. In the graph the payment is NOT
              linked to the sale, so the debt shows and the phantom-debt flag fires.
              Payment dates (set equal to the sale dates) and credit limits are assumed.

  invented    Filler so there is more to ask about: 12 made-up customers (CUST-01 to
              CUST-12) with normal sales, payments and promises. CUST-01 has one broken
              promise (the demo: NO turns to YES when it is removed). CUST-02 has one
              phantom debt. Every invented promise is kept, except CUST-01's.

No names, phones, addresses, notes or item names exist in this file.
"""
REAL = "real_audit"
INVENTED = "invented"

# (sale code, customer, owed amount shown in the ledger, sale date)
_REAL_TRADES = [
    ("TR-1", "CUST-A", 1280, "2026-05-04"),
    ("TR-2", "CUST-B", 224960, "2026-05-30"),
    ("TR-3", "CUST-B", 47500, "2026-06-05"),
    ("TR-4", "CUST-B", 70750, "2026-06-14"),
    ("TR-5", "CUST-C", 200, "2026-06-22"),
    ("TR-6", "CUST-A", 50, "2026-07-10"),
    ("TR-7", "CUST-C", 100, "2026-07-12"),
    ("TR-8", "CUST-D", 43500, "2026-07-16"),
]

# customer: [(sale amount, sale date, [(payment amount, payment date), ...], phantom?)]
# A payment list that sums to the sale means paid in full. phantom=True means the payment
# exists but is not linked to the sale.
_INVENTED = {
    "CUST-01": [(20000, "2026-07-01", [(20000, "2026-07-05")], False),
                (30000, "2026-08-10", [(30000, "2026-08-14")], False),
                (15000, "2026-08-18", [(5000, "2026-08-25")], False)],
    "CUST-02": [(12000, "2026-08-02", [(12000, "2026-08-06")], False),
                (17500, "2026-09-02", [(17500, "2026-09-04")], True)],
    "CUST-03": [(18000, "2026-06-10", [(18000, "2026-06-14")], False),
                (22000, "2026-07-12", [(22000, "2026-07-15")], False),
                (25000, "2026-08-20", [(25000, "2026-08-24")], False),
                (16000, "2026-09-18", [(16000, "2026-09-21")], False)],
    "CUST-04": [(9000, "2026-08-08", [(9000, "2026-08-10")], False),
                (25000, "2026-09-20", [], False)],
    "CUST-05": [(28000, "2026-08-01", [(14000, "2026-08-09")], False),
                (6000, "2026-09-03", [(6000, "2026-09-05")], False)],
    "CUST-06": [(22000, "2026-09-25", [], False),
                (8000, "2026-07-30", [(8000, "2026-08-02")], False)],
    "CUST-07": [(10000, "2026-07-02", [(10000, "2026-07-06")], False),
                (12000, "2026-08-14", [(12000, "2026-08-17")], False),
                (15000, "2026-09-11", [(15000, "2026-09-15")], False)],
    "CUST-08": [(12000, "2026-09-10", [], False),
                (30000, "2026-10-01", [], False)],
    "CUST-09": [(20000, "2026-07-20", [(20000, "2026-07-27")], False),
                (14000, "2026-09-07", [(14000, "2026-09-12")], False)],
    "CUST-10": [(16000, "2026-09-14", [(8000, "2026-09-22")], False)],
    "CUST-11": [(8000, "2026-08-05", [(8000, "2026-08-07")], False),
                (6000, "2026-09-29", [(6000, "2026-10-01")], False)],
    "CUST-12": [(11000, "2026-10-05", [], False)],
}

# (customer, amount, date made, due date, kept). Only CUST-01's is not kept.
_INVENTED_PROMISES = [
    ("CUST-01", 10000, "2026-08-20", "2026-09-15", False),
    ("CUST-03", 8000, "2026-07-01", "2026-07-20", True),
    ("CUST-05", 7000, "2026-08-12", "2026-08-30", True),
    ("CUST-09", 6000, "2026-08-01", "2026-08-25", True),
]


def build():
    customers = [{"id": c, "source": REAL} for c in ("CUST-A", "CUST-B", "CUST-C", "CUST-D")]
    customers += [{"id": c, "source": INVENTED} for c in sorted(_INVENTED)]
    sales, payments = [], []
    for i, (code, cust, amount, day) in enumerate(_REAL_TRADES, 1):
        sales.append({"id": code, "kind": "sale", "customer": cust, "amount": amount,
                      "date": day, "paid": amount, "source": REAL})
        payments.append({"id": "PY-R%d" % i, "customer": cust, "amount": amount, "date": day,
                         "settles": None, "applied": 0, "source": REAL})
    n_sale = n_pay = 0
    for cust in sorted(_INVENTED):
        for amount, day, pays, phantom in _INVENTED[cust]:
            n_sale += 1
            sid = "TI-%03d" % n_sale
            total_paid = sum(a for a, _ in pays)
            sales.append({"id": sid, "kind": "sale", "customer": cust, "amount": amount,
                          "date": day, "paid": total_paid, "source": INVENTED})
            for pamt, pday in pays:
                n_pay += 1
                payments.append({"id": "PY-%03d" % n_pay, "customer": cust, "amount": pamt,
                                 "date": pday, "settles": None if phantom else sid,
                                 "applied": 0 if phantom else pamt, "source": INVENTED})
    promises = [{"id": "PR%03d" % i, "customer": c, "amount": a, "date": made, "due": due,
                 "kept": kept, "source": INVENTED}
                for i, (c, a, made, due, kept) in enumerate(_INVENTED_PROMISES, 1)]
    return {"customers": customers, "sales": sales, "payments": payments, "promises": promises}


SEED = build()
