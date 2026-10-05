# Gage finishing pass: final report

Branch `hardening-pass`, 4–5 October 2026. One commit per part; nothing pushed.
Raw outputs of every test are in `test_runs/`; each part also has a
`partN_summary.txt` there.

**Final pass bar: met on the revised Part 8 run (Groq, the default engine).**
`hardening-pass` was merged into `main` locally.

| Part | What | Commit | Result | Evidence |
|---|---|---|---|---|
| 0 | Setup: `LLM_PROVIDER=groq` stays the default, single line; p7.db deleted; `.env.example` settings all in use | 85e0134 | Pass | `part0_setup.txt` |
| 1 | Groq load: token budget, `gpt-oss-20b` helper model, leaner prompt (5,386 → 1,402 tokens), retry-once / 503 | e84848b | Pass: 10/10 fact checks completed (was 0/4), median +0.98 s; a burst of 3 was all answered (2 checks skipped by budget); the 503 path is proven by the selftest only | `part1_summary.txt`, `part1_calls_*.json`, `part1_load.*` |
| 2 | Answer rules: knowledge vs farm questions, number/reading rules | 1849ed5 | Pass: knowledge questions are no longer refused (see Part 8) | `part2_summary.txt`, `part2_questions*` |
| 3 | Local number, input and judgement checks (no Groq) | 25ce750 | Pass: all 5 required unit cases; a replay on 19 real answers found real inventions | `part3_summary.txt`, `part3_replay.*` |
| 4 | FlyBrain data cleaning and baseline comparison | 2a16c31 | Pass: 549 → 183 clean rows; threshold 0.3859; reading 299 normal at 0.153, reading 534 flagged at 0.635; FlyBrain AUROC 0.995–0.998 vs z-score 0.968–0.990 vs IsolationForest 0.745–0.889 | `part4_summary.txt`, `part4_eval*` |
| 5 | Real MaleCNS graph without the 13 GB table | 82cdab5 | Partial: built (166,700 neurons, 25.6 M connections, 51 s), 4.3 s/reading on the GPU, but it misses abnormal reading 534, so it is not switched on | `part5_summary.txt`, `part5_*` |
| 6 | Demo from zero: script, fresh install, dashboard, voice, ENVIRONMENT.md | c816866 | Pass: fresh clone → venv → install → DB → login (API and browser); voice STT → answer → TTS in 6 chunks, joined | `part6_summary.txt`, `part6_*.png`, `part6_voice.json` |
| 6b | Answer engine per request (`provider` field, dashboard dropdown, lazy fine-tuned load, no silent fallback) | 6c17dbd | Pass: model not loaded at startup; first fine-tuned request 22.1 s including the load, next 4.4 s; a missing adapter gives 503 with 0 Groq calls | `part6b_summary.txt`, `part6b_*` |
| 7 | KNOWN_LIMITATIONS.md, the stale summary comment (and the gap it hid), README | adf748a | Pass | `part7_summary.txt` |
| 8 | Final acceptance, both engines | 0f0e1c2 + "Part 8 (revised)" | Pass on the default engine (Groq); see below | `part8_groq.*`, `part8_finetuned.*`, `part8_summary.txt` |
| 9 | Merge into main | the merge commit on main | Merged locally, not pushed | — |

## Part 8: the two answer engines, same ten questions

Both runs used one server (Groq default) on a fresh copy of the real database.
The runs went one after the other, never at the same time: Groq first, then
the fine-tuned engine (after a warm-up request that loaded the model, 32.7 s).
Same retrieval, same local checks, same caveats.

| Engine | Right document retrieved | Key facts present | Invented numbers sent without a caveat | Refusals | Seconds per answer (mean / max) | Engine time (mean) |
|---|---|---|---|---|---|---|
| Groq `openai/gpt-oss-120b` | 10 / 10 | 9 / 10 | 0 | 0 | 7.7 / 19.3 | 3.3 s |
| Fine-tuned Sarvam-1 (RTX 3050, 4-bit) | 10 / 10 | 5 / 10 | 0 | 0 | 18.5 / 28.6 | 14.1 s |

