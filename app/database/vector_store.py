import os
import json
import uuid
from typing import List, Optional, Any
import psycopg2
from psycopg2.extras import execute_values, RealDictCursor
from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStore

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
                            filter_clause = "AND document_id = ANY(%s::uuid[])"
                            params.append(doc_ids)
                    elif "document_id" in filter:
                        doc_id = filter["document_id"]
                        if doc_id:
                            filter_clause = "AND document_id = %s::uuid"
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
