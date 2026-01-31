# ADR-001: Adoption of femtologging library

## Status

Accepted (implementation in progress; 2026-01-31)

## Context

Ghillie historically used Python's standard library `logging` module for
application logging. The pre-migration logging footprint was minimal and
concentrated around ingestion observability and runtime startup:

- Logging calls live in a handful of modules (ingestion, observability,
  runtime, and test fixtures).
- All follow the `logger = logging.getLogger(__name__)` pattern.
- Runtime logging is configured in the ASGI entry point.
- Ruff LOG rules already enforced via `pyproject.toml`.

The observability work planned in Task 1.3.d requires structured logging for
ingestion health metrics. This ADR evaluates femtologging as a replacement for
stdlib logging.

### Pre-migration logging usage

| File                              | Call(s)                     | Purpose                                                |
| --------------------------------- | --------------------------- | ------------------------------------------------------ |
| `ghillie/silver/services.py`      | `logger.warning()`          | Log failed raw event transforms                        |
| `ghillie/github/ingestion.py`     | `logger.warning()`          | Log DB connectivity issues during noise filter loading |
| `ghillie/github/ingestion.py`     | `logger.exception()`        | Log SQLAlchemy errors with traceback                   |
| `ghillie/github/observability.py` | `logger.info/warning/error` | Emit ingestion observability events                    |
| `ghillie/runtime.py`              | `logger.info/warning/error` | Log runtime startup and config validation              |
| `tests/conftest.py`               | `logger.warning()`          | Log py-pglite fallback to SQLite                       |

### Femtologging features

Femtologging[^femtologging] is a lightweight alternative to stdlib logging with
the following characteristics:

- Async-friendly with bounded queues (1024 capacity) and worker threads
- Uses `get_logger(name)` instead of `getLogger(name)`
- Primary method is `logger.log(level, message)`
- Handlers: `FemtoStreamHandler`, `FemtoFileHandler`,
  `FemtoRotatingFileHandler`, `FemtoSocketHandler`
- Configuration via `basicConfig`, `ConfigBuilder`, or `dictConfig`/`fileConfig`

### Exception support update

Femtologging now supports `exc_info` and `stack_info` on `logger.log()` in the
snapshot commit used for dogfooding. The `logger.exception()` convenience
method is still not implemented, but equivalent behaviour is achieved by
calling `logger.log("ERROR", message, exc_info=exc)`. Structured `extra` fields
remain unsupported.

## Decision

Adopt femtologging as Ghillie's logging library using the snapshot commit
`7c139fb7aca18f9277e00b88604b8bf5eb471be0` while the library is pre-release.

### Hard dependencies

The following must be in place before migration can proceed:

1. Femtologging provides `exc_info`/`stack_info` support on `logger.log()`
2. The application can depend on the snapshot commit until a release lands

### Migration approach

1. Add femtologging to project dependencies in `pyproject.toml` using the
   snapshot commit.
2. Introduce `ghillie/logging.py` to centralise `get_logger`, log formatting,
   and `exc_info` usage.
3. Update `ghillie/silver/services.py`, `ghillie/github/ingestion.py`,
   `ghillie/github/observability.py`, `ghillie/runtime.py`, and
   `tests/conftest.py`:
   - Replace stdlib logging imports with `ghillie.logging`.
   - Replace `logger.warning/info/error(...)` calls with `logger.log(...)` and
     preformatted messages.
   - Pass `exc_info` for exception logging.
4. Update tests and BDD steps to capture femtologging output instead of
   stdlib `caplog`.
5. Configure femtologging at application entry points (runtime server, worker,
   and CLI) using `configure_logging`.
6. Update `.rules/python-exception-design-raising-handling-and-logging.md` to
   reference femtologging patterns.

## Consequences

### Positive

- Async-native logging aligned with Ghillie's async architecture
- Bounded queues prevent logging from blocking ingestion workers
- Thread-based handlers improve throughput for high-volume logging
- Foundation for structured logging in observability work (Task 1.3.d)

### Negative

- New dependency to maintain and version (pinned to a snapshot commit)
- Team must learn femtologging API differences
- Ruff LOG rules may need adjustment (femtologging uses different patterns)

### Neutral

- Minimal migration effort due to small logging footprint (four calls)
- No breaking changes to external interfaces

## Alternatives considered

### Remain on stdlib logging

Stdlib logging is mature and well-understood. However, its synchronous design
may become a bottleneck as observability requirements grow. The lack of bounded
queues means logging I/O can block async workers during high-throughput
ingestion.

### structlog

Structlog provides structured logging with processor pipelines, offering richer
features than femtologging. Rejected due to additional complexity for current
needs; the minimal logging footprint does not justify the learning curve.

### loguru

Loguru offers a simpler API than stdlib logging with automatic exception
formatting. However, femtologging's async-native design with bounded queues and
worker threads is better aligned with Ghillie's architecture.

## References

- Task 1.3.d: Add observability for ingestion health (`docs/roadmap.md`)
- Task 1.3.e: Migrate to femtologging library (`docs/roadmap.md`)
- Current logging guidelines:
  `.rules/python-exception-design-raising-handling-and-logging.md`
- Femtologging user guide: `docs/femtologging-users-guide.md`

[^femtologging]: Femtologging repository:
    <https://github.com/leynos/femtologging/>
