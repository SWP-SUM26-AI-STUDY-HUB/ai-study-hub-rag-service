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
# TCP keepalives + một connect-timeout để connection idle bị postgres restart
# (hoặc mạng đứt) phát hiện sớm thay vì bị phát ra stale. Tunable qua env;
# health-check trong db_connection() mới là đảm bảo đúng đắn thực sự.
_POOL_KWARGS = {
    "connect_timeout": int(os.environ.get("DB_CONNECT_TIMEOUT", "10")),
    "keepalives": 1,
    "keepalives_idle": int(os.environ.get("DB_KEEPALIVES_IDLE", "30")),
    "keepalives_interval": int(os.environ.get("DB_KEEPALIVES_INTERVAL", "10")),
    "keepalives_count": int(os.environ.get("DB_KEEPALIVES_COUNT", "3")),
}

_pool = None


def _get_pool() -> "pg_pool.ThreadedConnectionPool":
    global _pool
    if _pool is None:
        _pool = pg_pool.ThreadedConnectionPool(
            minconn=_DEFAULT_MIN,
            maxconn=_DEFAULT_MAX,
            dsn=settings.DATABASE_URL,
            **_POOL_KWARGS,
        )
        logger.info(
            "Created PostgreSQL connection pool (minconn=%d, maxconn=%d, keepalives=on)",
            _DEFAULT_MIN,
            _DEFAULT_MAX,
        )
    return _pool


def _is_alive(conn) -> bool:
    """Probe rẻ: connection còn dùng được không (`SELECT 1`).

    Bắt connection đã chết (postgres restart, mạng đứt) ngay lúc mượn thay vì
    để truy vấn đầu tiên của caller vỡ nát. Trả True nếu còn sống.
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        return True
    except Exception:  # noqa: BLE001
        return False


@contextmanager
def db_connection() -> Iterator:
    """Mượn một connection từ pool, trả lại pool khi thoát.

    Connection KHÔNG bị close (đó mới là mục đích pool). Rollback ở finally để
    đảm bảo connection trả về pool ở trạng thái sạch (kể cả khi chỉ đọc, tránh
    để lại transaction ngầm); là no-op nếu caller đã commit.
    """
    conn = _get_pool().getconn()
    # Health-check khi mượn (test-on-borrow): nếu connection trong pool đã chết
    # (vd postgres restart lúc nó đang idle), vứt bỏ (close=True) và lấy cái
    # mới. Thử lại đúng 1 lần — nếu DB thực sự xuống, để caller nhận lỗi rõ.
    if not _is_alive(conn):
        logger.warning("Discarded dead pooled connection; acquiring a fresh one")
        _get_pool().putconn(conn, close=True)
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
