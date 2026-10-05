"""Offline: embedding-only vs hybrid (embedding + IDF-weighted keyword overlap) retrieval,
on the exact queries the server logged for the ten acceptance questions."""
import json, math, re, sys
sys.path.insert(0, "."); sys.path.insert(0, "scripts")
from collections import Counter
from backend.ai import knowledge as k
import acceptance as A
k.warm_up()
docs = k._index._docs
tok = lambda t: {w[:-1] if w.endswith("s") and len(w) > 4 else w for w in re.findall(r"[a-z]{3,}", t.lower())}
STOP = tok("the and for with how what which why when this that are from your you can per each should does any give much many about into will have has sir please help right best")
df = Counter(w for d in docs for w in tok(d.title + " " + d.text))
idf = {w: math.log(len(docs) / (1 + c)) for w, c in df.items()}
def bonus(queries, d, wt):
    q = set().union(*(tok(x) for x in queries)) - STOP
    q = {w for w in q if w in idf}
    if not q: return 0.0
    dt = tok(d.title + " " + d.text)
    return wt * sum(idf[w] for w in q & dt) / sum(idf[w] for w in q)
traces = {}
for line in open("test_runs/part8_server.log", encoding="utf-8", errors="replace"):
    if "answer trace" in line:
        t = json.loads(line.split("answer trace ", 1)[1]); traces[t["question"]] = t["retrieval_methods"]
import numpy as np
for wt in (0.0, 0.02, 0.03, 0.05):
    ok = 0; rows = []
    for item in A.QUESTIONS:
        qs = list(traces.get(item["q"], {"original": item["q"]}).values())
        best = {}
        for q in qs:
            for h in k._index.search(q, 40, min_score=-1):
                key = (h.source, h.text)
                if h.score >= 0.83 and (key not in best or h.score > best[key][0]): best[key] = (h.score, h)
        ranked = sorted(best.values(), key=lambda x: -(x[0] + bonus(qs, x[1], wt)))[:4]
        srcs = [h.source for _, h in ranked]
        hit = (not item["doc"]) or any(any(s.startswith(d) for d in item["doc"]) for s in srcs)
        ok += hit; rows.append(f"{item['id']}:{'ok' if hit else 'MISS'}:{srcs[0].split('/')[-1][:28] if srcs else '-'}")
    print(f"weight {wt}: expected doc in top 4 for {ok}/10 | " + " ".join(rows))
