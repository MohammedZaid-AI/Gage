"""Conversational assistant endpoint (English / Kannada), scoped to a farm.

The router only resolves ownership and delegates to the AI Orchestrator, which
owns context assembly, RAG, prompting, the LLM call, and saving the turn.

Declared as a plain `def` on purpose: FastAPI runs it in a worker thread, so a
slow model generation never blocks the event loop (sensor ingest, other users).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.ai.base import LLMError
from backend.ai.orchestrator import AIOrchestrator
from backend.database import get_db
from backend.dependencies import get_current_farmer, owned_farm
from backend.models import Farmer
from backend.schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(
    req: ChatRequest,
    farmer: Farmer = Depends(get_current_farmer),
    db: Session = Depends(get_db),
) -> ChatResponse:
    farm = owned_farm(db, farmer, req.farm_id)
    try:
        result = AIOrchestrator.answer(db, farm, req.question)
    except LLMError as exc:
        # Honest failure: nothing was saved, and the farmer is not shown a
        # made-up answer.
        raise HTTPException(503, f"The assistant could not answer right now: {exc}") from exc
    return ChatResponse(question=req.question, answer=result.answer, language=result.language,
                        unsupported_claims=result.unsupported)
