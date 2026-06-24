import logging
import os
from typing import List

from langchain.retrievers import EnsembleRetriever
from langchain.retrievers.multi_query import MultiQueryRetriever
from langchain_community.retrievers import BM25Retriever
from pydantic import Field

# S2: dùng singleton LLM/reranker thay vì new mỗi request.
from app.core.clients import llm, reranker
# Instrumentation: đo từng giai đoạn của funnel.
from app.core.performance import stage
from app.database.document_store import get_document_title
from app.pipeline.dependencies import retriever, state

logger = logging.getLogger(__name__)

# S8: Multi-Query mặc định TẮT. Theo đo lường, `query_generation` chiếm ~6s/request
# và đa phần QA không cần. Bật bằng ENABLE_MULTI_QUERY=1 khi query phức tạp/đa khía cạnh.
ENABLE_MULTI_QUERY = os.getenv("ENABLE_MULTI_QUERY", "0").lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def _build_filtered_bm25(document_ids):
    """S6: trả về BM25Retriever chỉ chứa parent docs thuộc document_ids.

    Trước đây BM25 toàn cục không nhận filter -> rút k=25 từ toàn corpus mọi user
    (leakage bảo mật + lãng phí slot rerank). Pre-filter ở đây chặn leakage ngay
    nguồn và giảm input cho rerank. Nếu không có document_ids, trả về BM25 toàn cục.
    """
    base = state.bm25_retriever
    if not document_ids or not base:
        return base
    allowed = set(document_ids)
    filtered_docs = [
        d for d in base.docs if d.metadata.get("document_id") in allowed
    ]
    if not filtered_docs:
        # Không có doc nào khớp -> giữ base; filter dense vẫn chặn ở tầng SQL.
        return base
    return BM25Retriever.from_documents(filtered_docs, k=25)


class CapturingMultiQueryRetriever(MultiQueryRetriever):
    """Ghi lại các sub-query do đúng một lời gọi LLM sinh ra trong invoke().

    Nhờ đó caller đọc được `generated_queries` sau khi chạy funnel, thay vì phải
    gọi thêm `generate_queries()` riêng (S1 — tránh 1 LLM call trùng lặp ~1.5s).
    Chỉ dùng khi ENABLE_MULTI_QUERY=1 (S8).
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
    Thực thi pipeline truy vấn: Hybrid Search (BM25 + Dense) + Cross-Encoder
    Re-ranking. Multi-Query (S8) mặc định tắt, bật bằng env ENABLE_MULTI_QUERY=1.
    """
    base_bm25 = state.bm25_retriever
    if not base_bm25:
        raise ValueError("No documents have been indexed yet. BM25Retriever is empty.")

    # --- S6: BM25 pre-filter theo document_ids (chặn leakage ngay nguồn) ---
    with stage("bm25_build"):
        bm25_retriever = _build_filtered_bm25(document_ids)

    # Dense retriever (ParentDocumentRetriever) lọc ở tầng SQL.
    if document_ids:
        retriever.search_kwargs["filter"] = {"document_ids": document_ids}
    else:
        retriever.search_kwargs.pop("filter", None)

    # --- A. Hybrid Search (Ensemble: BM25 30% + Dense 70%) ---
    ensemble_retriever = EnsembleRetriever(
        retrievers=[bm25_retriever, retriever],
        weights=[0.3, 0.7]
    )

    # --- B. (Tùy chọn) Multi-Query — S8: mặc định TẮT ---
    if ENABLE_MULTI_QUERY:
        logger.info("Retrieval: Multi-Query ON -> generate sub-queries + hybrid search + rerank")
        mq_retriever = CapturingMultiQueryRetriever.from_llm(
            retriever=ensemble_retriever,
            llm=llm
        )
        with stage("multi_query_search"):
            # generate_queries (1 LLM, bị capture) -> lặp sub-query qua Ensemble
            # (embed + SQL + BM25 + docstore).
            candidates = mq_retriever.invoke(query)
        generated_queries = list(mq_retriever.captured_queries)
    else:
        logger.info("Retrieval: Multi-Query OFF -> single hybrid search + rerank")
        with stage("hybrid_search"):
            # 1 embed_query + 1 dense_sql (+ BM25) — không tốn LLM sinh sub-query.
            candidates = ensemble_retriever.invoke(query)
        generated_queries = [query]

    # --- C. Cross-Encoder Re-ranking (tách riêng để đo, dùng singleton S2) ---
    with stage("rerank"):
        retrieved_docs = reranker.compress_documents(candidates, query)

    # S6: BM25 đã pre-filter + dense filter ở SQL -> KHÔNG còn post-filter.
    valid_retrieved_docs = retrieved_docs

    # --- D. Format output + fetch title (đo riêng thời gian DB lookup) ---
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
