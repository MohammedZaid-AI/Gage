"""Local fact checks that need no network, so they run on every answer even
when the Groq grounding check is skipped or unavailable.

1. Numbers: every number with a unit in the answer (cm, mm, %, kg, days, ₹ ...)
   must appear in the sources: the retrieved text, the farmer's question or the
   farm's readings. Units are normalised first (70 mm == 7 cm, two weeks ==
   2 weeks == 14 days, Kannada digits -> 0-9, "7 to 8" / "7–8" / "7 ರಿಂದ 8"
   ranges), so a faithful conversion is not flagged.
2. Inputs: a fertiliser / chemical / amendment named in the answer but never
   named in the sources.
3. Judgements: a farm reading called low / high / optimal / too dry ... when the
   retrieved text gives no range in that unit to judge it by.

Numbers without a unit (list numbering, "step 2") are not checked.
"""
import re
from dataclasses import dataclass

_KN_DIGITS = str.maketrans("೦೧೨೩೪೫೬೭೮೯", "0123456789")
_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
}
# Kannada and English range joiners: 7-8, 7–8, 7 to 8, 7 ರಿಂದ 8
_DASH = r"(?:\s*[-–—‑~]\s*|\s+to\s+|\s*ರಿಂದ\s*)"
_NUM = r"\d+(?:[.,]\d+)?"

# unit token -> (kind, factor to the kind's base unit)
_UNITS = {
    "mm": ("length", 1), "millimetre": ("length", 1), "millimeter": ("length", 1),
    "ಮಿ.ಮೀ": ("length", 1), "ಮಿಮೀ": ("length", 1),
    "cm": ("length", 10), "centimetre": ("length", 10), "centimeter": ("length", 10),
    "ಸೆಂ.ಮೀ": ("length", 10), "ಸೆಂಮೀ": ("length", 10), "ಸೆಂಟಿಮೀಟರ್": ("length", 10),
    "m": ("length", 1000), "metre": ("length", 1000), "meter": ("length", 1000),
    "ಮೀ": ("length", 1000), "ಮೀಟರ್": ("length", 1000),
    "%": ("percent", 1), "percent": ("percent", 1), "per cent": ("percent", 1),
    "ಶೇ": ("percent", 1), "ಶೇಕಡಾ": ("percent", 1),
    "kg": ("mass", 1), "kgs": ("mass", 1), "ಕೆಜಿ": ("mass", 1), "ಕಿ.ಗ್ರಾಂ": ("mass", 1),
    "g": ("mass", 0.001), "gm": ("mass", 0.001), "ಗ್ರಾಂ": ("mass", 0.001),
    "quintal": ("mass", 100), "quintals": ("mass", 100), "q": ("mass", 100),
    "ಕ್ವಿಂಟಾಲ್": ("mass", 100),
    "t": ("mass", 1000), "tonne": ("mass", 1000), "tonnes": ("mass", 1000),
    "ton": ("mass", 1000), "tons": ("mass", 1000), "ಟನ್": ("mass", 1000),
    "l": ("volume", 1), "litre": ("volume", 1), "litres": ("volume", 1), "liter": ("volume", 1),
    "liters": ("volume", 1), "ಲೀಟರ್": ("volume", 1), "ml": ("volume", 0.001),
    "ha": ("area", 1), "hectare": ("area", 1), "hectares": ("area", 1), "ಹೆಕ್ಟೇರ್": ("area", 1),
    "acre": ("area", 0.4047), "acres": ("area", 0.4047), "ಎಕರೆ": ("area", 0.4047),
    "day": ("time", 1), "days": ("time", 1), "ದಿನ": ("time", 1), "ದಿನಗಳು": ("time", 1),
    "ದಿನಗಳ": ("time", 1), "ದಿನಗಳಲ್ಲಿ": ("time", 1), "ದಿನಗಳೊಳಗೆ": ("time", 1),
    "week": ("time", 7), "weeks": ("time", 7), "ವಾರ": ("time", 7), "ವಾರಗಳು": ("time", 7),
    "month": ("time", 30), "months": ("time", 30), "ತಿಂಗಳು": ("time", 30), "ತಿಂಗಳ": ("time", 30),
    "hour": ("hours", 1), "hours": ("hours", 1), "hrs": ("hours", 1), "h": ("hours", 1),
    "ಗಂಟೆ": ("hours", 1),
    "°c": ("temp", 1), "c": ("temp", 1), "degc": ("temp", 1), "ಡಿಗ್ರಿ": ("temp", 1),
    "ppm": ("ppm", 1), "dap": ("days_after_planting", 1),
}
_CURRENCY = r"(?:₹|rs\.?|inr|ರೂ\.?)"
_UNIT_ALT = "|".join(sorted((re.escape(u) for u in _UNITS), key=len, reverse=True))
# number (or range) followed by a unit; the unit must end at a word boundary so
# "5 months" is not read as "5 m".
_WITH_UNIT = re.compile(
    rf"(?P<a>{_NUM})(?:{_DASH}(?P<b>{_NUM}))?\s*(?P<unit>{_UNIT_ALT})(?![a-zಀ-೿])",
    re.I)
