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
    ENABLE_POLICY_GUARDRAIL: bool = os.getenv("ENABLE_POLICY_GUARDRAIL", "0").lower() in ("1", "true", "yes", "on")

settings = Settings()
