import os
import re
import logging
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from pydantic import BaseModel

# Import from the new modular structure
from app.services.ingestion import (
    process_document_task,
    extract_document_task,
    index_document_task,
    delete_document,
    update_document_visibility,
)
from app.services.router import route_chat_request
from app.services.generation import generate_rag_response
from app.services.guardrail import check_chat_request, detect_prompt_injection
from app.services.study_material import (
    generate_quiz,
    generate_flashcards,
    QUIZ_MIN, QUIZ_MAX, QUIZ_DEFAULT,
    FLASHCARD_MIN, FLASHCARD_MAX, FLASHCARD_DEFAULT,
)
from app.pipeline.dependencies import initialize_bm25
from app.core.performance import start_trace
from app.core.langfuse_client import trace_chat, trace_material

from typing import Optional, List
from datetime import datetime, timezone

class ChatHistoryItem(BaseModel):
    """Một lượt hội thoại trước đó (multi-turn memory, P0)."""
    role: str  # "user" | "assistant" (bất kỳ giá trị khác -> assistant)
    content: str

class ChatRequest(BaseModel):
    query: str
    user_id: str
    document_id: Optional[str] = None
    history: List[ChatHistoryItem] = []

class ProcessRequest(BaseModel):
    document_id: str
    file_url: str

class IndexRequest(BaseModel):
    document_id: str

class VisibilityRequest(BaseModel):
    visibility: str

class StudyMaterialRequest(BaseModel):
    document_id: str
    count: Optional[int] = None   # clamped per-type in the endpoint
    focus: Optional[str] = None   # optional topic scope; guarded against injection

app = FastAPI(
    title="RAG Ingestion Pipeline", 
    description="A modular RAG ingestion pipeline using FastAPI.",
    version="1.0"
)

# Startup event: initialize BM25 + warm up external API clients.
@app.on_event("startup")
async def startup_event():
    initialize_bm25()
    _warmup_clients()


def _warmup_clients(timeout_s: float = 20.0):
    """Đàm (warm up) client LLM + embedding ngay lúc startup.

    Request đầu sau mỗi lần khởi động từng chịu cold-start ~14s ở Gemini (TLS +
    OAuth token + SDK init, có thể kèm retry). Warmup đẩy chi phí đó về startup
    thay vì lên request đầu của user. Chạy trong thread kèm timeout để không block
    startup vô hạn; lỗi warmup không làm sập server.
    """
    import threading

    from app.core.clients import llm
    from app.pipeline.dependencies import embeddings

    warmup_logger = logging.getLogger("warmup")
    result = {"ok": False}

    def _do():
        try:
            llm.invoke("hi")
            embeddings.embed_query("warmup")
            result["ok"] = True
        except Exception as e:  # noqa: BLE001
            result["err"] = str(e)

    warmup_logger.info("Warming up LLM + embeddings clients...")
    t = threading.Thread(target=_do, daemon=True)
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        warmup_logger.warning(
            "Warmup chưa xong sau %.0fs — request đầu có thể chậm.", timeout_s
        )
    elif result.get("ok"):
        warmup_logger.info("Warmup complete.")
    else:
        warmup_logger.warning(
            "Warmup failed (%s) — sẽ warm lười ở request đầu.", result.get("err")
        )

@app.post("/api/v1/rag/process")
async def process_document(
    request: ProcessRequest,
    background_tasks: BackgroundTasks
):
    """
    Endpoint called by the Java backend to trigger document processing.
    Downloads the file from file_url and indexes it in the background.
    """
    from urllib.parse import urlparse
    parsed_url = urlparse(request.file_url)
    path = parsed_url.path
    filename = os.path.basename(path)
    if not filename:
        filename = f"{request.document_id}.pdf"

    # Trigger background task
    metadata = {
        "document_id": request.document_id
    }
    background_tasks.add_task(process_document_task, request.file_url, filename, metadata)

    return JSONResponse(
        content={
            "status": "success",
            "message": "Document download complete, indexing started in background"
        },
        status_code=202
    )

