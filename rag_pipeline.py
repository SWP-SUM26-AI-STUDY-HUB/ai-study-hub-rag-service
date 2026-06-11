import os
import logging
from datetime import datetime
import json
import uuid
import urllib.request
import shutil
import time
from typing import List, Tuple, Any, Optional

from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStore
from langchain_community.document_loaders import PyPDFLoader, TextLoader, Docx2txtLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain.storage import LocalFileStore
from langchain.storage.encoder_backed import EncoderBackedStore
from langchain.retrievers import ParentDocumentRetriever
from langchain_community.retrievers import BM25Retriever
from langchain.retrievers import EnsembleRetriever
from langchain.retrievers.multi_query import MultiQueryRetriever
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.retrievers import ContextualCompressionRetriever
from langchain.retrievers.document_compressors import CrossEncoderReranker
from langchain_community.cross_encoders import HuggingFaceCrossEncoder
from langchain_core.callbacks.manager import CallbackManagerForRetrieverRun
import psycopg2
from psycopg2.extras import execute_values, RealDictCursor

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==========================================
# 1. CUSTOM POSTGRES VECTOR STORE
# ==========================================
class PostgresVectorStore(VectorStore):
    def __init__(self, connection_string: str, embedding_function, table_name: str = "document_chunks"):
        self.connection_string = connection_string
        self.embedding_function = embedding_function
        self.table_name = table_name

    def _get_connection(self):
        return psycopg2.connect(self.connection_string)

    def add_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[dict]] = None,
        **kwargs: Any,
    ) -> List[str]:
        embeddings = self.embedding_function.embed_documents(texts)
        ids = [str(uuid.uuid4()) for _ in texts]
        
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                rows = []
                for i, text in enumerate(texts):
                    metadata = metadatas[i] if metadatas else {}
                    # Extract document_id from metadata or kwargs
                    doc_id = metadata.get("document_id") or kwargs.get("document_id")
                    
                    # page_number (Chroma stores it as page)
                    page_number = metadata.get("page") or metadata.get("page_number")
                    if page_number is not None:
                        try:
                            page_number = int(page_number)
                        except ValueError:
                            page_number = None
                    
                    # chunk_index
                    chunk_index = metadata.get("chunk_index", i)
                    
                    # embedding as a list of floats -> PGVector format [f1,f2,...]
                    emb = embeddings[i]
                    emb_str = "[" + ",".join(map(str, emb)) + "]"
                    
                    rows.append((
                        ids[i],
                        doc_id,
                        chunk_index,
                        text,
                        emb_str,
                        json.dumps(metadata),
                        page_number
                    ))
                
                execute_values(
                    cur,
                    f"""
                    INSERT INTO {self.table_name} (id, document_id, chunk_index, content, embedding, metadata, page_number)
                    VALUES %s
                    """,
                    rows
                )
                conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
        return ids

    def similarity_search_by_vector(
        self,
        embedding: List[float],
        k: int = 4,
        filter: Optional[dict] = None,
        **kwargs: Any,
    ) -> List[Document]:
        conn = self._get_connection()
        docs = []
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                filter_clause = ""
                params = []
                
                emb_str = "[" + ",".join(map(str, embedding)) + "]"
                params.append(emb_str)
                
                if filter:
                    if "document_ids" in filter:
                        doc_ids = filter["document_ids"]
                        if doc_ids:
                            filter_clause = "AND document_id = ANY(%s)"
                            params.append(doc_ids)
                    elif "document_id" in filter:
                        doc_id = filter["document_id"]
                        if doc_id:
                            filter_clause = "AND document_id = %s"
                            params.append(doc_id)
                
                sql = f"""
                SELECT content, metadata, page_number, (embedding <=> %s) AS distance
                FROM {self.table_name}
                WHERE 1=1 {filter_clause}
                ORDER BY embedding <=> %s
                LIMIT %s
                """
                params.extend([emb_str, k])
                
                cur.execute(sql, params)
                results = cur.fetchall()
                for row in results:
                    metadata = row["metadata"] or {}
                    if row["page_number"] is not None:
                        metadata["page_number"] = row["page_number"]
                    docs.append(Document(
                        page_content=row["content"],
                        metadata=metadata
                    ))
        finally:
            conn.close()
        return docs

    def similarity_search(
        self,
        query: str,
        k: int = 4,
        filter: Optional[dict] = None,
        **kwargs: Any,
    ) -> List[Document]:
        embedding = self.embedding_function.embed_query(query)
        return self.similarity_search_by_vector(embedding, k=k, filter=filter, **kwargs)

    def count_chunks(self) -> int:
        conn = self._get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {self.table_name}")
                return cur.fetchone()[0]
        finally:
            conn.close()

    @classmethod
    def from_texts(
        cls,
        texts: List[str],
        embedding,
        metadatas: Optional[List[dict]] = None,
        **kwargs: Any,
    ) -> "PostgresVectorStore":
        connection_string = kwargs.get("connection_string") or os.getenv("DATABASE_URL")
        table_name = kwargs.get("table_name", "document_chunks")
        store = cls(connection_string, embedding, table_name)
        store.add_texts(texts, metadatas, **kwargs)
        return store

