import os
import shutil
import urllib.request
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import JSONResponse
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from pydantic import BaseModel

# Import the processing task from our RAG pipeline module
from rag_pipeline import process_document_task, retrieve_documents

class QueryRequest(BaseModel):
    query: str

class ProcessRequest(BaseModel):
    document_id: str
    file_url: str

app = FastAPI(
    title="RAG Ingestion Pipeline", 
    description="A simplified monolithic RAG ingestion pipeline using FastAPI's BackgroundTasks.",
    version="1.0"
)

# Ensure temp directory exists for saving files locally before background processing
TEMP_DIR = "temp"
os.makedirs(TEMP_DIR, exist_ok=True)

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
async def retrieve_chat(request: QueryRequest):
    """
    Endpoint to retrieve relevant documents using Hybrid Search (BM25 + Dense)
    and Multi-Query generation.
    """
    try:
        result = retrieve_documents(request.query)
        return JSONResponse(content=result, status_code=200)
    except ValueError as ve:
        # E.g., when BM25 is empty because no docs are indexed yet
        return JSONResponse(status_code=400, content={"status": "error", "message": str(ve)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"Retrieval failed: {str(e)}"})

if __name__ == "__main__":
    import uvicorn
    # To run this script: `python main.py` or `uvicorn main:app --reload`
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
