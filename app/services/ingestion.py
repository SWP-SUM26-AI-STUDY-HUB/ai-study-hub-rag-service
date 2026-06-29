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

def _download_and_load(file_url: str, filename: str, document_id: str):
    """Steps A-C: download from S3, load by extension, enrich metadata.

    Returns (docs, file_path). On unsupported extension returns (None, file_path)
    so the caller can still clean up the temp file and send a FAILED callback.
    """
    temp_dir = settings.TEMP_DIR
    os.makedirs(temp_dir, exist_ok=True)
    file_path = os.path.join(temp_dir, f"{document_id}_{filename}")

    # A. Download
    logger.info(f"Downloading file from S3: {file_url}")
    req = urllib.request.Request(file_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as response, open(file_path, "wb") as out_file:
        shutil.copyfileobj(response, out_file)

    # B. Load
    ext = os.path.splitext(filename)[1].lower()
    if ext == '.pdf':
        loader = PyPDFLoader(file_path)
    elif ext in ('.txt', '.md'):
        loader = TextLoader(file_path, encoding='utf-8')
    elif ext == '.docx':
        loader = Docx2txtLoader(file_path)
    else:
        logger.error(f"Unsupported file type: {ext}")
        return None, file_path
    docs = loader.load()

    # C. Metadata enrichment (page/chunk citations + document_id)
    system_metadata = {
        "source_file": filename,
        "file_type": ext,
        "processed_date": datetime.now().isoformat(),
    }
    for doc in docs:
        page_num = doc.metadata.get("page", 0) + 1
        doc.metadata["document_citation"] = f"Document ID: {document_id}, File: {filename}"
        doc.metadata["chunk_citation"] = f"Page: {page_num}"
        doc.metadata.update(system_metadata)
        doc.metadata["document_id"] = document_id
    return docs, file_path


def _extract_to_store(docs: List[Document], document_id: str):
    """Step D: parent-child split, store parent docs, insert child chunks with
    embedding = NULL (deferred until moderation + index). Returns (parents, children).

    Reuses ParentDocumentRetriever._split_docs_for_adding so children carry
    metadata[doc_id] = parent uuid and parent-fetch retrieval stays intact.
    """
    logger.info("Executing Parent-Child chunking (embedding deferred)...")
    child_docs, parent_pairs = retriever._split_docs_for_adding(
        docs, ids=None, add_to_docstore=True
    )
    store.mset(parent_pairs)  # persist parents keyed by uuid
    child_count = vectorstore.add_texts_without_embedding(child_docs)
    logger.info(
        f"Extracted document {document_id}: {len(parent_pairs)} parent doc(s), "
        f"{child_count} child chunk(s) (embedding deferred)."
    )
    return len(parent_pairs), child_count


def process_document_task(file_url: str, filename: str, metadata_input: dict):
    """PRIVATE documents: extract + index + summary in one pass (no moderation)."""
    logger.info(f"Starting background processing for {filename}...")
    document_id = metadata_input.get("document_id")
    file_path = None
    try:
        docs, file_path = _download_and_load(file_url, filename, document_id)
        if docs is None:
            if document_id:
                send_callback(document_id, "FAILED")
            return
        _extract_to_store(docs, document_id)
        # Private docs skip moderation -> index immediately.
        vectorstore.embed_pending_chunks(document_id)
        update_bm25()
        summary = generate_document_summary(docs) if document_id else ""
        if document_id:
            send_callback(document_id, "SUCCESS", summary)
    except Exception as e:
        logger.error(f"Error processing document {filename}: {e}")
        if document_id:
            send_callback(document_id, "FAILED")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Cleaned up temporary file: {file_path}")


def extract_document_task(file_url: str, filename: str, metadata_input: dict):
    """PUBLIC documents: extract only (NULL-embedding children) + summary.

    Chunks become available via GET /documents/{id}/chunks for the moderation
    service. Embedding/indexing is deferred to ``index_document_task`` after
    approval. Sends EXTRACTED (summary included); the backend status is left
    untouched (stays PENDING).
    """
    logger.info(f"Starting background EXTRACTION (public) for {filename}...")
    document_id = metadata_input.get("document_id")
    file_path = None
    try:
        docs, file_path = _download_and_load(file_url, filename, document_id)
        if docs is None:
            if document_id:
                send_callback(document_id, "FAILED")
            return
        _extract_to_store(docs, document_id)
        # NO embedding, NO BM25 rebuild — wait for moderation + approval.
        summary = generate_document_summary(docs) if document_id else ""
        if document_id:
            send_callback(document_id, "EXTRACTED", summary)
    except Exception as e:
        logger.error(f"Error extracting document {filename}: {e}")
        if document_id:
            send_callback(document_id, "FAILED")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Cleaned up temporary file: {file_path}")


def index_document_task(document_id: str):
    """Approved public document: embed pending chunks + rebuild BM25.

    Idempotent: if already indexed (private->public update where /process
    embedded earlier), embed_pending_chunks is a no-op. Sends SUCCESS (no
    summary — already stored at extract time).
    """
    logger.info(f"Indexing document {document_id}...")
    try:
        count = vectorstore.embed_pending_chunks(document_id)
        update_bm25()
        logger.info(f"Indexed {count} chunk(s) for document {document_id}.")
        send_callback(document_id, "SUCCESS")
    except Exception as e:
        logger.error(f"Error indexing document {document_id}: {e}")
        send_callback(document_id, "FAILED")


def delete_document(document_id: str) -> dict:
    """Remove every chunk + parent doc for a document (reject / delete flows)."""
    logger.info(f"Deleting vectors + parent docs for document {document_id}...")
    try:
        count, parent_ids = vectorstore.delete_by_document_id(document_id)
        if parent_ids:
            store.mdelete(parent_ids)
        update_bm25()
        logger.info(
            f"Deleted {count} chunk(s) + {len(parent_ids)} parent doc(s) for {document_id}."
        )
        return {"chunks_deleted": count, "parents_deleted": len(parent_ids)}
    except Exception as e:
        logger.error(f"Error deleting document {document_id}: {e}")
        return {"chunks_deleted": 0, "parents_deleted": 0, "error": str(e)}


def update_document_visibility(document_id: str, visibility: str) -> dict:
    """Stamp visibility into chunk metadata (metadata only; Java gates retrieval)."""
    logger.info(f"Updating visibility={visibility} for document {document_id}...")
    try:
        updated = vectorstore.update_chunk_visibility(document_id, visibility)
        return {"chunks_updated": updated}
    except Exception as e:
        logger.error(f"Error updating visibility for {document_id}: {e}")
        return {"chunks_updated": 0, "error": str(e)}
