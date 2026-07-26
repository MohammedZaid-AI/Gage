"""Voice endpoints: the farmer speaks, Gage answers in speech.

Pipeline (Sarvam or mock, chosen by config):
  audio -> STT -> AIOrchestrator.answer (Phase 3 grounding) -> TTS -> audio.

The router stays thin: resolve ownership, call the speech facade + orchestrator.
Speech providers live behind ai.transcribe / ai.synthesize; swapping in real
Sarvam is a config change only.
"""
import base64
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from backend import ai
from backend.ai.orchestrator import AIOrchestrator
from backend.database import get_db
from backend.dependencies import get_current_farmer, owned_farm
from backend.models import Farmer
from backend.schemas import SpeakRequest, SpeakResponse, VoiceAnswer

logger = logging.getLogger("gage.voice")
router = APIRouter(prefix="/voice", tags=["voice"])


@router.post("/ask", response_model=VoiceAnswer)
async def voice_ask(
    farm_id: int = Form(...),
    audio: UploadFile = File(...),
    farmer: Farmer = Depends(get_current_farmer),
    db: Session = Depends(get_db),
) -> VoiceAnswer:
    farm = owned_farm(db, farmer, farm_id)
    raw = await audio.read()

    try:
        transcript, _lang = ai.transcribe(raw)
    except Exception:
        logger.exception("speech-to-text failed")
        raise HTTPException(502, "Speech recognition is unavailable")
    if not transcript.strip():
        raise HTTPException(422, "Could not understand the audio")

    answer, language = AIOrchestrator.answer(db, farm, transcript)

    try:
        audio_out = ai.synthesize(answer, language)
    except Exception:  # text answer still valuable if TTS hiccups
        logger.exception("text-to-speech failed")
        audio_out = b""

    return VoiceAnswer(
        transcript=transcript,
        answer=answer,
        language=language,
        audio_base64=base64.b64encode(audio_out).decode(),
    )


@router.post("/speak", response_model=SpeakResponse)
def voice_speak(
    req: SpeakRequest,
    farmer: Farmer = Depends(get_current_farmer),
) -> SpeakResponse:
    """Text-to-speech for arbitrary text (e.g. read an alert or summary aloud)."""
    language = req.language or ai.detect_language(req.text)
    try:
        audio_out = ai.synthesize(req.text, language)
    except Exception:
        logger.exception("text-to-speech failed")
        raise HTTPException(502, "Speech synthesis is unavailable")
    return SpeakResponse(language=language, audio_base64=base64.b64encode(audio_out).decode())
