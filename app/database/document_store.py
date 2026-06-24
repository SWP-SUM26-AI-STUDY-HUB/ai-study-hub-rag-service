import logging
from typing import List

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
    Fetches all document IDs belonging to a given user using a pooled connection.
    """
    try:
        with db_connection() as conn:
            with conn.cursor() as cur:
                # Cast id to text for Python string array compatibility
                sql = "SELECT id::text FROM documents WHERE uploader_id = %s"
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
