"""AI Orchestrator — the single entry point for answering a farmer's question.

Routers call `AIOrchestrator.answer(...)` and nothing else. The orchestrator:
  1. builds the Farm Context (services/farm_context)
  2. retrieves RAG knowledge (ai/knowledge)
  3. builds the structured prompt (ai/prompt_builder)
  4. calls the LLM (ai/service.complete)
  5. persists the conversation turn (chat memory)
  6. returns (answer, language)
"""
import logging

from sqlalchemy.orm import Session

from backend.ai import knowledge, prompt_builder, service
from backend.models import Conversation, Farm
from backend.services import farm_context

logger = logging.getLogger("gage.orchestrator")


class AIOrchestrator:
    @staticmethod
    def answer(db: Session, farm: Farm, question: str) -> tuple[str, str]:
        language = service.detect_language(question)
        ctx = farm_context.build(db, farm)

        prior = "\n".join(c.question + " " + c.answer for c in ctx.conversation)
        # A confident classifier verdict is retrieval evidence: it pulls in that
        # disease's agronomy even when the farmer never named it (and even when
        # they asked in Kannada, which the ASCII tokeniser cannot match on).
        # `vision_label` is NULL whenever the model abstained, so an unidentified
        # image can never retrieve disease-specific treatment advice.
        vision = (ctx.latest.vision_label or "") if ctx.latest else ""
        docs = knowledge.retrieve(question, prior + " " + vision.replace("_", " "), k=3)

        prompt = prompt_builder.build(ctx, docs, question)
        answer = service.complete(question, prompt, language)

        db.add(Conversation(
            farm_id=farm.id, farmer_id=farm.farmer_id,
            question=question, answer=answer, language=language,
        ))
        db.commit()
        logger.info("answered for farm %d (%s, %d kb docs)", farm.id, language, len(docs))
        return answer, language
