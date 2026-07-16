import logging
from typing import List, Optional

# S4: connection pool thay vì connect/close mỗi lookup.
from app.database.pool import db_connection
from app.core.config import settings  # noqa: F401  (đảm bảo .env đã load)

logger = logging.getLogger(__name__)


def get_document_summary(document_id: str) -> str:
    """
    Fetches the summary for a given document_id using a pooled connection.
    """
    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                sql = "SELECT summary FROM documents WHERE id = %s"
                cur.execute(sql, (document_id,))
                result = cur.fetchone()

                if result and result[0]:
                    return result[0]
                else:
                    return "Summary not found for this document."
    except Exception as e:
        logger.error(f"Error fetching summary for document {document_id}: {e}")
        return f"An error occurred while retrieving the document summary: {str(e)}"


def get_user_document_ids(user_id: str) -> List[str]:
    """
    Fetches a user's COMPLETED, non-soft-deleted document IDs (pooled connection).
    Scopes the multi-doc /chat (document_id=null) path to docs that are actually
    indexed + visible — excludes PENDING/FAILED/REJECTED/DELETED so neither BM25
    nor dense retrieval can surface content the user does not expect.
    """
    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                # Cast id to text for Python string array compatibility
                sql = "SELECT id::text FROM documents WHERE uploader_id = %s AND status = 'completed' AND deleted_at IS NULL"
                cur.execute(sql, (user_id,))
                results = cur.fetchall()

                if results:
                    return [row[0] for row in results]
                else:
                    return []
    except Exception as e:
        logger.error(f"Error fetching document IDs for user {user_id}: {e}")
        return []


def get_document_title(document_id: str) -> str:
    """
    Fetches the title for a given document_id using a pooled connection.
    """
    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                sql = "SELECT title FROM documents WHERE id = %s"
                cur.execute(sql, (document_id,))
                result = cur.fetchone()

                if result and result[0]:
                    return result[0]
                else:
                    return "Unknown Title"
    except Exception as e:
        logger.error(f"Error fetching title for document {document_id}: {e}")
        return "Unknown Title"


def get_document_content(document_id: str, max_chars: int = 30000) -> Optional[str]:
    """Concatenates a document's chunk content in reading-order (chunk_index ASC).

    Quiz/flashcard generation needs broad, coherent document coverage — not the
    top-k retrieval used by /chat. Content is capped at `max_chars` to bound the
    Gemini context (matches the 20k cap convention in generate_document_summary).

    Only embedded chunks (embedding IS NOT NULL) are returned: an extracted-but-
    not-indexed public doc yields None, so the generator refuses rather than
    hallucinating on empty content. Returns None when there is no indexed content.
    """
    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                sql = """
                    SELECT content
                    FROM document_chunks
                    WHERE document_id = %s::uuid AND embedding IS NOT NULL
                    ORDER BY chunk_index ASC
                """
                cur.execute(sql, (document_id,))
                rows = cur.fetchall()
        if not rows:
            return None
        text = "\n\n".join((r[0] or "") for r in rows).strip()
        return text[:max_chars] if text else None
    except Exception as e:
        logger.error(f"Error fetching content for document {document_id}: {e}")
        return None
