"""Helpers for capturing femtologging output in tests."""

from __future__ import annotations

import contextlib
import dataclasses
import os
import sys
import threading
import time
import typing as typ

from femtologging import get_logger

_ORIGINAL_PID = os.getpid()


@dataclasses.dataclass(slots=True)
class FemtoLogRecord:
    """Captured femtologging record for test assertions."""

    logger: str
    level: str
    message: str
    exc_info: object | None = None
    stack_info: object | None = None


class FemtoLogCapture:
    """Capture femtologging records via a Python handler."""

    def __init__(self) -> None:
        """Initialise storage and synchronization primitives."""
        self.records: list[FemtoLogRecord] = []
        self._condition = threading.Condition()

    def handle(self, logger: str, level: str, message: str) -> None:
        """Handle a log record from the femtologging worker thread."""
        self._append_record(
            FemtoLogRecord(
                logger=str(logger),
                level=str(level),
                message=message,
            )
        )

    def handle_record(self, record: dict[str, object]) -> None:
        """Handle structured record payloads from femtologging."""
        self._append_record(
            FemtoLogRecord(
                logger=str(record.get("logger", "")),
                level=str(record.get("level", "")),
                message=str(record.get("message", "")),
                exc_info=record.get("exc_info"),
                stack_info=record.get("stack_info"),
            )
        )

    def _append_record(self, record: FemtoLogRecord) -> None:
        """Store a record and notify any waiting assertions."""
        with self._condition:
            self.records.append(record)
            self._condition.notify_all()

    def wait_for_count(self, count: int, timeout: float = 1.0) -> None:
        """Wait until at least ``count`` records are captured."""
        deadline = time.monotonic() + timeout
        with self._condition:
            while len(self.records) < count:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)

        assert len(self.records) >= count, (
            f"Expected {count} records, got {len(self.records)}"
        )

    def wait_for_timeout(self, timeout: float = 0.1) -> None:
        """Wait for the specified duration to allow records to flush."""
        deadline = time.monotonic() + timeout
        with self._condition:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(timeout=remaining)


class _SyncLogger:
    """Synchronous logger used in forked test processes."""

    def __init__(self, name: str, handler: FemtoLogCapture) -> None:
        self._name = name
        self._handler = handler

    def log(
        self,
        level: object,
        message: str,
        /,
        *,
        exc_info: object | None = None,
        stack_info: bool = False,
    ) -> str:
        """Capture the log record immediately for forked test runs."""
        level_name = str(level).upper()
        if level_name == "WARNING":
            level_name = "WARN"
        self._handler.handle_record(
            {
                "logger": self._name,
                "level": level_name,
                "message": message,
                "exc_info": exc_info,
                "stack_info": stack_info,
            }
        )
        return message

    def set_level(self, level: object) -> None:
        """No-op for compatibility with femtologging API."""
        del level

    def set_propagate(self, *, flag: bool) -> None:
        """No-op for compatibility with femtologging API."""
        del flag

    def add_handler(self, handler: object) -> None:
        """No-op for compatibility with femtologging API."""
        del handler

    def remove_handler(self, handler: object) -> bool:
        """No-op for compatibility with femtologging API."""
        del handler
        return True


class _LoggerModule(typ.Protocol):
    """Protocol for modules that expose a ``logger`` attribute."""

    logger: object


@contextlib.contextmanager
def capture_femto_logs(
    logger_name: str,
    *,
    level: str = "TRACE",
) -> typ.Iterator[FemtoLogCapture]:
    """Capture logs for the named femtologging logger."""
    logger = get_logger(logger_name)
    previous_level = logger.level
    previous_propagate = logger.propagate

    logger.set_level(level)
    logger.set_propagate(False)

    handler = FemtoLogCapture()
    logger.add_handler(handler)
    module_logger: object | None = None
    module: object | None = None
    if os.getpid() != _ORIGINAL_PID:
        # Forked test processes inherit a dead worker thread; use sync capture.
        module = sys.modules.get(logger_name)
        if module is not None and hasattr(module, "logger"):
            logger_module = typ.cast("_LoggerModule", module)
            module_logger = logger_module.logger
            logger_module.logger = _SyncLogger(logger_name, handler)
    try:
        yield handler
    finally:
        if module is not None and module_logger is not None:
            logger_module = typ.cast("_LoggerModule", module)
            logger_module.logger = module_logger
        logger.remove_handler(handler)
        logger.set_level(previous_level)
        logger.set_propagate(previous_propagate)
