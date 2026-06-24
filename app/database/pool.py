"""Connection pool PostgreSQL toàn process (S4).

Thay cho `psycopg2.connect()`/`close()` trên mỗi truy vấn (cộng thêm 20-50ms
handshake+auth mỗi lần và không keep-alive). Dùng `ThreadedConnectionPool` vì
FastAPI chạy các sync `def` handler trong threadpool (S3) -> truy cập DB từ
nhiều worker thread.
"""
import atexit
import logging
import os
from contextlib import contextmanager
from typing import Iterator

from psycopg2 import pool as pg_pool

from app.core.config import settings

logger = logging.getLogger(__name__)

_DEFAULT_MIN = 1
_DEFAULT_MAX = int(os.environ.get("DB_POOL_MAX", "20"))

_pool = None


def _get_pool() -> "pg_pool.ThreadedConnectionPool":
    global _pool
    if _pool is None:
        _pool = pg_pool.ThreadedConnectionPool(
            minconn=_DEFAULT_MIN,
            maxconn=_DEFAULT_MAX,
            dsn=settings.DATABASE_URL,
        )
        logger.info(
            "Created PostgreSQL connection pool (minconn=%d, maxconn=%d)",
            _DEFAULT_MIN,
            _DEFAULT_MAX,
        )
    return _pool


@contextmanager
def db_connection() -> Iterator:
    """Mượn một connection từ pool, trả lại pool khi thoát.

    Connection KHÔNG bị close (đó mới là mục đích pool). Rollback ở finally để
    đảm bảo connection trả về pool ở trạng thái sạch (kể cả khi chỉ đọc, tránh
    để lại transaction ngầm); là no-op nếu caller đã commit.
    """
    conn = _get_pool().getconn()
    try:
        yield conn
    finally:
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001
            pass
        _get_pool().putconn(conn)


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None
        logger.info("Closed PostgreSQL connection pool")


atexit.register(close_pool)