def _filename_from_url(file_url: str, document_id: str) -> str:
    from urllib.parse import urlparse
    filename = os.path.basename(urlparse(file_url).path)
    return filename or f"{document_id}.pdf"


@app.post("/api/v1/rag/extract")
async def extract_document(request: ProcessRequest, background_tasks: BackgroundTasks):
    """PUBLIC documents: extract only (NULL-embedding chunks) for moderation.

    Chunks become available at GET /api/v1/rag/documents/{id}/chunks. Indexing
    is deferred to /api/v1/rag/index until the document is approved. Sends an
    EXTRACTED callback (summary included); backend status stays PENDING.
    """
    filename = _filename_from_url(request.file_url, request.document_id)
    metadata = {"document_id": request.document_id}
    background_tasks.add_task(extract_document_task, request.file_url, filename, metadata)
    return JSONResponse(
        content={
            "status": "accepted",
            "message": "Extraction started; chunks will be available for moderation",
        },
        status_code=202,
    )


@app.post("/api/v1/rag/index")
def index_document(request: IndexRequest, background_tasks: BackgroundTasks):
    """Approved public document: embed pending chunks + rebuild BM25 (background)."""
    background_tasks.add_task(index_document_task, request.document_id)
    return JSONResponse(
        content={"status": "accepted", "message": "Indexing started in background"},
        status_code=202,
    )


@app.patch("/api/v1/rag/documents/{document_id}/visibility")
def patch_visibility(document_id: str, request: VisibilityRequest):
    """Stamp a visibility flag into chunk metadata (metadata only)."""
    result = update_document_visibility(document_id, request.visibility)
    return JSONResponse(content=result, status_code=200)


@app.delete("/api/v1/rag/documents/{document_id}")
def delete_document_endpoint(document_id: str):
    """Delete every chunk + parent doc for a document (reject / delete flows)."""
    result = delete_document(document_id)
    return JSONResponse(content=result, status_code=200)

_CITATION_RE = re.compile(r"\[(\d+)\]")

def _lf_record(root, *, route: str, answer: str = None, retrieved_count: int = 0,
               refusal: str = None, empty_retrieval: bool = False, error: str = None):
    """Ghi metadata + score lên root trace. No-op nếu root None hoặc lỗi (fail-open).

    `route` ∈ {guardrail_block, smalltalk, summary, qa, error, exception}.
    `citation_coverage` score (range 0..1) = tỷ lệ marker [N] hợp lệ (1..retrieved_count)
    xuất hiện trong answer / số docs retrieved — chỉ chấm cho QA branch có answer + context.
    """
    if not root:
        return
    try:
        meta = {"route": route, "empty_retrieval": empty_retrieval}
        if retrieved_count:
            meta["retrieved_count"] = retrieved_count
        if refusal:
            meta["refusal_category"] = refusal
        if error:
            meta["error"] = error[:200]
        root.update(metadata=meta)
        if route == "qa" and answer and retrieved_count > 0 and not empty_retrieval:
            found = {int(m) for m in _CITATION_RE.findall(answer)}
            valid = sum(1 for n in found if 1 <= n <= retrieved_count)
            root.score(name="citation_coverage", value=round(valid / retrieved_count, 3))
    except Exception:
        pass  # tracing không được làm sập request

def _lf_record_material(root, *, kind: str, result=None, refused: bool = False,
                        refusal_category: str = None, generated: int = 0, error: str = None):
    """Ghi metadata cho quiz/flashcard trace. No-op nếu root None (fail-open).

    `kind` ∈ {quiz, flashcard}. `result` (GenerationResult) nếu có -> tự lấy refused/items.
    """
    if not root:
        return
    try:
        if result is not None:
            refused = result.refused
            generated = len(result.items)
            error = result.reason if result.refused else None
        meta = {"route": kind, "refused": refused}
        if generated:
            meta["generated"] = generated
        if refusal_category:
            meta["refusal_category"] = refusal_category
        if error:
            meta["error"] = error[:200]
        root.update(metadata=meta)
    except Exception:
        pass  # tracing không được làm sập request

