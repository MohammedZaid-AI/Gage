"""Sugarcane agricultural knowledge base + retrieval (the RAG source).

ponytail: a curated in-code KB with keyword-overlap retrieval (light stemming via
a shared prefix so "irrigate" matches "irrigation"). Plenty for a focused
sugarcane assistant and needs no vector DB or embeddings. Promote to a
`knowledge_base` table + embeddings only when the corpus grows past keyword
matching or farmers need to edit it. The `retrieve()` signature is the seam —
swapping the backing store is a change in this module only.
"""
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeDoc:
    title: str
    keywords: tuple[str, ...]
    text: str


_DOCS: tuple[KnowledgeDoc, ...] = (
    KnowledgeDoc(
        "Irrigation & soil moisture",
        ("irrigation", "water", "watering", "soil", "moisture", "dry", "drought"),
        "Sugarcane needs steady soil moisture, especially during the tillering and "
        "grand-growth stages. Soil moisture below ~20% signals water stress; irrigate "
        "at the earliest. Above ~60% for long periods risks waterlogging and root rot.",
    ),
    KnowledgeDoc(
        "Humidity & disease",
        ("humidity", "disease", "fungus", "fungal", "red rot", "smut", "rust"),
        "Prolonged high humidity (>85%) favours fungal diseases such as red rot and "
        "rust in sugarcane. Ensure drainage and airflow between rows; remove infected "
        "canes early to limit spread.",
    ),
    KnowledgeDoc(
        "Temperature & heat stress",
        ("temperature", "heat", "hot", "cold", "climate"),
        "Sugarcane grows best between 20-35C. Sustained temperatures above 40C cause "
        "heat stress and moisture loss; maintain soil moisture and mulch to buffer heat.",
    ),
    KnowledgeDoc(
        "Leaf yellowing & nutrition",
        ("yellow", "yellowing", "nitrogen", "nutrient", "fertilizer", "chlorosis"),
        "Yellowing lower leaves often indicates nitrogen deficiency or waterlogging. "
        "If soil moisture is adequate, a nitrogen top-dressing usually helps. Confirm "
        "with a leaf/soil test before heavy fertiliser use.",
    ),
    KnowledgeDoc(
        "Weed management",
        ("weed", "weeds", "grass", "competition"),
        "Weeds compete strongly with young sugarcane for water and nutrients. Keep the "
        "crop weed-free for the first 90-120 days through manual weeding or recommended "
        "pre-emergence herbicides.",
    ),
    KnowledgeDoc(
        "Canopy & growth stages",
        ("canopy", "growth", "tillering", "stage", "density", "sparse"),
        "A dense, even canopy indicates healthy tillering. Sparse or thin canopy can "
        "mean poor germination, nutrient deficiency, or pest damage — inspect the base "
        "of the canes and the soil.",
    ),
    # --- one doc per class of the deployed classifier -------------------------
    # The orchestrator adds the predicted label to the retrieval query, so a
    # confident verdict pulls its own agronomy in. Keywords use the snake_cased
    # label's words, since retrieval tokenises on [a-z]+ and splits underscores.
    KnowledgeDoc(
        "Healthy crop — keep it that way",
        ("healthy", "normal", "good"),
        "A healthy sugarcane stand shows upright green leaves with no lesions, "
        "streaks or stunting. Keep monitoring weekly, hold irrigation to the crop "
        "stage, and keep records — most losses come from a problem noticed late, "
        "not from a problem with no treatment.",
    ),
    KnowledgeDoc(
        "Smut",
        ("smut", "whip", "sporisorium"),
        "Sugarcane smut shows a black whip-like structure emerging from the growing "
        "point, with thin grassy shoots and stunted canes. It is soil- and sett-borne. "
        "Rogue out whip-bearing clumps before the whip ruptures and bag them; do not "
        "leave them in the field. Use setts from a disease-free nursery and resistant "
        "varieties in the next planting. Fungicide on a standing crop is not effective.",
    ),
    KnowledgeDoc(
        "Brown rust",
        ("rust", "brown", "pustule", "pustules", "uredinia"),
        "Brown rust shows small orange-brown pustules on the underside of leaves, "
        "which merge in severe cases and dry the leaf. It is favoured by high humidity "
        "and moderate temperatures with dense planting. Improve airflow between rows "
        "and avoid excess nitrogen. Severe early-stage infections may justify a "
        "recommended fungicide — confirm with an agricultural officer first.",
    ),
    KnowledgeDoc(
        "Brown spot",
        ("spot", "brown", "lesion", "lesions", "cercospora"),
        "Brown spot appears as small reddish-brown spots on leaves, often with a pale "
        "halo, spreading in prolonged wet and humid weather. It mainly reduces "
        "photosynthetic area rather than killing the cane. Ensure drainage and balanced "
        "nutrition; remove heavily affected lower leaves to reduce inoculum.",
    ),
    KnowledgeDoc(
        "Pokkah Boeng",
        ("pokkah", "boeng", "twisted", "malformed", "fusarium"),
        "Pokkah Boeng shows chlorotic, wrinkled and twisted top leaves, sometimes with "
        "a knife-cut appearance or a rotted top in severe cases. It is favoured by "
        "sudden humid weather after dry spells. The crop often recovers on its own as "
        "conditions change; cut and remove severely affected tops and keep nutrition "
        "balanced. Do not panic-spray on the first twisted leaves.",
    ),
    KnowledgeDoc(
        "Sett rot & red rot of setts",
        ("sett", "rot", "germination", "pineapple", "planting"),
        "Sett rot attacks the planted sett before or during germination, causing poor "
        "and patchy germination and a reddish, sour-smelling internal tissue. Treat "
        "setts before planting, plant in well-drained soil, and avoid waterlogging in "
        "the first weeks. Gap-fill early so the stand stays even.",
    ),
    KnowledgeDoc(
        "Grassy shoot",
        ("grassy", "shoot", "phytoplasma", "stunted", "tillers"),
        "Grassy shoot disease produces a mass of thin, pale, grass-like tillers with no "
        "cane formation — a phytoplasma spread through infected setts and by insect "
        "vectors. There is no field cure: rogue out affected clumps completely, and use "
        "heat-treated setts from a healthy nursery for the next crop.",
    ),
    KnowledgeDoc(
        "Banded chlorosis",
        ("banded", "chlorosis", "bands", "cold"),
        "Banded chlorosis shows pale yellow-white bands running across the leaf blade, "
        "usually a physiological response to cold nights, waterlogging or a "
        "micronutrient shortage rather than an infection. It commonly grows out as "
        "conditions improve. Check drainage and soil nutrition before treating it as a "
        "disease.",
    ),
    KnowledgeDoc(
        "Viral disease (mosaic and streak)",
        ("viral", "virus", "mosaic", "streak", "aphid"),
        "Sugarcane mosaic and related viruses show irregular light and dark green "
        "patches or streaks on young leaves, with gradual yield decline. They spread "
        "through infected setts and aphids. There is no chemical cure: use virus-free "
        "planting material, rogue severely affected clumps, and control aphids.",
    ),
    KnowledgeDoc(
        "Yellow leaf disease",
        ("yellow", "yellowing", "midrib", "chlorosis", "leaf"),
        "Yellow leaf disease yellows the midrib on the underside of older leaves first, "
        "spreading into the blade, and is spread by sugarcane aphids and infected "
        "setts. Distinguish it from nitrogen deficiency: nutrient yellowing is uniform "
        "and responds to a top-dressing, whereas yellow leaf disease starts at the "
        "midrib and does not. Use healthy setts and manage aphids.",
    ),
    KnowledgeDoc(
        "Dried or withered leaves",
        ("dried", "drying", "withered", "senescence", "scorch"),
        "Widespread leaf drying can be normal senescence of lower leaves, or water "
        "stress, heat scorch, root damage or a late-stage disease. Read it together "
        "with soil moisture and temperature: dry soil points to irrigation, while "
        "drying with adequate moisture points to root or stalk problems worth an "
        "expert inspection.",
    ),
)