_MONEY = re.compile(rf"{_CURRENCY}\s*(?P<a>{_NUM})(?:{_DASH}{_CURRENCY}?\s*(?P<b>{_NUM}))?", re.I)
_WORD_NUM = re.compile(r"\b(" + "|".join(_WORD_NUMBERS) + r")\b", re.I)


@dataclass(frozen=True)
class Quantity:
    text: str          # as written in the answer
    kind: str          # length | percent | mass | time | money | ...
    values: tuple      # normalised value(s): one, or the two ends of a range


def _normalise_text(text: str) -> str:
    text = text.translate(_KN_DIGITS)
    text = _WORD_NUM.sub(lambda m: str(_WORD_NUMBERS[m.group(1).lower()]), text)
    return text.replace(" ", " ").replace(" ", " ")


def _num(s: str) -> float:
    return float(s.replace(",", ".") if s.count(",") == 1 and len(s.split(",")[1]) != 3
                 else s.replace(",", ""))


def quantities(text: str) -> list[Quantity]:
    """Every number-with-unit (and money amount) in `text`, normalised."""
    text = _normalise_text(text)
    out, taken = [], []
    for m in _MONEY.finditer(text):
        vals = tuple(_num(v) for v in (m.group("a"), m.group("b")) if v)
        out.append(Quantity(m.group(0).strip(), "money", vals))
        taken.append(m.span())
    for m in _WITH_UNIT.finditer(text):
        if any(s <= m.start() < e for s, e in taken):
            continue
        kind, factor = _UNITS[m.group("unit").lower()]
        vals = tuple(round(_num(v) * factor, 4) for v in (m.group("a"), m.group("b")) if v)
        out.append(Quantity(m.group(0).strip(), kind, vals))
    return out


def _source_values(sources: str) -> dict[str, set]:
    """kind -> every normalised value in the sources (range ends included).
    Bare numbers are kept under 'any', so '355 per quintal' still matches."""
    found: dict[str, set] = {"any": set()}
    for q in quantities(sources):
        found.setdefault(q.kind, set()).update(q.values)
    for m in re.finditer(_NUM, _normalise_text(sources)):
        found["any"].add(_num(m.group(0)))
    return found


def _known(value: float, kind: str, src: dict[str, set]) -> bool:
    pool = src.get(kind, set())
    if any(abs(value - v) < 1e-6 for v in pool):
        return True
    # The source may state the same quantity without a parsed unit (e.g. a
    # table cell "355"), but only in the same base unit as written there.
    return kind in ("money", "percent") and any(abs(value - v) < 1e-6 for v in src["any"])


def unsupported_numbers(answer: str, sources: str) -> list[str]:
    """Numbers with units in `answer` that the sources do not contain."""
    src = _source_values(sources)
    flagged = []
    for q in quantities(answer):
        if not all(_known(v, q.kind, src) for v in q.values):
            if q.text not in flagged:
                flagged.append(q.text)
    return flagged


# --- inputs (fertilisers, amendments, pesticides) ---
_INPUTS = (
    "gypsum", "lime", "dolomite", "urea", "dap", "mop", "muriate of potash", "potash",
    "single super phosphate", "ssp", "ammonium sulphate", "ferrous sulphate", "feso4",
    "iron sulphate", "zinc sulphate", "znso4", "manganese sulphate", "mnso4", "borax",
    "boron", "copper sulphate", "magnesium sulphate", "sulphur", "neem cake", "fym",
    "farmyard manure", "press mud", "vermicompost", "biofertiliser", "azospirillum",
    "trichoderma", "carbofuran", "chlorpyrifos", "fipronil", "imidacloprid",
    "chlorantraniliprole", "atrazine", "metribuzin", "2,4-d", "glyphosate", "carbendazim",
    "mancozeb", "propiconazole",
    "ಜಿಪ್ಸಮ್", "ಯೂರಿಯಾ", "ಸುಣ್ಣ", "ಬೇವಿನ ಹಿಂಡಿ",
)


# Names for the same input; a source naming any one of them counts for all.
_ALIASES = [
    {"fym", "farmyard manure", "farm yard manure"},
    {"feso4", "ferrous sulphate", "ferrous sulfate", "iron sulphate", "iron sulfate"},
    {"znso4", "zinc sulphate", "zinc sulfate"},
    {"mnso4", "manganese sulphate", "manganese sulfate"},
    {"mop", "muriate of potash", "potash"},
    {"gypsum", "ಜಿಪ್ಸಮ್"}, {"urea", "ಯೂರಿಯಾ"}, {"lime", "ಸುಣ್ಣ"},
    {"neem cake", "ಬೇವಿನ ಹಿಂಡಿ"},
]
_SUBSCRIPTS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")


