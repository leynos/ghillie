# Configuration for model selection

This execution plan (ExecPlan) is a living document. The sections `Progress`,
`Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must
be kept up to date as work proceeds.

## Purpose / big picture

Task 2.2.c enables operators to select the status model backend and key
configuration (temperature, maximum tokens) per environment, allowing the same
reporting job to run against different model backends without code changes.

Success is observable when:

1. A `create_status_model()` factory function exists that reads
   `GHILLIE_STATUS_MODEL_BACKEND` and returns the appropriate implementation
2. The `mock` backend returns `MockStatusModel` without additional configuration
3. The `openai` backend returns `OpenAIStatusModel` with full environment
   configuration
4. Temperature and max_tokens are configurable via `GHILLIE_OPENAI_TEMPERATURE`
   and `GHILLIE_OPENAI_MAX_TOKENS`
5. Invalid configurations raise `StatusModelConfigError` with clear messages
6. Unit tests and Behaviour-Driven Development (BDD) behavioural tests validate
   all scenarios
7. Documentation in `docs/users-guide.md` covers the new configuration options

## Progress

- [x] Write unit tests for factory function (`test_factory.py`)
- [x] Write unit tests for extended config (`test_openai_config.py`)
- [x] Write BDD feature and step definitions (`model_selection.feature`)
- [x] Implement `StatusModelConfigError` in `errors.py`
- [x] Extend `OpenAIStatusModelConfig.from_env()` in `config.py`
- [x] Implement `create_status_model()` in `factory.py`
- [x] Update `__init__.py` exports
- [x] Update documentation in `docs/users-guide.md`
- [x] Mark Task 2.2.c as done in `docs/roadmap.md`
- [x] All quality gates passed (check-fmt, typecheck, lint, markdownlint, test)

## Surprises and discoveries

No major surprises. The implementation followed established patterns from the
existing OpenAI configuration and GitHub client code.

## Decision log

1. **Explicit backend selection**: Use `GHILLIE_STATUS_MODEL_BACKEND` with
   values `mock` or `openai` rather than implicit selection based on API key
   presence. Rationale: explicit selection is clearer and allows operators to
   deliberately use mock even when API keys are configured (useful for testing
   infrastructure without incurring API costs).

2. **Environment-based configuration**: Extend `from_env()` to read temperature
   and max_tokens via `GHILLIE_OPENAI_TEMPERATURE` and
   `GHILLIE_OPENAI_MAX_TOKENS`. Rationale: provides complete configurability
   without code changes, consistent with existing patterns.

3. **Factory function placement**: Create `ghillie/status/factory.py` as a
   separate module rather than adding to `config.py`. Rationale: separation of
   concerns - config handles data structures, factory handles instantiation
   logic.

4. **Validation ranges**: Temperature validated to 0.0-2.0 (OpenAI API range),
   max_tokens validated to positive integers. Rationale: fail fast on invalid
   configuration rather than propagating errors to the API.

## Outcomes and retrospective

(To be completed after quality gates pass)

## Context and orientation

### Existing structures

The StatusModel infrastructure is complete (Tasks 2.2.a and 2.2.b):

- **StatusModel Protocol** (`ghillie/status/protocol.py`): `@runtime_checkable`
  Protocol with `async summarize_repository()` method
- **MockStatusModel** (`ghillie/status/mock.py`): Deterministic heuristic-based
  implementation, no configuration required
- **OpenAIStatusModel** (`ghillie/status/openai_client.py`): OpenAI-compatible
  implementation using `OpenAIStatusModelConfig`
- **OpenAIStatusModelConfig** (`ghillie/status/config.py`): Frozen dataclass
  with `from_env()` classmethod reading `GHILLIE_OPENAI_API_KEY`,
  `GHILLIE_OPENAI_ENDPOINT`, `GHILLIE_OPENAI_MODEL`

### Key patterns followed

1. **Configuration dataclass**: Use `dataclasses.dataclass(frozen=True,
   slots=True)` with `from_env()` classmethod
2. **Custom exceptions**: Use classmethod factory constructors (e.g.,
   `cls.missing_backend()`, `cls.invalid_temperature()`)
3. **Environment variables**: Follow `GHILLIE_*` naming convention
4. **Test-Driven Development (TDD) workflow**: Write tests BEFORE implementation
   per AGENTS.md
5. **Documentation**: Update users' guide for new functionality

## Plan of work

### Phase 1: Write failing tests first (AGENTS.md requirement)

Created unit tests and BDD scenarios before implementation:

- Unit tests in `tests/unit/status/test_factory.py` covering factory function
- Extended tests in `tests/unit/status/test_openai_config.py` for temperature
  and max_tokens
- BDD feature in `tests/features/model_selection.feature` with scenarios for
  backend selection and configuration

### Phase 2: Implement error handling

Added `StatusModelConfigError` to `ghillie/status/errors.py` with factory
classmethods:

- `missing_backend()` - when `GHILLIE_STATUS_MODEL_BACKEND` is not set
- `invalid_backend(name)` - when an unrecognized backend name is provided
- `invalid_temperature(value)` - when temperature cannot be parsed or is out of
  range (0.0-2.0)
- `invalid_max_tokens(value)` - when max_tokens cannot be parsed or is
  non-positive

### Phase 3: Extend configuration

Extended `OpenAIStatusModelConfig.from_env()` to read:

- `GHILLIE_OPENAI_TEMPERATURE` (optional, float, default: 0.3)
- `GHILLIE_OPENAI_MAX_TOKENS` (optional, int, default: 2048)

### Phase 4: Implement factory function

Created `ghillie/status/factory.py` with `create_status_model()`:

1. Read `GHILLIE_STATUS_MODEL_BACKEND` from environment
2. Return `MockStatusModel` for `mock` backend
3. Return `OpenAIStatusModel` (with config from env) for `openai` backend
4. Raise `StatusModelConfigError` for missing or invalid backend names
5. Handle case-insensitive matching and whitespace trimming

### Phase 5: Update exports and documentation

- Updated `ghillie/status/__init__.py` with new exports
- Updated `docs/users-guide.md` with configuration documentation
- Marked Task 2.2.c as done in `docs/roadmap.md`

## Validation and acceptance

The change is accepted when:

1. `create_status_model()` returns `MockStatusModel` when
   `GHILLIE_STATUS_MODEL_BACKEND=mock`
2. `create_status_model()` returns `OpenAIStatusModel` when
   `GHILLIE_STATUS_MODEL_BACKEND=openai` with valid API key
3. `GHILLIE_OPENAI_TEMPERATURE` configures temperature (0.0-2.0 range)
4. `GHILLIE_OPENAI_MAX_TOKENS` configures max_tokens (positive integer)
5. Invalid configurations raise `StatusModelConfigError` with actionable
   messages
6. Unit tests cover all factory and configuration scenarios
7. BDD scenarios cover backend selection and configuration
8. Documentation in users' guide is complete and accurate
9. All quality gates pass

## Artefacts and notes

### Environment variables summary

| Variable                       | Required | Default                                      | Description                    |
| ------------------------------ | -------- | -------------------------------------------- | ------------------------------ |
| `GHILLIE_STATUS_MODEL_BACKEND` | Yes      | -                                            | `mock` or `openai`             |
| `GHILLIE_OPENAI_API_KEY`       | OpenAI   | -                                            | API key for authentication     |
| `GHILLIE_OPENAI_ENDPOINT`      | No       | `https://api.openai.com/v1/chat/completions` | Chat completions endpoint URL  |
| `GHILLIE_OPENAI_MODEL`         | No       | `gpt-5.1-thinking`                           | Model identifier               |
| `GHILLIE_OPENAI_TEMPERATURE`   | No       | `0.3`                                        | Sampling temperature (0.0-2.0) |
| `GHILLIE_OPENAI_MAX_TOKENS`    | No       | `2048`                                       | Maximum tokens in response     |

