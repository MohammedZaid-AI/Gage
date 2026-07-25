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
)


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
    return sum(1 for kw in doc.keywords if _matches(kw, terms))


def retrieve(query: str, context: str = "", k: int = 3) -> list[KnowledgeDoc]:
    """Return up to k knowledge docs most relevant to the question + farm context,
    ranked by keyword overlap. Empty list if nothing is relevant (never guess)."""
    terms = set(re.findall(r"[a-z]+", (query + " " + context).lower()))
    scored = [(doc, _score(doc, terms)) for doc in _DOCS]
    hits = sorted((d for d in scored if d[1] > 0), key=lambda x: x[1], reverse=True)
    return [doc for doc, _ in hits[:k]]
