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

# High-precision chitchat, split into 4 locale-aware canned replies (no retrieval,
# no generation). All four used to share one greeting-style reply, so "thanks"/"bye"
# answered "Hi!" — each category now has its own reply. Keyword coverage is unchanged.
_GREETING_PATTERN = re.compile(r"\b(hi|hello|hey|halo|chào|chao|xin chào)\b", re.IGNORECASE)
_THANKS_PATTERN = re.compile(r"\b(thanks|thank you|cảm ơn|cam on)\b", re.IGNORECASE)
_FAREWELL_PATTERN = re.compile(r"\b(bye|goodbye|tạm biệt|tam biet)\b", re.IGNORECASE)
_IDENTITY_PATTERN = re.compile(r"\b(who are you|bạn là ai|ban la ai)\b", re.IGNORECASE)

# Check order matters: more specific intents first so "hi, who are you?" -> identity
# and "thanks, bye" -> thanks rather than collapsing to a bare greeting.
_CHITCHAT_CATEGORIES = (
    ("identity", _IDENTITY_PATTERN),
    ("thanks", _THANKS_PATTERN),
    ("farewell", _FAREWELL_PATTERN),
    ("greeting", _GREETING_PATTERN),
)

# Locale-aware canned replies per chitchat category: (English, Vietnamese).
# ASCII query -> English (preserves the original heuristic; e.g. "cam on" is ASCII).
_SMALLTALK_REPLIES = {
    "greeting": (
        "Hi! I can help you find and answer information from your uploaded "
        "documents. Ask me anything about their content.",
        "Xin chào! Mình có thể giúp bạn tìm và trả lời thông tin từ tài liệu "
        "đã tải lên. Hãy đặt câu hỏi về nội dung tài liệu nhé.",
    ),
    "thanks": (
        "You're welcome! Let me know if you have any other questions about your documents.",
        "Không có gì! Nếu bạn còn câu hỏi nào về tài liệu, cứ hỏi mình nhé.",
    ),
    "farewell": (
        "Goodbye! Come back anytime you need help with your documents.",
        "Tạm biệt! Bạn quay lại bất cứ lúc nào khi cần hỗ trợ về tài liệu nhé.",
    ),
    "identity": (
        "I'm the AI Study Hub assistant. I answer questions based on the documents you've uploaded.",
        "Mình là trợ lý AI Study Hub. Mình trả lời câu hỏi dựa trên tài liệu bạn đã tải lên.",
    ),
}

# Explicit summary/overview requests. Only meaningful for ONE selected document,
# so this is only consulted when document_id is set.
_SUMMARY_PATTERN = re.compile(
    r"\b(summar(y|ize|ised|ized)|tóm tắt|tom tat|tóm lược|tom luoc|"
    r"tổng quan|tong quan|ý chính|y chinh|overview|main points|key points|gist)\b",
    re.IGNORECASE,
)


def _smalltalk_reply(query: str, category: str) -> str:
    """Locale-aware canned reply for a chitchat category (no retrieval, no generation).
    ASCII query -> English reply, otherwise Vietnamese."""
    english, vietnamese = _SMALLTALK_REPLIES[category]
    return english if query.isascii() else vietnamese


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
    #    First matching category wins (identity/thanks checked before greeting).
    for category, pattern in _CHITCHAT_CATEGORIES:
        if pattern.search(q):
            logger.info("Router: SMALLTALK/%s (rule) for query '%s'", category, q)
            return {"type": "smalltalk", "content": _smalltalk_reply(q, category)}

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
