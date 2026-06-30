# Báo cáo tiến trình xây dựng Chatbot RAG — AI Study Hub

> Tài liệu nội bộ ghi nhận các vấn đề hệ thống gặp phải và giải pháp đã áp dụng,
> làm tư liệu để tổng hợp báo cáo tổng thể "từ ngày đầu build đến khi hoàn thiện".
>
- **Phạm vi:** RAG service (`ai-study-hub-rag-service`, FastAPI/Python) + phần giao
  tiếp với backend Java (`ai-study-hub-api`).
- **Ngày lập:** 2026-06-30.
- **Lưu ý về bằng chứng:** các con số latency trong Giai đoạn 1 (~50–150ms,
  ~14s, ~6s) là **giá trị codebase đã ghi nhận** trong comment/log, không phải số
  đo của phiên soạn báo cáo này. Giai đoạn 2 được xác minh bằng test đơn vị/hành
  vi (Python `py_compile` + mock test; Java Mockito) — không phải số liệu production.

---

## 1. Bối cảnh & kiến trúc

Chatbot thuộc nền tảng **AI Study Hub**, được tách thành **2 service** giao tiếp qua HTTP, **cùng dùng 1 PostgreSQL** (`aistudyhub` + pgvector) và **1 `INTERNAL_API_SECRET`**:

| Service | Vai trò |
|---|---|
| **Backend Java** (Spring Boot, :8080) | API gateway: `users`/`documents`/`chat_sessions`, auth JWT, moderation, billing VNPay, quota AI. |
| **RAG Python** (FastAPI, :8000) | Sở hữu `document_chunks`: ingestion (tải→parse→chunk→embed→index), hybrid retrieval (BM25 + pgvector dense + Jina rerank), generation (Gemini) với trích dẫn `[N]`. |

```
User ──▶ Backend (JWT, quota, lưu chat_sessions/messages)
              │  POST /api/v1/chat {query, user_id, document_id, history}
              ▼
         RAG Service ── route (SMALLTALK/SUMMARY/QA) ── retrieve ── generate ──▶ [N] citations
              │  callback {document_id, status, summary}  (X-Internal-Secret)
              ▼
         Backend (cập nhật trạng thái document)
```

Hai pha ingestion: **extract** (chunk với `embedding=NULL` chờ duyệt) → **index** (embed sau khi duyệt). Lọc `embedding IS NOT NULL` ở retrieval là lưới an toàn chống leak tài liệu chưa duyệt.

---

## 2. Giai đoạn 1 — Vấn đề hiệu năng & kiến trúc (early days)

Đây là các bài toán nền tảng phải giải **trước** khi chatbot chạy ổn. Codebase đánh dấu bằng nhãn `S` và các ghi chú trong source.

### 2.1 Khởi tạo client mỗi request (`S2` — Singletons)
- **Vấn đề:** mỗi request đều `new ChatGoogleGenerativeAI(...)` / `new JinaRerank(...)` → chi phí thiết lập TLS/keep-alive **~50–150ms/lần**.
- **Giải pháp:** tạo client **một lần lúc import** (`app/core/clients.py`: `llm`, `embeddings`, `reranker`; `app/pipeline/dependencies.py`: `vectorstore`, `store`, `retriever`, splitters, BM25 `state`), tái sử dụng cho mọi thread.
- **Kết quả:** loại bỏ hoàn toàn chi phí setup mỗi request.

### 2.2 Blocking I/O đe dọa event loop (`S3` — Sync handlers)
- **Vấn đề:** Gemini/Jina/psycopg2 là I/O blocking; nếu handler `async def` mà gọi blocking sẽ **chặn event loop**.
- **Giải pháp:** endpoint dùng `def` thường → FastAPI đẩy vào threadpool; blocking I/O chạy ở thread riêng, event loop không bị stall.
- **Quy ước:** endpoint mới giữ `def` trừ khi thực sự async.

