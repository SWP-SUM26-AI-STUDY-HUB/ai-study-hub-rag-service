# Phân tích hiệu năng module truy vấn RAG

> **Trạng thái:** Phân tích gốc rễ + đề xuất giải pháp (chưa implement). Cần nghiên cứu thêm trước khi ra quyết định.
>
> **Triệu chứng quan sát:**
> - Truy vấn theo chunk của **1 tài liệu** (qua `document_id`): **~15s**
> - Truy vấn với **nhiều tài liệu**: **>60s**
> - Ảnh hưởng nặng nề tới triển khai chatbot.

---

## Tóm tắt nguyên nhân chính

Pipeline truy vấn hiện tại **không có bước nào song song**, và mỗi request phải **xếp hàng chờ một chuỗi 7–8 cuộc gọi API bên ngoài (Gemini + Jina) nối tiếp nhau**, chạy đồng bộ (blocking) ngay bên trong một handler `async` của FastAPI. Không có connection pool DB, embedding bị tính lặp lại, và `MultiQueryRetriever` sinh query bằng LLM **2 lần** cho mỗi request. Đây là lý do 15s cho 1 tài liệu; 60s+ cho nhiều tài liệu là hệ quả cộng dồn (phân tích ở cuối).

---

## Phân tích chi tiết luồng (kèm dòng code)

Sơ đồ chuỗi gọi hiện tại cho **1 request chat**:

```mermaid
graph TD
    A[/api/v1/chat async handler] --> B[Router: ChatGoogleGenerativeAI<br/>LLM #1 ~1.5s]
    B --> C[retrieve_documents]
    C --> D[mq.generate_queries<br/>LLM #2 ~1.5s — REDUNDANT]
    D --> E[compression_retriever.invoke]
    E --> F[MultiQueryRetriever sinh sub-queries<br/>LLM #3 ~1.5s]
    F --> G[Sub-query 1: Ensemble<br/>embed Gemini ~0.6s + SQL + BM25 + docstore files]
    G --> H[Sub-query 2: Ensemble<br/>serial, embed + SQL + BM25]
    H --> I[Sub-query 3: Ensemble<br/>serial, embed + SQL + BM25]
    I --> J[JinaRerank API ~2-3s<br/>top_n=5]
    J --> K[Post-filter BM25 leakage]
    K --> L[get_document_title — NEW DB conn]
    L --> M[generation: LLM #4 ~2.5s]
    M --> N[Response]

    style D fill:#fbb,stroke:#c00
    style G fill:#ffd,stroke:#a80
    style H fill:#ffd,stroke:#a80
    style I fill:#ffd,stroke:#a80
```

Mỗi ô vàng/đỏ là một round-trip mạng chặn event loop. Cộng tuyến tính → ~12–15s. Khớp với quan sát.

### Vấn đề từng điểm (có dẫn chứng dòng code)

**1. Multi-query generation gọi LLM 2 lần (LÃNG PHÍ HOÀN TOÀN)** — `retrieval.py:72` và `retrieval.py:80`
- Dòng 72 gọi `mq_retriever.generate_queries(query, run_manager)` → Gemini sinh sub-queries.
- Dòng 80 `compression_retriever.invoke(query)` → bên trong `MultiQueryRetriever._get_relevant_documents` **lại sinh sub-queries lần nữa**. `langchain` **không cache** giữa 2 lời gọi.
- → Một request mất thêm ~1.5–2s không cần thiết. Dòng 72 chỉ để lấy `generated_queries` trả về API; có thể thu thập bằng cách khác (xem giải pháp).

**2. Mỗi sub-query → 1 cuộc gọi embedding Gemini riêng, nối tiếp** — `vector_store.py:137`, `dependencies.py:60` (k=25)
- `ParentDocumentRetriever` (k=25) chạy cho **mỗi sub-query** (~3–4 cái). Mỗi lần `similarity_search` gọi `embed_query()` → 1 round-trip Gemini embedding.
- 3–4 sub-query × ~0.5–0.8s = ~2–3s, chạy **tuần tự** vì `EnsembleRetriever._get_relevant_documents` (sync) và `MultiQueryRetriever` (sync) đều lặp tuần tự, không `gather`.

**3. Handler `async` nhưng toàn bộ logic là blocking** — `main.py:90`, `retrieval.py` toàn bộ, `document_store.py:13/36/60`
- `async def chat_router` gọi `retrieve_documents` (đồng bộ: `psycopg2.connect`, SDK Gemini/Jina, file I/O). Việc này **chặn event loop** của uvicorn → không thể chồng giao nhau, và dưới tải thì toàn bộ worker bị đứng. Đây là lý do "ảnh hưởng nặng nề tới chatbot": latency không tệ chỉ ở 1 user mà tăng cấp số khi có người dùng đồng thời.

