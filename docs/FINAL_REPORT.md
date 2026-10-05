# Gage finishing pass: final report

Branch `hardening-pass`, 4–5 October 2026. One commit per part; nothing pushed.
Raw outputs of every test are in `test_runs/` (each part also has a
`partN_summary.txt` there). **The final pass bar was not met, so
`hardening-pass` was not merged into `main`.**

| Part | What | Commit | Result | Evidence |
|---|---|---|---|---|
| 0 | Setup: one `LLM_PROVIDER=groq` line, p7.db deleted, `.env.example` settings all in use | 85e0134 | Pass | `part0_setup.txt` |
| 1 | Groq load: token budget, `gpt-oss-20b` helper model, leaner prompt (5,386 → 1,402 tokens), retry-once / 503 | e84848b | Pass: 10/10 fact checks completed (was 0/4), median +0.98 s; burst of 3 all answered (2 checks skipped by budget). 503 path proven by selftest only | `part1_summary.txt`, `part1_calls_*.json`, `part1_load.*` |
| 2 | Answer rules: knowledge vs farm questions, number/reading rules | 1849ed5 | Partial: refusals of knowledge questions gone (Q3, Q9 answered); acceptance runs 9/10 and 7/10 with network errors and the Q8 date conflict | `part2_summary.txt`, `part2_questions*` |
| 3 | Local number, input and judgement checks (no Groq) | 25ce750 | Pass: all 5 required unit cases; replay on 19 real answers found real inventions | `part3_summary.txt`, `part3_replay.*` |
| 4 | FlyBrain data cleaning and baseline comparison | 2a16c31 | Pass: 549 → 183 clean rows; threshold 0.3859; 299 normal 0.153, 534 flagged 0.635; FlyBrain AUROC 0.995–0.998 vs z-score 0.968–0.990 vs IsolationForest 0.745–0.889 | `part4_summary.txt`, `part4_eval*` |
| 5 | Real MaleCNS graph without the 13 GB table | 82cdab5 | Partial: built (166,700 neurons, 25.6 M connections, 51 s), 4.3 s/reading on GPU, but it misses abnormal reading 534, so it is not switched on | `part5_summary.txt`, `part5_*` |
| 6 | Demo from zero: script, fresh install, dashboard, voice, ENVIRONMENT.md | c816866 | Pass: fresh clone → venv → install → DB → login (API and browser); voice STT → answer → TTS 6 chunks joined | `part6_summary.txt`, `part6_*.png`, `part6_voice.json` |
| 7 | KNOWN_LIMITATIONS.md, stale summary comment (and the gap it hid), README | adf748a | Pass | `part7_summary.txt` |
| 8 | Final acceptance test | 0f0e1c2 | **Fail** (twice): see below | `part8_summary.txt`, `part8_acceptance.*`, `part8_attempt1_*` |
| 9 | This report; no merge | (this commit) | — | — |

## Final acceptance (Part 8)

| Pass-bar criterion | Attempt 1 | Attempt 2 |
|---|---|---|
| Right document retrieved, 10 of 10 | 7 | 7 |
| No invented number without a caveat | met | met |
| Q9 answered, not refused | not met (HTTP 503) | met |
| Grounding check on at least 8 of 10 | met (8) | not met (7) |
| Sensor upload p95 under 150 ms | not met (344 ms) | not met (318.6 ms) |

- Every missed document in attempt 2 was a question that got HTTP 503 because
  this machine's connection to Groq dropped (connection error or timeout).
  Every question that reached Groq retrieved the right document.
- Upload p50 was about 79 ms. The p95 is the single slowest of 17–19 uploads,
  in a window where FlyBrain's daily fit was starting; without the fit, p95 was
  99–108 ms. The cause of the outlier is not proven.
- Also run against the attempt-2 server: `check_security.py` (exit 0, no
  failures), `validate_pipeline.py` (24/24), selftest (passed).

## Open items

Full text in [OPEN_ITEMS.md](OPEN_ITEMS.md); summary:

1. **Final pass bar** not met: Groq connection drops on this machine; upload
   p95 outlier during the FlyBrain fit.
2. **Q8 note vs today's date:** the note wants ₹355 (2025-26). In October 2026
   "this season" is 2026-27, ₹365 in the knowledge base. Decide which is right.
3. **Real MaleCNS graph** does not separate normal from abnormal yet (score
   dominated by near-silent neurons). It stays off.
4. **Synapse-point table** is incomplete (93.7 MB of 13 GB). It is not needed
   for the graph; the resume command is in OPEN_ITEMS.md.
5. **One vision-era AI summary** in the real database is still shown on Home
   until a new one is generated; the SQL to clear it (after a backup) is in
   OPEN_ITEMS.md.
6. **Test machine** sleeps or loses network during long runs.

## Things to know

- The Part 3 commit (25ce750) also contains a one-line firmware change that was
  already on disk, not made in this pass: `HUM_MAX` 90 → 85 in
  `firmware/esp32_node.ino`, matching the backend's `humidity_max`. Existing
  commits were not rewritten.
- `.env` (not committed) now has a single `LLM_PROVIDER=groq` and the new
  `GROQ_HELPER_MODEL` / `GROQ_TOKENS_PER_MINUTE` lines.
- Limitations are in [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md); exact
  working versions are in [ENVIRONMENT.md](ENVIRONMENT.md).
