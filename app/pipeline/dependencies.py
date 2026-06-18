import json
import logging
from typing import Optional

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain.storage import LocalFileStore
from langchain.storage.encoder_backed import EncoderBackedStore
from langchain.retrievers import ParentDocumentRetriever
from langchain_community.retrievers import BM25Retriever

from app.core.config import settings
from app.database.vector_store import PostgresVectorStore

logger = logging.getLogger(__name__)

# --- Embeddings & Vector Store ---
class CustomGoogleEmbeddings(GoogleGenerativeAIEmbeddings):
    def embed_documents(self, texts, **kwargs):
        kwargs["output_dimensionality"] = 1536
        return super().embed_documents(texts, **kwargs)
        
    def embed_query(self, text, **kwargs):
        kwargs["output_dimensionality"] = 1536
        return super().embed_query(text, **kwargs)

embeddings = CustomGoogleEmbeddings(model="models/gemini-embedding-001")
vectorstore = PostgresVectorStore(
    connection_string=settings.DATABASE_URL,
    embedding_function=embeddings
)

# --- Persistent LocalFileStore ---
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

# --- Splitters ---
parent_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
child_splitter = RecursiveCharacterTextSplitter(chunk_size=200, chunk_overlap=50)

# --- Parent Document Retriever ---
retriever = ParentDocumentRetriever(
    vectorstore=vectorstore,
    docstore=store,
    child_splitter=child_splitter,
    parent_splitter=parent_splitter,
    search_kwargs={"k": 25}
)

# --- BM25 Retriever State ---
# We store BM25 globally so it can be re-used across requests
class PipelineState:
    bm25_retriever: Optional[BM25Retriever] = None

state = PipelineState()

def initialize_bm25():
    try:
        keys = list(store.yield_keys())
        if keys:
            all_parent_docs = store.mget(keys)
            all_parent_docs = [doc for doc in all_parent_docs if doc is not None]
            if all_parent_docs:
                state.bm25_retriever = BM25Retriever.from_documents(all_parent_docs, k=25)
                logger.info(f"Startup: Successfully rebuilt BM25Retriever with {len(all_parent_docs)} documents from persistent store.")
            else:
                logger.info("Startup: No valid documents found in persistent store. BM25Retriever remains empty.")
        else:
            logger.info("Startup: No documents found in persistent store. BM25Retriever remains empty.")
    except Exception as e:
        logger.error(f"Startup: Failed to rebuild BM25Retriever: {e}")

def update_bm25():
    """Rebuilds the BM25 retriever after new documents are ingested."""
    keys = list(store.yield_keys())
    if keys:
        all_parent_docs = store.mget(keys)
        all_parent_docs = [doc for doc in all_parent_docs if doc is not None]
        if all_parent_docs:
            state.bm25_retriever = BM25Retriever.from_documents(all_parent_docs, k=25)
            logger.info(f"Successfully rebuilt BM25Retriever with {len(all_parent_docs)} documents.")
