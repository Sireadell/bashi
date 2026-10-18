"""Write CYPHER.md: every Cypher query in the app's own .py files, with a plain purpose.

Run:  python list_cypher.py          (writes CYPHER.md next to this file)
      python list_cypher.py --check  (exit 1 if CYPHER.md is out of date or a query has no purpose)

How it works: it reads each app .py file as a syntax tree, finds the text strings that are
Cypher queries, and notes the file, line and function. It skips tests/, headwater-graph/ and
any file git ignores. Reads or writes is decided from the keywords in the query. The one-line
purposes below were written by reading the code. A purpose is looked up by a short fingerprint of
the query text, so if a query changes, its purpose goes missing and the script says so
instead of showing an old, wrong line. Same code in, same file out.
"""
import ast
import hashlib
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "CYPHER.md")
SKIP_DIRS = ("tests/", "headwater-graph/")
STARTS = re.compile(r"^\s*(OPTIONAL\s+MATCH|MATCH|MERGE|CREATE|UNWIND|CALL|WITH|DROP)\b", re.I)
WRITES = re.compile(r"\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE|DROP)\b", re.I)

# Groups, in the order they appear in CYPHER.md. A query goes to the first group that matches
# its file and function name.
GROUPS = [
    ("Deciding", "Reading the books, applying the rules and saving a decision with its evidence."),
    ("Receipts", "Building the receipt a person reads and the record pages behind each number."),
    ("What-if copies", "Trying a change on a throwaway copy of the graph."),
    ("Verify and tamper checks", "Replaying a decision, and deliberately changing data to prove the check catches it."),
    ("MCP and API", "What the JSON routes and the agent tools read and write."),
    ("Loading data", "Creating the practice shop, the own shop, imported CSV files and the indexes."),
    ("Startup and keep-alive", "Cheap reads that check the database is awake and filled."),
]
GROUP_RULES = [
    ("Deciding", [("rules.py", None), ("linking.py", None), ("agent.py", None), ("scorecard.py", None)]),
    ("Receipts", [("app.py", "build_receipt"), ("app.py", "record")]),
    ("What-if copies", [("whatif.py", None)]),
    ("Verify and tamper checks", [("verify.py", None), ("tamper.py", None), ("tamper_sweep.py", None),
                                  ("sealed/run_sealed.py", None)]),
    ("MCP and API", [("agent_api.py", None), ("app.py", "customers")]),
    ("Loading data", [("seed.py", None), ("import_csv.py", None), ("own_shop.py", None),
                      ("real_shop.py", None), ("startup.py", "ensure_indexes")]),
    ("Startup and keep-alive", [("keepalive.py", None), ("app.py", None), ("db.py", None),
                                ("startup.py", None)]),
]


def app_files():
    out = subprocess.check_output(["git", "ls-files", "-co", "--exclude-standard", "*.py"],
                                  cwd=HERE, text=True)
    files = [f for f in out.split("\n") if f and not f.startswith(SKIP_DIRS)]
    return sorted(set(files))