### Error message patterns

- Missing backend: "GHILLIE_STATUS_MODEL_BACKEND environment variable is
  required"
- Invalid backend: "Invalid status model backend 'X'. Valid options are: 'mock',
  'openai'"
- Invalid temperature: "Invalid temperature 'X'. Must be a float between 0.0 and
  2.0"
- Invalid max_tokens: "Invalid max_tokens 'X'. Must be a positive integer"

## Critical files

| File                                                 | Action | Purpose                                      |
| ---------------------------------------------------- | ------ | -------------------------------------------- |
| `ghillie/status/factory.py`                          | Create | Factory function for model selection         |
| `ghillie/status/errors.py`                           | Modify | Add StatusModelConfigError                   |
| `ghillie/status/config.py`                           | Modify | Extend from_env() for temperature/max_tokens |
| `ghillie/status/__init__.py`                         | Modify | Add new exports                              |
| `tests/unit/status/test_factory.py`                  | Create | Factory unit tests                           |
| `tests/unit/status/test_openai_config.py`            | Modify | Extended config tests                        |
| `tests/features/model_selection.feature`             | Create | BDD scenarios                                |
| `tests/features/steps/test_model_selection_steps.py` | Create | BDD step definitions                         |
| `docs/users-guide.md`                                | Modify | Configuration documentation                  |
| `docs/roadmap.md`                                    | Modify | Mark Task 2.2.c done                         |
