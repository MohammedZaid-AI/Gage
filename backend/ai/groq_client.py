"""Every Groq call goes through `call()` here: the answer and summary (via the
Groq provider) and the small helpers (query rewrite, grounding check).

It keeps a per-model token budget, because this account's limit is per model
and per minute (8000 tokens/min on the free tier) and Groq counts a request's
prompt plus its max_tokens when the request starts. Calls have a priority:

    answer (always sent) > fact check > rewrite > summary

An optional call is skipped (GroqSkipped) when the model's budget for the
current 60 s window is too low to leave room for higher-priority work. The
budget is the tighter of two estimates: our own sliding 60 s window of tokens
charged, and Groq's last x-ratelimit-remaining-tokens header, refilled at the
rate Groq reports.

Every function raises GroqUnavailable (or a subclass) on any failure, so
callers can fall back instead of failing the request.
"""
import json
import logging
import re
import threading
import time
from collections import deque
from dataclasses import dataclass

from openai import OpenAI

from backend.config import get_settings

logger = logging.getLogger("gage.ai.groq_client")


class GroqUnavailable(RuntimeError):
    """No key, timeout, network/API error, or an unusable response."""


class GroqRateLimited(GroqUnavailable):
    """Groq answered 429. `retry_after` is Groq's own wait time in seconds."""

    def __init__(self, message: str, retry_after: float, limit: str):
        super().__init__(message)
        self.retry_after = retry_after
        self.limit = limit          # e.g. "tokens per minute (TPM)"


class GroqSkipped(GroqUnavailable):
    """Not sent: the token budget is needed for higher-priority calls."""


# Lower number = more important. Only "answer" is never skipped.
PRIORITY = {"answer": 0, "fact_check": 1, "rewrite": 2, "summary": 3}
# Share of the per-minute limit an optional call must leave free after itself,
# so that the calls above it in PRIORITY still fit.
_RESERVE = {"fact_check": 0.0, "rewrite": 0.30, "summary": 0.50}
_WINDOW_S = 60.0


def estimate_tokens(text: str) -> int:
    """Rough token count. Kannada script is about one token per character
    (three UTF-8 bytes); English is about four characters per token."""
    return int(len(text.encode("utf-8")) / 3.5) + 1


@dataclass
class _Header:
    at: float
    remaining: int
    limit: int
    reset_s: float


