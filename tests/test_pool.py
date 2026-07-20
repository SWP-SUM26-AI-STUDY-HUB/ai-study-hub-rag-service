"""Standalone test cho app/database/pool.py — health-check khi mượn connection.

Chạy:  .venv/bin/python -m tests.test_pool
Không cần DB thật: monkeypatch `pool._pool` bằng fake trả connection chết
trước, sống sau; kiểm tra db_connection() tự discard + lấy cái mới.
"""
import sys

from app.database import pool


class _FakeCursor:
    """Cursor giả: execute() raise nếu connection đang đóng."""

    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql):
        if self._conn.dead:
            raise RuntimeError("simulated dead connection (server closed)")

    def fetchone(self):
        return (1,)


class _FakeConn:
    def __init__(self, *, dead=False):
        self.dead = dead
        self.rolled_back = False
        self.closed = False

    def cursor(self):
        return _FakeCursor(self)

    def rollback(self):
        self.rolled_back = True


class _FakePool:
    """getconn() trả các connection theo thứ tự; ghi lại putconn(close=)."""

    def __init__(self, conns):
        self._conns = list(conns)
        self.put_calls = []
        self.get_count = 0

    def getconn(self):
        self.get_count += 1
        return self._conns.pop(0)

    def putconn(self, conn, close=False):
        self.put_calls.append((conn, close))
        if close:
            conn.closed = True

    def closeall(self):
        # no-op để atexit.close_pool không lỗi khi _pool là fake
        self.closed_all = True


def test_recovers_from_dead_then_live():
    dead = _FakeConn(dead=True)
    live = _FakeConn(dead=False)
    fake = _FakePool([dead, live])
    pool._pool = fake  # bypass _get_pool() — không tạo pool thật

    with pool.db_connection() as c:
        assert c is live, "phải yield connection sống sau khi vứt connection chết"

    assert fake.get_count == 2, "phải gọi getconn 2 lần (1 chết + 1 sống)"
    assert (dead, True) in fake.put_calls, "connection chết phải được putconn(close=True)"
    assert dead.closed, "connection chết phải bị close"
    assert fake.put_calls[-1] == (live, False), "connection sống trả pool bình thường"
    print("PASS: test_recovers_from_dead_then_live")


def test_live_connection_not_discarded():
    live = _FakeConn(dead=False)
    fake = _FakePool([live])
    pool._pool = fake

    with pool.db_connection() as c:
        assert c is live

    assert fake.get_count == 1, "connection sống thì không lấy thêm"
    assert fake.put_calls == [(live, False)], "trả lại đúng 1 lần, không close"
    print("PASS: test_live_connection_not_discarded")


class _ExpectRaise:
    """assertRaises mini để không phụ thuộc pytest."""

    def __init__(self, exc):
        self.exc = exc

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        assert exc_type is not None, f"kỳ vọng raise {self.exc.__name__}"
        return issubclass(exc_type, self.exc)


def test_second_dead_propagates_to_caller():
    # Cả 2 connection chết -> db_connection yield cái thứ 2 và để caller nổ
    # (DB thực sự xuống). Không retry vô hạn.
    dead1 = _FakeConn(dead=True)
    dead2 = _FakeConn(dead=True)
    fake = _FakePool([dead1, dead2])
    pool._pool = fake

    with pool.db_connection() as c:
        assert c is dead2
        with _ExpectRaise(Exception):
            # truy vấn đầu tiên trên dead2 sẽ nổ
            with c.cursor() as cur:
                cur.execute("SELECT 1")

    assert fake.get_count == 2, "thử đúng 1 lần retry, không loop"
    print("PASS: test_second_dead_propagates_to_caller")


if __name__ == "__main__":
    test_recovers_from_dead_then_live()
    test_live_connection_not_discarded()
    test_second_dead_propagates_to_caller()
    # restore module state để atexit.close_pool không đụng fake
    pool._pool = None
    print("\nAll pool tests passed.")
    sys.exit(0)
