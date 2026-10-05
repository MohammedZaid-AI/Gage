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
    for _ in range(40):
        time.sleep(0.5)
        if js("!!document.querySelector('nav') && !document.querySelector('#login:not(.hidden)')"):
            break
    js("go('ask'); true")
    time.sleep(2)
    print("engine options:", js("[...document.querySelectorAll('#ask-engine option')].map(o => o.textContent)"))
    js("""const s = document.querySelector('#ask-engine'); s.value = 'sarvam_finetuned';
          s.dispatchEvent(new Event('change')); true""")
    js("""document.querySelector('#ask-input').value = 'How deep should each irrigation be for sugarcane?';
          document.querySelector('#ask-send').click(); true""")
    tag = ""
    for _ in range(240):
        time.sleep(0.5)
        tag = js("(document.querySelector('.bubble.bot .engine-tag') || {}).textContent || ''") or ""
        if tag:
            break
    time.sleep(1)
    shot = cdp("Page.captureScreenshot", format="png", captureBeyondViewport=True)
    open(OUT, "wb").write(base64.b64decode(shot["data"]))
    print("engine tag on bubble:", tag or "-")
    print("saved choice:", js("JSON.parse(localStorage.getItem('gage_prefs')).engine"))
    print("screenshot:", OUT)
finally:
    proc.terminate()
