"""Langfuse client singleton + helpers (fail-open).

Round 1: chỉ trace /api/v1/chat (QA branch + guardrail + retrieval funnel).
Mọi helper đều fail-open — nếu LANGFUSE_ENABLED=0 hoặc thiếu key hoặc SDK lỗi,
trả no-op / None và /chat chạy bình thường, không đụng tới path chính.

SDK v4 (OpenTelemetry backend):
- `CallbackHandler` (từ langfuse.langchain) auto-capture LLM call của LangChain
  (input/output/usage/cost/latency) khi truyền vào `config={"callbacks": [...]}`.
- `start_as_current_observation` mở span (root span tự trở thành trace).
- `propagate_attributes` set trace-level attributes (user_id/session_id/tags).
- `@observe` decorator bọc hàm thành observation — dùng cho retrieval funnel +
  generation (chỉ /chat Round 1).

Token + cost tự có qua callback (Gemini usage_metadata). Cost (USD) cần định
nghĩa giá model trong Langfuse UI (model definitions) — không code ở đây.
"""
import logging
from contextlib import contextmanager, nullcontext
from typing import Optional

from langchain_core.callbacks import BaseCallbackHandler

from app.core.config import settings

logger = logging.getLogger(__name__)

_client = None
_initialized = False


def _init_client():
    """Lazy-init Langfuse client singleton (chạy sau load_dotenv)."""
    global _client, _initialized
    if _initialized:
        return _client
    _initialized = True

    if not settings.LANGFUSE_ENABLED:
        logger.info("Langfuse: disabled (LANGFUSE_ENABLED=0) -> all instrumentation no-op.")
        return None
    if not settings.LANGFUSE_PUBLIC_KEY or not settings.LANGFUSE_SECRET_KEY:
        logger.warning(
            "Langfuse: enabled but LANGFUSE_PUBLIC_KEY/SECRET_KEY missing -> no-op. "
            "Set them in .env to enable tracing."
        )
        return None
    try:
        # Import sau để tránh crash module khi langfuse chưa cài (defense-in-depth).
        from langfuse import get_client
        _client = get_client()
        logger.info("Langfuse: client ready (base_url=%s).", settings.LANGFUSE_BASE_URL)
    except Exception as e:  # noqa: BLE001 — fail-open là đúng contract
        logger.warning("Langfuse: client init failed (%s) -> no-op.", e)
        _client = None
    return _client


def get_langfuse():
    """Trả Langfuse client singleton hoặc None (disabled/fail-open)."""
    return _init_client()


def get_langchain_handler() -> Optional[BaseCallbackHandler]:
    """Trả CallbackHandler để truyền vào `config={"callbacks": [...]}` của LangChain.

    None khi disabled -> caller lọc None trước khi build list callbacks.
    Fail-open: exception bất kỳ -> None, không sập request.
    """
    if not _init_client():
        return None
    try:
        from langfuse.langchain import CallbackHandler
        return CallbackHandler()
    except Exception as e:  # noqa: BLE001
        logger.warning("Langfuse: CallbackHandler init failed (%s) -> no-op.", e)
        return None


def get_langchain_callbacks() -> list:
    """List callbacks sẵn sàng truyền thẳng vào `config={"callbacks": ...}`.

    Trả [] khi disabled -> LangChain skip hoàn toàn callback overhead.
    """
    h = get_langchain_handler()
    return [h] if h else []


@contextmanager
def lf_span(name: str):
    """Mở Langfuse span `name` nếu client ready, no-op otherwise.

    Dùng song song với `app.core.performance.stage(name)` để vừa ghi
    logs/performance.log vừa ghi Langfuse trace. Fail-open: exception -> yield None.
    """
    client = get_langfuse()
    if not client:
        yield None
        return
    try:
        with client.start_as_current_observation(as_type="span", name=name) as span:
            yield span
    except Exception as e:  # noqa: BLE001
        logger.warning("Langfuse: span '%s' failed (%s) -> no-op.", name, e)
        yield None


@contextmanager
def trace_chat(query: str, user_id: str = "", document_id: str = ""):
    """Mở root trace cho /chat request + set trace attributes (user/session/input).

    Yield root span (hoặc None nếu disabled). Caller set metadata/tags/score sau
    khi biết route + answer qua `root.update(...)` / `root.score(...)`.
    Fail-open toàn bộ.
    """
    client = get_langfuse()
    if not client:
        yield None
        return
    try:
        from langfuse import propagate_attributes
        with client.start_as_current_observation(as_type="span", name="chat") as root:
            with propagate_attributes(
                trace_name="chat",
                user_id=user_id or None,
                # document_id đóng vai trò scope session (1 doc = 1 ngữ cảnh QA).
                session_id=document_id or None,
                tags=["chat"],
            ):
                root.update(
                    input={"query": (query or "")[:500]},  # truncate để giảm noise
                    metadata={"user_id": user_id, "document_id": document_id},
                )
                yield root
    except Exception as e:  # noqa: BLE001
        logger.warning("Langfuse: trace_chat failed (%s) -> no-op.", e)
        yield None
