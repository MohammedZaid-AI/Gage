"""Part 3: run the local checks over real Groq answers saved in Part 2 (no network)."""
import json, os, sys
sys.path.insert(0, ".")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.abspath("test_runs/_p2c_server.db").replace(os.sep, "/")
from backend.ai import knowledge, claim_check, prompt_builder
from backend.database import SessionLocal
from backend.models import Farm
from backend.services import farm_context
knowledge.warm_up()
chunks = knowledge._index._docs
with SessionLocal() as s:
    ctx = farm_context.build(s, s.get(Farm, 1))
out = []
for f in ("test_runs/part2_questions_run1.json", "test_runs/part2_questions.json"):
    for r in json.load(open(f, encoding="utf-8"))["results"]:
        if not r.get("raw_answer"):
            continue
        titles = {(x["source"], x["section"]) for x in r["sources"]}
        docs = [d for d in chunks if (d.source, d.title) in titles]
        sources, readings, kb = prompt_builder.check_sources(ctx, docs, r["question"])
        found = claim_check.local_findings(r["raw_answer"], sources, readings, kb)
        out.append({"run": f, "id": r["id"], "findings": found})
        print(f.split("/")[-1], r["id"], found)
json.dump(out, open("test_runs/part3_replay.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
