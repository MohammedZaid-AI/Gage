"""Part 1.4: list Groq models on this account and read each candidate's rate limits."""
import json, sys
sys.path.insert(0, ".")
import truststore; truststore.inject_into_ssl()
from openai import OpenAI
from backend.config import get_settings
c = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=get_settings().groq_api_key, max_retries=0)
models = sorted(m.id for m in c.models.list().data)
print("MODELS:", json.dumps(models, indent=1))
for m in ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b"]:
    try:
        r = c.chat.completions.with_raw_response.create(model=m, messages=[{"role": "user", "content": "Reply with the JSON object {\"ok\": true}"}],
                                                       max_completion_tokens=300, **({"reasoning_effort": "low"} if "gpt-oss" in m else {}), response_format={"type": "json_object"})
        h = r.headers; body = r.parse()
        print(m, "| limit-tokens", h.get("x-ratelimit-limit-tokens"), "remaining", h.get("x-ratelimit-remaining-tokens"),
              "| limit-requests", h.get("x-ratelimit-limit-requests"), "remaining", h.get("x-ratelimit-remaining-requests"),
              "| reply", repr(body.choices[0].message.content)[:40])
    except Exception as e:
        print(m, "ERROR", type(e).__name__, str(e)[:200])