def _mentions(text: str, name: str) -> bool:
    text = text.translate(_SUBSCRIPTS)
    if re.fullmatch(r"[a-z0-9 ,\-]+", name):
        return re.search(rf"(?<![a-z]){re.escape(name)}(?![a-z])", text) is not None
    return name in text


def _names_for(name: str) -> set[str]:
    for group in _ALIASES:
        if name in group:
            return group | {name}
    return {name}


def _mentions_any(text: str, name: str) -> bool:
    return any(_mentions(text, n) for n in _names_for(name))


def unsupported_inputs(answer: str, sources: str) -> list[str]:
    a, s = answer.lower(), sources.lower()
    names = [n for n in _INPUTS if _mentions(a, n) and not _mentions_any(s, n)]
    # "ferrous sulphate" also matches "sulphate"-free names; drop names that are
    # part of a longer flagged name ("potash" inside "muriate of potash").
    return [n for n in names if not any(n != o and n in o for o in names)]


_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+|\n+")


def _sentences(text: str) -> list[str]:
    """Split at a full stop followed by space, or a newline — not inside "0.5"
    or "ಸೆಂ.ಮೀ"."""
    return [s for s in _SENTENCE_END.split(text) if s.strip()]


# What an input is said to be FOR: a nutrient, a soil problem or a pest.
_PURPOSES = {
    "iron": ("iron", "fe", "ferrous", "ಕಬ್ಬಿಣ"), "zinc": ("zinc", "zn"),
    "manganese": ("manganese", "mn"), "nitrogen": ("nitrogen", "ಸಾರಜನಕ"),
    "phosphorus": ("phosphorus", "phosphate"), "potassium": ("potassium", "potash"),
    "sulphur": ("sulphur", "sulfur"), "calcium": ("calcium",), "boron": ("boron",),
    "chlorosis": ("chlorosis", "yellowing", "ಹಳದಿ"), "sodic": ("sodic", "alkaline", "alkali"),
    "acidic": ("acidic", "acid soil"), "saline": ("saline", "salinity"),
    "borer": ("borer",), "termite": ("termite",), "weed": ("weed",),
    "fungus": ("fungus", "fungal", "rot", "smut", "wilt"),
}


def _purposes_in(sentence: str) -> set[str]:
    s = sentence.lower()
    return {p for p, words in _PURPOSES.items() if any(_mentions(s, w) for w in words)}


def unsupported_input_purposes(answer: str, sources: str) -> list[str]:
    """'gypsum for iron': an input the answer ties to a purpose (in one sentence)
    that no source paragraph ties it to. A paragraph (a retrieved chunk; blocks
    separated by a blank line), not a sentence, because sources often give the
    purpose once in a list heading ("Treatments for iron chlorosis: 1. FeSO4 ...").
    Inputs absent from the sources are left to unsupported_inputs."""
    src_sents = [p.lower() for p in re.split(r"\n\s*\n", sources) if p.strip()]
    flagged = []
    for sent in _sentences(answer):
        low = sent.lower()
        for name in (n for n in _INPUTS if _mentions(low, n)):
            with_name = [s for s in src_sents if _mentions_any(s, name)]
            if not with_name:
                continue
            purposes = _purposes_in(low) - _purposes_in(name)
            for p in purposes:
                if not any(p in _purposes_in(s) for s in with_name):
                    item = f"{name} for {p}"
                    if item not in flagged:
                        flagged.append(item)
    return flagged


# --- judgements on farm readings ---
_JUDGEMENT = re.compile(
    r"\b(optimal|optimum|ideal|adequate|sufficient|normal|too (?:dry|wet|low|high)|"
    r"(?:below|above) (?:optimal|optimum|normal|ideal)|low|high|dry|good|bad|poor|"
    r"deficient|excess(?:ive)?)\b|ಕಡಿಮೆ|ಹೆಚ್ಚು|ಒಣ|ಸೂಕ್ತ|ಸಾಮಾನ್ಯ", re.I)


def unsupported_judgements(answer: str, readings: list[Quantity], knowledge: str) -> list[str]:
    """Sentences that call one of the farm's readings good/bad/low/high ... when
    the retrieved knowledge has no range in that unit to judge it against."""
    if not readings:
        return []
    ranges: dict[str, int] = {}
    for q in quantities(knowledge):
        if len(q.values) == 2:          # a stated range, e.g. "60-80 %"
            ranges[q.kind] = ranges.get(q.kind, 0) + 1
    flagged = []
    for sent in _sentences(_normalise_text(answer)):
        qs = quantities(sent)
        hit = [q for q in qs for r in readings if q.kind == r.kind and q.values == r.values]
        if hit and _JUDGEMENT.search(sent) and not ranges.get(hit[0].kind):
            flagged.append(f"{hit[0].text} {_JUDGEMENT.search(sent).group(0)}")
    return flagged
