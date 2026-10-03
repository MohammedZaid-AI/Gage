"""Knowledge retrieval (the RAG source) over the project's knowledge base.

The corpus is the curated markdown in `knowledge_base/` (ICAR-IISR, government
scheme and advisory documents; provenance in knowledge_base_index.csv). Each
document is split into section chunks, and chunks are embedded with a
multilingual model (intfloat/multilingual-e5-small, which covers Kannada), so a
question written in Kannada script, romanized Kannada or English all retrieve
from the same English documents by meaning rather than by shared words.

The index is built once per process (`warm_up()` at startup, or lazily on the
first query) and kept in memory: ~150 chunks, a few seconds on CPU.
"""
import logging
import re
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from backend.config import get_settings

logger = logging.getLogger("gage.knowledge")

# Bibliographic sections carry no agronomy; they would only add retrieval noise.
_SKIP_SECTIONS = {"source", "publication date", "url"}
_MAX_CHUNK_CHARS = 900


@dataclass(frozen=True)
class KnowledgeDoc:
    """One retrievable chunk: `title` names the document and section."""
    title: str
    text: str
    source: str          # path relative to the knowledge base root
    score: float = 0.0   # cosine similarity to the query (0 when not retrieved)


def _split_long(text: str) -> list[str]:
    """Split a section on line boundaries into pieces of at most _MAX_CHUNK_CHARS."""
    if len(text) <= _MAX_CHUNK_CHARS:
        return [text]
    pieces, cur = [], ""
    for line in text.splitlines():
        if cur and len(cur) + len(line) + 1 > _MAX_CHUNK_CHARS:
            pieces.append(cur.strip())
            cur = ""
        cur += line + "\n"
    if cur.strip():
        pieces.append(cur.strip())
    return pieces


def _chunk_document(path: Path, root: Path) -> list[KnowledgeDoc]:
    raw = path.read_text(encoding="utf-8")
    m = re.search(r"^#\s+(.+)$", raw, re.M)
    doc_title = m.group(1).strip() if m else path.stem
    chunks: list[KnowledgeDoc] = []
    for sec in re.split(r"^##\s+", raw, flags=re.M)[1:]:
        heading, _, body = sec.partition("\n")
        heading, body = heading.strip(), body.strip()
        if not body or heading.lower() in _SKIP_SECTIONS:
            continue
        for piece in _split_long(body):
            chunks.append(KnowledgeDoc(
                title=f"{doc_title} — {heading}",
                text=piece,
                source=path.relative_to(root).as_posix(),
            ))
    return chunks


def _local_or_remote(model_id: str) -> str:
    """Prefer the already-downloaded snapshot directory, so startup needs no
    network (transformers otherwise queries the Hub even for cached models).
    Falls back to the id, which downloads on first use."""
    if Path(model_id).is_dir():
        return model_id
    from huggingface_hub import snapshot_download

    try:
        return snapshot_download(model_id, local_files_only=True)
    except Exception:
        return model_id


class _Index:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._model = None
        self._docs: list[KnowledgeDoc] = []
        self._matrix: np.ndarray | None = None

    def ready(self) -> bool:
        return self._matrix is not None

    def build(self) -> None:
        with self._lock:
            if self._matrix is not None:
                return
            from sentence_transformers import SentenceTransformer  # heavy: import on demand

            s = get_settings()
            root = Path(s.knowledge_base_dir)
            files = sorted(p for p in root.rglob("*.md") if p.name != "knowledge_sources.md")
            if not files:
                raise RuntimeError(f"no knowledge base documents found under {root.resolve()}")
            docs = [c for f in files for c in _chunk_document(f, root)]
            model = SentenceTransformer(_local_or_remote(s.embedding_model), device="cpu")
            # e5 models are trained with these role prefixes; omitting them degrades retrieval.
            matrix = model.encode([f"passage: {d.title}\n{d.text}" for d in docs],
                                  normalize_embeddings=True, batch_size=32)
            self._model, self._docs, self._matrix = model, docs, np.asarray(matrix)
            logger.info("knowledge index built: %d chunks from %d documents (%s)",
                        len(docs), len(files), s.embedding_model)

    def search(self, query: str, k: int) -> list[KnowledgeDoc]:
        if self._matrix is None:
            self.build()
        q = self._model.encode([f"query: {query}"], normalize_embeddings=True)[0]
        scores = self._matrix @ q
        min_score = get_settings().retrieval_min_score
        out = []
        for i in np.argsort(-scores)[:k]:
            if scores[i] < min_score:
                break
            d = self._docs[i]
            out.append(KnowledgeDoc(d.title, d.text, d.source, round(float(scores[i]), 4)))
        return out


_index = _Index()


def warm_up() -> None:
    """Build the index now (call at startup) so the first question isn't slow."""
    _index.build()


@dataclass(frozen=True)
class Retrieval:
    docs: list[KnowledgeDoc]
    queries: list[str]   # the text(s) actually searched, for logging / audit


def _has_kannada(text: str) -> bool:
    return any("ಀ" <= ch <= "೿" for ch in text)


def _merge(*hit_lists: list[KnowledgeDoc], k: int) -> list[KnowledgeDoc]:
    """Union of hit lists, keeping each chunk's best score."""
    best: dict[tuple[str, str], KnowledgeDoc] = {}
    for hits in hit_lists:
        for h in hits:
            key = (h.source, h.text)
            if key not in best or h.score > best[key].score:
                best[key] = h
    return sorted(best.values(), key=lambda d: d.score, reverse=True)[:k]


def retrieve(question: str, k: int = 3) -> Retrieval:
    """Up to k knowledge chunks relevant to the farmer's question, best first.

    The corpus is English, so non-English questions are translated first (see
    query_translation): Kannada script always; Latin text only when the direct
    match is weak, which is how romanized Kannada shows up. Chunks scoring below
    RETRIEVAL_MIN_SCORE are dropped, so an unrelated question returns no docs.
    If translation is unavailable, retrieval degrades to the original text and
    says so in the log rather than failing the answer.
    """
    from backend.ai import query_translation as qt

    if not question.strip():
        return Retrieval([], [])
    s = get_settings()
    try:
        if _has_kannada(question):
            english = qt.kannada_to_english(question)
            return Retrieval(_index.search(english, k), [english])
        direct = _index.search(question, k)
        if direct and direct[0].score >= s.retrieval_romanized_trigger:
            return Retrieval(direct, [question])
        english = qt.romanized_kannada_to_english(question)
        return Retrieval(_merge(direct, _index.search(english, k), k=k), [question, english])
    except qt.TranslationUnavailable as exc:
        logger.warning("query translation unavailable (%s); retrieving on the original text, "
                       "which is unreliable for Kannada", exc)
        return Retrieval(_index.search(question, k), [question])
