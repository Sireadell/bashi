# Every Cypher query in the app

132 queries across 18 files.

Made by `python list_cypher.py` from the app code (not tests, not the headwater-graph folder, not git-ignored files). Re-run it and you get this same file. Each purpose is a short line written from reading the code. Some queries are built in two parts in code (a fixed start plus a list of columns added later, or a label filled in at run time). The table shows the fixed text that is in the file.

| Job | Queries | Reads | Writes |
|---|---|---|---|
| Deciding | 23 | 12 | 11 |
| Receipts | 8 | 8 | 0 |
| What-if copies | 2 | 1 | 1 |
| Verify and tamper checks | 42 | 16 | 26 |
| MCP and API | 5 | 5 | 0 |
| Loading data | 45 | 14 | 31 |
| Startup and keep-alive | 7 | 7 | 0 |

## Deciding

Reading the books, applying the rules and saving a decision with its evidence.

| File:line | Function | What it does | Reads or writes | Query starts |
|---|---|---|---|---|
| agent.py:123 | list_customers | List every customer with their credit limit, for the agent's customer list tool. | reads | `MATCH (c:Customer) RETURN c.id, c.name, c.credit_limit ORDER BY c.id` |
| agent.py:132 | record_promise | Save a new promise for a customer (kept is false until the due date passes). | writes | `MATCH (c:Customer {id:$cid}) CREATE (c)-[:PROMISED]->(:Promise {id:...` |
| linking.py:70 | read_customer_rows | Find a customer's sales that no payment settles, to match payments to sales. | reads | `MATCH (:Customer {id:$cid})-[:MADE]->(t:Trade) WHERE NOT (:Payment)...` |
| linking.py:73 | read_customer_rows | Find a customer's payments that settle nothing, to match them to sales. | reads | `MATCH (:Customer {id:$cid})-[:PAID]->(p:Payment) WHERE NOT (p)-[:SE...` |
| linking.py:84 | infer_all | Count saved decisions, because re-matching payments would break their replays. | reads | `MATCH (d:Decision) RETURN count(d)` |
| linking.py:88 | infer_all | List all customer ids to run payment matching for each. | reads | `MATCH (c:Customer) RETURN c.id ORDER BY c.id` |
| linking.py:102 | infer_all | Clear the old guessed payment-to-sale links before matching again. | writes | `MATCH ()-[r:INFERRED_SETTLES]->() DELETE r` |
| linking.py:106 | infer_all | Save the new guessed payment-to-sale links with the method that found them. | writes | `UNWIND $rows AS r MATCH (p:Payment {id:r.pid}), (t:Trade {id:r.tid}...` |
| rules.py:51 | read_state | Read everything the rules need for one customer in one go: limit, sales, payments, settlements, promises and broken promises, as of a date. | reads | `MATCH (c:Customer {id:$cid}) RETURN 'C' AS k, c.id AS a, c.credit_l...` |
| rules.py:184 | possible_phantoms | Check if any payments are tied to customers in this graph. | reads | `MATCH ()-[r:PAID]->() RETURN count(r)` |
| rules.py:188 | possible_phantoms | Find a customer's payments that settle nothing and have no guessed match, as possible phantom debts. | reads | `MATCH (:Customer {id:$cid})-[:PAID]->(p:Payment) WHERE NOT (p)-[:SE...` |
| rules.py:193 | possible_phantoms | Find unmatched payments anywhere in the shop when payments are not tied to customers. | reads | `MATCH (p:Payment) WHERE NOT (p)-[:SETTLES]->() RETURN p.id, p.amoun...` |
| rules.py:243 | _existing_max | List existing ids of one kind so a new counter starts after the highest. | reads | `MATCH (n:%s) RETURN n.id` |
| rules.py:254 | allocate_id | Bump an id counter by one and read the new value, so no two requests get the same id. | writes | `MATCH (k:Counter {id:$k}) SET k.n = k.n + 1 RETURN k.n` |
| rules.py:257 | allocate_id | Create a counter that starts at the highest id already used. | writes | `MERGE (k:Counter {id:$k}) ON CREATE SET k.n = $base` |
| rules.py:281 | mark_overdue_promises | Mark a promise as broken once its due date has passed without being kept. | writes | `MATCH (c:Customer)-[:PROMISED]->(p:Promise) WHERE p.kept = false AN...` |
| rules.py:290 | prune_decisions | Count saved decisions, to see if the cap is reached. | reads | `MATCH (d:Decision) RETURN count(d)` |
| rules.py:293 | prune_decisions | Delete the oldest decisions and their links when over the cap. Sales, payments and promises are never deleted. | writes | `MATCH (d:Decision) WITH d ORDER BY d.created ASC, d.id ASC LIMIT $n...` |
| rules.py:301 | _save | Save the rule text once (no duplicate if it exists). | writes | `MERGE (r:Rule {id:$id}) ON CREATE SET r.text=$text` |
| rules.py:304 | _save | Save a decision: the verdict, the reason, its fingerprint and a snapshot of the records, linked to the customer. | writes | `MATCH (c:Customer {id:$cid}) CREATE (d:Decision {id:$did, customer_...` |
| rules.py:320 | _save | Link a decision to each record it used as evidence. | writes | `UNWIND $ids AS eid MATCH (d:Decision {id:$did}), (e:%s {id:eid}) CR...` |
| rules.py:324 | _save | Link a decision to the rule it applied. | writes | `MATCH (d:Decision {id:$did}), (r:Rule {id:$rid}) CREATE (d)-[:APPLI...` |
| scorecard.py:39 | make_questions | List customers to build the scorecard's test questions around each limit. | reads | `MATCH (c:Customer) RETURN c.id, c.name, c.credit_limit ORDER BY c.id` |

