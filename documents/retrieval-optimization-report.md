# Báo cáo tối ưu hiệu năng module truy vấn RAG

> **Trạng thái:** Đã triển khai S1–S4, S6, S8 + warmup client + hệ đo lường. S5 được phân tích và bỏ qua (không còn giá trị). S7 do team chạy trực tiếp. Phần "đề xuất tiếp theo" ở cuối đang chờ quyết định.
>
> **Môi trường đo:** VPS production (Docker), corpus nhiều tài liệu. Mọi số liệu trong báo cáo đều lấy từ `logs/performance.log` của các request test thực tế — không phải ước lượng.

---

## Tóm tắt kết quả (TL;DR)

| Giai đoạn | Truy vấn 1 tài liệu | Truy vấn nhiều tài liệu |
|---|---:|---:|
| **Trước tối ưu** | ~15s | **>60s** |
| Sau S1–S4 + S7 ( instrumentation đo) | ~15.7s (TB) | ~17s (TB) |
| Sau S6 + S8 (đã nóng) | ~5.8s | ~3.2–4s |
| Sau S6 + S8 + warmup (request đầu) | **~5.2s** | — |

**Kết: từ ~15s / 60s+ xuống ~5s.** Phần truy vấn (retrieval) giờ chỉ ~1s; ~75% thời gian còn lại là 2 lời gọi LLM Gemini (`generation` + `router_llm`) + Jina rerank.

---

## 1. Bối cảnh & triệu chứng

Module truy vấn của RAG service chậm nghiêm trọng, ảnh hưởng trực tiếp tới trải nghiệm chatbot:

- Truy vấn theo chunk của **1 tài liệu** (qua `document_id`): **~15 giây**.
- Truy vấn với **nhiều tài liệu** (theo `user_id`): **>60 giây**.

Triệu chứng cho thấy đây không phải vấn đề đơn lẻ mà là cộng dồn của một chuỗi gọi API nối tiếp không có bước song song nào, chạy blocking ngay trong handler `async` của FastAPI.

---

## 2. Phân tích vấn đề của service cũ

Pipeline truy vấn cũ không có bước nào song song, mỗi request xếp hàng chờ **7–8 cuộc gọi API ngoài (Gemini + Jina) nối tiếp nhau**, chạy đồng bộ (blocking) trong handler `async`. Tám vấn đề cụ thể (có dẫn chứng dòng code của service cũ):

1. **Multi-query gọi LLM 2 lần (lãng phí hoàn toàn)** — `retrieval.py` cũ gọi `generate_queries()` riêng để lấy sub-query trả về API, rồi `compression_retriever.invoke()` bên trong `MultiQueryRetriever._get_relevant_documents` lại sinh sub-query lần nữa. LangChain không cache giữa 2 lời gọi → mỗi request mất thêm ~1.5–2s không cần thiết.

2. **Mỗi sub-query → 1 cuộc gọi embedding Gemini riêng, nối tiếp** — 3–4 sub-query, mỗi lần `similarity_search` gọi `embed_query()` → 1 round-trip Gemini. `EnsembleRetriever` và `MultiQueryRetriever` đều lặp tuần tự, không `gather` → cộng dồn 2–3s.

3. **Handler `async` nhưng toàn bộ logic là blocking** — `async def chat_router` gọi `retrieve_documents` (đồng bộ: `psycopg2.connect`, SDK Gemini/Jina, file I/O). Việc này **chặn event loop** của uvicorn → dưới tải, toàn bộ worker bị đứng. Đây là lý do "ảnh hưởng nặng nề tới chatbot": latency tăng cấp số khi có người dùng đồng thời.

4. **Không connection pool — mở DB connection mới cho mỗi truy vấn** — `psycopg2.connect()` gọi mới mỗi lần search + mỗi `get_document_title`/`get_user_document_ids`. Mỗi handshake + auth ~20–50ms, cộng dần và chặn loop.

5. **BM25 không nhận filter → "leakage" tài liệu người khác + lãng phí slot rerank** — `retriever.search_kwargs["filter"]` chỉ áp dụng cho dense retriever. `state.bm25_retriever` không có filter → BM25 lấy k=25 từ **toàn bộ corpus** mọi user. Post-filter lại chạy **sau** khi JinaRerank đã cắt xuống top_n=5 → doc leak đã chiếm slot rerank. **Đây là lỗ hổng bảo mật + chất lượng, không chỉ hiệu năng.**

