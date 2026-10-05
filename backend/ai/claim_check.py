"""Grounding checks on a model answer, run before the farmer sees it.

Local checks, always run (no network; ai/number_check.py and below):
1. Numbers with units not found in the sources (retrieved text, question, farm
   readings), after unit normalisation (70 mm == 7 cm).
2. Inputs (gypsum, urea, ...) the sources never name.
3. Farm readings called low/high/optimal without a range in the text.
4. Invented people ("Dr. X Y", "Minister X Y", "X Y, Minister") whose exact name
   is not in the context.
Groq check, when the token budget allows: one call that lists each factual
claim and marks it supported, unsupported or contradicted (strict JSON).

All findings are merged into one short caveat before the answer, naming them.
The checks never block the answer: if the Groq call is skipped, fails or times
out, the answer gets a one-line note that only the local checks ran.
"""
import logging
import re
import time
from dataclasses import dataclass, field

from backend.ai import number_check
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
    "restatements of the farmer's own question, or statements that some information "
    "is missing, not covered or should be confirmed.\n"
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
           "name": "this person is not in Gage's sources",
           "number": "this number is not in Gage's sources",
           "input": "Gage's sources do not mention this input",
           "judgement": "Gage's sources give no range to judge this reading by"},
    "kn": {"unsupported": "Gage ಮಾಹಿತಿ ದಾಖಲೆಗಳಲ್ಲಿ ಇಲ್ಲ", "contradicted": "Gage ಮಾಹಿತಿ ದಾಖಲೆಗಳಿಗೆ ವಿರುದ್ಧವಾಗಿದೆ",
           "name": "ಈ ವ್ಯಕ್ತಿಯ ಹೆಸರು Gage ಮಾಹಿತಿ ದಾಖಲೆಗಳಲ್ಲಿ ಇಲ್ಲ",
           "number": "ಈ ಸಂಖ್ಯೆ Gage ಮಾಹಿತಿ ದಾಖಲೆಗಳಲ್ಲಿ ಇಲ್ಲ",
           "input": "ಈ ಒಳಸುರಿಯನ್ನು Gage ಮಾಹಿತಿ ದಾಖಲೆಗಳು ಹೇಳುವುದಿಲ್ಲ",
           "judgement": "ಈ ಓದುವಿಕೆಯನ್ನು ನಿರ್ಣಯಿಸಲು Gage ದಾಖಲೆಗಳಲ್ಲಿ ಮಿತಿ ಇಲ್ಲ"},
}
_UNAVAILABLE = {
    "en": "(Full fact-checking was unavailable for this answer; only the local number "
          "and name checks ran.)",
    "kn": "(ಈ ಉತ್ತರದ ಪೂರ್ಣ ಪರಿಶೀಲನೆ ಈಗ ಲಭ್ಯವಿಲ್ಲ; ಸಂಖ್ಯೆ ಮತ್ತು ಹೆಸರು ಪರಿಶೀಲನೆ ಮಾತ್ರ ನಡೆದಿದೆ.)",
}
_MAX_CAVEAT_ITEMS = 3


@dataclass(frozen=True)
class CheckResult:
    answer: str              # what the farmer receives (caveated / noted if needed)
    unsupported: list[str]   # claims flagged, e.g. "unsupported: X", "name: Y"
    checked: list[str]       # every claim examined, with its status
    status: str = "checked"  # checked | unavailable | skipped (token budget)
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
        purpose="fact_check", timeout=s.grounding_timeout_s, max_tokens=s.groq_check_max_tokens,
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


def local_findings(answer: str, sources: str, readings: str = "",
                   knowledge: str | None = None) -> list[tuple[str, str]]:
    """(kind, item) for every local finding: number, input, judgement, name.

    `sources` is everything the answer may draw on (retrieved text, question,
    farm readings); `readings` is the farm-readings part, `knowledge` the
    retrieved-text part (defaults to `sources`)."""
    knowledge = sources if knowledge is None else knowledge
    found = [("number", n) for n in number_check.unsupported_numbers(answer, sources)]
    found += [("input", n) for n in number_check.unsupported_inputs(answer, sources)]
    found += [("input", n) for n in number_check.unsupported_input_purposes(answer, sources)]
    found += [("judgement", j) for j in number_check.unsupported_judgements(
        answer, number_check.quantities(readings), knowledge)]
    src_lower = sources.lower()
    found += [("name", n) for n in sorted(_names(answer)) if n.lower() not in src_lower]
    return found


def check(answer: str, context: str, language: str = "en", *, sources: str | None = None,
          readings: str = "", knowledge: str | None = None) -> CheckResult:
    """Check `answer`; caveat or note it. `context` goes to the Groq check;
    `sources` (default: `context`) to the local checks — see local_findings."""
    lang = "kn" if language == "kn" else "en"
    labels = _LABEL[lang]

    # 1. local checks, always run
    local = local_findings(answer, context if sources is None else sources, readings, knowledge)
    flagged = [f"{kind}: {item}" for kind, item in local]
    caveat_items = [f'"{item}" ({labels[kind]})' for kind, item in local]
    local_numbers = {d for kind, item in local if kind == "number"
                     for d in re.findall(r"\d+", number_check._normalise_text(item))}

    # 2. grounding call; never blocks the answer
    t0 = time.perf_counter()
    from backend.ai.groq_client import GroqSkipped

    try:
        claims = _grounding(answer, context)
        status = "checked"
    except GroqSkipped as exc:
        logger.info("grounding check skipped: %s", exc)
        claims, status = [], "skipped"
    except Exception as exc:
        logger.warning("grounding check unavailable: %s", exc)
        claims, status = [], "unavailable"
    seconds = round(time.perf_counter() - t0, 2)

    for c in claims:
        if c["status"] != "supported":
            flagged.append(f'{c["status"]}: {c["claim"]}')
            # One caveat: skip a Groq finding about a number already flagged locally.
            claim_digits = re.findall(r"\d+", c["claim"])
            if claim_digits and all(d in local_numbers for d in claim_digits):
                continue
            caveat_items.append(f'"{c["claim"]}" ({labels[c["status"]]})')

    final = answer
    if caveat_items:
        shown = caveat_items[:_MAX_CAVEAT_ITEMS]
        if len(caveat_items) > len(shown):
            shown.append(f"+{len(caveat_items) - len(shown)}")
        final = _CAVEAT[lang].format(items="; ".join(shown)) + "\n\n" + final
    if status != "checked":
        final = f"{final}\n\n{_UNAVAILABLE[lang]}"
    logger.info("grounding %s in %.2fs: %d claims, %d flagged", status, seconds,
                len(claims), len(flagged))
    return CheckResult(final, flagged, [f'{c["status"]}: {c["claim"]}' for c in claims],
                       status, seconds, claims)
