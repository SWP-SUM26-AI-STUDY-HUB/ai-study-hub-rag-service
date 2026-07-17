"""Quiz & Flashcard generator (Gemini, native JSON mode).

Generates structured study materials from a single document's content. Unlike
/chat (query-scoped top-k retrieval), generation here works over the document's
full content in reading-order — quizzes/flashcards need broad, coherent coverage.

Reliability is enforced two ways:
  1. `llm.with_structured_output(schema)` — Gemini native JSON mode (response_mime_type
     = application/json + response_schema), so output is schema-validated, not a
     free-text string the prompt "asks" to be JSON.
  2. A `suitable` flag in the schema: Gemini returns suitable=false + a reason when
     the content is too short / fragmented / non-textual, and the generator refuses.

Refusal is two-layered (first wins):
  - Layer 1 (deterministic, pre-LLM): content below a length floor -> refuse, no
    Gemini call (saves quota; mirrors the /chat empty-retrieval guard).
  - Layer 2 (LLM suitability): Gemini signals unsuitable content -> refuse.

A refusal returns GenerationResult(refused=True, reason=...) — the endpoint maps
that to HTTP 200 with empty items + debug.refused (NOT an error status), matching
the guardrail canned-refusal pattern in /chat.
"""
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from pydantic import BaseModel, Field

# S2: reuse the process-wide singleton LLM (holds a warm HTTP/TLS pool).
from app.core.clients import llm
# Instrumentation: per-stage timing -> logs/performance.log.
from app.core.performance import stage, start_trace
from app.core.langfuse_client import lf_span, get_langchain_callbacks
from langfuse import observe
from app.database.document_store import get_document_content

logger = logging.getLogger(__name__)

# --- Tuning params (module-level, not env — match guardrail.py convention) ----
MAX_CONTENT_CHARS = 30000           # cap context sent to Gemini (~5-7k tokens)
MIN_CONTENT_CHARS_QUIZ = 800        # below -> too little for a quality quiz
MIN_CONTENT_CHARS_FLASHCARD = 400   # below -> too little for flashcards
QUIZ_MIN, QUIZ_MAX = 5, 20
QUIZ_DEFAULT = 10
FLASHCARD_MIN, FLASHCARD_MAX = 5, 30
FLASHCARD_DEFAULT = 15
QUIZ_OPTIONS_COUNT = 4              # exactly 4 options per question


# --- Structured-output schemas (Gemini native JSON mode) ----------------------
class QuizQuestion(BaseModel):
    """One multiple-choice question."""
    question: str
    options: List[str] = Field(..., min_length=QUIZ_OPTIONS_COUNT, max_length=QUIZ_OPTIONS_COUNT)
    correct_index: int = Field(..., ge=0, le=QUIZ_OPTIONS_COUNT - 1)
    explanation: str


class QuizOutput(BaseModel):
    """Top-level quiz payload. `suitable=false` => refuse (fragmented/short content)."""
    suitable: bool
    reason: str = ""
    quiz: List[QuizQuestion] = []


class FlashcardItem(BaseModel):
    """One flashcard."""
    term: str
    definition: str


class FlashcardOutput(BaseModel):
    """Top-level flashcard payload. `suitable=false` => refuse."""
    suitable: bool
    reason: str = ""
    flashcards: List[FlashcardItem] = []


@dataclass
class GenerationResult:
    """Service-level result — the endpoint translates refused/items into the wire shape."""
    items: List[dict] = field(default_factory=list)
    refused: bool = False
    reason: str = ""

    @classmethod
    def refused_result(cls, reason: str) -> "GenerationResult":
        return cls(items=[], refused=True, reason=reason)


