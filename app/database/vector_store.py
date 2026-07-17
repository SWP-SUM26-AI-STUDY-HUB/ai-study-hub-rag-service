import os
import json
import uuid
from typing import List, Optional, Any
from psycopg2.extras import execute_values, RealDictCursor
from langchain_core.documents import Document
from langchain_core.vectorstores import VectorStore

# S4: mượn connection từ pool thay vì connect/close mỗi lần.
from app.database.pool import db_connection
# Instrumentation: đo từng giai đoạn dense search.
from app.core.performance import stage
from app.core.langfuse_client import lf_span


class PostgresVectorStore(VectorStore):
    def __init__(self, connection_string: str, embedding_function, table_name: str = "document_chunks"):
        self.connection_string = connection_string
        self.embedding_function = embedding_function
        self.table_name = table_name

    def add_texts(
        self,
        texts: List[str],
        metadatas: Optional[List[dict]] = None,
        **kwargs: Any,
    ) -> List[str]:
        embeddings = self.embedding_function.embed_documents(texts)
        ids = [str(uuid.uuid4()) for _ in texts]

        # S4: connection mượn từ pool; db_connection tự rollback khi có lỗi.
        with db_connection() as conn:
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
        return ids
    # ----------------------------------------------------------------------
    # Two-phase extract/index support for public documents (moderation gate).
    # Extract inserts child chunks with embedding = NULL (not retrievable).
    # Index embeds those NULL rows; only embedded chunks are ever returned.
    # ----------------------------------------------------------------------

    def add_texts_without_embedding(self, documents: List["Document"]) -> int:
        """Extract phase: insert child chunks with embedding = NULL.

        Children already carry metadata[doc_id] = parent uuid (set by
        ParentDocumentRetriever._split_docs_for_adding) plus document_id and
        citation metadata, so parent-fetch retrieval keeps working once the
        chunks are later embedded by ``embed_pending_chunks``.
        """
        with db_connection() as conn:
            with conn.cursor() as cur:
                rows = []
                for i, doc in enumerate(documents):
                    metadata = doc.metadata or {}
                    doc_id = metadata.get("document_id")
                    page_number = metadata.get("page") or metadata.get("page_number")
                    if page_number is not None:
                        try:
                            page_number = int(page_number)
                        except (ValueError, TypeError):
                            page_number = None
                    chunk_index = metadata.get("chunk_index", i)
                    rows.append((
                        str(uuid.uuid4()),
                        doc_id,
                        chunk_index,
                        doc.page_content,
                        None,  # embedding: NULL until embed_pending_chunks fills it (index phase)
                        json.dumps(metadata),
                        page_number,
                    ))
                if rows:
                    execute_values(
                        cur,
                        f"""
                        INSERT INTO {self.table_name}
                            (id, document_id, chunk_index, content, embedding, metadata, page_number)
                        VALUES %s
                        """,
                        rows,
                    )
                    conn.commit()
        return len(rows)

    def embed_pending_chunks(self, document_id: str) -> int:
        """Index phase: embed child chunks whose embedding is still NULL for a document.

        Single ``embed_documents`` round-trip over all pending chunks of the
        document, then per-row UPDATE. Returns the number of chunks embedded.
        """
        with stage("embed_documents"), db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT id, content FROM {self.table_name} "
                    f"WHERE document_id = %s AND embedding IS NULL",
                    (document_id,),
                )
                pending = cur.fetchall()
                if not pending:
                    return 0
                contents = [row[1] for row in pending]
                with lf_span("embed_documents"):
                    embeddings = self.embedding_function.embed_documents(contents)
                for (chunk_id, _content), emb in zip(pending, embeddings):
                    emb_str = "[" + ",".join(map(str, emb)) + "]"
                    cur.execute(
                        f"UPDATE {self.table_name} SET embedding = %s WHERE id = %s",
                        (emb_str, chunk_id),
                    )
                conn.commit()
                return len(pending)

    def delete_by_document_id(self, document_id: str):
        """Delete every chunk of a document. Returns (chunks_deleted, parent_ids).

        ``parent_ids`` are the distinct ``metadata.doc_id`` values so the caller
        can also purge the matching parent docs from the docstore.
        """
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT DISTINCT metadata->>'doc_id' FROM {self.table_name} "
                    f"WHERE document_id = %s AND metadata->>'doc_id' IS NOT NULL",
                    (document_id,),
                )
                parent_ids = list({row[0] for row in cur.fetchall()})
                cur.execute(
                    f"DELETE FROM {self.table_name} WHERE document_id = %s",
                    (document_id,),
                )
                count = cur.rowcount
                conn.commit()
                return count, parent_ids

    def update_chunk_visibility(self, document_id: str, visibility: str) -> int:
        """Stamp a visibility flag into chunk metadata jsonb for a document.

        Forward-looking: lets retrieval filter by visibility if needed later.
        Today Java gates which document_ids reach RAG chat, so this is metadata
        only. Returns the number of chunks updated.
        """
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {self.table_name} "
                    f"SET metadata = COALESCE(metadata, '{{}}'::jsonb) "
                    f"|| jsonb_build_object('visibility', %s::text) "
                    f"WHERE document_id = %s",
                    (visibility, document_id),
                )
                updated = cur.rowcount
                conn.commit()
                return updated

    def similarity_search_by_vector(
        self,
        embedding: List[float],
        k: int = 4,
        filter: Optional[dict] = None,
        **kwargs: Any,
    ) -> List[Document]:
        docs = []
        # Instrumentation: 'dense_sql' đo truy vấn vector (bao gồm mượn conn + thực thi SQL).
        with stage("dense_sql"), db_connection() as conn:
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
                -- embedding IS NOT NULL: never surface extracted-but-not-indexed chunks
                -- (public docs awaiting moderation are extracted with NULL embeddings).
                WHERE embedding IS NOT NULL {filter_clause}
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
        return docs

    def similarity_search(
        self,
        query: str,
        k: int = 4,
        filter: Optional[dict] = None,
        **kwargs: Any,
    ) -> List[Document]:
        # Instrumentation: tách riêng bước embedding (1 round-trip Gemini / sub-query).
        with stage("embed_query"):
            embedding = self.embedding_function.embed_query(query)
        return self.similarity_search_by_vector(embedding, k=k, filter=filter, **kwargs)

    def count_chunks(self) -> int:
        with db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {self.table_name}")
                return cur.fetchone()[0]

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