# ==========================================
# 2. RAG PIPELINE INITIALIZATION
# ==========================================
# Embeddings: Using lightweight Vietnamese model as requested
embeddings = HuggingFaceEmbeddings(model_name="dangvantuan/vietnamese-embedding")

# Vector Store: Postgres pgvector table instead of ChromaDB
db_url = os.getenv("DATABASE_URL", "postgresql://nnct:Nnct1608@localhost:5432/aistudyhub")
vectorstore = PostgresVectorStore(
    connection_string=db_url,
    embedding_function=embeddings
)

# Document Store: Persistent LocalFileStore to hold the large parent documents.
def _doc_to_bytes(doc: Document) -> bytes:
    return json.dumps({"page_content": doc.page_content, "metadata": doc.metadata}).encode("utf-8")

def _bytes_to_doc(b: bytes) -> Document:
    data = json.loads(b.decode("utf-8"))
    return Document(page_content=data["page_content"], metadata=data["metadata"])

fs = LocalFileStore("./parent_docs_store")
store = EncoderBackedStore(
    store=fs,
    key_encoder=lambda x: x,
    value_serializer=_doc_to_bytes,
    value_deserializer=_bytes_to_doc
)

# Splitters: Define Small-to-Big chunking strategy
# parent_splitter keeps large context for the LLM
parent_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
# child_splitter creates small, focused chunks for precise vector retrieval
child_splitter = RecursiveCharacterTextSplitter(chunk_size=200, chunk_overlap=50)

# Parent Document Retriever Setup (Top of Funnel: Dense search gets k=25)
retriever = ParentDocumentRetriever(
    vectorstore=vectorstore,
    docstore=store,
    child_splitter=child_splitter,
    parent_splitter=parent_splitter,
    search_kwargs={"k": 25}
)

# Global BM25 Retriever
bm25_retriever = None

# --- Auto-Rebuild BM25 on Startup ---
# Since our document store is now persistent, we must load all existing documents
# when the server starts so that the BM25 search engine is ready immediately.
def initialize_bm25():
    global bm25_retriever
    try:
        keys = list(store.yield_keys())
        if keys:
            all_parent_docs = store.mget(keys)
            all_parent_docs = [doc for doc in all_parent_docs if doc is not None]
            if all_parent_docs:
                bm25_retriever = BM25Retriever.from_documents(all_parent_docs, k=25)
                logger.info(f"Startup: Successfully rebuilt BM25Retriever with {len(all_parent_docs)} documents from persistent store.")
            else:
                logger.info("Startup: No valid documents found in persistent store. BM25Retriever remains empty.")
        else:
            logger.info("Startup: No documents found in persistent store. BM25Retriever remains empty.")
    except Exception as e:
        logger.error(f"Startup: Failed to rebuild BM25Retriever: {e}")