- **Key facts** are each question's checks in `scripts/acceptance.py`: iron for
  Q2; 7–8 cm for Q3, Q4, Q7; 8 June and Bengaluru for Q5; no crossbreeding or
  germplasm for Q6; ₹355 and 14 days for Q8; no date that is not in the sources
  for Q1; for Q10, the farm's soil reading or a statement of what is missing.
- Groq's one miss is Q8: it answered ₹365 (the approved 2026-27 FRP, the current
  season in October 2026) where the note expects ₹355 (2025-26). See OPEN_ITEMS.
- The fine-tuned engine missed Q2 (no iron), Q5 (no date or place), Q7 (no
  depth: "use general guidelines"), Q8 (invented "Rs 2,800 per quintal"; the
  local check caveated it) and Q10 (talked about rainfall instead of the soil
  reading). It often does not use the retrieved text.
- Both runs: grounding check completed 10 / 10; sensor upload p95 during an
  answer 55.1 ms (Groq run, 153 uploads) and 56.8 ms (fine-tuned run, 109
  uploads); all uploads HTTP 200.

**Default engine: Groq (kept).** The rule was to switch to `sarvam_finetuned`
only with at least 8 / 10 key facts, zero uncaveated invented numbers, and under
45 s per answer. It met the last two (0, and 18.5 s mean / 28.6 s max) but got
**5 / 10 key facts**, so `LLM_PROVIDER=groq` stays. The fine-tuned engine
remains selectable per request.

**Pass bar on the default engine (Groq run, `part8_groq.json`):**

| Criterion | Result |
|---|---|
| Right document retrieved, 10 / 10 | met (10) |
| No invented number without a caveat | met (0) |
| Q9 answered, not refused | met |
| Grounding check completed on at least 8 / 10 | met (10) |
| Sensor upload p95 under 150 ms | met (55.1 ms) |

Also on the final code: `check_security.py` passed with no failures,
`validate_pipeline.py` passed 24 / 24, and the selftest passed
(`part8_check_security.txt`, `part8_validate_pipeline.txt`, `part8_selftest.txt`).

**Earlier attempts.** Before the engine switch, Part 8 failed its bar twice
(`part8_attempt1_*`, `part8_attempt2_*`). The failures were Groq connection
drops on this machine (HTTP 503), a wrong document for Q6 (fixed by hybrid
retrieval), and an upload p95 of 318–344 ms that coincided with FlyBrain's
first fit. That latency did not recur in the revised run, but its cause was
never proven, so it may come back on a cold start.

## Open items

Full text in [OPEN_ITEMS.md](OPEN_ITEMS.md); summary:

1. **Q8 note vs today's date:** ₹355 (2025-26) vs ₹365 (2026-27, the current
   season). Decide which answer is right.
2. **Groq connection drops** on this machine caused 503s in two earlier runs;
   the server failed honestly, but a demo needs a stable connection.
3. **Upload latency outlier** (318–344 ms) seen twice around FlyBrain's first
   fit; cause not proven.
4. **Real MaleCNS graph** does not separate normal from abnormal yet; it stays off.
5. **Synapse-point table** is incomplete (not needed for the graph); the resume
   command is in OPEN_ITEMS.md.
6. **One AI summary from the removed photo-analysis feature** in the real
   database is still shown on Home; the SQL to clear it (after a backup) is in
   OPEN_ITEMS.md.
7. **The fine-tuned engine** gets 5 / 10 key facts; better training data or
   retrieval-grounded fine-tuning would be needed before it can be the default.

## Things to know

- The Part 3 commit (25ce750) also contains a one-line firmware change that was
  already on disk, not made in this pass: `HUM_MAX` 90 → 85 in
  `firmware/esp32_node.ino`, matching the backend's `humidity_max`. Existing
  commits were not rewritten.
- `.env` (not committed) has a single `LLM_PROVIDER=groq` and the new
  `GROQ_HELPER_MODEL` / `GROQ_TOKENS_PER_MINUTE` lines.
- Limitations are in [KNOWN_LIMITATIONS.md](KNOWN_LIMITATIONS.md); exact
  working versions are in [ENVIRONMENT.md](ENVIRONMENT.md).