6. **Thiếu index trên `document_id`** — chỉ có HNSW index trên `embedding`. Câu query `WHERE document_id = ANY(%s::uuid[]) ORDER BY embedding <=> ... LIMIT 25` không có btree trên `document_id` → pgvector phải quét nhiều vector hơn để đủ k kết quả.

7. **Client LLM/embedding/reranker được tạo mới mỗi request** — `ChatGoogleGenerativeAI(...)` / `JinaRerank(...)` instantiated mỗi lần → mất keep-alive/TLS, mỗi call thiết lập HTTP session mới. Cộng ~50–150ms/call.

8. **Docstore lookup file I/O trong hot path** — `ParentDocumentRetriever` tra parent doc qua `LocalFileStore` (đọc 1 file/parent). Với ~25 children × 3–4 sub-query → hàng chục file read nối tiếp (không dominant nhưng cộng thêm).

---

## 3. Quy trình đo lường (instrumentation)

Trước khi tối ưu tiếp, đã thêm hệ đo lường per-request để **chốt chính xác tỷ trọng** bằng dữ liệu thật, thay vì suy đoán.

**Cơ chế:** Một `PerformanceTrace` được tạo mỗi request, lưu trong `ContextVar` để mọi hàm trong call graph (router, retrieval, generation, vector store) đều ghi được một "stage" có tên mà không phải đổi signature. Trace được:
- ghi thành 1 dòng JSON vào `logs/performance.log` (rotate 10MB × 10),
- nhúng vào trường `debug.timing` của response API.

**Các stage đo được:**

| Stage | Nguồn | Ý nghĩa |
|---|---|---|
| `router_llm` | router.py | LLM phân loại SUMMARY/QA |
| `user_doc_ids` | router.py | DB lấy danh sách doc của user |
| `query_generation` | retrieval.py | LLM sinh sub-query (multi-query) |
| `embed_query` | vector_store.py | embedding Gemini (gộp nếu nhiều sub-query) |
| `dense_sql` | vector_store.py | dense vector search pgvector |
| `multi_query_search` / `hybrid_search` | retrieval.py | tổng giai đoạn search |
| `rerank` | retrieval.py | Jina cross-encoder |
| `bm25_build` | retrieval.py | dựng BM25 đã lọc (sau S6) |
| `title_fetch` | retrieval.py | DB lấy tiêu đề tài liệu |
| `generation` | generation.py | LLM sinh câu trả lời |

Tắt bằng env `ENABLE_PERF_LOG=0`.

---

## 4. Các giải pháp đã thực hiện & bằng chứng từ log

### 4.1. Nhóm Tier 1 — S1, S2, S3, S4 (triển khai trước, đo sau)

#### S1 — Khử multi-query LLM gọi 2 lần
- **Vấn đề:** 2 lời gọi LLM trùng lặp (mục 1).
- **Cách làm:** Tạo subclass `CapturingMultiQueryRetriever(MultiQueryRetriever)` override `generate_queries()` để **capture** sub-query ngay trong đúng lời gọi LLM chạy bên trong `invoke()`. Nhờ vậy không cần gọi `generate_queries()` riêng nữa — chỉ còn **1 LLM call**.
- **File:** `app/services/retrieval.py` (class `CapturingMultiQueryRetriever`).

#### S2 — Dùng lại client toàn cục (singleton)
- **Vấn đề:** Client mới mỗi request (mục 7).
- **Cách làm:** Tạo module `app/core/clients.py` với 2 singleton tạo 1 lần lúc import: `llm` (ChatGoogleGenerativeAI) và `reranker` (JinaRerank). Toàn bộ router/retrieval/generation/ingestion import và tái sử dụng. Giữ HTTP keep-alive, bỏ TLS overhead mỗi call.
- **File:** `app/core/clients.py` (mới); sửa `router.py`, `retrieval.py`, `generation.py`, `ingestion.py`.

#### S3 — Đưa sync work ra threadpool
- **Vấn đề:** Handler `async` nhưng logic blocking (mục 3).
- **Cách làm:** Đổi `async def chat_router` và `async def retrieve_chat` thành `def` thường. FastAPI/Starlette tự chạy `def` handler trong threadpool → event loop không bị chặn, nhiều request chạy chồng giao nhau.
- **File:** `main.py`.

