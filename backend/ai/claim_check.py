"""Grounding check on a model answer, run before the farmer sees it.

1. A cheap first filter: a regex for invented people ("Dr. X Y", "Minister X Y",
   "X Y, Minister") whose exact name is not in the context.
2. The real check: one extra Groq call that reads the context the answering
   model was given and the answer, lists each factual claim, and marks it
   supported, unsupported or contradicted (strict JSON).

Unsupported or contradicted claims get a short caveat before the answer, naming
them. The check never blocks the answer: if the Groq call fails or times out,
the answer is returned with a one-line note that checking was unavailable.
"""
import logging
import re
import time
from dataclasses import dataclass, field

from backend.config import get_settings

logger = logging.getLogger("gage.claim_check")

_GROUNDING_SYSTEM = (
    "You check an agricultural advisor's ANSWER against the CONTEXT it was given "
    "(reference documents, the farm's own sensor readings and alerts, and the "
    "farmer's question). List every specific factual claim in the ANSWER: numbers "
    "and ranges, quantities and doses, chemicals and nutrients and what they "
    "supply, dates, names and organisations, and agronomic judgements (for example "
    "whether a reading is low, high or optimal, or what causes a symptom). Do not "
    "list greetings, generic advice like 'monitor the field' or 'consult an expert', "
    "or restatements of the farmer's own question.\n"
    "For each claim choose exactly one status:\n"
    "- supported: the CONTEXT states it or it follows directly from the CONTEXT "
    "(a plain unit conversion of a context value counts as supported)\n"
    "- unsupported: the CONTEXT does not say it\n"
    "- contradicted: the CONTEXT says something incompatible\n"
    "The answer may be in Kannada or Kanglish; write each claim in English.\n"
    'Reply with strict JSON only: {"claims": [{"claim": "<short English '
    'paraphrase>", "status": "supported|unsupported|contradicted", "reason": '
    '"<one short sentence citing the context>"}]}'
)

_CAVEAT = {
    "en": "Please double-check before acting: {items}.",
    "kn": "ದಯವಿಟ್ಟು ಮುಂದುವರಿಯುವ ಮೊದಲು ಪರಿಶೀಲಿಸಿ: {items}.",
}
_LABEL = {
    "en": {"unsupported": "not in Gage's sources", "contradicted": "contradicts Gage's sources",
           "name": "this person is not in Gage's sources"},
    "kn": {"unsupported": "Gage ಮಾಹಿತಿ ದಾಖಲೆಗಳಲ್ಲಿ ಇಲ್ಲ", "contradicted": "Gage ಮಾಹಿತಿ ದಾಖಲೆಗಳಿಗೆ ವಿರುದ್ಧವಾಗಿದೆ",
           "name": "ಈ ವ್ಯಕ್ತಿಯ ಹೆಸರು Gage ಮಾಹಿತಿ ದಾಖಲೆಗಳಲ್ಲಿ ಇಲ್ಲ"},
}
_UNAVAILABLE = {
    "en": "(Automatic fact-checking was unavailable for this answer.)",
    "kn": "(ಈ ಉತ್ತರದ ಸ್ವಯಂಚಾಲಿತ ಪರಿಶೀಲನೆ ಈಗ ಲಭ್ಯವಿಲ್ಲ.)",
}
_MAX_CAVEAT_ITEMS = 3


@dataclass(frozen=True)
class CheckResult:
    answer: str              # what the farmer receives (caveated / noted if needed)
    unsupported: list[str]   # claims flagged, e.g. "unsupported: X", "name: Y"
    checked: list[str]       # every claim examined, with its status
    status: str = "checked"  # checked | unavailable
    seconds: float = 0.0     # time spent in the grounding call
    claims: list[dict] = field(default_factory=list)  # raw grounding verdicts


_CAP = r"[A-Z][a-z]+(?:-[A-Z][a-z]+)?"
_TITLE = (r"(?:Dr|Prof|Mr|Mrs|Ms|Smt|Shri|Sri|Shrimati)\.?"
          r"|(?:(?:Hon'?ble|Honourable)\s+)?(?:(?:Union|State|Chief|Deputy|Agriculture|Cabinet)\s+)*"
          r"(?:Minister|Secretary|Commissioner|Director|Governor|Collector)(?:\s+of\s+" + _CAP + r")?")