### 2.3 Mở/đóng connection DB mỗi lookup (`S4` — Connection pool)
- **Vấn đề:** connect/close PostgreSQL mỗi truy vấn → overhead + cạn kiệt connection.
- **Giải pháp:** `ThreadedConnectionPool` (`minconn=1`, `maxconn=DB_POOL_MAX`=20) + context manager `db_connection()` (rollback ở `finally` để trả connection sạch).
- **Kết quả:** connection dùng lại, pool giới hạn rõ ràng.

### 2.4 BM25 rút từ toàn corpus mọi user (`S6` — BM25 pre-filter)
- **Vấn đề:** BM25 toàn cục lấy `k=25` từ **toàn bộ tài liệu mọi user** → (a) **rò rỉ dữ liệu** giữa các user, (b) lãng phí slot rerank bằng kết quả không liên quan.
- **Giải pháp:** pre-filter BM25 chỉ giữ parent docs thuộc `document_ids` được phép (`_build_filtered_bm25`); dense search cũng lọc ở tầng SQL (`document_id = ANY(...)`).
- **Kết quả:** chặn leak **ngay tại nguồn**, giảm nhiễu đầu vào rerank.

### 2.5 Multi-Query tốn ~6s/request (`S8` — Multi-query off)
- **Vấn đề:** multi-query sinh sub-query bằng 1 LLM call thêm → **~6s/request**, đa phần QA không cần.
- **Giải pháp:** mặc định **TẮT**, bật bằng env `ENABLE_MULTI_QUERY=1` khi query phức tạp/đa khía cạnh.
- **Kết quả:** tiết kiệm ~6s cho phần lớn request.

### 2.6 Cold-start ~14s Gemini (warmup)
- **Vấn đề:** request đầu tiên sau khởi động bị Gemini cold-start **~14s**.
- **Giải pháp:** `_warmup_clients()` chạy ở startup event để "khuấy" Gemini trước.

### 2.7 Cổng kiểm duyệt tài liệu công (two-phase extract/index)
- **Vấn đề:** tài liệu PUBLIC phải được moderation **trước** khi đưa vào retrieval.
- **Giải pháp:** pha extract lưu chunk với `embedding=NULL`; pha index (sau duyệt) mới embed. `similarity_search_by_vector` lọc `WHERE embedding IS NOT NULL` → chunk chưa index không bao giờ bị trả về. **Không bao giờ bỏ filter này.**

### 2.8 Parent–Child retrieval
- **Kỹ thuật:** chunk con (200/50) dùng để match chính xác; khi khớp, fetch parent (1000/200) từ `LocalFileStore` làm context rộng. Chunk con mang `metadata["doc_id"]` = parent uuid (LangChain `MultiVectorRetriever.id_key="doc_id"`).

---

## 3. Giai đoạn 2 — Vấn đề tính "hoàn thiện" của chatbot

Sau khi hiệu năng ổn, chatbot vẫn **chưa thật sự là chatbot**: thiếu memory, router lãng phí, một số lỗ hổng. Đây là phần nâng cấp chính.

### 3.1 Chatbot không có memory hội thoại (`P0`)
- **Vấn đề:** wire contract `{query, user_id, document_id}` **không mang theo lịch sử** → mỗi câu hỏi cô lập. Câu follow-up/giải đại từ ("người đó là ai?", "giải thích phần này đơn giản hơn") **gãy**.
- **Nguyên nhân gốc:** backend đã lưu đầy đủ `chat_messages` (USER+BOT+citations) và `sessionId`, nhưng **không truyền qua biên giới HTTP**.
- **Giải pháp:**
  - Backend (`ChatServiceImpl`) build `history` = 10 message gần nhất của session (`{role, content}`, oldest-first), gửi qua `ChatbotClient.chat(query, userId, documentId, history)` 4-arg.
  - RAG (`ChatRequest.history`) nhận và đưa vào prompt generation dưới dạng block "Conversation so far".
  - **Ràng buộc:** history chỉ **auxiliary** — trả lời vẫn phải dựa context đã retrieve và cite `[N]`, không dùng history làm nguồn trích dẫn.