## Receipts

Building the receipt a person reads and the record pages behind each number.

| File:line | Function | What it does | Reads or writes | Query starts |
|---|---|---|---|---|
| app.py:299 | build_receipt | Look up where a customer's data came from (practice, own shop or real audit) for the receipt label. | reads | `MATCH (c:Customer {id:$c}) RETURN c.source` |
| app.py:339 | build_receipt | Add up everything this customer paid, to show money that no sale could use. | reads | `MATCH (:Customer {id:$c})-[:PAID]->(p:Payment) RETURN sum(p.amount)` |
| app.py:348 | build_receipt | Real shop: find this customer's payments that settle no sale, to flag a possible phantom debt that matches an open sale. | reads | `MATCH (:Customer {id:$c})-[:PAID]->(p:Payment) WHERE NOT (p)-[:SETT...` |
| app.py:357 | build_receipt | Practice or own shop: find payments that settle no sale, to flag a possible phantom debt that matches an open sale. | reads | `MATCH (p:Payment) WHERE NOT (p)-[:SETTLES]->(:Trade) RETURN p.id, p...` |
| app.py:440 | record | Fetch every stored field of one record (sale, payment or promise) for its record page. | reads | `MATCH (n:%s {id:$i}) RETURN properties(n)` |
| app.py:446 | record | Show a sale with its customer and the payments that settle it, for the sale's record page. | reads | `MATCH (c:Customer)-[:MADE]->(t:Trade {id:$i}) OPTIONAL MATCH (p:Pay...` |
| app.py:453 | record | Show a payment with the sale it settles and that sale's customer, for the payment's record page. | reads | `MATCH (p:Payment {id:$i}) OPTIONAL MATCH (p)-[s:SETTLES]->(t:Trade)...` |
| app.py:460 | record | Find the customer who made a promise, for the promise's record page. | reads | `MATCH (c:Customer)-[:PROMISED]->(p:Promise {id:$i}) RETURN c.name` |

## What-if copies

Trying a change on a throwaway copy of the graph.

| File:line | Function | What it does | Reads or writes | Query starts |
|---|---|---|---|---|
| whatif.py:32 | load_decision | Load a saved decision with its customer, for the what-if. | reads | `MATCH (d:Decision {id:$d})-[:ABOUT]->(c:Customer) RETURN d.id, d.cu...` |
| whatif.py:95 | whatif | On a throwaway copy of the graph, delete the chosen records to see if the verdict changes. | writes | `MATCH (n) WHERE n.id = $i AND (n:Trade OR n:Payment OR n:Promise) D...` |

## Verify and tamper checks

Replaying a decision, and deliberately changing data to prove the check catches it.

