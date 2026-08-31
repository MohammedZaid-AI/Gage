"""Provider interfaces. Implement these to add a new AI backend."""
from abc import ABC, abstractmethod
from dataclasses import dataclass

# Vocabulary shared by the classifier, the label generator and the health score.
# These are the 11 classes of the deployed sugarcane model (Teachable Machine
# export), snake_cased from its labels.txt. labels.txt stays the source of truth
# at inference time — this tuple is what the rest of the app reasons about.
DISEASE_CLASSES = (
    "healthy",
    "banded_chlorosis",
    "brown_spot",
    "brown_rust",
    "dried",
    "grassy_shoot",
    "pokkah_boeng",
    "sett_rot",
    "smut",
    "viral_disease",
    "yellow_leaf",
)
# `not_sugarcane` is NOT a class of the current model — a closed-set softmax
# always names one of the 11 above, so it cannot say "that's a dog". It stays in
# the vocabulary as the seam for a model retrained with a reject class; until
# then non-sugarcane images are handled by abstention, imperfectly. See
# providers/tflite_vision.py for exactly what that does and does not catch.
NOT_CROP = "not_sugarcane"
VISION_CLASSES = DISEASE_CLASSES + (NOT_CROP,)

# Disease classes that indicate a problem (healthy is a finding, not a problem).
DISEASED = tuple(c for c in DISEASE_CLASSES if c != "healthy")


@dataclass(frozen=True)
class VisionResult:
    """What the vision layer saw.

    `description` is prose for the LLM prompt and is always present. `label` and
    `confidence` are populated only by a real classifier; a heuristic provider
    leaves them None. `abstained` means: do NOT diagnose from this image — either
    it isn't sugarcane, or confidence fell below the operating threshold.
    """

    description: str
    label: str | None = None
    confidence: float | None = None
    abstained: bool = False
    reason: str | None = None          # why we abstained, shown to the farmer
    # Full class distribution, highest first — for logging and developer views.
    # A tuple of pairs, not a dict, so the dataclass stays frozen/hashable.
    probabilities: tuple[tuple[str, float], ...] = ()

    @property
    def usable(self) -> bool:
        """True when a diagnosis may be relied on downstream."""
        return not self.abstained and self.label is not None

    @property
    def is_diseased(self) -> bool:
        return self.usable and self.label in DISEASED


class VisionProvider(ABC):
    """Turns an image (raw bytes) into an agronomic finding."""

    @abstractmethod
    def analyze(self, image_bytes: bytes) -> VisionResult: ...


class LLMProvider(ABC):
    """Answers a farmer's question given assembled field context."""

    @abstractmethod
    def answer(self, question: str, context: str, language: str) -> str: ...


class SpeechProvider(ABC):
    """Speech-to-text and text-to-speech (e.g. Sarvam AI) for the voice loop."""

    @abstractmethod
    def transcribe(self, audio: bytes, language: str | None = None) -> tuple[str, str]:
        """Return (transcript, language-code) for the spoken audio."""

    @abstractmethod
    def synthesize(self, text: str, language: str) -> bytes:
        """Return audio bytes (a playable file) speaking `text` in `language`."""