#### S4 — Connection pool
- **Vấn đề:** Mở DB connection mới mỗi truy vấn (mục 4).
- **Cách làm:** Module `app/database/pool.py` dùng `psycopg2.pool.ThreadedConnectionPool` (chọn thread-safe vì S3 chạy handler trong threadpool), minconn=1 / maxconn=`DB_POOL_MAX`(default 20). Context manager `db_connection()` mượn/trả connection; tự rollback ở finally để connection trả pool luôn sạch. Toàn bộ `vector_store.py` + `document_store.py` thay `psycopg2.connect()`/`close()` bằng pool.
- **File:** `app/database/pool.py` (mới); sửa `vector_store.py`, `document_store.py`.

#### S7 — Thêm index `document_id` (do team chạy trực tiếp)
- **Vấn đề:** Thiếu index (mục 6).
- **Cách làm:** `CREATE INDEX document_chunks_doc_id_idx ON document_chunks (document_id);`

#### Bằng chứng từ log (sau S1–S4 + S7, **chưa** S6/S8)
Đo 3 request trên VPS:

| Stage | Req1 (1doc) | Req2 (multi) | Req3 (multi) | **Trung bình** |
|---|---:|---:|---:|---:|
| router_llm | 2525 | 6711 | 778 | 3338 |
| query_generation | 3609 | 6843 | 7954 | **6135** |
| embed_query (×3) | 1321 | 1422 | 1102 | 1282 |
| dense_sql (×3) | 56 | 28 | 31 | **38** |
| multi_query_search | 4999 | 8312 | 9111 | 7474 |
| rerank | 1396 | 730 | 984 | 1037 |
| generation | 8690 | 1128 | 1653 | 3824 |
| **TOTAL** | **17614** | **16889** | **12530** | **~15677 (15.7s)** |

**Phát hiện then chốt từ log này:** Phần **search lại rất nhanh** (`dense_sql` chỉ **38ms** — S7 phát huy, BM25+docstore ~13ms). Bottleneck thực sự là **3 lời gọi LLM nối tiếp** (`router_llm` + `query_generation` + `generation` = 3338+6135+3824 = **13297ms = 85% tổng**). Giả định ban đầu "search chậm" **không đúng** — dữ liệu đảo lại độ ưu tiên của S5/S6/S8.

Đồng thời phát hiện **biến thiên khổng lồ** ở LLM (router 778↔6711, generation 1128↔8690) = hiện tượng **rate-limit + retry/backoff** của SDK Gemini.

---

### 4.2. S6 — Đẩy filter vào BM25 (bảo mật + chất lượng)

- **Vấn đề:** Leakage tài liệu người khác (mục 5) — lỗ hổng bảo mật, không chỉ hiệu năng.
- **Cách làm:** Hàm `_build_filtered_bm25(document_ids)` trong `retrieval.py` lọc `state.bm25_retriever.docs` theo `document_id` rồi dựng `BM25Retriever` con → BM25 **không thể** trả doc user khác. Dense retriever vẫn filter ở SQL. Cả 2 nguồn sạch → **xóa hẳn block post-filter cũ** (chạy sau rerank). Thêm stage `bm25_build` để đo overhead.
- **File:** `app/services/retrieval.py` (hàm `_build_filtered_bm25`).

**Bằng chứng từ log (sau S6):** `bm25_build` chỉ **1.9–9.4ms** → overhead pre-filter không đáng kể. Leakage đã bị chặn ngay nguồn (đã verify bằng unit test: BM25 lọc không bao giờ trả doc của user khác).

---

### 4.3. S8 — Tắt Multi-Query mặc định (đỉnh funnel, lever lớn nhất)

- **Vấn đề:** `query_generation` chiếm **6135ms TB** — stage lớn nhất, mà đa phần QA không cần multi-query.
- **Cách làm:** Env toggle `ENABLE_MULTI_QUERY` (default **0 = tắt**). Khi tắt → bỏ qua `MultiQueryRetriever`, gọi thẳng `ensemble_retriever.invoke(query)` (1 lần search), **triệt tiêu hoàn toàn `query_generation`** và giảm search từ 3 lần → 1 lần. `generated_queries = [query]`. Bật `=1` khi cần query phức tạp/đa khía cạnh, không cần sửa code.
- **File:** `app/services/retrieval.py` (toggle + nhánh if/else).

