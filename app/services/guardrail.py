"""Input guardrail layer for POST /api/v1/chat (runs BEFORE the intent router).

Ba nhánh kiểm tra, block đầu tiên thắng:
  1. validate_input        — deterministic, luôn ON (rỗng / quá dài / ký tự control /
                             cấu trúc history sai).
  2. detect_prompt_injection — rule-based regex (EN + VI), luôn ON (override lệnh,
                             role-hijack, chat-template injection).
  3. check_policy_topic    — LLM classifier, chỉ chạy khi ENABLE_POLICY_GUARDRAIL=1
                             (y tế/pháp lý/bạo lực/…). Fail-open: LLM lỗi -> ALLOW.

Mọi block đều trả HTTP 200 kèm lời từ chối chuẩn trong data.llm_response (giống
pattern smalltalk / empty-retrieval hiện có) — KHÔNG gọi retrieval/generation.
Locale cho lời từ chối dùng query.isascii() (giống router._smalltalk_reply):
ASCII -> English, có dấu -> Vietnamese.

Tài liệu upload KHÔNG qua guardrail này — đã được moderation ở phía ingestion gate.
"""
import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

# S2: tái dùng singleton LLM (không `new` per request).
from app.core.clients import llm
# Instrumentation: đo từng nhánh guardrail.
from app.core.performance import stage
from app.core.config import settings

logger = logging.getLogger(__name__)

# --- Toggles ---------------------------------------------------------------
# Policy/Topic guardrail tốn ~1 LLM call nên mặc định TẮT (khớp triết lý tiết kiệm
# quota: multi-query OFF, query-rewrite OFF, router deterministic). Hai lớp
# deterministic ở trên luôn chạy. Bật bằng .env ENABLE_POLICY_GUARDRAIL=1.
ENABLE_POLICY_GUARDRAIL: bool = settings.ENABLE_POLICY_GUARDRAIL

# --- Tham số tinh chỉnh (không phải toggle ops -> để trong module, không vào config) ---
MAX_QUERY_LENGTH = 2000
MAX_HISTORY_TURNS = 10          # khớp cap ở generation._format_history
MAX_HISTORY_ITEM_LENGTH = 2000


@dataclass
class GuardrailResult:
    allowed: bool
    refusal: str = ""           # non-empty khi block -> đưa vào data.llm_response
    category: str = "allowed"   # allowed | validation | injection | policy
    reason: str = ""            # lý do nội bộ để log/debug


# --- Locale-aware canned refusals (English, Vietnamese) --------------------
# Lời từ chối cố định — KHÔNG echo text do LLM/user sinh ra (tránh leakage).
_EMPTY = (
    "Please enter a question.",
    "Vui lòng nhập câu hỏi của bạn.",
)
_TOO_LONG = (
    "Your question is too long. Please keep it under 2000 characters.",
    "Câu hỏi của bạn quá dài. Vui lòng giới hạn trong 2000 ký tự.",
)
_UNSUPPORTED_CHARS = (
    "Your message contains unsupported characters. Please remove them and try again.",
    "Tin nhắn của bạn chứa ký tự không được hỗ trợ. Vui lòng bỏ các ký tự đó và thử lại.",
)
_TOO_MANY_TURNS = (
    "Too many conversation turns were sent. Please start a new chat session.",
    "Số lượt hội thoại gửi quá nhiều. Vui lòng bắt đầu một phiên trò chuyện mới.",
)
_BAD_HISTORY_ITEM = (
    "One of the previous messages is missing or too long.",
    "Một trong các tin nhắn trước đó bị thiếu hoặc quá dài.",
)
_INJECTION = (
    "I can't follow instructions that try to override my guidelines. "
    "Please ask a study-related question.",
    "Tôi không thể làm theo các chỉ dẫn cố thay đổi quy tắc hệ thống. "
    "Vui lòng đặt câu hỏi liên quan đến học tập.",
)
_POLICY = (
    "I can only help with study and document-related questions. "
    "I can't assist with that request.",
    "Tôi chỉ hỗ trợ các câu hỏi về học tập và tài liệu. "
    "Tôi không thể hỗ trợ yêu cầu này.",
)


def _refusal(text_for_locale: str, pair) -> str:
    """Chọn lời từ chối theo locale của `text_for_locale` (isascii -> EN)."""
    en, vi = pair
    return en if (text_for_locale or "").isascii() else vi


# --- Ký tự control / zero-width -------------------------------------------
# Cho phép \n (\x0a) và \t (\x09) — ngắt dòng/tab hợp lệ trong câu hỏi.
# Block: C0 control chars (trừ \t \n), DEL, zero-width + bidi marks, line/para
# separator, word joiner, BOM.
_CONTROL_CHARS = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u200b-\u200f\u2028\u2029\u2060\ufeff]"
)


