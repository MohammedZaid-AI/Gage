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
