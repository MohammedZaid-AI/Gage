"""AI Orchestrator — the single entry point for answering a farmer's question.

Routers call `AIOrchestrator.answer(...)` and nothing else. The orchestrator:
  1. builds the Farm Context (services/farm_context)
  2. retrieves knowledge (ai/knowledge; translates Kannada questions first)
  3. builds the prompt the active model expects (ai/prompt_builder)
  4. calls the LLM (ai/service.complete) — raises LLMError on failure
  5. checks specific claims against the context it gave the model (ai/claim_check)
  6. persists the conversation turn (chat memory) — only real answers
  7. returns an AnswerResult with every intermediate step, for audit

It is blocking (model inference, HTTP to Sarvam): routers run it in a threadpool.
"""
import json
import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from backend.ai import claim_check, knowledge, prompt_builder, service
from backend.models import Conversation, Farm
from backend.services import farm_context

logger = logging.getLogger("gage.orchestrator")


@dataclass
class AnswerResult:
    question: str
    language: str
    retrieval_queries: list[str]
    docs: list[knowledge.KnowledgeDoc]
    context: str            # exactly what the model was given
    raw_answer: str         # the model's own text
    unsupported: list[str]  # specific claims not found in the context
    answer: str             # what the farmer receives (caveated if needed)
    claims: list[str] = field(default_factory=list)


class AIOrchestrator:
    @staticmethod
    def answer(db: Session, farm: Farm, question: str) -> AnswerResult:
        language = service.detect_language(question)
        ctx = farm_context.build(db, farm)
        retrieval = knowledge.retrieve(question, k=3)

        # What the model sees as the farmer's turn. The compact (fine-tuned) prompt
        # is knowledge + the farmer's question only; no sensor readings.
        model_question = question
        if service.prompt_style() == "compact":
            context, model_question = prompt_builder.build_compact(retrieval.docs, question)
        else:
            context = prompt_builder.build(ctx, retrieval.docs, question)

        # LLMError propagates: nothing is saved, the router reports the failure.
        raw = service.complete(model_question, context, language)
        checked = claim_check.check(raw, f"{context}\n{model_question}", language)

        db.add(Conversation(
            farm_id=farm.id, farmer_id=farm.farmer_id,
            question=question, answer=checked.answer, language=language,
        ))
        db.commit()

        result = AnswerResult(
            question=question, language=language, retrieval_queries=retrieval.queries,
            docs=retrieval.docs, context=context, raw_answer=raw,
            unsupported=checked.unsupported, answer=checked.answer, claims=checked.checked,
        )
        logger.info("answer trace %s", json.dumps({
            "farm": farm.id, "language": language, "question": question,
            "retrieval_queries": retrieval.queries,
            "model_input": {"context": context, "farmer": model_question},
            "retrieval_methods": retrieval.methods,
            "retrieval_best_by_method": retrieval.best_by_method,
            "retrieved": [{"source": d.source, "section": d.title, "score": d.score, "via": d.via}
                          for d in retrieval.docs],
            "raw_answer": raw, "claims": checked.checked,
            "unsupported": checked.unsupported, "final_answer": checked.answer,
        }, ensure_ascii=False))
        return result
