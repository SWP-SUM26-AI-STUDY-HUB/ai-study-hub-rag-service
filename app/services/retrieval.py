import logging
from typing import List

from langchain.retrievers import EnsembleRetriever
from langchain.retrievers.multi_query import MultiQueryRetriever
from pydantic import Field

# S2: dùng singleton LLM/reranker thay vì new mỗi request.
from app.core.clients import llm, reranker
# Instrumentation: đo từng giai đoạn của funnel.
from app.core.performance import stage
from app.database.document_store import get_document_title
from app.pipeline.dependencies import retriever, state

logger = logging.getLogger(__name__)


class CapturingMultiQueryRetriever(MultiQueryRetriever):
    """Ghi lại các sub-query do đúng một lời gọi LLM sinh ra trong invoke().

    Nhờ đó caller đọc được `generated_queries` sau khi chạy funnel, thay vì phải
    gọi thêm `generate_queries()` riêng (S1 — tránh 1 LLM call trùng lặp ~1.5s).
    """

    captured_queries: List[str] = Field(default_factory=list)

    def generate_queries(self, question: str, run_manager) -> List[str]:
        # Instrumentation: tách riêng LLM sinh sub-query khỏi phần search loop.
        with stage("query_generation"):
            queries = super().generate_queries(question, run_manager)
        self.captured_queries = list(queries) if queries else []
        return queries


def retrieve_documents(query: str, document_ids: List[str] = None):
    """
    Thực thi pipeline truy vấn: Hybrid Search (BM25 + Dense) + Multi-Query
    Generation + Cross-Encoder Re-ranking. Trả về top tài liệu liên quan.
    """
    bm25_retriever = state.bm25_retriever

    if not bm25_retriever:
        raise ValueError("No documents have been indexed yet. BM25Retriever is empty.")

    # Inject filter vào ParentDocumentRetriever nếu có document_ids.
    # (BM25 vẫn chưa nhận filter — đây là lỗ hổng leakage sẽ xử lý ở S6.)
    if document_ids:
        retriever.search_kwargs["filter"] = {"document_ids": document_ids}
    else:
        retriever.search_kwargs.pop("filter", None)

    # --- A. Hybrid Search (Ensemble Retriever) ---
    # 30% keyword (BM25), 70% semantic (dense).
    ensemble_retriever = EnsembleRetriever(
        retrievers=[bm25_retriever, retriever],
        weights=[0.3, 0.7]
    )

    # --- B. Multi-Query (dùng LLM singleton S2 + capturing S1) ---
    mq_retriever = CapturingMultiQueryRetriever.from_llm(
        retriever=ensemble_retriever,
        llm=llm
    )

    # Full funnel: sinh sub-query (1 LLM) + hybrid search từng sub-query,
    # sau đó Jina rerank riêng để đo trúng từng giai đoạn.
    logger.info("Executing Full Funnel: Multi-Query -> Hybrid Search -> Cross-Encoder Re-ranking...")
    with stage("multi_query_search"):
        # mq_retriever.invoke chạy: generate_queries (1 LLM, bị capture) ->
        # lặp từng sub-query qua EnsembleRetriever (embed + SQL + BM25 + docstore).
        candidates = mq_retriever.invoke(query)
    generated_queries = list(mq_retriever.captured_queries)

    # --- C. Cross-Encoder Re-ranking (tách riêng để đo, dùng singleton S2) ---
    with stage("rerank"):
        retrieved_docs = reranker.compress_documents(candidates, query)

    # --- D. Post-filtering (BM25 leakage mitigation, sẽ đưa vào BM25 ở S6) ---
    valid_retrieved_docs = []
    if document_ids:
        for d in retrieved_docs:
            doc_id = d.metadata.get("document_id") or d.metadata.get(
                "document_citation", ""
            ).split(",")[0].replace("Document ID: ", "").strip()
            # Check data safety to prevent BM25 from returning other users' documents
            if doc_id in document_ids:
                valid_retrieved_docs.append(d)
    else:
        valid_retrieved_docs = retrieved_docs

    # --- E. Format output + fetch title (đo riêng thời gian DB lookup) ---
    results = []
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
                with stage("title_fetch"):
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