**4. Không connection pool — mở DB connection mới cho mỗi truy vấn** — `vector_store.py:17`, `document_store.py:13/36/60`
- `psycopg2.connect()` gọi mới mỗi lần search (multi-query = 3–4 conn) + mỗi `get_document_title`/`get_user_document_ids`. Mỗi handshake + auth ~20–50ms, cộng dần và chặn loop.

**5. BM25 không nhận filter → "leakage" tài liệu người khác + lãng phí slot rerank** — `retrieval.py:30` (chỉ set filter cho dense retriever), `retrieval.py:87-94` (post-filter SAU rerank)
- `retriever.search_kwargs["filter"]` chỉ áp dụng cho `ParentDocumentRetriever`. `state.bm25_retriever` (line 39) **không có filter** → BM25 lấy k=25 từ **toàn bộ corpus** mọi user.
- Post-filter (line 87–92) chạy **sau khi JinaRerank đã cắt xuống top_n=5**. Các doc leak từ user khác đã chiếm slot rerank → kết quả hợp lệ ít hơn hoặc = 0, và chi phí rerank bị lãng phí trên doc rác. Đây là **lỗ hổng bảo mật + chất lượng**, không chỉ hiệu năng.

**6. Thiếu index trên `document_id`** — `initdb.sql:175-190`
- Chỉ có HNSW index trên `embedding`. Câu query `WHERE document_id = ANY(%s::uuid[]) ORDER BY embedding <=> ... LIMIT 25` (`vector_store.py:99-113`) không có btree trên `document_id`. Với filter chọn lọc cao (1 tài liệu), pgvector phải quét nhiều vector hơn để đủ k kết quả match → query dense chậm hơn mức cần thiết.

**7. Client LLM/embedding được tạo mới mỗi request** — `router.py:43`, `retrieval.py:45`, `generation.py:46`, `dependencies.py:28`
- `ChatGoogleGenerativeAI(...)` instantiated mỗi lần → mất keep-alive/TLS, mỗi call thiết lập HTTP session mới. Cộng ~50–150ms/call.

**8. Docstore lookup file I/O không cần thiết trong hot path** — `dependencies.py:42-48`, `parent_docs_store/` (137+ files)
- `ParentDocumentRetriever` tra parent doc qua `LocalFileStore` (đọc 1 file/parent). Với ~25 children × 3–4 sub-queries → hàng chục file read nối tiếp. Không dominant (~0.2–0.5s) nhưng cộng thêm.

---

## Tại sao 1 tài liệu ~15s, nhiều tài liệu ~60s+?

- 15s được giải thích đầy đủ bởi chuỗi 7–8 API call nối tiếp (mục 1–4) — **chắc chắn**.
- Nhảy lên 60s+ cho nhiều tài liệu — `[INFERENCE]` là cộng dồn của:
  - BM25 leakage lớn hơn khi corpus lớn → nhiều candidate rác hơn đẩy vào Jina → Jina rerank v3 **tuyến tính theo số doc đầu vào**, candidate có thể tăng từ ~30 lên 75–100.
  - Nhiều cuộc gọi Gemini hơn → khả năng dính **rate-limit + exponential backoff/retry** của SDK (`langchain-google-genai` retry mặc định), mỗi retry thêm vài giây.
  - Filter `ANY(uuid[])` với list lớn + không index → planner có thể chọn seq scan.
- Để **chốt chính xác** 60s, cần đo từng giai đoạn (xem phần instrumentation). Nhưng các sửa đổi cấu trúc dưới đây sẽ cắt phần lớn ở **cả hai** trường hợp.

---

## Đề xuất giải pháp (theo độ ưu tiên / tác động)

### Tier 1 — Nhanh, tác động lớn (giảm 4–6s/request)

**S1. Khử multi-query LLM gọi 2 lần.** Đừng gọi `generate_queries` riêng ở line 72. Bật logging của `MultiQueryRetriever` để capture queries, hoặc override `_get_relevant_documents` để trả sub-queries ra ngoài qua callback/instance attr. Tiết kiệm 1 LLM call (~1.5s).

**S2. Dùng lại client Gemini/Jina toàn cục** (singleton module-level), không `new` mỗi request. Bật HTTP keep-alive → giảm TLS overhead mỗi call.

**S3. Đưa sync work ra threadpool.** Đổi `async def chat_router`/`retrieve_chat` thành `def` (FastAPI sẽ tự chạy trong threadpool), hoặc bọc `await run_in_executor(None, retrieve_documents, ...)`. Đây là **sửa đơn giản nhất** để event loop không bị chặn và cho phép chạy song song nhiều request.

