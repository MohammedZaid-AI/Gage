"""Basic grounding check on a model answer — a safety net, not fact-checking.

Pulls the *specific* claims out of an answer (numbers, named nutrients and
chemicals, months, acronyms / variety codes) and checks that each one appears
somewhere in the context the model was given (retrieved knowledge + farm data +
the farmer's own question). Anything specific that is not in that context gets
a short caveat prepended, so it is not presented as established fact.

Known limits (deliberately simple): it checks presence, not meaning — "iron" in
the context supports any sentence using "iron"; chemical names written in
Kannada script are only caught for the nutrients listed below.
"""
import re
from dataclasses import dataclass

_KN_DIGITS = str.maketrans("೦೧೨೩೪೫೬೭೮೯", "0123456789")
_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")

# Each group is one claim; any surface form found in the context supports it.
_TERM_GROUPS: dict[str, tuple[str, ...]] = {
    "iron": ("iron", "fe", "feso4", "ferrous", "fe-edta", "ಕಬ್ಬಿಣ"),
    "calcium": ("calcium", "ಕ್ಯಾಲ್ಸಿಯಂ"),
    "zinc": ("zinc", "zn", "znso4", "ಸತು", "ಜಿಂಕ್"),
    "manganese": ("manganese", "mn", "mnso4"),
    "magnesium": ("magnesium", "mg", "mgso4"),
    "nitrogen": ("nitrogen", "ಸಾರಜನಕ"),
    "phosphorus": ("phosphorus", "phosphate", "ರಂಜಕ"),
    "potassium": ("potassium", "potash", "ಪೊಟ್ಯಾಷ್"),
    "sulphur": ("sulphur", "sulfur", "ಗಂಧಕ"),
    "boron": ("boron", "borax"),
    "copper": ("copper", "cuso4"),
    "molybdenum": ("molybdenum", "molybdate"),
    "lime": ("lime", "ಸುಣ್ಣ"),
    "gypsum": ("gypsum",),
    "urea": ("urea", "ಯೂರಿಯಾ"),
    "dap": ("dap",),
    "mop": ("mop", "muriate"),
    "npk": ("npk",),
    "chlorpyrifos": ("chlorpyrifos", "chlorpyriphos"),
    "imidacloprid": ("imidacloprid",),
    "fipronil": ("fipronil",),
    "carbofuran": ("carbofuran",),
    "phorate": ("phorate", "thimet"),
    "atrazine": ("atrazine",),
    "metribuzin": ("metribuzin",),
    "glyphosate": ("glyphosate",),
    "2,4-d": ("2,4-d",),
    "mancozeb": ("mancozeb",),
    "carbendazim": ("carbendazim",),
    "propiconazole": ("propiconazole",),
    "trichogramma": ("trichogramma", "trichocard"),
    "cotesia": ("cotesia",),
    "trichoderma": ("trichoderma",),
}
# Case-sensitive month forms; "May" only when it is not the verb ("may be").
_MONTHS: dict[str, tuple[str, ...]] = {
    "January": ("January", "Jan", "ಜನವರಿ"), "February": ("February", "Feb", "ಫೆಬ್ರವರಿ"),
    "March": ("March", "Mar", "ಮಾರ್ಚ್"), "April": ("April", "Apr", "ಏಪ್ರಿಲ್"),
    "May": ("May", "ಮೇ"), "June": ("June", "Jun", "ಜೂನ್"), "July": ("July", "Jul", "ಜುಲೈ"),
    "August": ("August", "Aug", "ಆಗಸ್ಟ್"), "September": ("September", "Sept", "Sep", "ಸೆಪ್ಟೆಂಬರ್"),
    "October": ("October", "Oct", "ಅಕ್ಟೋಬರ್"), "November": ("November", "Nov", "ನವೆಂಬರ್"),
    "December": ("December", "Dec", "ಡಿಸೆಂಬರ್"),
}
# Acronyms that are formatting or units, not claims.
_NOT_ENTITIES = {"I", "OK", "UTC", "AM", "PM", "AI", "SMS", "ID", "NA", "N/A"}