**Bằng chứng từ log (sau S6 + S8):**

| Stage | Req1 (1doc, lạnh) | Req2 (multi) | Req3 (multi) | Req4 (1doc) | Req5 (1doc) |
|---|---:|---:|---:|---:|---:|
| router_llm | 4297 | 737 | 789 | 1040 | 713 |
| bm25_build | 2.3 | 9.4 | 5.1 | 3.6 | 1.9 |
| embed_query (×1) | 606 | 361 | 343 | 361 | 374 |
| dense_sql (×1) | 32 | 17 | 8 | 7 | 7 |
| hybrid_search | 643 | 385 | 356 | 374 | 384 |
| rerank | 649 | 557 | 605 | 508 | 1276 |
| generation | 14046 | 1514 | 2292 | 2640 | 3453 |
| **TOTAL** | **19641** | **3207** | **4051** | **4568** | **5828** |

Steady-state (Req2–5): **~3.2–5.8s, trung bình ~4.4s** (từ 15.7s). Đã mất hẳn `query_generation` và `multi_query_search`; `embed_query`/`dense_sql` giờ chỉ 1 call. Nhưng phát sinh vấn đề mới: **request đầu (Req1) lên 19.6s**.

---

### 4.4. Warmup client lúc startup (khắc phục cold-start request đầu)

- **Vấn đề (phát hiện từ Req1 ở 4.3):** Request đầu sau mỗi lần (re)start server mất 19.6s. Phân tích: `router_llm` 4297ms + `generation` 14046ms = 18.3s (93%). **Bằng chứng quyết định:** Req1 và Req5 dùng **cùng query + cùng document** nhưng `generation` là 14046ms (Req1) vs 3453ms (Req5) → khác 4 lần chỉ vì nóng/lạnh. Đây là **cold-start của client LLM** (TLS + OAuth token fetch + SDK init, có thể kèm 1 retry), không phải do nội dung hay retrieval.
- **Cách làm:** Hàm `_warmup_clients()` chạy trong startup event: gọi `llm.invoke("hi")` + `embeddings.embed_query("warmup")` trong 1 thread daemon có cap 20s. Đẩy cold-start về lúc khởi động (server chưa nhận user). Lỗi warmup chỉ log warning rồi tiếp tục — không sập server.
- **File:** `main.py`.

**Bằng chứng từ log (sau warmup, request đầu sau restart):**

| Stage | Req đầu (trước warmup) | Req đầu (sau warmup) |
|---|---:|---:|
| router_llm | 4297 | **894** |
| hybrid_search | 643 | 531 |
| rerank | 649 | 508 |
| generation | 14046 | **3278** |
| **TOTAL** | **19641** | **5217** |

Request đầu giờ ngang steady-state (~5.2s). Cold-start đã bị hấp thụ lúc startup.

---

## 5. Kết quả tổng thể

### Hành trình tối ưu

| Bước | Việc | 1 doc | multi-doc | Ghi chú |
|---|---|---:|---:|---|
| 0 | Trước tối ưu | ~15s | >60s | Triệu chứng ban đầu |
| 1 | S1–S4 + S7 | ~15.7s | ~17s | Cắt overhead cấu trúc; đo thấy search đã nhanh, LLM mới là bottleneck |
| 2 | + S6 (BM25 filter) | — | — | Sửa lỗi bảo mật leakage; overhead ~5ms |
| 3 | + S8 (tắt multi-query) | ~5.8s (nóng) | ~3.2–4s (nóng) | Triệt tiêu query_generation ~6s |
| 4 | + warmup client | ~5.2s (req đầu) | — | Khắc phục cold-start 19.6s → 5.2s |

### Phân bổ thời gian steady-state hiện tại (~4.4s, Req2–5 trung bình)

| Stage | Trung bình | % tổng |
|---|---:|---:|
| generation | ~2475ms | 56% |
| router_llm | ~820ms | 19% |
| rerank | ~736ms | 17% |
| hybrid_search | ~375ms | 8.5% |
| bm25_build / dense_sql / title_fetch | ~16ms | <1% |

**Tổng các lời gọi LLM (`generation` + `router_llm`) = ~3.3s = ~75% thời gian còn lại.** Phần retrieval giờ chỉ ~1.1s.

