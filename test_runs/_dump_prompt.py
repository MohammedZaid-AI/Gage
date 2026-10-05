import os, sys
sys.path.insert(0, ".")
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.abspath("test_runs/_before.db").replace("\\", "/")
from backend.database import SessionLocal
from backend.models import Farm
from backend.services import farm_context
from backend.ai import prompt_builder, knowledge
q = sys.argv[1] if len(sys.argv) > 1 else "Prathi irrigation ge eshtu cm neeru hakbeku"
with SessionLocal() as s:
    ctx = farm_context.build(s, s.get(Farm, 1))
    docs = knowledge._index.search("irrigation depth per irrigation cm", 3)
    p = prompt_builder.build(ctx, docs, q)
    print(p)
    print("\n=== chars", len(p), "| conversation turns", len(ctx.conversation))