@app.post("/api/v1/chat")
def chat_router(request: ChatRequest):
    """
    Intent routing endpoint (deterministic, no LLM): SMALLTALK -> SUMMARY -> QA.
    - Smalltalk (greetings/thanks): canned reply, no retrieval.
    - Summary (explicit summary request on a selected doc): precomputed summary.
    - QA (default): hybrid retrieval + Gemini generation with [N] citations.
    """
    # S3: sync `def` handler -> FastAPI chạy trong threadpool, không chặn event loop.
    trace = start_trace("chat", user_id=request.user_id, document_id=request.document_id)
    with trace_chat(request.query, request.user_id, request.document_id) as lf_root:
        try:
            history_dicts = [h.model_dump() for h in request.history]
            gr = check_chat_request(request.query, history_dicts)
            if not gr.allowed:
                # Guardrail block -> HTTP 200 với lời từ chối chuẩn (giống pattern
                # smalltalk/empty-retrieval). KHÔNG gọi retrieval/generation.
                _lf_record(lf_root, route="guardrail_block", refusal=gr.category)
                timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                return JSONResponse(
                    status_code=200,
                    content={
                        "success": True,
                        "message": "Answer generated successfully",
                        "data": {
                            "llm_response": gr.refusal,
                            "debug": {
                                "guardrail": {"category": gr.category, "reason": gr.reason},
                                "timing": trace.as_dict(),
                            },
                        },
                        "timestamp": timestamp,
                    },
                )
            result = route_chat_request(request.query, request.user_id, request.document_id, history=history_dicts)
            timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

            if result.get("type") == "error":
                _lf_record(lf_root, route="error", error=result.get("message"))
                return JSONResponse(
                    status_code=400,
                    content={
                        "success": False,
                        "message": result.get("message", "Error"),
                        "data": {},
                        "timestamp": timestamp
                    }
                )
            elif result.get("type") == "smalltalk":
                _lf_record(lf_root, route="smalltalk")
                return JSONResponse(
                    status_code=200,
                    content={
                        "success": True,
                        "message": "Answer generated successfully",
                        "data": {
                            "llm_response": result.get("content", ""),
                            "debug": {"timing": trace.as_dict()}
                        },
                        "timestamp": timestamp
                    }
                )
            elif result.get("type") == "summary":
                _lf_record(lf_root, route="summary")
                return JSONResponse(
                    status_code=200,
                    content={
                        "success": True,
                        "message": "Summary retrieved successfully",
                        "data": {
                            "llm_response": result.get("content", ""),
                            "debug": {"timing": trace.as_dict()}
                        },
                        "timestamp": timestamp
                    }
                )
            else:  # type == "qa"
                retrieval_data = result.get("retrieval_data", {})
                documents = retrieval_data.get("documents", [])
                if not documents:
                    # P1: retrieval không tìm thấy đoạn liên quan -> KHÔNG gọi LLM trên
                    # context rỗng (tránh hallucination + tiết kiệm 1 LLM call).
                    llm_answer = (
                        "Không tìm thấy thông tin liên quan trong tài liệu "
                        "để trả lời câu hỏi này."
                    )
                    _lf_record(lf_root, route="qa", empty_retrieval=True)
                else:
                    llm_answer = generate_rag_response(
                        request.query,
                        documents,
                        history_dicts,
                    )
                    _lf_record(lf_root, route="qa", answer=llm_answer, retrieved_count=len(documents))
                return JSONResponse(
                    status_code=200,
                    content={
                        "success": True,
                        "message": "Answer generated successfully",
                        "data": {
                            "llm_response": llm_answer,
                            "debug": {**retrieval_data, "timing": trace.as_dict()},
                        },
                        "timestamp": timestamp
                    }
                )

        except Exception as e:
            _lf_record(lf_root, route="exception", error=str(e))
            timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            return JSONResponse(status_code=500, content={"success": False, "message": f"Router failed: {str(e)}", "data": {}, "timestamp": timestamp})
        finally:
            trace.emit(query=request.query)

