"""Shared helper for Part 1 measurements: log every HTTP call to api.groq.com
(model, max tokens asked, usage, rate-limit headers, and the full body of any
error) by wrapping httpx.Client.send. Import before the app modules."""
import json
import time

import httpx

CALLS: list[dict] = []
_orig_send = httpx.Client.send


def _purpose(body) -> str:
    first = (body.get("messages") or [{}])[0].get("content") or ""
    for key, name in (("search query", "rewrite"), ("You check an agricultural", "fact_check"),
                      ("status line", "summary"), ("You are Gage", "answer")):
        if key in first:
            return name
    return "other"


def _send(self, request, *args, **kwargs):
    if "api.groq.com" not in str(request.url) or not request.url.path.endswith("/chat/completions"):
        return _orig_send(self, request, *args, **kwargs)
    body = json.loads(request.content or b"{}")
    t0 = time.perf_counter()
    resp = _orig_send(self, request, *args, **kwargs)
    resp.read()
    rec = {
        "t": round(time.time(), 2),
        "model": body.get("model"),
        "max_completion_tokens": body.get("max_completion_tokens") or body.get("max_tokens"),
        "prompt_chars": sum(len(m.get("content") or "") for m in body.get("messages", [])),
        "purpose": _purpose(body),
        "status": resp.status_code,
        "seconds": round(time.perf_counter() - t0, 2),
        "headers": {k: v for k, v in resp.headers.items()
                    if k.startswith("x-ratelimit") or k in ("retry-after", "x-groq-region")},
    }
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text[:2000]}
    if resp.status_code == 200:
        u = data.get("usage") or {}
        rec["prompt_tokens"] = u.get("prompt_tokens")
        rec["completion_tokens"] = u.get("completion_tokens")
        rec["reasoning_tokens"] = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
    else:
        rec["error_body"] = data
    CALLS.append(rec)
    return resp


httpx.Client.send = _send
