"""Conversational assistant endpoint (English / Kannada), scoped to a farm.

The router only resolves ownership and delegates to the AI Orchestrator, which
owns context assembly, RAG, prompting, the LLM call, and saving the turn.
"""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.ai.orchestrator import AIOrchestrator
from backend.database import get_db
from backend.dependencies import get_current_farmer, owned_farm
from backend.models import Farmer
from backend.schemas import ChatRequest, ChatResponse

logger = logging.getLogger("gage.chat")
router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    farmer: Farmer = Depends(get_current_farmer),
    db: Session = Depends(get_db),
) -> ChatResponse:
    farm = owned_farm(db, farmer, req.farm_id)
    answer, language = AIOrchestrator.answer(db, farm, req.question)
    return ChatResponse(question=req.question, answer=answer, language=language)
