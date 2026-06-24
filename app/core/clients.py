"""Process-wide singleton clients for external APIs (S2).

Trước đây mỗi request đều `new ChatGoogleGenerativeAI(...)` / `JinaRerank(...)`,
mất chi phí thiết lập TLS/keep-alive (~50-150ms) mỗi lần. Các singleton này được
tạo một lần lúc import và được tái sử dụng bởi mọi handler/thread.

Bản chất các client này không có trạng thái ngoài một HTTP connection pool dùng
chung → an toàn khi chia sẻ giữa nhiều thread (FastAPI chạy sync `def` handler
trong threadpool, xem S3).
"""
import logging
import os

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_community.document_compressors import JinaRerank

# Import settings để đảm bảo load_dotenv() đã chạy trước khi đọc env ở dưới.
from app.core.config import settings  # noqa: F401

logger = logging.getLogger(__name__)

# Singleton LLM dùng chung cho router / multi-query / generation / ingestion.
llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-lite",
    temperature=0,
)

# Singleton Jina reranker dùng chung cho bước cross-encoder re-ranking.
reranker = JinaRerank(
    jina_api_key=os.environ.get("JINA_API_KEY"),
    model="jina-reranker-v3",
    top_n=5,
)

logger.info("Initialized shared LLM and Jina reranker singletons.")