# "Dr. Raghupathy Srinivasan", "Union Agriculture Minister Shivraj Singh Chouhan"
_TITLED_NAME = re.compile(rf"\b(?:{_TITLE})\s+((?:{_CAP})(?:\s+{_CAP}){{0,3}})")
# "Shivraj Singh Chouhan, Union Agriculture Minister"
_NAME_THEN_ROLE = re.compile(
    rf"\b({_CAP}(?:\s+{_CAP}){{1,3}}),?\s+(?:the\s+)?(?:(?:Union|State|Chief|Deputy|Agriculture|Cabinet)\s+)*"
    r"(?:Minister|Secretary|Commissioner|Director|Governor|Collector)\b")
_NOT_NAMES = {"Observation", "Analysis", "Confidence", "Recommendations", "Immediate", "Monitoring",
              "Agriculture", "Farmers", "Welfare", "India", "Karnataka", "Government", "Department",
              # role / honorific words are not part of a person's name
              "Union", "State", "Chief", "Deputy", "Cabinet", "Minister", "Shri", "Sri", "Smt",
              "Shrimati", "Dr", "Prof", "Mr", "Mrs", "Ms", "Hon'ble", "Honourable"}


def _names(text: str) -> set[str]:
    """Person names introduced with a title or role (a basic pattern check, not NER).
    Covers Latin-script names only."""
    found = set()
    for m in list(_TITLED_NAME.finditer(text)) + list(_NAME_THEN_ROLE.finditer(text)):
        words = [w for w in m.group(1).split() if w not in _NOT_NAMES]
        if words:
            found.add(" ".join(words))
    return found




def _grounding(answer: str, context: str) -> list[dict]:
    """The second Groq call. Raises groq_client.GroqUnavailable on any failure."""
    from backend.ai import groq_client

    s = get_settings()
    data = groq_client.chat_json(
        _GROUNDING_SYSTEM, f"CONTEXT:\n{context}\n\nANSWER:\n{answer}",
        timeout=s.grounding_timeout_s, max_tokens=4000,
    )
    claims = data.get("claims")
    if not isinstance(claims, list):
        raise groq_client.GroqUnavailable("JSON has no 'claims' list")
    out = []
    for c in claims:
        if isinstance(c, dict) and c.get("status") in ("supported", "unsupported", "contradicted"):
            out.append({"claim": str(c.get("claim", "")).strip(), "status": c["status"],
                        "reason": str(c.get("reason", "")).strip()})
    return out


def check(answer: str, context: str, language: str = "en") -> CheckResult:
    """Check `answer` against the `context` the model was given; caveat or note it."""
    lang = "kn" if language == "kn" else "en"
    labels = _LABEL[lang]

    # 1. cheap first filter: invented people
    ctx_lower = context.lower()
    invented = [n for n in sorted(_names(answer)) if n.lower() not in ctx_lower]
    flagged = [f"name: {n}" for n in invented]
    caveat_items = [f'"{n}" ({labels["name"]})' for n in invented]

    # 2. grounding call; never blocks the answer
    t0 = time.perf_counter()
    try:
        claims = _grounding(answer, context)
        status = "checked"
    except Exception as exc:
        logger.warning("grounding check unavailable: %s", exc)
        claims, status = [], "unavailable"
    seconds = round(time.perf_counter() - t0, 2)

    for c in claims:
        if c["status"] != "supported":
            flagged.append(f'{c["status"]}: {c["claim"]}')
            caveat_items.append(f'"{c["claim"]}" ({labels[c["status"]]})')

    final = answer
    if caveat_items:
        shown = caveat_items[:_MAX_CAVEAT_ITEMS]
        if len(caveat_items) > len(shown):
            shown.append(f"+{len(caveat_items) - len(shown)}")
        final = _CAVEAT[lang].format(items="; ".join(shown)) + "\n\n" + final
    if status == "unavailable":
        final = f"{final}\n\n{_UNAVAILABLE[lang]}"
    logger.info("grounding %s in %.2fs: %d claims, %d flagged", status, seconds,
                len(claims), len(flagged))
    return CheckResult(final, flagged, [f'{c["status"]}: {c["claim"]}' for c in claims],
                       status, seconds, claims)
