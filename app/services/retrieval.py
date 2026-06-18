import logging
from langchain.retrievers import EnsembleRetriever
from langchain.retrievers.multi_query import MultiQueryRetriever
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.retrievers import ContextualCompressionRetriever
from langchain_community.document_compressors import JinaRerank
import os
from langchain_core.callbacks.manager import CallbackManagerForRetrieverRun

from app.pipeline.dependencies import retriever, state

logger = logging.getLogger(__name__)

from app.database.document_store import get_document_title
from typing import List
def retrieve_documents(query: str, document_ids: List[str] = None):
    """
    Executes the advanced retrieval phase combining Multi-Query generation
    and Hybrid Search (BM25 + Dense Parent/Child).
    """
    bm25_retriever = state.bm25_retriever

    if not bm25_retriever:
        raise ValueError("No documents have been indexed yet. BM25Retriever is empty.")

    # Inject filter into ParentDocumentRetriever if document_ids is provided
    # pgvector and langchain postgres support {"document_ids": [...]} or {"document_id": {"$in": [...]}}
    # Temporarily assign to search_kwargs
    if document_ids:
        retriever.search_kwargs["filter"] = {"document_ids": document_ids}
    else:
        # Remove old filter if any
        retriever.search_kwargs.pop("filter", None)

    # --- A. Hybrid Search (Ensemble Retriever) ---
    # Combine the sparse (keyword) and dense (semantic) retrievers.
    # Weights: 30% importance to exact keyword match, 70% to semantic meaning.
    ensemble_retriever = EnsembleRetriever(
        retrievers=[bm25_retriever, retriever],
        weights=[0.3, 0.7]
    )

    # --- B. Multi-Query Generation ---
    # We use Google Gemini to generate multiple perspectives of the original query.
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", temperature=0)
    
    # Initialize the MultiQueryRetriever
    mq_retriever = MultiQueryRetriever.from_llm(
        retriever=ensemble_retriever,
        llm=llm
    )

    # --- C. Cross-Encoder Re-ranking (Bottom of Funnel) ---
    # We use Jina AI Reranker API to efficiently score the top documents without consuming local RAM.
    # It will return the top 5 most relevant documents.
    compressor = JinaRerank(
        jina_api_key=os.environ.get("JINA_API_KEY"),
        model="jina-reranker-v3",
        top_n=5
    )
    
    # Wrap the MultiQueryRetriever with the CompressionRetriever
    compression_retriever = ContextualCompressionRetriever(
        base_compressor=compressor,
        base_retriever=mq_retriever
    )

    # --- D. Execution & Extraction ---
    # Extract the generated queries first for the API response.
    try:
        run_manager = CallbackManagerForRetrieverRun.get_noop_manager()
        generated_queries = mq_retriever.generate_queries(query, run_manager)
    except Exception as e:
        logger.warning(f"Failed to extract generated queries cleanly: {e}")
        generated_queries = []

    # Now, run the entire funnel!
    # Original Query -> Gemini (3 queries) -> BM25 + Dense (k=25 each) -> Deduplicate -> Cross-Encoder -> Top 5
    logger.info("Executing Full Funnel: Multi-Query -> Hybrid Search -> Cross-Encoder Re-ranking...")
    retrieved_docs = compression_retriever.invoke(query)

    # Format output for the API response
    results = []
    
    # Post-filtering for BM25 Leakage mitigation
    valid_retrieved_docs = []
    if document_ids:
        for d in retrieved_docs:
            doc_id = d.metadata.get("document_id") or d.metadata.get("document_citation", "").split(",")[0].replace("Document ID: ", "").strip()
            # Check data safety to prevent BM25 from returning other users' documents
            if doc_id in document_ids:
                valid_retrieved_docs.append(d)
    else:
        valid_retrieved_docs = retrieved_docs

    title_cache = {}

    for d in valid_retrieved_docs:
        doc_citation = d.metadata.get("document_citation", f"File: {d.metadata.get('source_file', 'Unknown')}")
        chunk_citation = d.metadata.get("chunk_citation", "")
        
        # Determine document ID to fetch title
        doc_id = d.metadata.get("document_id")
        if not doc_id and "Document ID: " in doc_citation:
            doc_id = doc_citation.split(",")[0].replace("Document ID: ", "").strip()
            
        doc_title = "Unknown Title"
        if doc_id:
            if doc_id not in title_cache:
                title_cache[doc_id] = get_document_title(doc_id)
            doc_title = title_cache[doc_id]
        
        # Update metadata to explicitly include title
        d.metadata["document_title"] = doc_title
        
        # Update the document_citation in metadata to include the title
        updated_doc_citation = f"Title: {doc_title}, {doc_citation}"
        d.metadata["document_citation"] = updated_doc_citation
        
        # Concatenate citation to prepend right above the returned content
        combined_citation = f"[{updated_doc_citation}, {chunk_citation}]"
        formatted_content = f"{combined_citation}\n{d.page_content}"
        
        results.append({
            "content": formatted_content,
            "metadata": d.metadata
        })

    return {
        "original_query": query,
        "generated_queries": generated_queries,
        "documents": results
    }
