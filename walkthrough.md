# Tái cấu trúc RAG Pipeline - Walkthrough

Quá trình chia nhỏ file `rag_pipeline.py` cồng kềnh thành các module chức năng riêng biệt đã hoàn thành! Dưới đây là cái nhìn tổng quan về những thay đổi đã được thực hiện và lợi ích của chúng đối với kiến trúc AI backend.

## Tổng quan thay đổi

- **Cấu trúc lại toàn bộ module**: Đã chia `rag_pipeline.py` thành `app/core`, `app/database`, `app/pipeline` và `app/services`.
- **Phân tách trách nhiệm**: Mỗi function và class nay đã được chuyển vào đúng module của mình (ví dụ `PostgresVectorStore` vào `database`, `retrieve_documents` vào `services/retrieval`).
- **Dễ đọc, dễ bảo trì**: Code trở nên rõ ràng và tuân thủ nguyên tắc thiết kế tốt của Python. Không còn tình trạng một file đảm nhiệm mọi công việc (Monolithic).

## Kiến trúc thư mục mới

```text
ai-study-hub-rag-service/
├── main.py (Entry point của FastAPI)
└── app/
    ├── __init__.py
    ├── core/
    │   ├── __init__.py
    │   └── config.py          (Đọc biến môi trường như DB URL)
    ├── database/
    │   ├── __init__.py
    │   └── vector_store.py    (Lớp truy xuất PostgreSQL Vector)
    ├── pipeline/
    │   ├── __init__.py
    │   └── dependencies.py    (Khởi tạo LLM, Embeddings, Doc Store, Splitters)
    ├── services/
        ├── __init__.py
        ├── ingestion.py       (Logic xử lý file, tạo summary, gọi callback backend)
        └── retrieval.py       (Logic Hybrid search, Multi-query)
```

## Các File Quan Trọng Đã Được Tạo:

### 1. [app/core/config.py](file:///Users/chithien/code/ai-study-hub-rag-service/app/core/config.py)
Giờ đây, nếu cậu muốn đổi tên biến môi trường hoặc cấu hình chung, cậu chỉ cần vào file `config.py`.

### 2. [app/database/vector_store.py](file:///Users/chithien/code/ai-study-hub-rag-service/app/database/vector_store.py)
Class `PostgresVectorStore` có nhiệm vụ lưu document chunk (được biểu diễn vector). Việc đưa class này ra riêng biệt giúp sau này dễ dàng đổi sang database khác (như Chroma hay Milvus) nếu muốn.

### 3. [app/pipeline/dependencies.py](file:///Users/chithien/code/ai-study-hub-rag-service/app/pipeline/dependencies.py)
File này sử dụng design pattern Singleton để khởi tạo một lần các thành phần nặng của LLM như:
- `HuggingFaceEmbeddings`
- `PostgresVectorStore` instance
- `ParentDocumentRetriever`

### 4. Logic xử lý API
- Logic download và xử lý PDF/Docx nằm trong [app/services/ingestion.py](file:///Users/chithien/code/ai-study-hub-rag-service/app/services/ingestion.py).
- Logic truy vấn câu trả lời (Retrieval) nằm trong [app/services/retrieval.py](file:///Users/chithien/code/ai-study-hub-rag-service/app/services/retrieval.py).

### 5. [main.py](file:///Users/chithien/code/ai-study-hub-rag-service/main.py)
Cập nhật file entry point gọi các hàm từ `services`. Khởi tạo `BM25Retriever` trong sự kiện `startup_event`.

## Đã Xác Minh Thành Công
> [!TIP]
> Tớ đã chạy script test import và syntax `python -c "import main"`.
> Các module đều được import hoàn hảo mà không bị "circular import".

Giờ đây cậu có thể phát triển và quản lý các chức năng RAG thoải mái hơn rồi nhé! Mọi thứ đã được sắp xếp ngăn nắp. Cậu có thể test lại project bằng `uvicorn main:app --reload`!