- **Kết quả:** chatbot có memory nhiều lượt.

### 3.2 Retrieval rỗng vẫn gọi LLM (`P1` — Empty-retrieval guard)
- **Vấn đề:** khi retrieval trả 0 chunk liên quan, generation vẫn được gọi trên context rỗng → **dễ bịa** + lãng phí 1 LLM call.
- **Giải pháp:** `chat_router` short-circuit trả message cố định "Không tìm thấy thông tin liên quan..." mà không gọi generator.
- **Kết quả:** chống hallucination + tiết kiệm 1 generation call.

### 3.3 Endpoint `/chat/retrieve` leak toàn kho (`P2`)
- **Vấn đề:** endpoint `POST /api/v1/chat/retrieve` gọi `retrieve_documents(query)` **không truyền `document_ids`** → dense search không filter, BM25 lấy toàn `state.bm25_retriever` (toàn bộ tài liệu mọi user). Endpoint này **ngoài wire contract** (backend không gọi) nhưng vẫn expose công khai.
- **Giải pháp:** **xóa hẳn** endpoint + model `QueryRequest` + import `retrieve_documents` không dùng trong `main.py`.
- **Kết quả:** đóng lỗ hổng rò rỉ dữ liệu.

### 3.4 Router dùng LLM mỗi request + chitchat lệch (`P3` + `P4`)
- **Vấn đề:**
  - Router gọi **1 LLM call mỗi request** chỉ để phân loại SUMMARY vs QA → **latency + quota ảo**, dù phần lớn quyết định hiển nhiên (`document_id == null` → chắc chắn QA).
  - Câu chitchat ("hi", "cảm ơn") đi nhánh QA → retrieve tài liệu → trả lời lạ.
- **Giải pháp:** thay LLM router bằng **router deterministic theo regex, 3 nhánh, không LLM**:
  ```
  SMALLTALK (chào/cảm ơn/tạm biệt/bạn-là-ai) → SUMMARY ("tóm tắt/summarize/..." + có document_id) → QA (mặc định)
  ```
  - `document_id == null` luôn QA (SUMMARY cần doc cụ thể).
  - SMALLTALK trả canned reply (ASCII→English, còn lại→Tiếng Việt), không retrieval.
  - Miss-safe: câu xin tóm tắt không trúng keyword → rơi QA → vẫn trả lời trên doc đã chọn.
- **Kết quả:** **0 LLM call** ở router; chitchat xử lý gọn.

### 3.5 Follow-up vẫn hỏng retrieval dù đã có memory (Query Rewrite — option b)
- **Vấn đề:** memory ở `P0` chỉ tới **generation**, **không tới retrieval**. Câu "hãy trả lời nội dung đó" được embed nguyên văn cho dense search → vector "trống" ngữ nghĩa → chunk sai; BM25 match chữ "nội dung/đó" nhiễu. Dù generator có history, **context đã sai từ đầu**.
- **Giải pháp:** thêm flag `ENABLE_QUERY_REWRITE` (mặc định TẮT, sibling của `ENABLE_MULTI_QUERY`). Khi bật + query là follow-up (có đại từ/chỉ từ: `đó/nó/that/as mentioned/...`) + có history:
  - **1 LLM call** viết lại query thành câu tự đứng độc lập.
  - Câu rewritten dùng cho **cả candidate generation lẫn rerank**.
  - **Generator vẫn nhận câu gốc** (option b) → trả lời đúng intent, cite `[N]` đúng.
  - Bất kỳ lỗi nào (kể cả build chain) → fallback trả query gốc.
- **Kết quả:** follow-up giờ retrieve đúng chunk. Tradeoff: +1 LLM call (~0.3–0.5s) **chỉ khi** query là follow-up + có history.

---

## 4. Bảng so sánh Before / After (góc nhìn chatbot)

