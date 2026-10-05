"""Final acceptance test against a RUNNING Gage server (it does not start one).

    python scripts/acceptance.py --base http://127.0.0.1:8000 \
        --phone 9999999999 --password demo1234 --out test_runs/acceptance.json

Asks the ten questions below through POST /chat, SPACING seconds apart, and
records for each: the retrieved documents and scores, the answer, its caveats,
the fact-check status and the time. Each question is judged against its notes.
`--burst N` then sends N questions at once and reports what happened.
"""
import argparse
import json
import sys
import threading
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# id, question, expected source document(s), extra checks
QUESTIONS = [
    {"id": "Q1", "q": "Nodi anna, sugarcane borer training IISR yavaga nadesidru confirm madi.",
     "doc": ["pests/02_iisr_current_helpline_and_2024_2025_activities.md"],
     "note": "Must not invent a date."},
    {"id": "Q2", "q": "Ratoon crop nalli chlorosis yaake jaasti aaguttade yenu madbeku heli.",
     "doc": ["nutrient_deficiency/01_iron_chlorosis_and_micronutrient_deficiency.md"],
     "must": [["iron", "ಕಬ್ಬಿಣ", "fe"]], "note": "Must say iron."},
    {"id": "Q3", "q": "Prathi irrigation ge eshtu cm neeru hakbeku.",
     "doc": ["irrigation/01_irrigation_water_management.md"],
     "must": [["7", "೭"], ["8", "೮"]], "note": "Must say 7 to 8 cm."},
    {"id": "Q4", "q": "ಪ್ರತಿ irrigation ಗೆ ಎಷ್ಟು cm water ಹಾಕ್ಬೇಕು?",
     "doc": ["irrigation/01_irrigation_water_management.md"], "note": "Irrigation document."},
    {"id": "Q5", "q": "VKSA ಅಂತ ಒಂದು programme ಇದೆ ಅಂತ ಕೇಳಿದ್ದೀನಿ, ನಮ್ಮ ಕರ್ನಾಟಕದಲ್ಲಿ ಬಂತಾ?",
     "doc": ["government_schemes/02_viksit_krishi_sankalp_abhiyan_vksa_2025.md"],
     "must": [["8", "೮"], ["june", "ಜೂನ್"], ["bengaluru", "bangalore", "ಬೆಂಗಳೂರು"]],
     "note": "Must say 8 June 2025 and Bengaluru."},
    {"id": "Q6", "q": "ನಾನು ಯಾವ ಕಬ್ಬಿನ ತಳಿ ಹಾಕೊಬೇಕು ಅಂತ confuse ಆಗಿದೀನಿ, ಸರಿಯಾದ variety ಹೇಗೆ ಆರಿಸ್ಕೊಳಿ ಅಂತ ಹೇಳಿ.",
     "doc": ["sugarcane/01_sugarcane_cultivation_overview_india_and_karnataka.md"],
     "must_not": ["crossbreed", "cross-breed", "germplasm", "ಸಂಕರ", "ಜರ್ಮ್‌ಪ್ಲಾಸಂ"],
     "note": "Must not mention crossbreeding or germplasm."},
    {"id": "Q7", "q": "Sir every time watering how much depth I give, any standard number?",
     "doc": ["irrigation/01_irrigation_water_management.md"], "note": "Irrigation document."},
    {"id": "Q8", "q": "What is the FRP for sugarcane this season and how soon must the mill pay?",
     "doc": ["market/01_sugarcane_fair_and_remunerative_price_frp.md"],
     "must": [["355"], ["14"]], "note": "Must say Rs 355 per quintal for 2025-26 and 14 days."},
    {"id": "Q9", "q": "Why are the leaves of my cane turning yellow?",
     "doc": ["nutrient_deficiency/", "diseases/"], "no_refusal": True,
     "note": "Answered, not refused."},
    {"id": "Q10", "q": "Is my soil too dry right now?", "doc": [], "farm": True,
     "note": "Uses the farm readings; says what is missing if data is thin."},
]

REFUSAL = ("does not cover this", "don't have enough evidence", "do not have enough evidence", "not enough evidence",
           "ಸಾಕಷ್ಟು ಪುರಾವೆ", "ಸಾಕಷ್ಟು ಸಾಕ್ಷ್ಯ", "ಸಾಕಷ್ಟು ಮಾಹಿತಿ ಇಲ್ಲ")
_lock = threading.Lock()