# --- Prompts ------------------------------------------------------------------
# Language rule: gemini-2.5-flash-lite drifts to a wrong language under a vague
# "detect-then-write" instruction; a hard "same language, do not translate"
# constraint is stable (proven by generate_document_summary on EN/VI/FR docs).
_QUIZ_PROMPT = """You are an expert educational content creator. Generate high-quality multiple-choice quiz questions from the provided document content.

CRITICAL LANGUAGE RULE: Write every question, option, and explanation in the SAME language the document content is written in. Do NOT translate into any other language.

TASK:
- Generate exactly {count} multiple-choice questions based ONLY on the provided document content.
- Each question must have exactly 4 options. Exactly ONE option is correct.
- The explanation must justify the correct answer and be grounded in the document.

QUALITY REQUIREMENTS:
- Spread questions across different sections of the document — do NOT cluster them on one paragraph.
- Vary question types (definitions, comparisons, applications, cause-effect); avoid repetitive recall.
- Distractors (wrong options) must be plausible, not obviously absurd.
- Do NOT fabricate. Every question must be answerable from the document alone.
{focus_clause}

SUITABILITY CHECK (set the "suitable" field accordingly):
- Set suitable=false IF the content is too short, too fragmented/unrelated to each other, mostly non-textual data (e.g. tables of numbers), or otherwise cannot meaningfully support {count} quality questions.
- When suitable=false: put a brief reason (in the document's language) in "reason" and leave "quiz" an empty array.

Document content:
\"\"\"{content}\"\"\"
"""

_FLASHCARD_PROMPT = """You are an expert educational content creator. Generate high-quality flashcards from the provided document content.

CRITICAL LANGUAGE RULE: Write every term and definition in the SAME language the document content is written in. Do NOT translate into any other language.

TASK:
- Generate exactly {count} flashcards extracting the most important terms / concepts / definitions from the document.
- Each flashcard: "term" (the concept/keyword) and "definition" (a concise explanation).

QUALITY REQUIREMENTS:
- The definition MUST stand alone — understandable without extra context.
- Keep definitions concise (1-3 sentences).
- Cover diverse, high-value concepts across the document; do NOT cluster.
- Skip trivial or overly specific details; focus on what is worth memorizing.
- Do NOT fabricate. Every term/definition must come from the document.
{focus_clause}

SUITABILITY CHECK (set the "suitable" field accordingly):
- Set suitable=false IF the content is too short, too fragmented/unrelated, or has no meaningful terms/concepts to extract.
- When suitable=false: put a brief reason (in the document's language) in "reason" and leave "flashcards" an empty array.

Document content:
\"\"\"{content}\"\"\"
"""

_FOCUS_CLAUSE = (
    '\nSCOPE: Restrict the generated content to this specific topic/section only: "{focus}". '
    "Skip anything outside this scope."
)


def _build_prompt(template: str, content: str, count: int, focus: Optional[str]) -> str:
    return template.format(
        count=count,
        content=content,
        focus_clause=_FOCUS_CLAUSE.format(focus=focus) if focus else "",
    )


def _validate_quiz(items: List[QuizQuestion], count: int) -> List[dict]:
    """Strip invalid questions and truncate to `count`. Each question needs exactly 4
    options and a valid correct_index (already enforced by the schema, but defensive)."""
    out = []
    for q in items:
        if len(q.options) == QUIZ_OPTIONS_COUNT and 0 <= q.correct_index < QUIZ_OPTIONS_COUNT and q.question.strip():
            out.append(q.model_dump())
        if len(out) >= count:
            break
    return out


def _validate_flashcard(items: List[FlashcardItem], count: int) -> List[dict]:
    out = []
    for f in items:
        if f.term.strip() and f.definition.strip():
            out.append(f.model_dump())
        if len(out) >= count:
            break
    return out


