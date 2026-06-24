import os
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from pydantic import BaseModel

# Import from the new modular structure
from app.services.ingestion import process_document_task
from app.services.retrieval import retrieve_documents
from app.services.router import route_chat_request
from app.services.generation import generate_rag_response
from app.pipeline.dependencies import initialize_bm25
from app.core.performance import start_trace

from typing import Optional
from datetime import datetime, timezone

class ChatRequest(BaseModel):
    query: str
    user_id: str
    document_id: Optional[str] = None

class QueryRequest(BaseModel):
    query: str

class ProcessRequest(BaseModel):
    document_id: str
    file_url: str

app = FastAPI(
    title="RAG Ingestion Pipeline", 
    description="A modular RAG ingestion pipeline using FastAPI.",
    version="1.0"
)

# Startup event to initialize BM25
@app.on_event("startup")
async def startup_event():
    initialize_bm25()

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

@app.post("/api/v1/chat/retrieve")
def retrieve_chat(request: QueryRequest):
    """
    Endpoint to retrieve relevant documents using Hybrid Search (BM25 + Dense)
    and Multi-Query generation.
    """
    # S3: sync `def` handler -> FastAPI chạy trong threadpool, không chặn event loop.
    trace = start_trace("retrieve", query=request.query)
    try:
        result = retrieve_documents(request.query)
        result["timing"] = trace.as_dict()
        return JSONResponse(content=result, status_code=200)
    except ValueError as ve:
        # E.g., when BM25 is empty because no docs are indexed yet
        return JSONResponse(status_code=400, content={"status": "error", "message": str(ve)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"Retrieval failed: {str(e)}"})
    finally:
        trace.emit(query=request.query)

@app.post("/api/v1/chat")
def chat_router(request: ChatRequest):
    """
    Intelligent routing endpoint.
    Uses LLM to route between:
    - Summary fetch (if query asks for summary)
    - Full RAG retrieval (if query asks about content)
    """
    # S3: sync `def` handler -> FastAPI chạy trong threadpool, không chặn event loop.
    trace = start_trace("chat", user_id=request.user_id, document_id=request.document_id)
    try:
        result = route_chat_request(request.query, request.user_id, request.document_id)
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        if result.get("type") == "error":
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": result.get("message", "Error"),
                    "data": {},
                    "timestamp": timestamp
                }
            )
        elif result.get("type") == "summary":
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
            llm_answer = generate_rag_response(request.query, documents)
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
        timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return JSONResponse(status_code=500, content={"success": False, "message": f"Router failed: {str(e)}", "data": {}, "timestamp": timestamp})
    finally:
        trace.emit(query=request.query)

if __name__ == "__main__":
    import uvicorn
    # To run this script: `python main.py` or `uvicorn main:app --reload`
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
