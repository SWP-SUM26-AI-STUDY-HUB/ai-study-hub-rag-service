import logging
import re
from typing import Optional

from app.core.performance import stage
from app.services.retrieval import retrieve_documents
from app.database.document_store import get_document_summary, get_user_document_ids

logger = logging.getLogger(__name__)

# --- Intent routing (P3 + P4): deterministic, NO LLM.
#
# Why no LLM here: with only 3 intents (smalltalk / summary / QA) the decision is
# trivially rule-based. An LLM call per request added ~0.3-0.8s latency + 1 quota
# increment for an almost-already-certain answer. The LLM is reserved for the one
# place it earns its cost — generation.
#
# Misses are safe by design:
#   - a chitchat message that escapes the regex -> QA (retrieval returns little,
#     the generation prompt then says "no information").
#   - a paraphrased summary request with no keyword -> QA over the selected doc,
#     which still answers (just not the precomputed curated summary).

# High-precision chitchat: greetings / thanks / farewell / explicit bot-identity.
_SMALLTALK_PATTERN = re.compile(
    r"\b(hi|hello|hey|halo|chào|chao|xin chào|thanks|thank you|cảm ơn|cam on|"
    r"bye|goodbye|tạm biệt|tam biet|who are you|bạn là ai|ban la ai)\b",
    re.IGNORECASE,
)

# Explicit summary/overview requests. Only meaningful for ONE selected document,
# so this is only consulted when document_id is set.
_SUMMARY_PATTERN = re.compile(
    r"\b(summar(y|ize|ised|ized)|tóm tắt|tom tat|tóm lược|tom luoc|"
    r"tổng quan|tong quan|ý chính|y chinh|overview|main points|key points|gist)\b",
    re.IGNORECASE,
)


def _smalltalk_reply(query: str) -> str:
    """Locale-aware canned reply (no retrieval, no generation). ASCII query -> English."""
    if query.isascii():
        return ("Hi! I can help you find and answer information from your uploaded "
                "documents. Ask me anything about their content.")
    return ("Xin chào! Mình có thể giúp bạn tìm và trả lời thông tin từ tài liệu "
            "đã tải lên. Hãy đặt câu hỏi về nội dung tài liệu nhé.")


def route_chat_request(query: str, user_id: str, document_id: Optional[str] = None, history=None) -> dict:
    """
    Deterministic intent router: SMALLTALK -> SUMMARY -> QA (default), no LLM.

    Returns one of:
      {"type": "smalltalk", "content": str}            # canned, no retrieval
      {"type": "summary",   "content": str}            # precomputed doc summary
      {"type": "qa",        "retrieval_data": dict}    # hybrid retrieve + (generation in caller)
      {"type": "error",     "message": str}
    """
    q = (query or "").strip()
    if not q:
        return {"type": "error", "message": "Query must not be empty."}

    # 1. Smalltalk (chitchat) — instant; needs neither documents nor retrieval.
    if _SMALLTALK_PATTERN.search(q):
        logger.info("Router: SMALLTALK (rule) for query '%s'", q)
        return {"type": "smalltalk", "content": _smalltalk_reply(q)}

    # 2. Summary — only meaningful for a single selected document.
    if document_id and _SUMMARY_PATTERN.search(q):
        logger.info("Router: SUMMARY (rule) for query '%s' on document %s", q, document_id)
        with stage("document_summary_fetch"):
            summary_text = get_document_summary(document_id)
        return {"type": "summary", "content": summary_text}

    # 3. QA (default). Resolve document scope: the selected doc, or all of the user's.
    if document_id:
        document_ids = [document_id]
    else:
        with stage("user_doc_ids"):
            document_ids = get_user_document_ids(user_id)
        if not document_ids:
            return {"type": "error", "message": "No documents found belonging to this user."}

    logger.info("Router: QA (default) for query '%s' over %d document(s)", q, len(document_ids))
    retrieval_data = retrieve_documents(query, document_ids, history=history)
    return {"type": "qa", "retrieval_data": retrieval_data}
