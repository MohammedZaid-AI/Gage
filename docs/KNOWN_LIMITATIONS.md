# Known limitations

What Gage does not do well yet, stated plainly. Evidence files are in
`test_runs/`; open work is in [OPEN_ITEMS.md](OPEN_ITEMS.md).

## The fine-tuned model is not the live answerer

- The LoRA adapter on Sarvam-1 (`models/sarvam_agri_final`) was trained for
  4 epochs. It runs on the local GPU (RTX 3050, 4-bit) at about 0.15 seconds
  per token.
- In the verification runs it answered only 2 of 5 test questions correctly
  and ignored the retrieved text on others.
- On the ten acceptance questions (5 October 2026, test_runs/part8_finetuned.*)
  it got 5 of 10 key facts against Groq's 9 of 10, at 18.5 s per answer: it often
  does not use the retrieved text (for example "use general guidelines" instead
  of 7-8 cm, an invented "Rs 2,800 per quintal").
- So Groq (`openai/gpt-oss-120b`) is the default answerer. The fine-tuned model
  can be chosen per question (`"provider": "sarvam_finetuned"` or the Answer
  engine dropdown); it is loaded on first use and needs the GPU.
- The validation set of that training run may contain copies of training
  records, so its reported validation loss is optimistic.

## FlyBrain

- FlyBrain runs on the graph named by `GET /farm/{id}/anomaly` and on the
  dashboard. By default that is a **synthetic test graph**, not the real fly
  connectome.
- The real MaleCNS v1.0 graph can be built and run (166,700 neurons, 25.6 M
  connections; 4.3 s per reading on the GPU, 10.4 s on the CPU). On this farm's
  data it missed the abnormal test reading that the synthetic graph flags, so it
  is not switched on (test_runs/part5_*).
- On injected anomalies FlyBrain beat IsolationForest and a z-score baseline
  (AUROC 0.995-0.998), but the anomalies were synthetic, the data is one farm,
  and the 1 % false-alarm threshold rests on 125 normal readings
  (test_runs/part4_eval*).
- Mapping soil moisture, temperature and humidity onto fly neurons is a design
  choice, not a biologically validated encoding. A score is a statistical flag
  relative to this farm's own history, not a diagnosis.

## Sensor history has gaps

- 366 of 549 readings on the demo farm have soil moisture exactly 0 in long
  runs: the probe was almost certainly disconnected. FlyBrain leaves those rows
  out (183 clean rows remain) and does not score a soil-0 reading.
- The soil alert rule still fires on a 0 reading ("Low soil moisture 0%"); the
  alert rules were not changed.
- The node was also offline for long stretches, so recent readings can be days old.

## Fact checking under rate limits

- The Groq account allows 8,000 tokens per minute per model. The Groq grounding
  check is skipped when the token budget is nearly used (for example, three
  questions at once). Then only the local number and name checks run, and the
  answer says so.
- The local checks only catch numbers with units, named inputs, judgements on
  readings and titled person names. Other kinds of invented claims are caught
  only by the Groq check.
- The Groq check sometimes lists generic advice (for example "observe the
  crop") as "not in Gage's sources", so caveats can be longer than needed.

## Answers and retrieval

- Retrieval of mixed Kannada/English questions depends on the Groq rewrite,
  which is not word-for-word repeatable; the chosen document can change between
  runs (Q6 in test_runs/part2_questions*).
- "This season" depends on today's date, which is in the prompt; the FRP for
  2025-26 (₹355) and 2026-27 (₹365) are both in the knowledge base.
- Spoken answers can be long (one Kannada answer was 2.8 minutes of audio).
- Gage needs internet for answers (Groq) and voice (Sarvam). There is no
  offline answerer.
- Gage does not analyse photos.
