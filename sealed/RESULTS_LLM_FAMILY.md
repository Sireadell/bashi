# AI without the graph, on the family cases

One run, 30 locked cases (set F: 20, set G: 10; answer keys fixed before any run). The AI is gemini-flash-lite-latest, temperature 0, the same set-up as the 200-case test. It got the same facts as Bashi as plain lists (accounts and what each owes, people and what they own or buy for, family pairs, limit, request) and the rules in words, family rule included. It did not get the graph. The prompt was committed before the run and was not changed. Run once, no re-runs, no failed calls.

| Arm | Right | Wrong approvals | Wrong refusals | Other wrong |
|---|---|---|---|---|
| Bashi | 30/30 | 0 (N0) | 0 | 0 |
| AI without graph | 19/30 | 1 (N84,000) | 9 | 1 |
| This account alone | 19/30 | 11 (N560,000) | 0 | 0 |

Bashi's row is from RESULTS_FAMILY.md and RESULTS_FAMILY_G.md. Other wrong = the AI answered something that was neither YES nor the correct NO (for example CANNOT TRACE).

| Case | Links deep | Network owes | Limit | Asked | Correct | Bashi | AI without graph | This account alone |
|---|---|---|---|---|---|---|---|---|
| F01 | 0 | N0 | N150,000 | N17,000 | YES | YES | NO (wrong) | YES |
| F02 | 0 | N10,000 | N200,000 | N225,000 | NO | NO | NO | NO |
| F03 | 0 | N0 | N100,000 | N8,000 | YES | YES | NO (wrong) | YES |
| F04 | 1 | N5,000 | N200,000 | N48,000 | YES | YES | YES | YES |
| F05 | 1 | N0 | N100,000 | N108,000 | NO | NO | NO | NO |
| F06 | 2 | N15,000 | N200,000 | N218,000 | NO | NO | NO | NO |
| F07 | 2 | N40,000 | N100,000 | N53,000 | YES | YES | NO (wrong) | YES |
| F08 | 3 | N5,000 | N150,000 | N181,000 | NO | NO | NO | NO |
| F09 | 3 | N0 | N200,000 | N59,000 | YES | YES | NO (wrong) | YES |
| F10 | 4 | N95,000 | N200,000 | N113,000 | NO | NO | NO | YES (wrong) |
| F11 | 4 | N25,000 | N100,000 | N25,000 | YES | YES | NO (wrong) | YES |
| F12 | 5 | N85,000 | N200,000 | N132,000 | NO | NO | NO | YES (wrong) |
| F13 | 5 | N60,000 | N200,000 | N102,000 | YES | YES | NO (wrong) | YES |
| F14 | 6 | N95,000 | N150,000 | N95,000 | NO | NO | NO | YES (wrong) |
| F15 | 7 | N160,000 | N100,000 | N1,000 | NO | NO | NO | YES (wrong) |
| F16 | 7 | N60,000 | N100,000 | N25,000 | YES | YES | NO (wrong) | YES |
| F17 | 8 | N30,000 | N150,000 | N153,000 | NO | NO | NO | NO |
| F18 | 8 | N115,000 | N150,000 | N2,000 | YES | YES | NO (wrong) | YES |
| F19 | 9 | N100,000 | N100,000 | N35,000 | NO | NO | NO | YES (wrong) |
| F20 | 9 | N110,000 | N150,000 | N56,000 | NO | NO | NO | YES (wrong) |
| G01 | 10 | N140,000 | N200,000 | N84,000 | NO | NO | YES (wrong) | YES (wrong) |
| G02 | 11 | N135,000 | N200,000 | N15,000 | YES | YES | NO (wrong) | YES |
| G03 | 12 | N120,000 | N150,000 | N41,000 | NO | NO | UNREADABLE (wrong) | YES (wrong) |
| G04 | 14 | N195,000 | N200,000 | N2,000 | YES | YES | YES | YES |
| G05 | 15 | N215,000 | N200,000 | N1,000 | NO | NO | NO | YES (wrong) |
| G06 | 17 | N215,000 | N150,000 | N1,000 | NO | NO | NO | YES (wrong) |
| G07 | 19 | N150,000 | N200,000 | N10,000 | YES | YES | YES | YES |
| G08 | 20 | N235,000 | N200,000 | N1,000 | NO | NO | NO | YES (wrong) |
| G09 | 21 | N185,000 | N200,000 | N13,000 | YES | YES | YES | YES |
| G10 | 22 | N180,000 | N200,000 | N9,000 | YES | YES | YES | YES |

G03: the AI replied with a list of answers instead of one, which the shared answer reader scores as unreadable (counted wrong, not changed).

Served model: gemini-3.5-flash-lite. Raw answers and reasons for every case: sealed/llm_results_family_gemini-flash-lite-latest.json.