| Khía cạnh | Trước | Sau |
|---|---|---|
| **Memory hội thoại** | Stateless, mỗi câu cô lập | Có history (≤10 turn) → hiểu follow-up/đại từ |
| **Router** | 1 LLM call/request (SUMMARY vs QA) | Regex deterministic, 0 LLM, 3 nhánh (SMALLTALK/SUMMARY/QA) |
| **Chitchat ("hi")** | Đi QA, retrieve rồi trả lời lạ | Canned reply, không retrieval |
| **Follow-up ("...nội dung đó")** | Retrieval embed câu rỗng ngữ nghĩa → sai | Query rewrite → retrieve đúng (option b) |
| **Retrieval rỗng** | Vẫn gọi generator → hallucinate | Short-circuit, không gọi LLM |
| **Leak `/chat/retrieve`** | Toàn kho không filter | Đã xóa endpoint |
| **Chi phí LLM/request** | router (luôn) + generation | generation (+ rewrite chỉ khi follow-up) |
| **An toàn dữ liệu** | Leak qua BM25 toàn cục (S6) + endpoint P2 | Pre-filter theo user/doc + endpoint đã gỡ |

---

## 5. Trạng thái hiện tại & hạng mục tương lai

**Đã hoàn thành & xác minh:**
- P0 memory, P1 empty-guard, P2 gỡ endpoint, P3+P4 router deterministic, query rewrite (option b).
- Xác minh: `py_compile` RAG; mock test 21/21 (rewrite) + 20/20 (router); backend `mvn test` 104 test (0 fail).

**Mặc định TẮT (bật theo nhu cầu):**
- `ENABLE_MULTI_QUERY=1` (sub-query, ~6s).
- `ENABLE_QUERY_REWRITE=1` (rewrite follow-up, ~0.3–0.5s/follow-up).

**Chưa làm (đề xuất tương lai):**
- **Streaming response:** hiện backend block với timeout 30s; đáp án dài + retrieval chậm có thể đụt. Cần SSE cả 2 phía.
- **Chitchat miễn phí quota:** smalltalk hiện vẫn bị backend đếm quota (vì backend increment trước khi gọi RAG). Muốn free thì backend tự detect.
- **Bộ test tự động RAG:** hiện verify thủ công (không có `tests/` + `pytest`). Nên có regression test cho router/retrieval.
- **Recall của query rewrite:** heuristic `_FOLLOWUP_PATTERN` bias precision; có thể thêm LLM fallback hoặc mở rộng pattern nếu miss nhiều.

---

## Phụ lục A — File thay đổi (giai đoạn 2)

**RAG service:**
- `main.py` — `ChatRequest.history`; guard retrieval rỗng; gỡ `/chat/retrieve` + `QueryRequest`; nhánh smalltalk; truyền `history` cho router & generation.
- `app/services/router.py` — viết lại: router deterministic regex (SMALLTALK/SUMMARY/QA), nhận `history`.
- `app/services/retrieval.py` — `ENABLE_QUERY_REWRITE`, `_needs_context`, `_rewrite_query`, `_format_history_for_rewrite`; `retrieve_documents(query, document_ids, history=None)` dùng `retrieval_query` cho funnel + rerank.
- `app/services/generation.py` — `generate_rag_response(query, documents, history=None)` + `_format_history`.

**Backend Java:**
- `service/ChatbotClient.java` — `chat(...)` 4-arg + `ChatbotRequest.history` + `HistoryTurn`.
- `service/impl/ChatbotClientImpl.java` — gửi `history`.
- `service/impl/ChatServiceImpl.java` — `buildHistory()` (10 msg gần nhất) + `HISTORY_WINDOW`.
- `test/.../ChatServiceImplTest.java` — stub/verify sang matcher 4-arg.

## Phụ lục B — Không ảnh hưởng database

Toàn bộ giai đoạn 2 là **application logic** (router rules, prompt, wire payload `history`): **không sửa schema, không thêm/xóa cột, không migration.** `initdb.sql` không đổi. Deploy không cần chạy migration.