# --- Prompt-injection patterns (rule-based, EN + VI) -----------------------
# Một re.compile duy nhất; block đầu tiên thắng qua pattern.search.
# Mỗi nhánh là một |-branch độc lập -> dễ cô lập khi cần thu hẹp false-positive.
_INJECTION_PATTERN = re.compile(
    r"(?:"
    # --- EN: override / extraction attempts ---
    r"\bignore\b.*\b(?:previous|prior|above|all)\b.*\b(?:instruction|rule|prompt)\b"
    r"|\bdisregard\b.*\b(?:instruction|rule|prompt)\b"
    r"|\b(?:override|bypass)\b.*\b(?:rule|instruction|system|restrict)\b"
    r"|\bforget\b.*\b(?:everything|all|previous|prior)\b"
    r"|\bdo not follow\b"
    r"|\breveal\b.*\b(?:system\s+)?prompt\b"
    # --- VI: override / extraction attempts ---
    r"|bỏ\s*qua.*?(?:hướng\s*dẫn|lệnh|chỉ\s*định|yêu\s*cầu|quy\s*tắc)"
    r"|vô\s*hiệu\s*hoá.*?(?:quy\s*tắc|hướng\s*dẫn)"
    r"|quên.*(?:mọi\s*thứ|hướng\s*dẫn|tất\s*cả)"
    r"|không\s*(?:cần\s*)?tuân\s*theo"
    r"|vượt\s*qua.*?(?:hạn\s*chế|ràng\s*buộc)"
    r"|tiết\s*lộ.*?(?:prompt|hướng\s*dẫn)"
    # --- Role-override: CHễ fire khi đi kèm từ khóa override để tránh
    #     false-positive với câu học tập hợp lệ ("act as a tutor"). ---
    r"|\b(?:you\s+are\s+now|act\s+as\s+if|pretend\s+(?:you\s+are|to\s+be))\b"
    r".*\b(?:no\s+rules|unrestricted|different\s+(?:ai|assistant|model)|jailbreak|dan\b)"
    # --- Chat-template injection (block tuyệt đối, high precision) ---
    r"|<\|?(?:system|im_start|im_end|sys)\|?>"
    r"|\[/?(?:inst|sys)\]"
    r"|<<\s*sys\s*>>"
    r"|</?\s*s\s*>"
    r"|\[system\]"
    r"|###\s*(?:system|instruction)"
    r")",
    re.IGNORECASE,
)


# --- Policy classifier prompt (LLM, opt-in) -------------------------------
_POLICY_PROMPT = (
    "You are the safety classifier for the \"AI Study Hub\" platform, "
    "a study and document assistant. Decide whether the user's QUESTION is "
    "in-scope (ALLOW) or out-of-scope (DENY).\n\n"
    "ALLOW: study/educational questions — explanations, summaries, Q&A over "
    "learning material, general academic knowledge, and homework help that does "
    "not amount to large-scale academic fraud.\n\n"
    "DENY any of these topics: medical diagnosis or advice; legal advice; "
    "financial/investment advice; weapons, violence, or harm to others; "
    "self-harm; sexual content or CSAM; hate speech; PII extraction or doxxing; "
    "malware or hacking help; copyright infringement or large-scale academic "
    "fraud.\n\n"
    "Respond with STRICT JSON only — no prose, no code fence:\n"
    "{{\"decision\": \"ALLOW\" or \"DENY\", "
    "\"category\": \"<study|medical|legal|finance|violence|self-harm|sexual"
    "|hate|pii|malware|fraud>\", "
    "\"reason\": \"<one short English sentence>\"}}\n\n"
    "User question: {query}"
)


def _history_content(h) -> str:
    """Lấy content của một history item một cách an toàn (item có thể sai cấu trúc)."""
    if isinstance(h, dict):
        c = h.get("content", "")
        return c if isinstance(c, str) else ""
    return ""


