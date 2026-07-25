"""Conversational assistant endpoint (English / Kannada), scoped to a farm."""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.ai import answer_question
from backend.database import get_db
from backend.dependencies import get_current_farmer, owned_farm
from backend.models import Conversation, Farmer
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
    answer, language = answer_question(db, farm.id, req.question)

    convo = Conversation(
        farm_id=farm.id,
        farmer_id=farmer.id,
        question=req.question,
        answer=answer,
        language=language,
    )
    db.add(convo)
    db.commit()
    logger.info("chat answered for farm %d (%s)", farm.id, language)
    return ChatResponse(question=req.question, answer=answer, language=language)
