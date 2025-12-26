# ADR-001: Adoption of femtologging library

## Status

Proposed (blocked on femtologging `exc_info` support)

## Context

Ghillie currently uses Python's standard library `logging` module for
application logging. The current logging footprint is minimal:

- Four logging calls across three files
- All follow the `logger = logging.getLogger(__name__)` pattern
- No centralised logging configuration, handlers, or formatters
- Ruff LOG rules already enforced via `pyproject.toml`

The observability work planned in Task 1.3.d requires structured logging for
ingestion health metrics. This ADR evaluates femtologging as a replacement for
stdlib logging.

### Current logging usage

| File                          | Line      | Call                 | Purpose                                                |
| ----------------------------- | --------- | -------------------- | ------------------------------------------------------ |
| `ghillie/silver/services.py`  | 139–144   | `logger.warning()`   | Log failed raw event transforms                        |
| `ghillie/github/ingestion.py` | 422–429   | `logger.warning()`   | Log DB connectivity issues during noise filter loading |
| `ghillie/github/ingestion.py` | 432–438   | `logger.exception()` | Log SQLAlchemy errors with traceback                   |
| `tests/conftest.py`           | 99        | `logger.warning()`   | Log py-pglite fallback to SQLite                       |

### Femtologging features

Femtologging[^femtologging] is a lightweight alternative to stdlib logging with
the following characteristics:

- Async-friendly with bounded queues (1024 capacity) and worker threads
- Uses `get_logger(name)` instead of `getLogger(name)`
- Primary method is `logger.log(level, message)`
- Handlers: `FemtoStreamHandler`, `FemtoFileHandler`,
  `FemtoRotatingFileHandler`, `FemtoSocketHandler`
- Configuration via `basicConfig`, `ConfigBuilder`, or `dictConfig`/`fileConfig`

### Critical limitation

Femtologging does not currently support:

- `exc_info` parameter on log methods
- `stack_info` parameter on log methods
- `extra` parameter for structured record fields
- `logger.exception()` convenience method

This is a **hard dependency** for Ghillie: the ingestion service uses
`logger.exception()` to capture SQLAlchemy error tracebacks at
`ghillie/github/ingestion.py:432–438`. The femtologging developers have been
notified and are actively working on this feature as a priority.

## Decision

Adopt femtologging as Ghillie's logging library once the `exc_info`/exception
support is implemented. Until then, the migration is blocked.

### Hard dependencies

The following must be in place before migration can proceed:

1. Femtologging must implement `exc_info` support on `logger.log()`
2. Femtologging must implement `logger.exception()` or equivalent
3. A PyPI release must be published containing these features

### Migration approach (when unblocked)

1. Add femtologging to project dependencies in `pyproject.toml`
2. Update `ghillie/silver/services.py`:
   - Replace `import logging` with `from femtologging import get_logger`
   - Replace `logging.getLogger(__name__)` with `get_logger(__name__)`
   - Replace `logger.warning(…)` with `logger.log("WARNING", …)`
3. Update `ghillie/github/ingestion.py`:
   - Same import changes
   - Replace `logger.warning(…, exc_info=exc)` with femtologging equivalent
   - Replace `logger.exception(…)` with femtologging equivalent
4. Update `tests/conftest.py`:
   - Same import and method changes
5. Configure femtologging at application entry points (worker main, CLI)
6. Update `.rules/python-exception-design-raising-handling-and-logging.md` to
   reference femtologging patterns

## Consequences

### Positive

- Async-native logging aligned with Ghillie's async architecture
- Bounded queues prevent logging from blocking ingestion workers
- Thread-based handlers improve throughput for high-volume logging
- Foundation for structured logging in observability work (Task 1.3.d)

### Negative

- Migration blocked until femtologging implements exception support
- New dependency to maintain and version
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

[^femtologging]: Femtologging user guide:
    <https://github.com/leynos/femtologging/>