# --- 1a. Input validation (deterministic, luôn ON) -------------------------
def validate_input(query: str, history) -> Optional[GuardrailResult]:
    """Trả GuardrailResult(allowed=False) khi vi phạm, None khi hợp lệ.
    Trật tự: block đầu tiên thắng."""
    if not isinstance(query, str) or not query.strip():
        return GuardrailResult(
            allowed=False, category="validation",
            refusal=_refusal(query, _EMPTY), reason="empty_query",
        )
    if len(query) > MAX_QUERY_LENGTH:
        return GuardrailResult(
            allowed=False, category="validation",
            refusal=_refusal(query, _TOO_LONG),
            reason=f"query_too_long:{len(query)}",
        )
    # Ký tự control/zero-width trong query.
    if _CONTROL_CHARS.search(query):
        return GuardrailResult(
            allowed=False, category="validation",
            refusal=_refusal(query, _UNSUPPORTED_CHARS),
            reason="query_control_char",
        )
    history = history or []
    # Ký tự control/zero-width trong bất kỳ history content nào (item sai cấu trúc
    # -> content="" -> không match, sẽ bị bắt ở bước kiểm tra cấu trúc phía dưới).
    for i, h in enumerate(history):
        if _CONTROL_CHARS.search(_history_content(h)):
            return GuardrailResult(
                allowed=False, category="validation",
                refusal=_refusal(query, _UNSUPPORTED_CHARS),
                reason=f"history_control_char:{i}",
            )
    # Quá nhiều lượt history.
    if len(history) > MAX_HISTORY_TURNS:
        return GuardrailResult(
            allowed=False, category="validation",
            refusal=_refusal(query, _TOO_MANY_TURNS),
            reason=f"history_too_many_turns:{len(history)}",
        )
    # Cấu trúc / độ dài từng item history.
    for i, h in enumerate(history):
        if not isinstance(h, dict) or "content" not in h or "role" not in h:
            return GuardrailResult(
                allowed=False, category="validation",
                refusal=_refusal(query, _BAD_HISTORY_ITEM),
                reason=f"history_item_missing_keys:{i}",
            )
        content = h["content"]
        if not isinstance(content, str) or len(content) > MAX_HISTORY_ITEM_LENGTH:
            return GuardrailResult(
                allowed=False, category="validation",
                refusal=_refusal(query, _BAD_HISTORY_ITEM),
                reason=f"history_item_too_long:{i}",
            )
    return None


# --- 1b. Prompt-injection detection (rule-based regex, luôn ON) ------------
def detect_prompt_injection(text: str) -> Optional[GuardrailResult]:
    """Trả GuardrailResult(allowed=False, category='injection') khi match, else None.
    Locale cho refusal theo text.isascii() (cho query == query.isascii())."""
    if not isinstance(text, str):
        return None
    m = _INJECTION_PATTERN.search(text)
    if not m:
        return None
    snippet = m.group(0)
    if len(snippet) > 100:
        snippet = snippet[:100] + "…"
    return GuardrailResult(
        allowed=False, category="injection",
        refusal=_refusal(text, _INJECTION),
        reason=f"matched:{snippet}",
    )


# --- 1c. Policy/Topic check (LLM, opt-in, fail-open) -----------------------
def check_policy_topic(query: str) -> GuardrailResult:
    """LLM classifier. Chỉ chạy khi ENABLE_POLICY_GUARDRAIL=1.
    Fail-open: LLM lỗi / parse lỗi / decision không hợp lệ -> ALLOW (log warning)."""
    try:
        prompt = _POLICY_PROMPT.format(query=query)
        response = llm.invoke(prompt)
        raw = (getattr(response, "content", "") or "").strip()
        # Bỏ code fence ```json … ``` nếu model vô tình thêm.
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw).strip()
        data = json.loads(raw)
        decision = str(data.get("decision", "")).strip().upper()
        if decision == "DENY":
            category = str(data.get("category", "")).strip()
            reason = str(data.get("reason", "")).strip()
            internal = f"{category}: {reason}" if category else reason
            logger.info("Policy guardrail DENY: %s", internal)
            return GuardrailResult(
                allowed=False, category="policy",
                refusal=_refusal(query, _POLICY),
                reason=internal,
            )
        if decision == "ALLOW":
            return GuardrailResult(
                allowed=True, category="policy", reason="llm_allow",
            )
        # decision không hợp lệ -> fail-open.
        logger.warning(
            "Policy guardrail: invalid decision=%r, failing open (ALLOW).", decision,
        )
        return GuardrailResult(
            allowed=True, category="policy",
            reason="llm_unavailable_fail_open",
        )
    except Exception as e:  # noqa: BLE001 - fail-open cố ý cho mọi lỗi LLM/parse.
        logger.warning("Policy guardrail LLM failed (%s); failing open (ALLOW).", e)
        return GuardrailResult(
            allowed=True, category="policy",
            reason="llm_unavailable_fail_open",
        )


# --- 1d. Orchestrator ------------------------------------------------------
def check_chat_request(query: str, history) -> GuardrailResult:
    """Chạy cả ba nhánh theo thứ tự, block đầu tiên thắng.
    Luôn chạy validation + injection; policy chỉ khi ENABLE_POLICY_GUARDRAIL=1."""
    with stage("guardrail_validation"):
        r = validate_input(query, history)
        if r:
            return r

    with stage("guardrail_injection"):
        r = detect_prompt_injection(query)
        if r:
            # Locale refusal luôn theo query (1d: query.isascii()), kể cả khi
            # injection bắt được trong history item (ghi đè locale mặc định).
            r.refusal = _refusal(query, _INJECTION)
            return r
        # History do backend forward từ input user -> có thể mang injection.
        for h in (history or []):
            r = detect_prompt_injection(_history_content(h))
            if r:
                r.refusal = _refusal(query, _INJECTION)
                return r

    if ENABLE_POLICY_GUARDRAIL:
        with stage("guardrail_policy"):
            return check_policy_topic(query)

    return GuardrailResult(allowed=True)