def const_text(node):
    """The text of a string, an f-string or two strings joined with +, else None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = const_text(node.left), const_text(node.right)
        if a is not None and b is not None:
            return a + b
    return None


def looks_like_cypher(t):
    return bool(STARTS.match(t)) and "(" in t and len(t) > 12 and \
        re.search(r"\b(RETURN|SET|MERGE|CREATE|DELETE|MATCH|CALL|REMOVE)\b", t, re.I) is not None


def find_queries(rel):
    with open(os.path.join(HERE, rel), encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    found = []

    def visit(node, fn):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn = node.name
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            return  # a docstring or a bare string, not a query
        t = const_text(node)
        if t is not None and looks_like_cypher(t):
            found.append((rel, node.lineno, fn, " ".join(t.split())))
            return
        for child in ast.iter_child_nodes(node):
            visit(child, fn)

    visit(tree, "<module>")
    return found


def key_of(rel, fn, text):
    return "%s|%s|%s" % (rel, fn, hashlib.sha1(text.encode("utf-8")).hexdigest()[:6])


def group_of(rel, fn):
    for name, rules in GROUP_RULES:
        for f, func in rules:
            if f == rel and (func is None or func == fn):
                return name
    return None


def collect():
    rows = []
    for rel in app_files():
        rows.extend(find_queries(rel))
    rows.sort(key=lambda r: (r[0], r[1], r[3]))
    return rows


def cell(s):
    return s.replace("|", "\\|")


def render(rows):
    by_group = {name: [] for name, _ in GROUPS}
    missing, ungrouped = [], []
    for rel, line, fn, text in rows:
        key = key_of(rel, fn, text)
        purpose = PURPOSES.get(key)
        if purpose is None:
            missing.append(key)
            purpose = "(purpose not written yet)"
        g = group_of(rel, fn)
        if g is None:
            ungrouped.append(key)
            g = GROUPS[-1][0]
        kind = "writes" if WRITES.search(text) else "reads"
        start = text if len(text) <= 70 else text[:67] + "..."
        by_group[g].append((rel, line, fn, purpose, kind, start))
    nfiles = len({r[0] for r in rows})
    lines = [
        "# Every Cypher query in the app",
        "",
        "%d queries across %d files." % (len(rows), nfiles),
        "",
        "Made by `python list_cypher.py` from the app code (not tests, not the headwater-graph folder, "
        "not git-ignored files). Re-run it and you get this same file. Each purpose is a short line "
        "written from reading the code. Some queries are built in two parts in code (a fixed start "
        "plus a list of columns added later, or a label filled in at run time). The table shows the "
        "fixed text that is in the file.",
        "",
        "| Job | Queries | Reads | Writes |",
        "|---|---|---|---|",
    ]
    for name, _ in GROUPS:
        items = by_group[name]
        lines.append("| %s | %d | %d | %d |" % (name, len(items),
                     sum(1 for i in items if i[4] == "reads"), sum(1 for i in items if i[4] == "writes")))
    for name, blurb in GROUPS:
        items = by_group[name]
        if not items:
            continue
        lines += ["", "## %s" % name, "", blurb, "",
                  "| File:line | Function | What it does | Reads or writes | Query starts |",
                  "|---|---|---|---|---|"]
        for rel, line, fn, purpose, kind, start in items:
            lines.append("| %s:%d | %s | %s | %s | `%s` |" % (rel, line, fn, cell(purpose), kind,
                                                         cell(start).replace("`", "'")))
    return "\n".join(lines) + "\n", missing, ungrouped


def main():
    rows = collect()
    if "--keys" in sys.argv:
        for rel, line, fn, text in rows:
            print("%s:%d\t%s\t%s" % (rel, line, key_of(rel, fn, text), text[:70]))
        return 0
    body, missing, ungrouped = render(rows)
    if "--check" in sys.argv:
        try:
            with open(OUT, encoding="utf-8") as fh:
                same = fh.read() == body
        except FileNotFoundError:
            same = False
        print("up to date" if same else "CYPHER.md is out of date")
        for k in missing:
            print("no purpose:", k)
        for k in ungrouped:
            print("no group:", k)
        return 0 if (same and not missing and not ungrouped) else 1
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(body)
    print("wrote %s: %d queries across %d files" % (OUT, len(rows), len({r[0] for r in rows})))
    for k in missing:
        print("no purpose:", k)
    for k in ungrouped:
        print("no group:", k)
    return 1 if missing else 0


PURPOSES = {
    'agent.py|list_customers|b8a363': "List every customer with their credit limit, for the agent's customer list tool.",
    'agent.py|record_promise|0e4f87': 'Save a new promise for a customer (kept is false until the due date passes).',
    'agent_api.py|run|84d74f': 'Check the customer exists before the API answers about them.',
    'agent_api.py|run|f2de3b': 'Fetch a saved decision so the receipt route can replay it.',
    'agent_api.py|run|c9ee71': 'List the records a decision used, so a what-if that removes a record it never used is refused.',
    'agent_api.py|run|06d42e': 'List every customer with id, name, limit and where the data came from, for the agent tools.',
    'app.py|own_available|f4a501': 'Count own-shop customers to tell if the own-shop data is loaded.',
    'app.py|real_available|f4a501': 'Count own-shop customers to tell if the real-data view can be offered.',
    'app.py|customers|06d42e': "List customers with their data label for the website's customer list.",
    'app.py|health|5f46ca': 'Count customers in a shop, for the health check.',
    'app.py|build_receipt|6a709c': "Look up where a customer's data came from (practice, own shop or real audit) for the receipt label.",
    'app.py|build_receipt|8ef5ca': 'Add up everything this customer paid, to show money that no sale could use.',
    'app.py|build_receipt|a99722': "Real shop: find this customer's payments that settle no sale, to flag a possible phantom debt that matches an open sale.",
    'app.py|build_receipt|950a17': 'Practice or own shop: find payments that settle no sale, to flag a possible phantom debt that matches an open sale.',
    'app.py|record|f0c8d4': 'Fetch every stored field of one record (sale, payment or promise) for its record page.',
    'app.py|record|d47ca6': "Show a sale with its customer and the payments that settle it, for the sale's record page.",
    'app.py|record|ced7ce': "Show a payment with the sale it settles and that sale's customer, for the payment's record page.",
    'app.py|record|db72d8': "Find the customer who made a promise, for the promise's record page.",
    'db.py|resolve_graph_name|f4a501': 'Count own-shop customers to decide which shop the command line tools use by default.',
    'import_csv.py|_write|8b1b28': 'Create the index on id for one kind of record when loading a CSV import.',
    'import_csv.py|_write|442443': 'Load imported customers from a CSV.',
    'import_csv.py|_write|54393f': 'Load imported sales from a CSV and link each to its customer.',
    'import_csv.py|_write|f3ead0': 'Load imported payments from a CSV.',
    'import_csv.py|_write|d9f7fe': 'Link each imported payment to the customer who paid.',
    'import_csv.py|_write|aea9a5': 'Link each imported payment to the sale it settles, with the amount.',
    'import_csv.py|_write|900f59': 'Load imported promises from a CSV.',
    'import_csv.py|_write|1d5741': 'Link each imported promise to its customer.',
    'import_csv.py|_write|41a870': 'Save the rule text the decisions are checked against.',
    'import_csv.py|_write|9e4b9d': 'Start the two id counters (decisions and promises) for a new import.',
    'keepalive.py|tiny_read|5f46ca': 'Cheap read to keep the database awake.',
    'keepalive.py|keep_own_shop|5f46ca': 'Cheap read to keep the own-shop graph awake.',
    'linking.py|read_customer_rows|364f54': "Find a customer's sales that no payment settles, to match payments to sales.",
    'linking.py|read_customer_rows|0dd8b0': "Find a customer's payments that settle nothing, to match them to sales.",
    'linking.py|infer_all|c6bf43': 'Count saved decisions, because re-matching payments would break their replays.',
    'linking.py|infer_all|11d3d5': 'List all customer ids to run payment matching for each.',
    'linking.py|infer_all|5b0647': 'Clear the old guessed payment-to-sale links before matching again.',
    'linking.py|infer_all|27d13d': 'Save the new guessed payment-to-sale links with the method that found them.',
    'own_shop.py|load|8b1b28': 'Create the index on id for one kind of record in the own shop.',
    'own_shop.py|load|a7e47e': "Load the own shop's customers (own data, limits assumed).",
    'own_shop.py|load|d2bca8': "Load the own shop's sales and link each to its customer.",
    'own_shop.py|load|3bb710': "Load the own shop's payments.",
    'own_shop.py|load|aea9a5': 'Link each own-shop payment to the sale it settles.',
    'own_shop.py|load|094b32': "Load the own shop's promises.",
    'own_shop.py|load|db75b2': 'Link each own-shop promise to its customer.',
    'own_shop.py|load|352d23': 'Start the id counters for the own shop.',
    'own_shop.py|needs_load|f4a501': 'Count own-shop customers to tell if the own shop needs loading.',
    'own_shop.py|needs_load|2b09c8': 'Check for customers with no source label, which means an old load that needs redoing.',
    'own_shop.py|find_demo_case|8d510e': 'Find the customer to use for the demo, optionally from one data source.',
    'own_shop.py|find_real_case|c7ee4a': 'Find the customers from the real audit data.',
    'real_shop.py|load_real|fb170a': 'Link each real-audit payment to the customer who paid.',
    'rules.py|read_state|b1acd8': 'Read everything the rules need for one customer in one go: limit, sales, payments, settlements, promises and broken promises, as of a date.',
    'rules.py|possible_phantoms|3ecc27': 'Check if any payments are tied to customers in this graph.',
    'rules.py|possible_phantoms|324847': "Find a customer's payments that settle nothing and have no guessed match, as possible phantom debts.",
    'rules.py|possible_phantoms|23e623': 'Find unmatched payments anywhere in the shop when payments are not tied to customers.',
    'rules.py|_existing_max|6dd0f5': 'List existing ids of one kind so a new counter starts after the highest.',
    'rules.py|allocate_id|c8758a': 'Bump an id counter by one and read the new value, so no two requests get the same id.',
    'rules.py|allocate_id|8657a1': 'Create a counter that starts at the highest id already used.',
    'rules.py|mark_overdue_promises|f210d5': 'Mark a promise as broken once its due date has passed without being kept.',
    'rules.py|prune_decisions|c6bf43': 'Count saved decisions, to see if the cap is reached.',
    'rules.py|prune_decisions|347aa3': 'Delete the oldest decisions and their links when over the cap. Sales, payments and promises are never deleted.',
    'rules.py|_save|3664df': 'Save the rule text once (no duplicate if it exists).',
    'rules.py|_save|1ae12c': 'Save a decision: the verdict, the reason, its fingerprint and a snapshot of the records, linked to the customer.',
    'rules.py|_save|813625': 'Link a decision to each record it used as evidence.',
    'rules.py|_save|21d76b': 'Link a decision to the rule it applied.',
    'scorecard.py|make_questions|b8a363': "List customers to build the scorecard's test questions around each limit.",
    'sealed/run_sealed.py|fix_up|55bbaa': 'Set the credit limit of each sealed-test customer.',
    'sealed/run_sealed.py|fix_up|d8e780': 'Blank the amounts that the sealed test marks as missing.',
    'seed.py|load|af31e9': 'Create the index on id for one kind of record in the practice shop.',
    'seed.py|load|af41c2': "Load the practice shop's customers (invented data).",
    'seed.py|load|0d9cd8': "Load the practice shop's sales and link each to its customer.",
    'seed.py|load|832af1': "Load the practice shop's payments.",
    'seed.py|load|aea9a5': 'Link each practice payment to the sale it settles.',
    'seed.py|load|63aae0': "Load the practice shop's promises.",
    'seed.py|load|db75b2': 'Link each practice promise to its customer.',
    'seed.py|load|ac142d': 'Record which promises were broken.',
    'seed.py|load|fbfdee': "Load the practice shop's rules.",
    'seed.py|load|9e4b9d': 'Start the id counters for the practice shop.',
    'seed.py|load|18edb3': 'Mark the sale and payment used in the demo story.',
    'seed.py|main|8cf769': 'Count customers after loading, as a check.',
    'seed.py|main|cb0d0a': 'Count sales after loading, as a check.',
    'seed.py|main|84052f': 'Count payments after loading, as a check.',
    'seed.py|main|1122de': 'Count payment-to-sale links after loading, as a check.',
    'seed.py|main|3e08ea': 'Count promises after loading, as a check.',
    'seed.py|main|123e0c': 'Count broken promises after loading, as a check.',
    'seed.py|main|af3734': 'Count rules after loading, as a check.',
    'seed.py|main|d93371': 'Count sales that are not fully paid, as a check.',
    'seed.py|main|88abad': "Add up one customer's open debt, as a check.",
    'startup.py|graph_is_populated|5f46ca': 'Check if the practice shop has customers, so startup knows whether to fill it.',
    'startup.py|ensure_indexes|ceb2a3': 'List the indexes that exist, so startup knows which are missing.',
    'startup.py|ensure_indexes|8b1b28': 'Add a missing index on id.',
    'tamper.py|tamper|5d2361': "Read a sale's current amount before changing it, so it can be put back.",
    'tamper.py|tamper|c088d9': "Change a sale's amount (the manual tamper command).",
    'tamper.py|restore|c088d9': "Put a sale's amount back to what it was.",
    'tamper_sweep.py|replay|f86210': 'Replay one saved decision: fetch its stored fields to check them again.',
    'tamper_sweep.py|main|d210af': 'Read which records a decision used as evidence, to rebuild the check.',
    'tamper_sweep.py|main|514968': "Put a sale's amount back after the first tamper test.",
    'tamper_sweep.py|main|d815d3': "Tamper test: add 1,000 to a sale's amount.",
    'tamper_sweep.py|main|f7a9c3': "Read a sale's amount so it can be restored.",
    'tamper_sweep.py|main|514968': "Put a sale's amount back after the second tamper test.",
    'tamper_sweep.py|main|8f1966': "Tamper test: double a sale's amount.",
    'tamper_sweep.py|main|f7a9c3': "Read a sale's amount so it can be restored.",
    'tamper_sweep.py|main|b10360': "Put a payment's amount back after its tamper test.",
    'tamper_sweep.py|main|4b1c87': "Tamper test: add 500 to a payment's amount.",
    'tamper_sweep.py|main|bdf089': "Read a payment's amount so it can be restored.",
    'tamper_sweep.py|main|367250': "Put a sale's date back after its tamper test.",
    'tamper_sweep.py|main|6b2bf7': "Tamper test: move a sale's date to 2020.",
    'tamper_sweep.py|main|12582e': "Read a sale's date so it can be restored.",
    'tamper_sweep.py|main|c9d3a5': "Put a promise's kept flag back after its tamper test.",
    'tamper_sweep.py|main|9c9243': 'Tamper test: mark a broken promise as kept.',
    'tamper_sweep.py|main|7b3ccb': "Read a promise's kept flag so it can be restored.",
    'tamper_sweep.py|main|ef5bb1': "Put a promise's amount back after its tamper test.",
    'tamper_sweep.py|main|54a754': "Tamper test: add 700 to a promise's amount.",
    'tamper_sweep.py|main|350011': "Read a promise's amount so it can be restored.",
    'tamper_sweep.py|main|ebe332': "Tamper test: raise a customer's credit limit by 100,000.",
    'tamper_sweep.py|main|73709c': "Put a customer's credit limit back after its tamper test.",
    'tamper_sweep.py|main|70558c': "Read a customer's credit limit so it can be restored.",
    'tamper_sweep.py|main|50de4a': "Put a decision's verdict back after its tamper test.",
    'tamper_sweep.py|main|14c1fe': "Tamper test: flip a decision's verdict to YES.",
    'tamper_sweep.py|main|da6827': "Read a decision's verdict so it can be restored.",
    'tamper_sweep.py|main|bd947d': "Put a decision's fingerprint back after its tamper test.",
    'tamper_sweep.py|main|0354a2': "Tamper test: replace a decision's fingerprint with a forged one.",
    'tamper_sweep.py|main|0e15e3': "Read a decision's fingerprint so it can be restored.",
    'tamper_sweep.py|main|04cbea': "Tamper test: rename a field inside a decision's saved snapshot.",
    'tamper_sweep.py|main|e60c82': "Put a decision's snapshot back after its tamper test.",
    'tamper_sweep.py|main|05e319': "Read a decision's snapshot so it can be restored.",
    'tamper_sweep.py|main|a44e57': "Tamper test: remove a record from a decision's evidence links.",
    'tamper_sweep.py|main|e8a028': 'Put the removed evidence link back after the test.',
    'verify.py|verify_decision|5b0e58': 'Read when a decision was made and the date it looked at, so the replay uses the same day.',
    'verify.py|verify_decision|75e24b': 'Read which records a decision used, to rebuild the check.',
    'verify.py|main|bbaf9c': 'List every saved decision so the command line check can replay each one.',
    'whatif.py|load_decision|5fdbad': 'Load a saved decision with its customer, for the what-if.',
    'whatif.py|whatif|6da956': 'On a throwaway copy of the graph, delete the chosen records to see if the verdict changes.',
}

if __name__ == "__main__":
    sys.exit(main())
