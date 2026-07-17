import os
from dotenv import load_dotenv

# Ensure environment variables are loaded
load_dotenv()

class Settings:
    DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql://nnct:Nnct1608@localhost:5432/aistudyhub")
    BACKEND_CALLBACK_URL: str = os.getenv("BACKEND_CALLBACK_URL", "http://localhost:8080/api/v1/internal/documents/callback")
    INTERNAL_API_SECRET: str = os.getenv("INTERNAL_API_SECRET", "default-secret-key-change-me")
    TEMP_DIR: str = "temp"
    # Input guardrail: bật lớp Policy/Topic (LLM) cho /chat. Validation +
    # Injection (deterministic/regex) luôn ON; lớp này tốn ~1 LLM call -> OFF mặc định.
    ENABLE_POLICY_GUARDRAIL: bool = os.getenv("ENABLE_POLICY_GUARDAIL", "0").lower() in ("1", "true", "yes", "on")

    # --- LLM Observability (Langfuse) ---------------------------------------
    # Mọi instrumentation phải fail-open: nếu LANGFUSE_ENABLED=0 hoặc thiếu key,
    # handler trả no-op -> /chat vẫn chạy bình thường, không đụng tới path chính.
    # Round 1: chỉ trace /chat (QA branch + guardrail + retrieval funnel).
    LANGFUSE_ENABLED: bool = os.getenv("LANGFUSE_ENABLED", "1").lower() in ("1", "true", "yes", "on")
    LANGFUSE_PUBLIC_KEY: str = os.getenv("LANGFUSE_PUBLIC_KEY", "")
    LANGFUSE_SECRET_KEY: str = os.getenv("LANGFUSE_SECRET_KEY", "")
    LANGFUSE_BASE_URL: str = os.getenv("LANGFUSE_BASE_URL", "https://cloud.langfuse.com")

settings = Settings()
