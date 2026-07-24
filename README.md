# AI Study Hub RAG Service

AI-powered RAG Service for AI Study Hub. Built with FastAPI and Python, this core service handles advanced text extraction, document chunking, embedding generation, and contextual summaries. It integrates seamlessly with PostgreSQL (pgvector) to provide high-performance semantic search for university learning materials.

## Overview

This is a FastAPI / Python service that powers the AI features of the AI Study Hub platform. It handles:
- **Ingestion**: Download → Parse → Parent-Child Chunk → Embed → Index
- **Hybrid Retrieval**: BM25 + pgvector dense (HNSW) + Jina cross-encoder re-rank
- **RAG Generation**: Gemini with numeric `[N]` citations
- **Input Guardrails**: Validates input and blocks prompt injection for chat queries.

It stores vectors in PostgreSQL + pgvector and shares the `aistudyhub` database with the sibling Java backend (`ai-study-hub-api`).

## Architecture & Data Flow

A single FastAPI app (`main.py`) exposing REST endpoints. There is no DB ORM layer — persistence is raw `psycopg2` over a process-wide `ThreadedConnectionPool`. External LLM/embedding/rerank clients are process-wide singletons, warmed at startup.

### Endpoints
- `POST /rag/extract`: Public docs extract only (chunks not embedded until approved).
- `POST /rag/index`: Embed pending chunks after backend approval.
- `POST /rag/process`: Private docs extract and index immediately.
- `PATCH /rag/documents/{id}/visibility`
- `DELETE /rag/documents/{id}`
- `POST /chat`: Main chat endpoint with deterministic routing (SMALLTALK → SUMMARY → QA) and input guardrails.
- `POST /quiz/generate`: Generate structured quizzes from full document content.
- `POST /flashcard/generate`: Generate structured flashcards from full document content.

Callbacks are sent to the Java backend via HTTP POST to `BACKEND_CALLBACK_URL` using `X-Internal-Secret` for authorization.

## Runtime Requirements

- **Python 3.11** (production target, matching Docker image)
- **PostgreSQL 16** with **pgvector** extension (requires `document_chunks` table with `vector(1536)` + HNSW index)
- **API Keys**: Google Gemini (`GOOGLE_API_KEY`) and Jina (`JINA_API_KEY`)

## Local Development Setup

1. **Install dependencies** (in a virtual environment):
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
   *Note: `langchain` is intentionally pinned to 0.3.x — do not bump to 1.x.*

2. **Environment Variables**:
   Create a `.env` file in the root directory (loaded automatically by `dotenv`):
   ```env
   DATABASE_URL=
   BACKEND_CALLBACK_URL=
   INTERNAL_API_SECRET=
   GOOGLE_API_KEY=
   JINA_API_KEY=
   
   # Optional configurations
   ENABLE_MULTI_QUERY=0
   ENABLE_QUERY_REWRITE=0
   ENABLE_POLICY_GUARDRAIL=0
   DB_POOL_MAX=20
   ENABLE_PERF_LOG=1
   TEMP_DIR=temp
   
   # Langfuse Tracing (Fail-open)
   LANGFUSE_ENABLED=1
   LANGFUSE_PUBLIC_KEY=
   LANGFUSE_SECRET_KEY=
   LANGFUSE_BASE_URL=https://cloud.langfuse.com
   ```

3. **Run the FastAPI server**:
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```
   *Swagger UI will be available at `http://localhost:8000/docs`.*

4. **Run via Docker**:
   ```bash
   docker compose up --build -d
   ```
   *This builds the image and joins the external `ai-study-hub-network` (managed by the backend's docker-compose).*

## Key Implementation Details

- **Input Guardrail**: Runs before the `/chat` router to validate input size and detect prompt injections (EN+VI regex). Optionally checks policy topics via LLM if enabled.
- **Two-phase Ingestion**: Public docs are extracted but not embedded (`embedding = NULL`) until approved by the backend, ensuring safe vector spaces.
- **Parent-Child Retrieval**: Retrieves child chunks via vector similarity, then fetches the larger parent chunk from the local file store for complete context generation.
- **Deterministic Intent Routing**: Smalltalk and specific summary queries bypass RAG retrieval for efficiency and lower API costs.
- **Multi-turn Memory**: Injects conversation history to resolve follow-up references for generation. Includes an optional query rewrite step for complex contextual follow-ups.
- **Study Material Generation**: Quizzes and flashcards use full document content in reading order and Gemini's structured output (JSON mode), protected by two-layer refusals (content length floor + LLM suitability flag).
- **Observability & Tracing**: Dual fail-open instrumentation using local performance logs and Langfuse for detailed execution traces, token usage, cost, and latency metrics without blocking the request path.
