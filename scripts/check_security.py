"""Security regression checks, run against real processes (not by reading code).

1. The server refuses to start with a missing/default/short JWT_SECRET.
2. A second farmer cannot see the first farmer's dataset export history.
3. /api/state, /ws and uploaded photos reject requests without a valid token.

    python scripts/check_security.py --base http://127.0.0.1:8000

Check 1 starts its own short-lived uvicorn processes; 2 and 3 need a running
server with the demo farmer seeded and at least one stored photo.
"""
import asyncio
import os
import subprocess
import sys

import httpx
import websockets

B = sys.argv[sys.argv.index("--base") + 1] if "--base" in sys.argv else "http://127.0.0.1:8000"

print("== 1. startup refuses forgeable JWT secrets")
for secret in ("dev-insecure-change-me", "", "short"):
    env = {**os.environ, "JWT_SECRET": secret}
    p = subprocess.run([sys.executable, "-c", "import backend.main"], env=env,
                       capture_output=True, text=True, timeout=300)
    refused = p.returncode != 0 and "JWT_SECRET" in p.stderr
    print(f"  JWT_SECRET={secret!r}: exit {p.returncode} -> {'REFUSED (ok)' if refused else 'STARTED (BAD)'}")
WS = B.replace("http", "ws")
c = httpx.Client(base_url=B, timeout=60)


def login(phone, pw):
    return c.post("/auth/login", json={"phone": phone, "password": pw}).json()["access_token"]


A = login("9999999999", "demo1234")
r = c.post("/auth/register", json={"phone": "8888800002", "password": "farmerB-pass"})
Bt = r.json()["access_token"] if r.status_code == 201 else login("8888800002", "farmerB-pass")
hA, hB = {"Authorization": f"Bearer {A}"}, {"Authorization": f"Bearer {Bt}"}
c.post("/farms", headers=hB, json={"name": "Farm B"})

print("== 2. export history isolation")
ex = c.post("/dataset/export", headers=hA, json={"fmt": "jsonl", "min_quality": 999}).json()
histA = [e["version"] for e in c.get("/dataset/stats", headers=hA).json()["export_history"]]
histB = [e["version"] for e in c.get("/dataset/stats", headers=hB).json()["export_history"]]
print("  farmer A export", ex["dataset_version"], "| A sees it:", ex["dataset_version"] in histA,
      "| B sees it:", ex["dataset_version"] in histB, "| B's history:", histB)
os.remove(ex["path"])

print("== 3. previously open endpoints without a valid token")
print("  /api/state  no token:", c.get("/api/state").status_code,
      "| bad token:", c.get("/api/state", headers={"Authorization": "Bearer junk"}).status_code,
      "| valid:", c.get("/api/state", headers=hA).status_code)
fn = next(o["image_path"].split("/")[-1] for o in c.get("/farm/1/timeline?limit=300", headers=hA).json()
          if o["image_path"])
u = f"/storage/images/{fn}"
print(f"  {u}  no token:", c.get(u).status_code, "| bad token:",
      c.get(u, headers={"Authorization": "Bearer junk"}).status_code,
      "| owner:", c.get(u, headers=hA).status_code, "| other farmer:", c.get(u, headers=hB).status_code)


async def ws(q):
    try:
        async with websockets.connect(f"{WS}/ws{q}", open_timeout=10):
            return "CONNECTED"
    except Exception as e:
        return f"refused ({str(e)[:55]})"

print("  /ws  no token:", asyncio.run(ws("")), "| bad token:", asyncio.run(ws("?token=junk")),
      "| valid:", asyncio.run(ws("?token=" + A)))