_CAVEAT = {
    "en": ("Please double-check before acting: these specifics in the answer are not in "
           "Gage's reference documents or your farm data: {items}. Confirm them with your "
           "local agriculture officer."),
    "kn": ("ದಯವಿಟ್ಟು ಮುಂದುವರಿಯುವ ಮೊದಲು ಪರಿಶೀಲಿಸಿ: ಈ ಉತ್ತರದಲ್ಲಿನ ಈ ವಿವರಗಳು Gage ನ "
           "ಮಾಹಿತಿ ದಾಖಲೆಗಳಲ್ಲಿ ಅಥವಾ ನಿಮ್ಮ ಜಮೀನಿನ ದತ್ತಾಂಶದಲ್ಲಿ ಇಲ್ಲ: {items}. "
           "ನಿಮ್ಮ ಸ್ಥಳೀಯ ಕೃಷಿ ಅಧಿಕಾರಿಯನ್ನು ಸಂಪರ್ಕಿಸಿ ಖಚಿತಪಡಿಸಿಕೊಳ್ಳಿ."),
}


@dataclass(frozen=True)
class CheckResult:
    answer: str              # what the farmer receives (caveated if needed)
    unsupported: list[str]   # specific claims not found in the context
    checked: list[str]       # every specific claim extracted


def _norm(text: str) -> str:
    return text.translate(_KN_DIGITS).translate(_SUBSCRIPTS)


def _numbers(text: str) -> set[str]:
    """Numeric claims, normalised (25.0 -> 25), ignoring list enumerators."""
    text = re.sub(r"(?m)^\s*\d+[.)]\s", " ", _norm(text))
    out = set()
    for m in re.finditer(r"(?<![\w.])(\d+(?:[.,]\d+)?)(?![\w])", text):
        n = m.group(1).replace(",", "")
        try:
            v = float(n)
        except ValueError:
            continue
        out.add(str(int(v)) if v == int(v) else str(v))
    return out


def _has_form(text_lower: str, form: str) -> bool:
    if re.fullmatch(r"[a-z0-9,\-]+", form):
        return re.search(rf"(?<![a-z0-9]){re.escape(form)}(?![a-z0-9])", text_lower) is not None
    return form in text_lower  # Kannada forms: substring (inflected suffixes)


def _terms(text: str) -> set[str]:
    low = _norm(text).lower()
    return {g for g, forms in _TERM_GROUPS.items() if any(_has_form(low, f) for f in forms)}


def _months(text: str) -> set[str]:
    found = set()
    for month, forms in _MONTHS.items():
        for f in forms:
            if f == "May":
                pat = r"\bMay\b(?!\s+(?:be|have|not|also|help|cause|need|vary|lead|reduce|increase))"
            elif f.isascii():
                pat = rf"\b{f}\b"
            else:
                pat = re.escape(f)
            if re.search(pat, text):
                found.add(month)
                break
    return found


def _entities(text: str) -> set[str]:
    """Acronyms (ICAR, IISR, FRP) and sugarcane variety codes (Co 86032, CoC 671)."""
    found = {m for m in re.findall(r"\b[A-Z]{2,6}\b", text) if m not in _NOT_ENTITIES}
    found |= {re.sub(r"\s+", " ", m) for m in re.findall(r"\bCo[A-Z]{0,3}\s?\d{3,5}\b", text)}
    return found


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


def check(answer: str, context: str, language: str = "en") -> CheckResult:
    """Return the answer, caveated if any specific claim is absent from `context`."""
    ctx_numbers, ctx_terms = _numbers(context), _terms(context)
    # A rounded figure is not a new claim: "32%" is supported by a reading of 32.3.
    ctx_numbers |= {str(f(float(n))) for n in ctx_numbers if "." in n for f in (round, int)}
    ctx_months, ctx_entities = _months(context), _entities(context)

    claims: list[tuple[str, bool]] = []
    claims += [(n, n in ctx_numbers) for n in sorted(_numbers(answer))]
    claims += [(t, t in ctx_terms) for t in sorted(_terms(answer))]
    claims += [(m, m in ctx_months) for m in sorted(_months(answer))]
    claims += [(e, e in ctx_entities or e in context) for e in sorted(_entities(answer))]
    # A named person is supported only if that exact name appears in the context.
    ctx_lower = context.lower()
    claims += [(f"name: {n}", n.lower() in ctx_lower) for n in sorted(_names(answer))]

    unsupported = [c for c, ok in claims if not ok]
    final = answer
    if unsupported:
        caveat = _CAVEAT["kn" if language == "kn" else "en"].format(items=", ".join(unsupported))
        final = f"{caveat}\n\n{answer}"
    return CheckResult(final, unsupported, [c for c, _ in claims])
