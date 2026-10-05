"""Part 6.3: log in through the dashboard's real login form in headless Chrome,
check the Home screen shows the FlyBrain card, and save a screenshot.
usage: _part6_screenshot.py <base> <phone> <out.png>   (password: env GAGE_DEMO_PASSWORD)"""
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

from websockets.sync.client import connect

BASE, PHONE, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
PASSWORD = os.environ["GAGE_DEMO_PASSWORD"]
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT = 9333
profile = tempfile.mkdtemp(prefix="gage_chrome_")
proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={PORT}",
                         f"--user-data-dir={profile}", "--window-size=430,2400", "about:blank"])
try:
    for _ in range(50):
        try:
            pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
            ws_url = next(p["webSocketDebuggerUrl"] for p in pages if p["type"] == "page")
            break
        except Exception:
            time.sleep(0.3)
    ws = connect(ws_url, max_size=50_000_000)
    n = [0]

    def cdp(method, **params):
        n[0] += 1
        ws.send(json.dumps({"id": n[0], "method": method, "params": params}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == n[0]:
                return msg.get("result", {})

    def js(expr):
        return cdp("Runtime.evaluate", expression=expr, awaitPromise=True,
                   returnByValue=True).get("result", {}).get("value")

    cdp("Page.enable")
    cdp("Page.navigate", url=BASE + "/")
    time.sleep(4)
    js(f"""document.querySelector('#lg-phone').value = {json.dumps(PHONE)};
           document.querySelector('#lg-pass').value = {json.dumps(PASSWORD)};
           document.querySelector('#lg-submit').click(); true""")
    text = ""
    for _ in range(40):
        time.sleep(0.5)
        text = js("document.body.innerText") or ""
        if "sensor pattern check" in text.lower():
            break
    time.sleep(1)
    shot = cdp("Page.captureScreenshot", format="png", captureBeyondViewport=True)
    open(OUT, "wb").write(base64.b64decode(shot["data"]))
    start = text.lower().find("sensor pattern check")
    print("logged in:", "Invalid phone or password" not in text and "Enter my farm" not in text[:400])
    print("FlyBrain card shown:", start >= 0)
    print("card text:", text[start:start + 300].replace("\n", " | ") if start >= 0 else "-")
    print("login message:", js("document.querySelector('#lg-msg') && document.querySelector('#lg-msg').textContent"))
    print("screenshot:", OUT)
finally:
    proc.terminate()
