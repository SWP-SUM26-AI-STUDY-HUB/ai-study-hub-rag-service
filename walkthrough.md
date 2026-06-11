# RAG Ingestion Pipeline Setup Complete

I have successfully created the RAG ingestion pipeline according to your requirements. I also commented out the AWS S3 upload logic as requested.

## What was implemented

1. **`requirements.txt`**: Added all necessary dependencies (`fastapi`, `langchain`, `boto3`, etc.).
2. **`main.py`**: The FastAPI entry point.
   - Exposes the `POST /api/v1/document/upload` endpoint.
   - Receives the `UploadFile` and Form metadata (`label`, `tag`, `description`).
   - Synchronously saves the file to a local `temp/` folder.
   - Triggers the background processing task and immediately returns a `202 Accepted` response.
3. **`rag_pipeline.py`**: The core processing logic.
   - **S3 Logic**: Added the `upload_to_s3` function but commented it out.
   - **Background Task (`process_document_task`)**:
     - Dynamically loads `.pdf` or `.txt` files.
     - **Metadata Inheritance**: Merges system metadata and user metadata into the `Document` object *before* splitting. This ensures all child chunks inherit these tags, which is critical for vector search filtering.
     - **Small-to-Big Indexing**: Uses `ParentDocumentRetriever`.
       - Parent chunks (`1000` chars) are stored in an `InMemoryStore` for maximum LLM context.
       - Child chunks (`200` chars) are embedded using `dangvantuan/vietnamese-embedding` and stored in `ChromaDB` for highly precise retrieval.
     - Logs the summary of parent documents and child chunks generated.
     - Cleans up the `temp/` file when finished.

## Notes for your Presentation

I have heavily commented the code in `rag_pipeline.py` to help you explain the architecture. Here are the key talking points:

> [!TIP]
> **Why Small-to-Big Indexing?**
> Explain that standard chunking is a trade-off: large chunks give the LLM good context but cause noisy vector searches; small chunks give precise vector matches but lack context for the LLM. The `ParentDocumentRetriever` solves this by searching on small chunks (child) and returning their larger source text (parent).

> [!TIP]
> **Metadata Enrichment Strategy**
> Emphasize that adding metadata *before* the text splitting process is vital. If you split first, you have to loop through thousands of chunks to add metadata. By adding it to the parent `Document` first, LangChain automatically propagates the metadata to every child chunk created.

## How to Run

1. Open a terminal in `C:\Users\Thien\OneDrive\Desktop\chatbot`.
2. Install dependencies: `pip install -r requirements.txt`
3. Start the server: `uvicorn main:app --reload`
4. Use a tool like Postman to send a `POST` request to `http://localhost:8000/api/v1/document/upload` with a file and form fields.
