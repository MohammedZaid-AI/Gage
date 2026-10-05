# Open items

Things that are not finished, or that need someone with access, a decision or
hardware. Each says what was seen and where the evidence is.

## From the finishing pass (October 2026)

### Q8 acceptance note conflicts with today's date
- The acceptance note says Q8 ("What is the FRP for sugarcane this season...")
  must answer ₹355/quintal for 2025-26. The knowledge base also lists
  ₹365/quintal approved for 2026-27, and the current date is October 2026, so
  "this season" is 2026-27. In test_runs/part2_questions.json Gage answered ₹365
  and 14 days, which matches the source for this season.
- The answer prompt now carries today's date, so the model can tell the seasons
  apart. The acceptance check still expects 355, as written; decide whether ₹365
  (2026-27) is also acceptable.

### Q6 retrieval varies between runs
- "ಸರಿಯಾದ variety ಹೇಗೆ ಆರಿಸ್ಕೊಳಿ" retrieved the cultivation overview in two runs
  and the seed-selection document (sugarcane/03) in a third
  (test_runs/part2_questions.json). The Groq query rewrite is not word-for-word
  repeatable, so the merged ranking shifts. The seed-selection document is a
  reasonable source for choosing a variety, but it is not the one the
  acceptance note names.

### Test machine sleeps / loses network during long runs
- Part 2 run 2: DNS failures ("getaddrinfo failed") for Sarvam and Groq; the
  server returned an honest 503 and saved nothing
  (test_runs/part2_server_run2.log).
- Part 2 run 3: one request measured 5418 s on the client clock and one Groq
  call took 293 s, consistent with the PC sleeping mid-test. Wall-clock times
  that cross a sleep are not meaningful; server-log timings are.

### Real MaleCNS graph runs, but does not yet separate normal from abnormal
- Built without the 13 GB synapse-point table (flycns only uses that table for
  synapse-centroid positions of neurons without a soma location; the
  neuron-to-neuron graph needs annotations, transmitters and weights):
  166,700 neurons, 25,582,938 connections, compiled in 51 s
  (test_runs/part5_compile.log).
- Time per reading (1500 steps): 10.3-10.6 s on the CPU (NumPy engine), 4.3-4.4 s
  on the RTX 3050 with flycns's torch engine (test_runs/part5_timing.txt).
- Scores on farm 1 (test_runs/part5_flybrain_real.txt): threshold 192,919 (p99 of
  60 held-out clean normal readings); reading 299 (normal) 36,511; reading 534
  (30.5 C, 88 %, soil 16 %) 185,454 -> NOT flagged. The synthetic graph flags 534.
- Likely cause: the score is the RMS z-score over all neurons with a 1e-6 floor
  on each neuron's baseline spread; on the real graph most neurons are almost
  silent, so near-zero spreads produce huge, noisy z-scores. A fix to try: score
  only neurons that fire in the baseline, or floor the spread (e.g. 0.1 Hz) —
  a method change, so it needs re-evaluation with scripts/eval_flybrain.py.
- FLYBRAIN_GRAPH stays "synthetic". To use the real graph anyway:
  FLYBRAIN_GRAPH=malecns (FLYBRAIN_ENGINE=auto picks the GPU when CUDA exists).
- The synapse-point table is still incomplete (93.7 MB of 13.06 GB). It is not
  needed for the graph. To finish it on a faster connection (resumes in place):
  curl -C - -L -o "models/malecns/raw/syn-points-male-cns-v1.0-minconf-0.5.feather" https://storage.googleapis.com/flyem-male-cns/v1.0/connectome-data/flat-connectome/syn-points-male-cns-v1.0-minconf-0.5.feather
  The loader (backend/ai/flybrain.load_real_malecns) currently always compiles
  without it; using it would mean passing synapse_centroids_for_missing=True and
  deleting models/malecns/compiled. Positions do not change the connections.

### One stored AI summary still describes the removed photo analysis
- The real database (storage/observations.db) has 1 observation whose
  `ai_summary` says "The image analysis indicates the crop appears severely dried
  (100 % confidence)" — written before the vision feature was removed. It is the
  newest stored summary, so the dashboard's "Today's report" shows it until a new
  summary is generated (on the next alert, or within SUMMARY_INTERVAL_MINUTES of
  new sensor data). Not changed here (data). To clear it, back up the database,
  then run:
  sqlite3 storage/observations.db "UPDATE observations SET ai_summary = NULL WHERE ai_summary LIKE '%image analysis%';"
  (test_runs/part7_summary_endpoint.txt)

### Final acceptance test (Part 8) failed its pass bar twice
Both runs: scripts/acceptance.py, 10 questions 30 s apart, Groq server on a copy
of the real database.

| Criterion | Attempt 1 | Attempt 2 |
|---|---|---|
| Right document, 10 of 10 | 7 (Q6 wrong doc; Q8, Q9 HTTP 503) | 7 (Q1, Q2, Q8 HTTP 503) |
| No uncaveated invented number | met | met |
| Q9 answered, not refused | not met (HTTP 503) | met |
| Grounding check on >= 8 of 10 | met (8) | not met (7; the 3 errors had no answer to check) |
| Sensor upload p95 < 150 ms | not met (344 ms; p50 78.5) | not met (318.6 ms; p50 78.8) |

- Every HTTP 503 was "Groq request failed: APIConnectionError: Connection error"
  or "APITimeoutError": this machine's connection to api.groq.com dropped
  (3 times in attempt 2). The server failed honestly and saved nothing. Every
  question that got through was answered with the right document in attempt 2.
- Q6 retrieved the seed-selection document in attempt 1; after hybrid
  retrieval (keyword bonus) it retrieved the cultivation overview first in
  attempt 2.
- Upload latency: p95 is the single slowest of 17-19 uploads. In both attempts
  the first upload started FlyBrain's daily baseline fit. Measured without the
  fit running, p95 was 99-108 ms (test_runs/part8_latency_diag.txt). Moving the
  simulation into a worker process did not remove the outlier, so its cause is
  not proven (candidates: the worker process start-up and the fit competing for
  this 4-core laptop's CPU). To check: run the latency test with the baseline
  already fitted, or start the worker at server start-up.
- Q8 expects ₹355 (2025-26); see "Q8 acceptance note conflicts with today's
  date" above.
- Evidence: test_runs/part8_attempt1_*, test_runs/part8_acceptance.*,
  test_runs/part8_server.log.
- Revised Part 8 (after the per-request engine switch, 5 October 13:30-14:00):
  the Groq run met every criterion (10/10 documents, 0 uncaveated numbers, Q9
  answered, 10/10 grounding checks, upload p95 55.1 ms). The 318-344 ms upload
  outlier did not recur, but its cause is still not proven.