initialize_bm25()

# ==========================================
# 3. BACKGROUND PROCESSING TASK
# ==========================================
def generate_document_summary(docs: List[Document]) -> str:
    """
    Generates a concise summary of the document content using Gemini.
    """
    try:
        full_text = ""
        for doc in docs:
            full_text += doc.page_content + "\n"
            if len(full_text) > 20000:
                break
        
        if not full_text.strip():
            return "No content available to summarize."

        llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", temperature=0)
        prompt = (
            "You are a professional study assistant.\n"
            "First, analyze the document content below to identify its primary language.\n"
            "Then, generate a concise summary (around 2-3 paragraphs) of the main points of the document. "
            "The summary must be written in the identified primary language of the document.\n"
            "Format the summary with a clear structure using Markdown.\n"
            "Return only the final summary. Do not include any language labels, preamble, or metadata in the response.\n\n"
            f"Document Content:\n{full_text[:20000]}"
        )
        
        response = llm.invoke(prompt)
        return response.content
    except Exception as e:
        logger.error(f"Failed to generate summary: {e}")
        return "Tài liệu đã được tải lên thành công, tuy nhiên việc tự động tạo tóm tắt gặp sự cố."

def send_callback(document_id: str, status: str, summary: str = "", max_retries: int = 3):
    callback_url = os.getenv("BACKEND_CALLBACK_URL", "http://localhost:8080/api/v1/internal/documents/callback")
    internal_secret = os.getenv("INTERNAL_API_SECRET", "default-secret-key-change-me")
    logger.info(f"Sending callback to backend: url={callback_url}, doc_id={document_id}, status={status}")
    
    payload = {
        "document_id": document_id,
        "status": status,
        "summary": summary
    }
    
    headers = {
        "Content-Type": "application/json",
        "X-Internal-Secret": internal_secret
    }
    
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(
                callback_url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                logger.info(f"Callback response status: {resp.status}")
                return
        except Exception as e:
            logger.error(f"Failed to send callback to backend (Attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                time.sleep(2 ** attempt)

# ==========================================
# 3. BACKGROUND PROCESSING TASK
# ==========================================
def process_document_task(file_url: str, filename: str, metadata_input: dict):
    """
    Background task to process the uploaded document and ingest it into the RAG pipeline.
    """
    logger.info(f"Starting background processing for {filename}...")
    document_id = metadata_input.get("document_id")

    TEMP_DIR = "temp"
    os.makedirs(TEMP_DIR, exist_ok=True)
    file_path = os.path.join(TEMP_DIR, f"{document_id}_{filename}")

    try:
        # --- A. Download File ---
        logger.info(f"Downloading file from S3: {file_url}")
        req = urllib.request.Request(
            file_url,
            headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req) as response, open(file_path, "wb") as out_file:
            shutil.copyfileobj(response, out_file)

        # --- B. Load Document ---
        ext = os.path.splitext(filename)[1].lower()
        if ext == '.pdf':
            loader = PyPDFLoader(file_path)
        elif ext in ('.txt', '.md'):
            loader = TextLoader(file_path, encoding='utf-8')
        elif ext == '.docx':
            loader = Docx2txtLoader(file_path)
        else:
            logger.error(f"Unsupported file type: {ext}")
            if document_id:
                send_callback(document_id, "FAILED")
            return

        docs = loader.load()

        # --- C. Metadata Enrichment ---
        system_metadata = {
            "source_file": filename,
            "file_type": ext,
            "processed_date": datetime.now().isoformat()
        }
        
        for doc in docs:
            doc.metadata.update(system_metadata)
            doc.metadata.update(metadata_input)

        # --- D. Parent-Child Indexing (Small-to-Big Strategy) ---
        logger.info("Executing Parent-Child chunking and vector indexing...")
        retriever.add_documents(docs, ids=None)

        # --- E. Pipeline Output Summary ---
        parent_docs_count = len(list(store.yield_keys()))
        child_chunks_count = vectorstore.count_chunks()
        
        logger.info(
            f"\n--- Indexing Summary ---\n"
            f"File processed: {filename}\n"
            f"Total Parent Documents in Store: {parent_docs_count}\n"
            f"Total Child Chunks in VectorStore: {child_chunks_count}\n"
            f"------------------------\n"
        )

        # --- F. Rebuild BM25 Retriever ---
        global bm25_retriever
        keys = list(store.yield_keys())
        if keys:
            all_parent_docs = store.mget(keys)
            all_parent_docs = [doc for doc in all_parent_docs if doc is not None]
            if all_parent_docs:
                bm25_retriever = BM25Retriever.from_documents(all_parent_docs, k=25)
                logger.info(f"Successfully rebuilt BM25Retriever with {len(all_parent_docs)} documents.")

        # --- G. Generate Summary & Call Backend ---
        if document_id:
            logger.info("Generating LLM summary for the document...")
            summary = generate_document_summary(docs)
            send_callback(document_id, "SUCCESS", summary)

    except Exception as e:
        logger.error(f"Error processing document {filename}: {e}")
        if document_id:
            send_callback(document_id, "FAILED")
    finally:
        # --- H. Cleanup ---
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Cleaned up temporary file: {file_path}")

# ==========================================
# 4. HYBRID SEARCH & MULTI-QUERY RETRIEVAL
# ==========================================
def retrieve_documents(query: str):
    """
    Executes the advanced retrieval phase combining Multi-Query generation
    and Hybrid Search (BM25 + Dense Parent/Child).
    """
    global bm25_retriever

    if not bm25_retriever:
        raise ValueError("No documents have been indexed yet. BM25Retriever is empty.")

    # --- A. Hybrid Search (Ensemble Retriever) ---
    # Combine the sparse (keyword) and dense (semantic) retrievers.
    # Weights: 30% importance to exact keyword match, 70% to semantic meaning.
    ensemble_retriever = EnsembleRetriever(
        retrievers=[bm25_retriever, retriever],
        weights=[0.3, 0.7]
    )

    # --- B. Multi-Query Generation ---
    # We use Google Gemini to generate multiple perspectives of the original query.
    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash-lite", temperature=0)
    
    # Initialize the MultiQueryRetriever
    mq_retriever = MultiQueryRetriever.from_llm(
        retriever=ensemble_retriever,
        llm=llm
    )

    # --- C. Cross-Encoder Re-ranking (Bottom of Funnel) ---
    # We use AITeamVN/Vietnamese_Reranker to meticulously score the top documents.
    # It will only return the top 5 most relevant documents.
    cross_encoder_model = HuggingFaceCrossEncoder(model_name="AITeamVN/Vietnamese_Reranker")
    compressor = CrossEncoderReranker(model=cross_encoder_model, top_n=5)
    
    # Wrap the MultiQueryRetriever with the CompressionRetriever
    compression_retriever = ContextualCompressionRetriever(
        base_compressor=compressor,
        base_retriever=mq_retriever
    )

    # --- D. Execution & Extraction ---
    # Extract the generated queries first for the API response.
    try:
        run_manager = CallbackManagerForRetrieverRun.get_noop_manager()
        generated_queries = mq_retriever.generate_queries(query, run_manager)
    except Exception as e:
        logger.warning(f"Failed to extract generated queries cleanly: {e}")
        generated_queries = []

    # Now, run the entire funnel!
    # Original Query -> Gemini (3 queries) -> BM25 + Dense (k=25 each) -> Deduplicate -> Cross-Encoder -> Top 5
    logger.info("Executing Full Funnel: Multi-Query -> Hybrid Search -> Cross-Encoder Re-ranking...")
    retrieved_docs = compression_retriever.invoke(query)

    # Format output for the API response
    results = []
    for d in retrieved_docs:
        results.append({
            "content": d.page_content,
            "metadata": d.metadata
        })

    return {
        "original_query": query,
        "generated_queries": generated_queries,
        "documents": results
    }