@observe(name="quiz-generation")
def generate_quiz(document_id: str, count: int = QUIZ_DEFAULT, focus: Optional[str] = None) -> GenerationResult:
    """Generate a quiz from a document. See module docstring for the refusal model."""
    trace = start_trace("quiz_generate", document_id=document_id, count=count)
    try:
        with stage("content_fetch"), lf_span("content_fetch"):
            content = get_document_content(document_id, MAX_CONTENT_CHARS)
        if not content:
            return GenerationResult.refused_result(
                "Tài liệu chưa có nội dung đã đánh chỉ mục (embedding) để tạo câu hỏi."
            )
        if len(content) < MIN_CONTENT_CHARS_QUIZ:
            return GenerationResult.refused_result(
                "Nội dung tài liệu quá ngắn để tạo bộ câu hỏi chất lượng."
            )

        clamped = max(QUIZ_MIN, min(count, QUIZ_MAX))
        prompt = _build_prompt(_QUIZ_PROMPT, content, clamped, focus)
        structured_llm = llm.with_structured_output(QuizOutput)

        with stage("generation"), lf_span("generation"):
            result = _invoke_with_retry(structured_llm, prompt)

        if not result.suitable:
            logger.info("Quiz generation refused by LLM for document %s: %s", document_id, result.reason)
            return GenerationResult.refused_result(result.reason or "Nội dung tài liệu không phù hợp để tạo câu hỏi.")

        items = _validate_quiz(result.quiz, clamped)
        if not items:
            return GenerationResult.refused_result("Không thể tạo câu hỏi hợp lệ từ nội dung tài liệu.")
        trace.meta["generated"] = len(items)
        return GenerationResult(items=items)
    except Exception as e:
        logger.error("Quiz generation failed for document %s: %s", document_id, e)
        return GenerationResult.refused_result("Đã xảy ra lỗi khi tạo câu hỏi. Vui lòng thử lại sau.")
    finally:
        trace.emit()


@observe(name="flashcard-generation")
def generate_flashcards(document_id: str, count: int = FLASHCARD_DEFAULT, focus: Optional[str] = None) -> GenerationResult:
    """Generate flashcards from a document. See module docstring for the refusal model."""
    trace = start_trace("flashcard_generate", document_id=document_id, count=count)
    try:
        with stage("content_fetch"), lf_span("content_fetch"):
            content = get_document_content(document_id, MAX_CONTENT_CHARS)
        if not content:
            return GenerationResult.refused_result(
                "Tài liệu chưa có nội dung đã đánh chỉ mục (embedding) để tạo flashcard."
            )
        if len(content) < MIN_CONTENT_CHARS_FLASHCARD:
            return GenerationResult.refused_result(
                "Nội dung tài liệu quá ngắn để tạo flashcard chất lượng."
            )

        clamped = max(FLASHCARD_MIN, min(count, FLASHCARD_MAX))
        prompt = _build_prompt(_FLASHCARD_PROMPT, content, clamped, focus)
        structured_llm = llm.with_structured_output(FlashcardOutput)

        with stage("generation"), lf_span("generation"):
            result = _invoke_with_retry(structured_llm, prompt)

        if not result.suitable:
            logger.info("Flashcard generation refused by LLM for document %s: %s", document_id, result.reason)
            return GenerationResult.refused_result(result.reason or "Nội dung tài liệu không phù hợp để tạo flashcard.")

        items = _validate_flashcard(result.flashcards, clamped)
        if not items:
            return GenerationResult.refused_result("Không thể tạo flashcard hợp lệ từ nội dung tài liệu.")
        trace.meta["generated"] = len(items)
        return GenerationResult(items=items)
    except Exception as e:
        logger.error("Flashcard generation failed for document %s: %s", document_id, e)
        return GenerationResult.refused_result("Đã xảy ra lỗi khi tạo flashcard. Vui lòng thử lại sau.")
    finally:
        trace.emit()


def _invoke_with_retry(structured_llm, prompt: str, max_attempts: int = 2):
    """Invoke the structured LLM, retrying once on a schema/parse failure.

    `with_structured_output` parses Gemini's response into the pydantic model; a
    malformed response raises. One retry recovers most transient JSON drift without
    a second content fetch.
    """
    last_err = None
    for attempt in range(1, max_attempts + 1):
        try:
            return structured_llm.invoke(prompt, config={"callbacks": get_langchain_callbacks()})
        except Exception as e:
            last_err = e
            logger.warning("Structured-output attempt %d failed: %s", attempt, e)
    raise last_err