| File:line | Function | What it does | Reads or writes | Query starts |
|---|---|---|---|---|
| sealed/run_sealed.py:85 | fix_up | Set the credit limit of each sealed-test customer. | writes | `UNWIND $rows AS r MATCH (c:Customer {id:r.cid}) SET c.credit_limit ...` |
| sealed/run_sealed.py:89 | fix_up | Blank the amounts that the sealed test marks as missing. | writes | `UNWIND $ids AS i MATCH (t:Trade {id:i}) REMOVE t.amount` |
| tamper.py:39 | tamper | Read a sale's current amount before changing it, so it can be put back. | reads | `MATCH (t:Trade {id:$id}) RETURN t.amount` |
| tamper.py:45 | tamper | Change a sale's amount (the manual tamper command). | writes | `MATCH (t:Trade {id:$id}) SET t.amount=$a` |
| tamper.py:53 | restore | Put a sale's amount back to what it was. | writes | `MATCH (t:Trade {id:$id}) SET t.amount=$a` |
| tamper_sweep.py:23 | replay | Replay one saved decision: fetch its stored fields to check them again. | reads | `MATCH (d:Decision {id:$i}) RETURN` |
| tamper_sweep.py:42 | main | Read which records a decision used as evidence, to rebuild the check. | reads | `MATCH (:Decision {id:$i})-[:USED_EVIDENCE]->(e) RETURN labels(e)[0]...` |
| tamper_sweep.py:53 | main | Put a sale's amount back after the second tamper test. | writes | `MATCH (n:Trade {id:$x}) SET n.amount = $o` |
| tamper_sweep.py:53 | main | Tamper test: add 1,000 to a sale's amount. | writes | `MATCH (n:Trade {id:$x}) SET n.amount = n.amount + 1000` |
| tamper_sweep.py:54 | main | Read a sale's amount so it can be restored. | reads | `MATCH (n:Trade {id:$x}) RETURN n.amount` |
| tamper_sweep.py:56 | main | Put a sale's amount back after the second tamper test. | writes | `MATCH (n:Trade {id:$x}) SET n.amount = $o` |
| tamper_sweep.py:56 | main | Tamper test: double a sale's amount. | writes | `MATCH (n:Trade {id:$x}) SET n.amount = n.amount * 2` |
| tamper_sweep.py:57 | main | Read a sale's amount so it can be restored. | reads | `MATCH (n:Trade {id:$x}) RETURN n.amount` |
| tamper_sweep.py:59 | main | Put a payment's amount back after its tamper test. | writes | `MATCH (n:Payment {id:$x}) SET n.amount = $o` |
| tamper_sweep.py:59 | main | Tamper test: add 500 to a payment's amount. | writes | `MATCH (n:Payment {id:$x}) SET n.amount = n.amount + 500` |
| tamper_sweep.py:60 | main | Read a payment's amount so it can be restored. | reads | `MATCH (n:Payment {id:$x}) RETURN n.amount` |
| tamper_sweep.py:62 | main | Put a sale's date back after its tamper test. | writes | `MATCH (n:Trade {id:$x}) SET n.date = $o` |
| tamper_sweep.py:62 | main | Tamper test: move a sale's date to 2020. | writes | `MATCH (n:Trade {id:$x}) SET n.date = '2020-01-01'` |
| tamper_sweep.py:63 | main | Read a sale's date so it can be restored. | reads | `MATCH (n:Trade {id:$x}) RETURN n.date` |
| tamper_sweep.py:65 | main | Put a promise's kept flag back after its tamper test. | writes | `MATCH (n:Promise {id:$x}) SET n.kept = $o` |
| tamper_sweep.py:65 | main | Tamper test: mark a broken promise as kept. | writes | `MATCH (n:Promise {id:$x}) SET n.kept = true` |
| tamper_sweep.py:66 | main | Read a promise's kept flag so it can be restored. | reads | `MATCH (n:Promise {id:$x}) RETURN n.kept` |
| tamper_sweep.py:68 | main | Put a promise's amount back after its tamper test. | writes | `MATCH (n:Promise {id:$x}) SET n.amount = $o` |
| tamper_sweep.py:68 | main | Tamper test: add 700 to a promise's amount. | writes | `MATCH (n:Promise {id:$x}) SET n.amount = n.amount + 700` |
| tamper_sweep.py:69 | main | Read a promise's amount so it can be restored. | reads | `MATCH (n:Promise {id:$x}) RETURN n.amount` |
| tamper_sweep.py:71 | main | Tamper test: raise a customer's credit limit by 100,000. | writes | `MATCH (n:Customer {id:$x}) SET n.credit_limit = n.credit_limit + 10...` |
| tamper_sweep.py:72 | main | Put a customer's credit limit back after its tamper test. | writes | `MATCH (n:Customer {id:$x}) SET n.credit_limit = $o` |
| tamper_sweep.py:73 | main | Read a customer's credit limit so it can be restored. | reads | `MATCH (n:Customer {id:$x}) RETURN n.credit_limit` |
| tamper_sweep.py:75 | main | Put a decision's verdict back after its tamper test. | writes | `MATCH (n:Decision {id:$x}) SET n.verdict = $o` |
| tamper_sweep.py:75 | main | Tamper test: flip a decision's verdict to YES. | writes | `MATCH (n:Decision {id:$x}) SET n.verdict = 'YES'` |
| tamper_sweep.py:76 | main | Read a decision's verdict so it can be restored. | reads | `MATCH (n:Decision {id:$x}) RETURN n.verdict` |
| tamper_sweep.py:78 | main | Put a decision's fingerprint back after its tamper test. | writes | `MATCH (n:Decision {id:$x}) SET n.fingerprint = $o` |
| tamper_sweep.py:78 | main | Tamper test: replace a decision's fingerprint with a forged one. | writes | `MATCH (n:Decision {id:$x}) SET n.fingerprint = 'forged'` |
| tamper_sweep.py:79 | main | Read a decision's fingerprint so it can be restored. | reads | `MATCH (n:Decision {id:$x}) RETURN n.fingerprint` |
| tamper_sweep.py:81 | main | Tamper test: rename a field inside a decision's saved snapshot. | writes | `MATCH (n:Decision {id:$x}) SET n.snapshot = replace(n.snapshot, '"a...` |
| tamper_sweep.py:82 | main | Put a decision's snapshot back after its tamper test. | writes | `MATCH (n:Decision {id:$x}) SET n.snapshot = $o` |
| tamper_sweep.py:83 | main | Read a decision's snapshot so it can be restored. | reads | `MATCH (n:Decision {id:$x}) RETURN n.snapshot` |
| tamper_sweep.py:94 | main | Tamper test: remove a record from a decision's evidence links. | writes | `MATCH (:Decision {id:$i})-[r:USED_EVIDENCE]->(:Trade {id:$t}) DELETE r` |
| tamper_sweep.py:96 | main | Put the removed evidence link back after the test. | writes | `MATCH (d:Decision {id:$i}), (t:Trade {id:$t}) CREATE (d)-[:USED_EVI...` |
| verify.py:57 | verify_decision | Read when a decision was made and the date it looked at, so the replay uses the same day. | reads | `MATCH (d:Decision {id:$did}) RETURN d.as_of, d.created` |
| verify.py:67 | verify_decision | Read which records a decision used, to rebuild the check. | reads | `MATCH (:Decision {id:$did})-[:USED_EVIDENCE]->(e) RETURN labels(e)[...` |
| verify.py:93 | main | List every saved decision so the command line check can replay each one. | reads | `MATCH (d:Decision) RETURN d.id, d.customer_id, d.request, d.verdict...` |

