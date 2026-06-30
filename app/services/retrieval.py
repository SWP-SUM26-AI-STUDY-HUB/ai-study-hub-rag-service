import logging
import os
import re
from typing import List

from langchain.retrievers import EnsembleRetriever
from langchain.retrievers.multi_query import MultiQueryRetriever
from langchain_community.retrievers import BM25Retriever
from pydantic import Field
from langchain_core.prompts import PromptTemplate

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


# --- Multi-turn: query rewrite for context-dependent follow-ups (option b).
#
# When ON and the latest query references prior turns (pronouns/deictics like
# "đó", "nó", "that", "as mentioned"), one cheap LLM call rewrites it into a
# self-contained question BEFORE retrieval. The rewritten query drives candidate
# generation + rerank; the generator still receives the ORIGINAL query (so it
# answers what the user actually asked and cites [N] correctly). Default OFF —
# costs ~1 extra LLM call per rewritten follow-up. Sibling flag of ENABLE_MULTI_QUERY.
ENABLE_QUERY_REWRITE = os.getenv("ENABLE_QUERY_REWRITE", "0").lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# Trigger: only rewrite queries that look like context-dependent follow-ups.
# Precision matters more than false-positive cost here — a miss degrades retrieval,
# while a false positive just wastes one rewrite call (the model returns ~the same
# query). Bare short diacritic-less words (e.g. "do", "no", "the") are deliberately
# excluded to avoid matching ordinary vocabulary.
_FOLLOWUP_PATTERN = re.compile(
    r"\b("
    r"đó|đấy|này|kia|nọ|vậy|thế|nó|họ|chúng|nữa|thêm|lại|"
    r"như\s+(?:trên|đã|vừa|nói)|phần\s+(?:đó|này|kia)|tiếp\s+(?:tục|tụ)|"
    r"nhu\s+(?:tren|da|vua|noi)|phan\s+(?:do|nay|kia)|tiep\s+(?:tuc|tu)|"
    r"that|this|those|these|"
    r"as\s+(?:mentioned|above|noted)|the\s+above|continue|earlier|previously|more|further|again"
    r")\b",
    re.IGNORECASE,
)


def _needs_context(query: str) -> bool:
    """True if the query looks like a follow-up that references prior context."""
    return bool(_FOLLOWUP_PATTERN.search(query or ""))


_REWRITE_TEMPLATE = """Given the conversation history and the user's latest message, rewrite the latest message into a single self-contained search query that can be understood WITHOUT the conversation context.

Rules:
- Resolve pronouns and references (e.g. "that", "it", "đó", "nó", "this", "as you mentioned") using the history.
- Keep the SAME language as the user's latest message.
- Output ONLY the rewritten query — no explanation, no quotes, no preamble.

Conversation history:
{history}

Latest message:
{question}

Standalone search query:"""


def _format_history_for_rewrite(history) -> str:
    """Render prior turns as 'User: ... / Assistant: ...' for the rewrite prompt.
    Caps to the last 10 turns. Accepts a list of {role, content} dicts (mirrors the
    shape consumed by generation._format_history)."""
    if not history:
        return ""
    lines = []
    for t in list(history)[-10:]:
        if isinstance(t, dict):
            role = t.get("role", "")
            content = t.get("content", "")
        else:
            role = getattr(t, "role", "")
            content = getattr(t, "content", "")
        label = "User" if str(role).lower() in ("user", "human") else "Assistant"
        content = (content or "").strip()
        if content:
            lines.append(f"{label}: {content}")
    return "\n".join(lines)


def _rewrite_query(query: str, history) -> str:
    """Rewrite a context-dependent follow-up into a self-contained question via one
    LLM call (used for RETRIEVAL only). Returns the original query on any failure
    or empty result (safe fallback)."""
    history_text = _format_history_for_rewrite(history)
    if not history_text:
        return query
    try:
        chain = PromptTemplate.from_template(_REWRITE_TEMPLATE) | llm
        with stage("query_rewrite"):
            resp = chain.invoke({"question": query, "history": history_text})
        rewritten = (getattr(resp, "content", "") or "").strip().strip("\"'").strip()
        return rewritten or query
    except Exception as e:
        logger.warning("Query rewrite failed, falling back to original query: %s", e)
        return query


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


def retrieve_documents(query: str, document_ids: List[str] = None, history=None):
    """
    Thực thi pipeline truy vấn: Hybrid Search (BM25 + Dense) + Cross-Encoder
    Re-ranking. Multi-Query (S8) mặc định tắt (bật bằng env ENABLE_MULTI_QUERY=1).

    Multi-turn (option b): khi ENABLE_QUERY_REWRITE=1 và query là follow-up tham
    chiếu hội thoại trước, một LLM call viết lại thành câu tự đứng độc lập và dùng
    câu đó cho cả candidate generation lẫn rerank. Generator vẫn nhận query gốc.
    """
    base_bm25 = state.bm25_retriever
    if not base_bm25:
        raise ValueError("No documents have been indexed yet. BM25Retriever is empty.")

    # --- Multi-turn (option b): rewrite context-dependent follow-ups for RETRIEVAL.
    # `retrieval_query` thay `query` trong toàn bộ funnel (candidate gen + rerank);
    # `query` gốc được giữ lại để trả về + để generator trả lời đúng câu hỏi thật.
    retrieval_query = query
    if ENABLE_QUERY_REWRITE and history and _needs_context(query):
        retrieval_query = _rewrite_query(query, history)
        if retrieval_query != query:
            logger.info("Retrieval: query rewritten for context: '%s' -> '%s'", query, retrieval_query)

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
            candidates = mq_retriever.invoke(retrieval_query)
        generated_queries = list(mq_retriever.captured_queries)
    else:
        logger.info("Retrieval: Multi-Query OFF -> single hybrid search + rerank")
        with stage("hybrid_search"):
            # 1 embed_query + 1 dense_sql (+ BM25) — không tốn LLM sinh sub-query.
            candidates = ensemble_retriever.invoke(retrieval_query)
        generated_queries = [retrieval_query]

    # --- C. Cross-Encoder Re-ranking (tách riêng để đo, dùng singleton S2) ---
    with stage("rerank"):
        retrieved_docs = reranker.compress_documents(candidates, retrieval_query)

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
        "retrieval_query": retrieval_query,
        "generated_queries": generated_queries,
        "documents": results
    }