class TokenBudget:
    """Per-model token accounting over a sliding 60 s window."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._spent: dict[str, deque] = {}      # model -> deque[(time, tokens)]
        self._header: dict[str, _Header] = {}

    def _limit(self, model: str) -> int:
        h = self._header.get(model)
        return h.limit if h else get_settings().groq_tokens_per_minute

    def available(self, model: str, now: float | None = None) -> int:
        now = time.monotonic() if now is None else now
        with self._lock:
            events = self._spent.setdefault(model, deque())
            while events and now - events[0][0] > _WINDOW_S:
                events.popleft()
            limit = self._limit(model)
            window_left = limit - sum(t for _, t in events)
            h = self._header.get(model)
            if h is None:
                return window_left
            # Groq refills linearly to the full limit over reset_s seconds.
            refill = (limit - h.remaining) * min(1.0, (now - h.at) / h.reset_s) if h.reset_s > 0 else limit
            since = sum(t for at, t in events if at > h.at)
            return min(window_left, int(min(limit, h.remaining + refill) - since))

    def allow(self, purpose: str, model: str, estimate: int) -> tuple[bool, int]:
        """Whether an optional call may go now, and the tokens available."""
        avail = self.available(model)
        if purpose == "answer":
            return True, avail
        reserve = int(_RESERVE.get(purpose, 0.5) * self._limit(model))
        return avail - estimate >= reserve, avail

    def charge(self, model: str, tokens: int) -> None:
        with self._lock:
            self._spent.setdefault(model, deque()).append((time.monotonic(), max(0, tokens)))

    def observe(self, model: str, headers) -> None:
        """Record Groq's own view of the bucket from a response's headers."""
        try:
            remaining = int(headers["x-ratelimit-remaining-tokens"])
            limit = int(headers["x-ratelimit-limit-tokens"])
        except (KeyError, TypeError, ValueError):
            return
        with self._lock:
            self._header[model] = _Header(time.monotonic(), remaining, limit,
                                          _seconds(headers.get("x-ratelimit-reset-tokens")))

    def reset(self) -> None:
        with self._lock:
            self._spent.clear()
            self._header.clear()


budget = TokenBudget()


def _seconds(value: str | None) -> float:
    """Groq durations: '12.3s', '1m4.5s', '450ms' -> seconds (0.0 if absent)."""
    if not value:
        return 0.0
    total = 0.0
    for num, unit in re.findall(r"([\d.]+)(ms|h|m|s)", value):
        total += float(num) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    return total


@dataclass
class CallLog:
    purpose: str
    model: str
    prompt_tokens: int | None
    completion_tokens: int | None
    seconds: float
    status: str          # ok | skipped | rate_limited | error
    seq: int = 0


# The last few calls, newest last (for traces and tests). With concurrent
# requests, calls_since() can include another request's calls.
recent_calls: deque = deque(maxlen=200)
_seq = 0
_seq_lock = threading.Lock()


def _log(entry: CallLog) -> None:
    global _seq
    with _seq_lock:
        _seq += 1
        entry.seq = _seq
        recent_calls.append(entry)


def last_seq() -> int:
    return _seq


def calls_since(seq: int) -> list[dict]:
    return [vars(c) for c in list(recent_calls) if c.seq > seq]
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    s = get_settings()
    if not s.groq_api_key:
        raise GroqUnavailable("GROQ_API_KEY is not set")
    if _client is None:
        # No SDK retries: retries are decided here (see the provider's answer()),
        # never silently, and a retry would only add latency to optional helpers.
        _client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=s.groq_api_key,
                         max_retries=0)
    return _client


def call(purpose: str, messages: list[dict], *, model: str, timeout: float,
         max_tokens: int | None = None, json_mode: bool = False,
         reasoning_effort: str | None = None) -> str:
    """One chat completion under the token budget. Raises GroqSkipped (budget),
    GroqRateLimited (429) or GroqUnavailable (anything else)."""
    estimate = sum(estimate_tokens(m["content"]) for m in messages) + (max_tokens or 0)
    ok, avail = budget.allow(purpose, model, estimate)
    if not ok:
        _log(CallLog(purpose, model, None, None, 0.0, "skipped"))
        logger.info("groq %s skipped: needs ~%d tokens, %d left this minute on %s",
                    purpose, estimate, avail, model)
        raise GroqSkipped(f"token budget: ~{estimate} needed, {avail} left on {model}")

    kwargs: dict = {}
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if max_tokens:
        kwargs["max_completion_tokens"] = max_tokens
    if reasoning_effort:
        kwargs["reasoning_effort"] = reasoning_effort
    t0 = time.perf_counter()
    budget.charge(model, estimate)   # Groq reserves prompt + max_tokens up front
    try:
        raw = _get_client().chat.completions.with_raw_response.create(
            model=model, messages=messages, temperature=0, timeout=timeout, **kwargs)
    except GroqUnavailable:
        raise
    except Exception as exc:
        seconds = round(time.perf_counter() - t0, 2)
        response = getattr(exc, "response", None)
        if response is not None:
            budget.observe(model, response.headers)
        if getattr(exc, "status_code", None) == 429 and response is not None:
            body = _body(response)
            retry = _retry_after(response.headers, body)
            limit = _limit_name(body)
            logger.warning("groq %s rate-limited on %s (%s), retry after %.1fs. headers=%s body=%s",
                           purpose, model, limit, retry, _rl_headers(response.headers), body)
            _log(CallLog(purpose, model, None, None, seconds, "rate_limited"))
            raise GroqRateLimited(f"Groq rate limit ({limit}) on {model}; retry in {retry:.0f}s",
                                  retry, limit) from exc
        _log(CallLog(purpose, model, None, None, seconds, "error"))
        raise GroqUnavailable(f"{type(exc).__name__}: {str(exc)[:160]}") from exc

    budget.observe(model, raw.headers)
    resp = raw.parse()
    usage = resp.usage
    p_tok = getattr(usage, "prompt_tokens", None)
    c_tok = getattr(usage, "completion_tokens", None)
    if p_tok is not None and c_tok is not None:
        # Generated tokens beyond the up-front estimate also count.
        extra = p_tok + c_tok - estimate
        if extra > 0:
            budget.charge(model, extra)
    seconds = round(time.perf_counter() - t0, 2)
    _log(CallLog(purpose, model, p_tok, c_tok, seconds, "ok"))
    logger.info("groq %s on %s: %s prompt + %s completion tokens in %.2fs (%s left)", purpose,
                model, p_tok, c_tok, seconds, raw.headers.get("x-ratelimit-remaining-tokens"))
    text = (resp.choices[0].message.content or "").strip() if resp.choices else ""
    if not text:
        raise GroqUnavailable("empty response")
    return text


def _body(response) -> dict:
    try:
        return response.json()
    except Exception:
        return {"raw": (response.text or "")[:500]}


def _rl_headers(headers) -> dict:
    return {k: v for k, v in headers.items() if k.startswith("x-ratelimit") or k == "retry-after"}


def _retry_after(headers, body: dict) -> float:
    """Groq's wait time: the message ('try again in 34.85s') is the most precise,
    then the retry-after header, then the token reset header."""
    msg = str((body.get("error") or {}).get("message", ""))
    m = re.search(r"try again in ([\dhms.]+)", msg)
    if m and _seconds(m.group(1)) > 0:
        return _seconds(m.group(1))
    try:
        return float(headers.get("retry-after"))
    except (TypeError, ValueError):
        return _seconds(headers.get("x-ratelimit-reset-tokens")) or 60.0


def _limit_name(body: dict) -> str:
    msg = str((body.get("error") or {}).get("message", ""))
    m = re.search(r"on (tokens|requests) per (minute|day) \((\w+)\)", msg)
    return m.group(0)[3:] if m else "unknown limit"


def chat(system: str, user: str, *, purpose: str, timeout: float, max_tokens: int,
         json_mode: bool = False) -> str:
    """One short helper completion on GROQ_HELPER_MODEL. Raises GroqUnavailable."""
    return call(purpose, [{"role": "system", "content": system}, {"role": "user", "content": user}],
                model=get_settings().groq_helper_model, timeout=timeout, max_tokens=max_tokens,
                json_mode=json_mode, reasoning_effort="low")


_REWRITE_SYSTEM = (
    "You turn a sugarcane farmer's question into a short English search query for "
    "an agricultural knowledge base. The question may be in English, Kannada script, "
    "or Kannada written in Latin letters (Kanglish); words like anna, sir, nodi, heli, "
    "madi, yaake, yavaga, eshtu are conversational Kannada, not crop terms. Keep "
    "domain terms (crop stage, pest, disease, nutrient, organisation names such as "
    "IISR or ICAR, units). Reply with only the query, at most 15 words, no quotes."
)


def rewrite_query(question: str) -> str:
    """Clean English search query for `question`. Raises GroqUnavailable."""
    s = get_settings()
    q = chat(_REWRITE_SYSTEM, question, purpose="rewrite", timeout=s.groq_helper_timeout_s,
             max_tokens=s.groq_rewrite_max_tokens).splitlines()[0].strip().strip('"')
    if not q:
        raise GroqUnavailable("empty rewrite")
    return q


def chat_json(system: str, user: str, *, purpose: str, timeout: float, max_tokens: int) -> dict:
    """A helper completion that must be a JSON object. Raises GroqUnavailable."""
    text = chat(system, user, purpose=purpose, timeout=timeout, max_tokens=max_tokens,
                json_mode=True)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GroqUnavailable(f"invalid JSON: {text[:120]}") from exc
    if not isinstance(data, dict):
        raise GroqUnavailable("JSON is not an object")
    return data