**S4. Connection pool.** Dùng `psycopg2.pool.SimpleConnectionPool` (hoặc `psycopg`/`asyncpg` nếu đi async). Thay `_get_connection()` mở mới → `pool.getconn()`/`putconn()`.

### Tier 2 — Cấu trúc, cắt sâu hơn (giảm thêm 3–6s)

**S5. Song song hóa các sub-query retrievals.** Trong `MultiQueryRetriever`, chạy các sub-query qua `asyncio.gather` (đã support qua `_aget_relevant_documents`) và gọi bằng `await aretrieve()` từ một handler async thật sự. 3–4 sub-query chạy song song thay vì nối tiếp → cắt ~2–3s.

**S6. Đẩy filter vào BM25.** Thay vì post-filter, lọc `state.bm25_retriever.docs` theo `document_ids` trước khi search (hoặc duy trì BM25 per-user / dùng `PreEnsembleProcessor`). Khử leakage (bảo mật + chất lượng) và giảm input cho rerank.

**S7. Thêm index `document_id`.**
```sql
CREATE INDEX document_chunks_doc_id_idx ON document_chunks (document_id);
```
Giúp planner lọc nhanh trước/sau HNSW.

**S8. Giảm độ sâu funnel.** Đánh giá lại: với cross-encoder rerank tốt (Jina v3), **Multi-Query thường không đáng** (chi phí 3–4x search + 2 LLM call để thu lợi biên nhỏ). Có thể tắt Multi-Query cho QA thường, chỉ bật khi query phức tạp/đa khía cạnh. Hoặc giảm k từ 25 → 10 trước rerank.

**S9. Embedding dùng batch / cache.** Tính 1 lần embedding của query gốc và dùng lại; với sub-query vẫn cần embed riêng nhưng có thể batch các sub-query qua `embed_documents` (1 call thay vì N) nếu Gemini embedding hỗ trợ batch (có).

### Tier 3 — Kiến trúc dài hạn

**S10. Caching query→answer** (Redis) cho các câu hỏi lặp trong chatbot.

**S11. Cân nhắc async full stack** (`asyncpg` + `langchain` async retrievers + `httpx` async) để tận dụng event loop đúng cách nếu traffic cao.

---

## Bảng ưu tiên thực thi

| Giải pháp | Effort | Tác động | Rủi ro |
|---|---|---|---|
| S1 (bỏ LLM call kép) | Thấp | ~1.5s | Thấp |
| S2 (reuse client) | Thấp | ~0.5s | Thấp |
| S3 (threadpool/async đúng) | Thấp | Cắt latency dưới tải rất lớn | Thấp |
| S4 (conn pool) | Thấp | ~0.5s + ổn định | Thấp |
| S6 (filter BM25) | Trung bình | Bảo mật + chất lượng + rerank | Thấp |
| S5 (song song sub-query) | Trung bình | ~2–3s | Trung bình (cần async đúng) |
| S7 (index doc_id) | Thấp | Dense search nhanh | Thấp |
| S8 (giảm funnel) | Thấp | 2–4s | Cần đo recall |

Làm S1+S2+S3+S4+S7 trước (đều effort thấp) → kỳ vọng giảm từ 15s xuống ~6–8s và 60s xuống ~15–20s cho multi-doc. Sau đó S5+S6+S8 để tối ưu tiếp.

---

## Đề xuất: đo trước khi tối ưu

Trước khi sửa, thêm timing (wrapping `time.perf_counter()`) quanh 5 mốc: router LLM, query-gen, sub-query search loop, Jina rerank, generation. Điều này sẽ **chốt chính xác** tỷ trọng và xác nhận 60s đến từ đâu (mạnh nghiện Jina input-size và/hoặc Gemini retry).

> **Lưu ý quan trọng:** Vấn đề ở dòng `retrieval.py:87-94` (post-filter sau rerank + BM25 không filter) **không chỉ là chậm mà là lỗi bảo mật** — người dùng A có thể nhận chunk của người dùng B vào pool rerank. Nên ưu tiên S6 sớm bất kể hiệu năng.

---

## File liên quan (để tham chiếu khi implement)

- `app/services/retrieval.py` — luồng retrieve chính
- `app/services/router.py` — router LLM + branching
- `app/services/generation.py` — LLM sinh câu trả lời
- `app/database/vector_store.py` — dense search + connection
- `app/database/document_store.py` — DB lookups (title/summary/user docs)
- `app/pipeline/dependencies.py` — retriever, BM25, embeddings setup
- `initdb.sql` — schema + index (thiếu index `document_id`)
- `main.py` — FastAPI handlers (async/sync)
