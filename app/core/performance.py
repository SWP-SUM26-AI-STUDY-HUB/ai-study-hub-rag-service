"""Đo hiệu năng theo từng request (instrumentation).

Mỗi request tạo một `PerformanceTrace` lưu trong ContextVar để bất kỳ hàm nào
trong call graph (router, retrieval, generation, vector store) đều có thể ghi
một stage có tên mà không phải đổi signature. Trace được:
  - ghi thành 1 dòng JSON vào `logs/performance.log` (phục vụ phân tích trên VPS), và
  - trích xuất qua `trace.as_dict()` để nhúng vào debug response của API.

Cùng một tên stage ghi nhiều lần sẽ cộng dồn (vd. 1 `embed_query`/sub-query),
báo cáo cả tổng thời gian lẫn số lần gọi. Tắt bằng `ENABLE_PERF_LOG=0`.
"""
import json
import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Dict, Optional

_ENABLED = os.environ.get("ENABLE_PERF_LOG", "1").lower() not in (
    "0",
    "false",
    "no",
    "",
)

_LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "logs",
)
try:
    os.makedirs(_LOG_DIR, exist_ok=True)
except OSError:
    _LOG_DIR = os.path.join(os.getcwd(), "logs")
    os.makedirs(_LOG_DIR, exist_ok=True)

_perf_logger = logging.getLogger("rag.performance")
_perf_logger.setLevel(logging.INFO)
if not _perf_logger.handlers:
    _handler = RotatingFileHandler(
        os.path.join(_LOG_DIR, "performance.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=10,
        encoding="utf-8",
    )
    _handler.setFormatter(
        logging.Formatter("%(asctime)s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    _perf_logger.addHandler(_handler)
# Đồng thời in ra console (qua root logger) khi dev.
_perf_logger.propagate = True


_current_trace: ContextVar = ContextVar("rag_performance_trace", default=None)


class PerformanceTrace:
    """Tập hợp timing các stage của một request."""

    def __init__(self, label: str, **meta) -> None:
        self.label = label
        self.meta = dict(meta)
        self._times: Dict[str, float] = {}
        self._counts: Dict[str, int] = {}
        self._start = time.perf_counter()

    @contextmanager
    def stage(self, name: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self._times[name] = self._times.get(name, 0.0) + (
                time.perf_counter() - t0
            )
            self._counts[name] = self._counts.get(name, 0) + 1

    def as_dict(self) -> Dict[str, Dict[str, float]]:
        """stage -> {'calls': n, 'ms': x} theo thứ tự thực thi."""
        return {
            name: {
                "calls": self._counts.get(name, 0),
                "ms": round(self._times.get(name, 0.0) * 1000, 1),
            }
            for name in self._times
        }

    def total_ms(self) -> float:
        return round((time.perf_counter() - self._start) * 1000, 1)

    def emit(self, **extra) -> Dict:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "label": self.label,
            **self.meta,
            **extra,
            "stages": self.as_dict(),
            "total_ms": self.total_ms(),
        }
        if _ENABLED:
            _perf_logger.info(json.dumps(payload, ensure_ascii=False))
        return payload


def start_trace(label: str, **meta) -> PerformanceTrace:
    trace = PerformanceTrace(label, **meta)
    _current_trace.set(trace)
    return trace


@contextmanager
def stage(name: str):
    """Ghi block hiện tại vào stage `name` của trace đang active.

    No-op (không có trace) khi gọi ngoài request, vd. test đơn lẻ.
    """
    trace = _current_trace.get()
    if trace is None:
        yield
        return
    with trace.stage(name):
        yield