# Function words carry no topic signal but DO match keywords by containment
# ("and" inside "banded", "with" inside "withered"), which quietly outranks the
# right document. Only words that can never be agronomic belong here.
_STOPWORDS = frozenset("""
about after all also and any are been before being but can could did does doing
done for from get got had has have her here him his how its just like make many
more most much must not now off only our out over own said same she should some
such than that the their them then there these they this those too under very
was way were what when where which while who why will with would you your
""".split())


def _matches(kw: str, terms: set[str]) -> bool:
    """A keyword matches a term on containment or a shared 4-char prefix, so
    'irrigate' hits 'irrigation' and 'humid' hits 'humidity' — cheap stemming."""
    for t in terms:
        if kw == t or kw in t or t in kw:
            return True
        if len(kw) >= 4 and len(t) >= 4 and kw[:4] == t[:4]:
            return True
    return False


def _score(doc: KnowledgeDoc, terms: set[str]) -> int:
    """Keyword overlap, plus a point per title word hit. The title bonus breaks
    ties towards the specific document: a "smut" query matches the general
    "Humidity & disease" doc and the "Smut" doc equally on keywords, and the
    farmer wants the one actually about smut."""
    title_words = set(re.findall(r"[a-z]{3,}", doc.title.lower())) - _STOPWORDS
    return (sum(1 for kw in doc.keywords if _matches(kw, terms))
            + len(title_words & terms))


def retrieve(query: str, context: str = "", k: int = 3) -> list[KnowledgeDoc]:
    """Return up to k knowledge docs most relevant to the question + farm context,
    ranked by keyword overlap. Empty list if nothing is relevant (never guess)."""
    # {3,}: a one- or two-letter token carries no retrieval signal but matches a
    # long keyword by containment ("ee" in "weed", "en" in "nitrogen"), which let
    # filler words from code-mixed questions ("Ee leaf ge en aagide?") outrank the
    # doc the farmer actually needed.
    terms = set(re.findall(r"[a-z]{3,}", (query + " " + context).lower())) - _STOPWORDS
    scored = [(doc, _score(doc, terms)) for doc in _DOCS]
    hits = sorted((d for d in scored if d[1] > 0), key=lambda x: x[1], reverse=True)
    return [doc for doc, _ in hits[:k]]
