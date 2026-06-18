import psycopg2
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

def get_document_summary(document_id: str) -> str:
    """
    Connects to the PostgreSQL database and fetches the summary for a given document_id.
    """
    conn = None
    try:
        conn = psycopg2.connect(settings.DATABASE_URL)
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
    finally:
        if conn:
            conn.close()

def get_user_document_ids(user_id: str) -> list[str]:
    """
    Connects to the PostgreSQL database and fetches all document IDs belonging to a given user.
    """
    conn = None
    try:
        conn = psycopg2.connect(settings.DATABASE_URL)
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
    finally:
        if conn:
            conn.close()

def get_document_title(document_id: str) -> str:
    """
    Connects to the PostgreSQL database and fetches the title for a given document_id.
    """
    conn = None
    try:
        conn = psycopg2.connect(settings.DATABASE_URL)
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
    finally:
        if conn:
            conn.close()