def ask(c: httpx.Client, farm_id: int, q: str) -> dict:
    t = time.perf_counter()
    try:
        r = c.post("/chat", json={"farm_id": farm_id, "question": q}, timeout=180)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"raw": r.text}
        status = r.status_code
        retry_after = r.headers.get("retry-after")
    except Exception as exc:
        body, status, retry_after = {"error": repr(exc)}, None, None
    return {"status": status, "seconds": round(time.perf_counter() - t, 2), "body": body,
            "retry_after": retry_after}


def judge(item: dict, res: dict) -> tuple[bool, list[str]]:
    body = res["body"]
    reasons = []
    if res["status"] != 200:
        return False, [f"HTTP {res['status']}: {str(body)[:200]}"]
    answer = body.get("answer", "")
    low = answer.lower()
    sources = [s["source"] for s in body.get("sources", [])]
    if item["doc"] and not any(any(s.startswith(d) for d in item["doc"]) for s in sources):
        reasons.append(f"expected document not retrieved (got {sources})")
    for alts in item.get("must", []):
        if not any(a.lower() in low for a in alts):
            reasons.append(f"missing one of {alts}")
    for bad in item.get("must_not", []):
        if bad.lower() in low:
            reasons.append(f"mentions '{bad}'")
    if item.get("no_refusal") and any(r in low for r in REFUSAL):
        reasons.append("refused")
    if body.get("unchecked_numbers"):
        reasons.append(f"numbers not in sources and not caveated: {body['unchecked_numbers']}")
    return not reasons, reasons


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--phone", default="9999999999")
    ap.add_argument("--password", default="demo1234")
    ap.add_argument("--spacing", type=float, default=30.0)
    ap.add_argument("--burst", type=int, default=0)
    ap.add_argument("--only", default="", help="comma-separated ids, e.g. Q2,Q9")
    ap.add_argument("--out", default="test_runs/acceptance.json")
    args = ap.parse_args()

    c = httpx.Client(base_url=args.base, timeout=60)
    r = c.post("/auth/login", json={"phone": args.phone, "password": args.password})
    r.raise_for_status()
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    farm_id = c.get("/farms").json()[0]["id"]

    items = [q for q in QUESTIONS if not args.only or q["id"] in args.only.split(",")]
    results = []
    for i, item in enumerate(items):
        if i:
            time.sleep(args.spacing)
        res = ask(c, farm_id, item["q"])
        ok, reasons = judge(item, res)
        b = res["body"]
        row = {"id": item["id"], "question": item["q"], "note": item["note"], "status": res["status"],
               "seconds": res["seconds"], "pass": ok, "reasons": reasons,
               "sources": b.get("sources"), "fact_check": b.get("fact_check"),
               "caveats": b.get("unsupported_claims"), "answer": b.get("answer"),
               "raw_answer": b.get("raw_answer"), "error": None if res["status"] == 200 else b}
        results.append(row)
        top = (b.get("sources") or [{}])[0]
        print(f"{item['id']}: {'PASS' if ok else 'FAIL'} {res['status']} {res['seconds']}s "
              f"fact_check={b.get('fact_check')} top={top.get('source')}@{top.get('score')} "
              f"{'; '.join(reasons)}", flush=True)

    burst = []
    if args.burst:
        time.sleep(args.spacing)
        threads, out = [], [None] * args.burst

        def run(j):
            out[j] = ask(c, farm_id, QUESTIONS[j % len(QUESTIONS)]["q"])

        for j in range(args.burst):
            threads.append(threading.Thread(target=run, args=(j,)))
            threads[-1].start()
        for t in threads:
            t.join()
        for j, res in enumerate(out):
            b = res["body"]
            burst.append({"question": QUESTIONS[j % len(QUESTIONS)]["id"], "status": res["status"],
                          "seconds": res["seconds"], "retry_after": res["retry_after"],
                          "fact_check": b.get("fact_check"), "detail": b.get("detail")})
            print(f"burst {j + 1}: {res['status']} {res['seconds']}s fact_check={b.get('fact_check')} "
                  f"{b.get('detail') or ''}", flush=True)

    passed = sum(r["pass"] for r in results)
    checked = sum(r["fact_check"] == "checked" for r in results)
    summary = {"passed": passed, "total": len(results), "fact_checks_completed": checked}
    print(json.dumps(summary))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"summary": summary, "results": results, "burst": burst},
                                         ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