## MCP and API

What the JSON routes and the agent tools read and write.

| File:line | Function | What it does | Reads or writes | Query starts |
|---|---|---|---|---|
| agent_api.py:159 | run | Check the customer exists before the API answers about them. | reads | `MATCH (c:Customer {id:$c}) RETURN c.id` |
| agent_api.py:218 | run | Fetch a saved decision so the receipt route can replay it. | reads | `MATCH (d:Decision {id:$d}) RETURN d.id, d.customer_id, d.request, d...` |
| agent_api.py:244 | run | List the records a decision used, so a what-if that removes a record it never used is refused. | reads | `MATCH (:Decision {id:$d})-[:USED_EVIDENCE]->(e) RETURN e.id` |
| agent_api.py:265 | run | List every customer with id, name, limit and where the data came from, for the agent tools. | reads | `MATCH (c:Customer) RETURN c.id, c.name, c.credit_limit, c.source OR...` |
| app.py:217 | customers | List customers with their data label for the website's customer list. | reads | `MATCH (c:Customer) RETURN c.id, c.name, c.credit_limit, c.source OR...` |

## Loading data

Creating the practice shop, the own shop, imported CSV files and the indexes.

| File:line | Function | What it does | Reads or writes | Query starts |
|---|---|---|---|---|
| import_csv.py:216 | _write | Create the index on id for one kind of record when loading a CSV import. | writes | `CREATE INDEX FOR (n:%s) ON (n.id)` |
| import_csv.py:217 | _write | Load imported customers from a CSV. | writes | `UNWIND $rows AS r CREATE (:Customer {id:r.id, name:r.name, credit_l...` |
| import_csv.py:219 | _write | Load imported sales from a CSV and link each to its customer. | writes | `UNWIND $rows AS r MATCH (c:Customer {id:r.cid}) CREATE (c)-[:MADE]-...` |
| import_csv.py:222 | _write | Load imported payments from a CSV. | writes | `UNWIND $rows AS r CREATE (:Payment {id:r.id, amount:r.amount, date:...` |
| import_csv.py:225 | _write | Link each imported payment to the customer who paid. | writes | `UNWIND $rows AS r MATCH (c:Customer {id:r.cid}), (p:Payment {id:r.i...` |
| import_csv.py:228 | _write | Link each imported payment to the sale it settles, with the amount. | writes | `UNWIND $rows AS r MATCH (p:Payment {id:r.pid}), (t:Trade {id:r.tid}...` |
| import_csv.py:231 | _write | Load imported promises from a CSV. | writes | `UNWIND $rows AS r CREATE (:Promise {id:r.id, date:r.date, due:r.due...` |
| import_csv.py:233 | _write | Link each imported promise to its customer. | writes | `UNWIND $rows AS r MATCH (c:Customer {id:r.cid}), (p:Promise {id:r.i...` |
| import_csv.py:236 | _write | Save the rule text the decisions are checked against. | writes | `CREATE (:Rule {id:$id, text:$text})` |
| import_csv.py:237 | _write | Start the two id counters (decisions and promises) for a new import. | writes | `CREATE (:Counter {id:'decision', n:0}), (:Counter {id:'promise', n:...` |
| own_shop.py:102 | load | Create the index on id for one kind of record in the own shop. | writes | `CREATE INDEX FOR (n:%s) ON (n.id)` |
| own_shop.py:103 | load | Load the own shop's customers (own data, limits assumed). | writes | `UNWIND $rows AS r CREATE (:Customer {id:r.id, name:r.name, credit_l...` |
| own_shop.py:107 | load | Load the own shop's sales and link each to its customer. | writes | `UNWIND $rows AS r MATCH (c:Customer {id:r.cid}) CREATE (c)-[:MADE]-...` |
| own_shop.py:110 | load | Load the own shop's payments. | writes | `UNWIND $rows AS r CREATE (:Payment {id:r.id, amount:r.amount, date:...` |
| own_shop.py:112 | load | Link each own-shop payment to the sale it settles. | writes | `UNWIND $rows AS r MATCH (p:Payment {id:r.pid}), (t:Trade {id:r.tid}...` |
| own_shop.py:114 | load | Load the own shop's promises. | writes | `UNWIND $rows AS r CREATE (:Promise {id:r.id, date:r.date, due:r.due...` |
| own_shop.py:116 | load | Link each own-shop promise to its customer. | writes | `UNWIND $rows AS r MATCH (c:Customer {id:r.cid}), (p:Promise {id:r.p...` |
| own_shop.py:118 | load | Start the id counters for the own shop. | writes | `CREATE (:Counter {id:'decision', n:$d}), (:Counter {id:'promise', n...` |
| own_shop.py:140 | needs_load | Count own-shop customers to tell if the own shop needs loading. | reads | `MATCH (c:Customer {own_shop:true}) RETURN count(c)` |
| own_shop.py:143 | needs_load | Check for customers with no source label, which means an old load that needs redoing. | reads | `MATCH (c:Customer) WHERE c.source IS NULL RETURN count(c)` |
| own_shop.py:171 | find_demo_case | Find the customer to use for the demo, optionally from one data source. | reads | `MATCH (c:Customer) WHERE $s IS NULL OR c.source = $s RETURN c.id OR...` |
| own_shop.py:205 | find_real_case | Find the customers from the real audit data. | reads | `MATCH (c:Customer {source:'real_audit'}) RETURN c.id ORDER BY c.id` |
| real_shop.py:39 | load_real | Link each real-audit payment to the customer who paid. | writes | `UNWIND $rows AS r MATCH (c:Customer {id:r.cid}), (p:Payment {id:r.p...` |
| seed.py:117 | load | Create the index on id for one kind of record in the practice shop. | writes | `CREATE INDEX FOR (n:{}) ON (n.id)` |
| seed.py:118 | load | Load the practice shop's customers (invented data). | writes | `UNWIND $rows AS r CREATE (:Customer {id:r.id, name:r.name, phone:r....` |
| seed.py:121 | load | Load the practice shop's sales and link each to its customer. | writes | `UNWIND $rows AS r MATCH (c:Customer {id:r.cid_ref}) CREATE (c)-[:MA...` |
| seed.py:123 | load | Load the practice shop's payments. | writes | `UNWIND $rows AS r CREATE (:Payment {id:r.id, amount:r.amount, date:...` |
| seed.py:125 | load | Link each practice payment to the sale it settles. | writes | `UNWIND $rows AS r MATCH (p:Payment {id:r.pid}), (t:Trade {id:r.tid}...` |
| seed.py:127 | load | Load the practice shop's promises. | writes | `UNWIND $rows AS r CREATE (:Promise {id:r.id, date:r.date, due:r.due...` |
| seed.py:129 | load | Link each practice promise to its customer. | writes | `UNWIND $rows AS r MATCH (c:Customer {id:r.cid}), (p:Promise {id:r.p...` |
| seed.py:131 | load | Record which promises were broken. | writes | `UNWIND $rows AS r MATCH (c:Customer {id:r.cid}), (p:Promise {id:r.p...` |
| seed.py:133 | load | Load the practice shop's rules. | writes | `UNWIND $rows AS r CREATE (:Rule {id:r.id, text:r.text})` |
| seed.py:135 | load | Start the id counters for the practice shop. | writes | `CREATE (:Counter {id:'decision', n:0}), (:Counter {id:'promise', n:...` |
| seed.py:139 | load | Mark the sale and payment used in the demo story. | writes | `MATCH (t:Trade {id:$t}), (p:Payment {id:$p}) SET t.demo_scene='phan...` |
| seed.py:163 | main | Count customers after loading, as a check. | reads | `MATCH (n:Customer) RETURN count(n)` |
| seed.py:164 | main | Count sales after loading, as a check. | reads | `MATCH (n:Trade) RETURN count(n)` |
| seed.py:165 | main | Count payments after loading, as a check. | reads | `MATCH (n:Payment) RETURN count(n)` |
| seed.py:166 | main | Count payment-to-sale links after loading, as a check. | reads | `MATCH ()-[r:SETTLES]->() RETURN count(r)` |
| seed.py:167 | main | Count promises after loading, as a check. | reads | `MATCH (n:Promise) RETURN count(n)` |
| seed.py:168 | main | Count broken promises after loading, as a check. | reads | `MATCH ()-[r:BROKE]->() RETURN count(r)` |
| seed.py:169 | main | Count rules after loading, as a check. | reads | `MATCH (n:Rule) RETURN count(n)` |
| seed.py:171 | main | Count sales that are not fully paid, as a check. | reads | `MATCH (t:Trade) OPTIONAL MATCH (:Payment)-[s:SETTLES]->(t) WITH t, ...` |
| seed.py:173 | main | Add up one customer's open debt, as a check. | reads | `MATCH (:Customer {id:'C001'})-[:MADE]->(t:Trade) OPTIONAL MATCH (:P...` |
| startup.py:23 | ensure_indexes | List the indexes that exist, so startup knows which are missing. | reads | `CALL db.indexes()` |
| startup.py:26 | ensure_indexes | Add a missing index on id. | writes | `CREATE INDEX FOR (n:%s) ON (n.id)` |