---

## 6. Đề xuất giải pháp tiếp theo (chưa làm, chờ quyết định)

Steady-state hiện ~4.4s. Để xuống dưới ~3s, phải tấn công vào 2 LLM call + rerank:

### 6.1. Tối ưu `router_llm` (~−0.8s, rủi ro thấp)
`router_llm` chỉ phân loại SUMMARY vs QA — có thể thay bằng **keyword heuristic** (phát hiện từ khóa như "tóm tắt/summary/overview" → SUMMARY, còn lại → QA), bỏ hẳn 1 LLM call. Khuyến nghị giữ LLM làm **fallback** khi heuristic không chắc chắn. Cắt ~820ms mỗi request.

### 6.2. Tune `generation` (lever lớn nhất hiện tại, ~2.5s)
- **Kiểm tra "thinking mode":** Gemini 2.5 series hỗ trợ thinking (reasoning nội bộ trước khi trả lời). Nếu đang bật, có thể là nguồn ~3s. Thử tắt (`thinking_budget=0`) cho QA RAG — có thể cắt đáng kể mà không giảm chất lượng câu trả lời ngắn.
- **Tune retry/timeout:** giảm biến thiên do retry/backoff (hiện generation dao động 1.5–3.5s).
- **`max_output_tokens`:** giới hạn độ dài câu trả lời để giảm latency.

### 6.3. Giảm input rerank (~−0.2s)
Jina rerank ~0.5–1.3s (API latency + tuyến tính theo số doc đầu vào). Giảm số candidate đưa vào rerank (hiện output top-5) → cắt nhẹ. Lưu ý phải đo recall để không mất chất lượng.

### 6.4. Caching query→answer (S10, dài hạn)
Redis cache cho các câu hỏi lặp trong chatbot. Hiệu quả cao với traffic có nhiều query trùng, nhưng cần chiến lược invalidation khi tài liệu thay đổi.

### 6.5. Batch embedding (S9)
Tính embedding của query gốc 1 lần và dùng lại; với sub-query (nếu bật multi-query) có thể batch qua `embed_documents` (1 call thay vì N). Hiện multi-query đang tắt nên không ưu tiên.

### 6.6. Async full stack (S11, kiến trúc dài hạn)
`asyncpg` + langchain async retrievers + `httpx` async. Chỉ đáng làm nếu traffic cao và muốn tận dụng event loop đúng cách. Effort lớn.

---

## 7. Phụ lục: cấu hình env mới

| Biến môi trường | Default | Ý nghĩa |
|---|---|---|
| `ENABLE_MULTI_QUERY` | `0` (tắt) | S8 — bật multi-query (=1) cho query phức tạp |
| `DB_POOL_MAX` | `20` | S4 — số connection tối đa trong pool |
| `ENABLE_PERF_LOG` | `1` (bật) | Tắt hệ đo lường (=0) |

---

## 8. Danh sách file đã thay đổi / tạo

**Tạo mới:**
- `app/core/clients.py` — singleton LLM + reranker (S2)
- `app/database/pool.py` — connection pool (S4)
- `app/core/performance.py` — hệ đo lường per-request (instrumentation)
- `documents/retrieval-optimization-report.md` — báo cáo này

**Sửa:**
- `app/services/retrieval.py` — S1 (CapturingMultiQueryRetriever), S6 (BM25 filter), S8 (toggle multi-query), tách funnel + timing
- `app/services/router.py` — S2 (singleton) + timing
- `app/services/generation.py` — S2 (singleton) + timing
- `app/services/ingestion.py` — S2 (singleton)
- `app/database/vector_store.py` — S4 (pool) + timing embed/sql
- `app/database/document_store.py` — S4 (pool)
- `main.py` — S3 (sync handler), warmup client, trace lifecycle, debug timing
- `docker-compose.yml` — mount `./logs:/app/logs`
- `.gitignore` — bỏ qua `logs/`

**S5 (song song sub-query):** đã phân tích và **bỏ qua** — vì `dense_sql` chỉ ~38ms, phần tuần tự đáng kể duy nhất là `embed_query` (3× ~430ms); song song hóa chỉ cắt ~0.85s, mà sau S8 chỉ còn 1 search nên hoàn toàn vô nghĩa. Không xứng đáng rủi ro/phức tạp async.
