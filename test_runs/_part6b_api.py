"""Part 6b: per-request answer engine against a running server (default groq)."""
import json, sys, time, httpx
B, LOG = sys.argv[1], sys.argv[2]
c = httpx.Client(base_url=B, timeout=900)
c.headers["Authorization"] = "Bearer " + c.post("/auth/login", json={"phone": "9999999999", "password": "demo1234"}).json()["access_token"]
q = "How deep should each irrigation be for sugarcane?"
out = []
for label, prov in (("no provider (env default)", None), ("provider=groq", "groq"),
                    ("provider=sarvam_finetuned (1st: loads model)", "sarvam_finetuned"),
                    ("provider=sarvam_finetuned (2nd)", "sarvam_finetuned"), ("provider=bogus", "bogus")):
    body = {"farm_id": 1, "question": q}
    if prov: body["provider"] = prov
    t = time.time(); r = c.post("/chat", json=body); sec = round(time.time() - t, 1)
    d = r.json()
    row = {"case": label, "http": r.status_code, "seconds": sec, "provider": d.get("provider"),
           "answer_seconds": d.get("answer_seconds"), "fact_check": d.get("fact_check"),
           "unsupported": d.get("unsupported_claims"), "answer_start": (d.get("answer") or str(d.get("detail")))[:300]}
    out.append(row); print(json.dumps(row, ensure_ascii=False))
log = open(LOG, encoding="utf-8", errors="replace").read()
print("model loads in log:", log.count("fine-tuned Sarvam-1 loaded"))
json.dump(out, open("test_runs/part6b_api.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
