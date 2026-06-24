import os
import logging
from datetime import datetime
import json
import urllib.request
import shutil
import time
from typing import List

from langchain_core.documents import Document
from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader
from app.core.clients import llm

from app.core.config import settings
from app.pipeline.dependencies import retriever, vectorstore, store, update_bm25

logger = logging.getLogger(__name__)

def generate_document_summary(docs: List[Document]) -> str:
    """
    Generates a concise summary of the document content using Gemini.
    """
    try:
        full_text = ""
        for doc in docs:
            full_text += doc.page_content + "\n"
            if len(full_text) > 20000:
                break
        
        if not full_text.strip():
            return "No content available to summarize."

        prompt = (
            "You are a professional study assistant.\n"
            "First, analyze the document content below to identify its primary language.\n"
            "Then, generate a concise summary (around 2-3 paragraphs) of the main points of the document. "
            "The summary must be written in the identified primary language of the document.\n"
            "Format the summary with a clear structure using Markdown.\n"
            "Return only the final summary. Do not include any language labels, preamble, or metadata in the response.\n\n"
            f"Document Content:\n{full_text[:20000]}"
        )
        
        response = llm.invoke(prompt)
        return response.content
    except Exception as e:
        logger.error(f"Failed to generate summary: {e}")
        return "The document was uploaded successfully, but an error occurred while generating the summary."

def send_callback(document_id: str, status: str, summary: str = "", max_retries: int = 3):
    callback_url = settings.BACKEND_CALLBACK_URL
    internal_secret = settings.INTERNAL_API_SECRET
    logger.info(f"Sending callback to backend: url={callback_url}, doc_id={document_id}, status={status}")
    
    payload = {
        "document_id": document_id,
        "status": status,
        "summary": summary
    }
    
    headers = {
        "Content-Type": "application/json",
        "X-Internal-Secret": internal_secret
    }
    
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(
                callback_url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                logger.info(f"Callback response status: {resp.status}")
                return
        except Exception as e:
            logger.error(f"Failed to send callback to backend (Attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                time.sleep(2 ** attempt)

def process_document_task(file_url: str, filename: str, metadata_input: dict):
    """
    Background task to process the uploaded document and ingest it into the RAG pipeline.
    """
    logger.info(f"Starting background processing for {filename}...")
    document_id = metadata_input.get("document_id")

    TEMP_DIR = settings.TEMP_DIR
    os.makedirs(TEMP_DIR, exist_ok=True)
    file_path = os.path.join(TEMP_DIR, f"{document_id}_{filename}")

    try:
        # --- A. Download File ---
        logger.info(f"Downloading file from S3: {file_url}")
        req = urllib.request.Request(
            file_url,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req) as response, open(file_path, "wb") as out_file:
            shutil.copyfileobj(response, out_file)

        # --- B. Load Document ---
        ext = os.path.splitext(filename)[1].lower()
        if ext == '.pdf':
            loader = PyPDFLoader(file_path)
        elif ext in ('.txt', '.md'):
            loader = TextLoader(file_path, encoding='utf-8')
        elif ext == '.docx':
            loader = Docx2txtLoader(file_path)
        else:
            logger.error(f"Unsupported file type: {ext}")
            if document_id:
                send_callback(document_id, "FAILED")
            return

        docs = loader.load()

        # --- C. Metadata Enrichment ---
        system_metadata = {
            "source_file": filename,
            "file_type": ext,
            "processed_date": datetime.now().isoformat()
        }
        
        for doc in docs:
            # Get page info if available (PyPDFLoader usually stores 'page' starting from 0)
            page_num = doc.metadata.get("page", 0) + 1
            
            # Document-level citation
            doc.metadata["document_citation"] = f"Document ID: {document_id}, File: {filename}"
            # Chunk/Page-level citation
            doc.metadata["chunk_citation"] = f"Page: {page_num}"
            
            doc.metadata.update(system_metadata)
            doc.metadata.update(metadata_input)

        # --- D. Parent-Child Indexing (Small-to-Big Strategy) ---
        logger.info("Executing Parent-Child chunking and vector indexing...")
        retriever.add_documents(docs, ids=None)

        # --- E. Pipeline Output Summary ---
        parent_docs_count = len(list(store.yield_keys()))
        child_chunks_count = vectorstore.count_chunks()
        
        logger.info(
            f"\n--- Indexing Summary ---\n"
            f"File processed: {filename}\n"
            f"Total Parent Documents in Store: {parent_docs_count}\n"
            f"Total Child Chunks in VectorStore: {child_chunks_count}\n"
            f"------------------------\n"
        )

        # --- F. Rebuild BM25 Retriever ---
        update_bm25()

        # --- G. Generate Summary & Call Backend ---
        if document_id:
            logger.info("Generating LLM summary for the document...")
            summary = generate_document_summary(docs)
            send_callback(document_id, "SUCCESS", summary)

    except Exception as e:
        logger.error(f"Error processing document {filename}: {e}")
        if document_id:
            send_callback(document_id, "FAILED")
    finally:
        # --- H. Cleanup ---
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Cleaned up temporary file: {file_path}")