## Startup and keep-alive

Cheap reads that check the database is awake and filled.

| File:line | Function | What it does | Reads or writes | Query starts |
|---|---|---|---|---|
| app.py:121 | own_available | Count own-shop customers to tell if the own-shop data is loaded. | reads | `MATCH (c:Customer {own_shop:true}) RETURN count(c)` |
| app.py:135 | real_available | Count own-shop customers to tell if the real-data view can be offered. | reads | `MATCH (c:Customer {own_shop:true}) RETURN count(c)` |
| app.py:227 | health | Count customers in a shop, for the health check. | reads | `MATCH (c:Customer) RETURN count(c)` |
| db.py:38 | resolve_graph_name | Count own-shop customers to decide which shop the command line tools use by default. | reads | `MATCH (c:Customer {own_shop:true}) RETURN count(c)` |
| keepalive.py:30 | tiny_read | Cheap read to keep the database awake. | reads | `MATCH (c:Customer) RETURN count(c)` |
| keepalive.py:45 | keep_own_shop | Cheap read to keep the own-shop graph awake. | reads | `MATCH (c:Customer) RETURN count(c)` |
| startup.py:15 | graph_is_populated | Check if the practice shop has customers, so startup knows whether to fill it. | reads | `MATCH (c:Customer) RETURN count(c)` |
