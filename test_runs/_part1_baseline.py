"""Part 1.2: every Groq call made for one normal answer and one summary (current code)."""
import json, os, shutil, sys, time
sys.path.insert(0, "."); sys.path.insert(0, "test_runs")
tag = sys.argv[1] if len(sys.argv) > 1 else "before"
db = os.path.abspath(f"test_runs/_{tag}.db")
shutil.copy2("storage/observations.db", db)
os.environ["DATABASE_URL"] = "sqlite:///" + db.replace("\\", "/")
os.environ["LLM_PROVIDER"] = "groq"
import truststore; truststore.inject_into_ssl()
import _groq_trace as tr
from backend.database import SessionLocal, init_db
from backend.models import Farm
from backend.ai.orchestrator import AIOrchestrator
from backend.ai import summarize_observation, claim_check
from backend.ai import knowledge
init_db(); knowledge.warm_up()
q = sys.argv[2] if len(sys.argv) > 2 else "Prathi irrigation ge eshtu cm neeru hakbeku"
out = {"question": q}
with SessionLocal() as s:
    farm = s.get(Farm, 1)
    t = time.perf_counter()
    r = AIOrchestrator.answer(s, farm, q)
    out["answer_seconds"] = round(time.perf_counter() - t, 2)
    out["answer_prompt_chars"] = len(r.context)
    out["final_answer"] = r.answer
    ctx = "Farm: demo. Latest reading: temperature 27.1 C, humidity 70 %, soil moisture 0 %. Open alerts: none."
    try:
        txt = summarize_observation(ctx, "en"); claim_check.check(txt, ctx, "en"); out["summary"] = txt
    except Exception as e:
        out["summary_error"] = repr(e)
out["groq_calls"] = tr.CALLS
json.dump(out, open(f"test_runs/part1_calls_{tag}.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
for c in tr.CALLS:
    print(c["purpose"], c["model"], c["status"], "prompt", c.get("prompt_tokens"), "completion", c.get("completion_tokens"),
          "(reasoning", c.get("reasoning_tokens"), ") max", c["max_completion_tokens"], "remaining", c["headers"].get("x-ratelimit-remaining-tokens"))
print("answer took", out["answer_seconds"], "s; prompt chars", out["answer_prompt_chars"])