def _material_envelope(result, payload_key: str, trace, message_ok: str):
    """Build the wire response for quiz/flashcard endpoints.

    A refusal (refused=True) maps to HTTP 200 + success:true + empty items +
    debug.refused (NOT an error), matching the guardrail canned-refusal pattern —
    the backend cannot tell a refusal from a success by status code and instead
    inspects debug.refused / item count. Genuine errors surface inside the service
    as a refused_result, so the endpoint never returns a raw 500 for them.
    """
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if result.refused:
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": result.reason,
                "data": {
                    payload_key: [],
                    "debug": {"refused": True, "reason": result.reason, "timing": trace.as_dict()},
                },
                "timestamp": timestamp,
            },
        )
    return JSONResponse(
        status_code=200,
        content={
            "success": True,
            "message": message_ok,
            "data": {
                payload_key: result.items,
                "debug": {"refused": False, "timing": trace.as_dict()},
            },
            "timestamp": timestamp,
        },
    )


def _check_focus_guardrail(focus: Optional[str]):
    """Guard the optional `focus` free-text against prompt injection (regex, always ON).

    No full guardrail run: quiz/flashcard generation has no user free-text `query`
    (only document_id + count); `focus` is the only user-controlled string, and the
    document content itself is moderated upstream at ingestion.
    """
    if not focus or not focus.strip():
        return None
    return detect_prompt_injection(focus)


@app.post("/api/v1/quiz/generate")
def generate_quiz_endpoint(request: StudyMaterialRequest):
    """Generate a multiple-choice quiz from one document (Gemini, structured JSON).

    Refuses (HTTP 200, empty `quiz`) when the document is too short / fragmented /
    not indexed. `focus` optionally scopes questions to a topic (injection-guarded).
    """
    trace = start_trace("quiz_endpoint", document_id=request.document_id)
    count = request.count if request.count is not None else QUIZ_DEFAULT
    with trace_material("quiz", request.document_id, count=count, focus=request.focus or "") as lf_root:
        try:
            block = _check_focus_guardrail(request.focus)
            if block and not block.allowed:
                _lf_record_material(lf_root, kind="quiz", refused=True, refusal_category=block.category)
                timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                return JSONResponse(
                    status_code=200,
                    content={
                        "success": True,
                        "message": block.refusal,
                        "data": {
                            "quiz": [],
                            "debug": {
                                "refused": True,
                                "guardrail": {"category": block.category, "reason": block.reason},
                                "timing": trace.as_dict(),
                            },
                        },
                        "timestamp": timestamp,
                    },
                )
            result = generate_quiz(request.document_id, count=count, focus=request.focus)
            _lf_record_material(lf_root, kind="quiz", result=result)
            return _material_envelope(result, "quiz", trace, "Quiz generated successfully")
        finally:
            trace.emit()


@app.post("/api/v1/flashcard/generate")
def generate_flashcard_endpoint(request: StudyMaterialRequest):
    """Generate flashcards from one document (Gemini, structured JSON).

    Refuses (HTTP 200, empty `flashcards`) when the document is too short /
    fragmented / not indexed. `focus` optionally scopes cards to a topic.
    """
    trace = start_trace("flashcard_endpoint", document_id=request.document_id)
    count = request.count if request.count is not None else FLASHCARD_DEFAULT
    with trace_material("flashcard", request.document_id, count=count, focus=request.focus or "") as lf_root:
        try:
            block = _check_focus_guardrail(request.focus)
            if block and not block.allowed:
                _lf_record_material(lf_root, kind="flashcard", refused=True, refusal_category=block.category)
                timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                return JSONResponse(
                    status_code=200,
                    content={
                        "success": True,
                        "message": block.refusal,
                        "data": {
                            "flashcards": [],
                            "debug": {
                                "refused": True,
                                "guardrail": {"category": block.category, "reason": block.reason},
                                "timing": trace.as_dict(),
                            },
                        },
                        "timestamp": timestamp,
                    },
                )
            result = generate_flashcards(request.document_id, count=count, focus=request.focus)
            _lf_record_material(lf_root, kind="flashcard", result=result)
            return _material_envelope(result, "flashcards", trace, "Flashcards generated successfully")
        finally:
            trace.emit()

if __name__ == "__main__":
    import uvicorn
    # To run this script: `python main.py` or `uvicorn main:app --reload`
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
