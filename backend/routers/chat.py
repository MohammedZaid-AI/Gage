"""Conversational assistant endpoint (English / Kannada)."""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.ai import answer_question
from backend.database import get_db
from backend.models import Conversation
from backend.routers.inspection import active_inspection
from backend.schemas import ChatRequest, ChatResponse

logger = logging.getLogger("gage.chat")
router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
async def chat(req: ChatRequest, db: Session = Depends(get_db)) -> ChatResponse:
    answer, language = answer_question(db, req.question)

    inspection = active_inspection(db)
    convo = Conversation(
        inspection_id=inspection.id if inspection else None,
        question=req.question,
        answer=answer,
        language=language,
    )
    db.add(convo)
    db.commit()
    logger.info("chat answered (%s)", language)
    return ChatResponse(question=req.question, answer=answer, language=language)
