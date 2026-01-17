# Implement initial Large Language Model (LLM) integration

This execution plan (ExecPlan) is a living document. The sections `Progress`,
`Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must
be kept up to date as work proceeds.

## Purpose / big picture

Task 2.2.b implements the first real LLM integration in Ghillie, connecting the
`StatusModel` protocol to an OpenAI-compatible API (GPT-5.1-thinking). This
integration enables repository evidence bundles to be transformed into
narrative and structured status reports using an actual language model, moving
beyond the deterministic heuristics of `MockStatusModel`.

Success is observable when:

1. An `OpenAIStatusModel` implementation exists that implements the
   `StatusModel` protocol
2. Round-trip inference is demonstrated using VidaiMock integration tests
3. Prompt templates transform evidence bundles into model-consumable context
4. Response parsing extracts both narrative and structured JSON output
5. Error handling covers API failures, timeouts, and malformed responses

The design aligns with ADR-002 (VidaiMock for LLM integration testing) and
extends Section 9.5 of `docs/ghillie-design.md`.

## Progress

- [x] Create unit tests for OpenAI client configuration and response parsing
- [x] Create BDD scenarios for LLM integration with VidaiMock
- [x] Implement `OpenAIStatusModelConfig` dataclass
- [x] Implement custom exception classes for LLM errors
- [x] Implement prompt templates (system and user)
- [x] Implement `OpenAIStatusModel` class
- [x] Implement VidaiMock pytest fixture
- [x] Create VidaiMock YAML configuration files
- [x] Write integration tests using VidaiMock
- [x] Update `ghillie/status/__init__.py` with new exports
- [x] Update documentation in `ghillie-design.md` (Section 9.5)
- [x] Update ADR-002 status from Proposed to Accepted
- [x] Mark Task 2.2.b as done in `roadmap.md`
- [ ] All quality gates passed (check-fmt, typecheck, lint, markdownlint, test,
  nixie)

## Surprises and discoveries

No major surprises. The VidaiMock fixture configuration required alignment with
ADR-002's updated format (nested `endpoints` within `providers` list).

## Decision log

1. Used `httpx.AsyncClient` for HTTP client (consistent with GitHub client
   pattern)
2. Config uses `from_env()` classmethod pattern (consistent with project
   conventions)
3. Prompt uses JSON mode with explicit schema in system prompt (reliable
   structured output)
4. Error classes use factory classmethods for consistency with existing
   patterns.

## Outcomes and retrospective

To be completed after quality gates pass.

## Context and orientation

### Existing structures

The StatusModel infrastructure is complete (Task 2.2.a):

- **StatusModel Protocol** (`ghillie/status/protocol.py`): `@runtime_checkable`
  Protocol with `async summarize_repository()` method
- **MockStatusModel** (`ghillie/status/mock.py`): Reference implementation with
  heuristic-based logic
- **RepositoryStatusResult** (`ghillie/status/models.py`): msgspec.Struct with
  summary, status, highlights, risks, next_steps
- **RepositoryEvidenceBundle** (`ghillie/evidence/models.py`): Complete evidence
  structure with commits, PRs, issues, docs, work type groupings.

The HTTP client pattern is established:

- **GitHubGraphQLConfig** (`ghillie/github/client.py`): Frozen dataclass with
  `from_env()` classmethod, `endpoint`, `token`, `timeout_s`, `user_agent`
- **GitHubGraphQLClient** (`ghillie/github/client.py`): Owns httpx.AsyncClient,
  has `aclose()` cleanup, supports injected `http_client` for testing
- **Custom Exceptions** (`ghillie/github/errors.py`): `GitHubAPIError`,
  `GitHubResponseShapeError`, `GitHubConfigError` with classmethod constructors

### Key patterns to follow

1. **Configuration dataclass**: Use `dataclasses.dataclass(frozen=True,
   slots=True)` with `from_env()` classmethod
2. **HTTP client ownership**: Support injected `http_client` for testing, own
   client if none provided
3. **Async cleanup**: Implement `aclose()` method for resource cleanup
4. **Custom exceptions**: Use classmethod factory constructors (for example,
   `cls.http_error()`, `cls.missing()`)
5. **msgspec for data**: Use msgspec.Struct for response parsing
6. **Environment variables**: Follow `GHILLIE_*` naming convention.

### Files to reference

- `ghillie/github/client.py` - HTTP client and config pattern
- `ghillie/github/errors.py` - Custom exception pattern
- `ghillie/status/protocol.py` - StatusModel Protocol
- `ghillie/status/mock.py` - Reference StatusModel implementation
- `ghillie/status/models.py` - RepositoryStatusResult struct
- `docs/adr-002-vidaimock-integration-testing.md` - VidaiMock fixture design
- `docs/ghillie-design.md` (Section 10) - LLM testing strategy
- `tests/unit/status/conftest.py` - Evidence bundle fixtures

## Plan of work

### Phase 1: Write failing tests first (AGENTS.md requirement)

Create unit tests and Behaviour-Driven Development (BDD) scenarios before
implementation:

- Unit tests in `tests/unit/status/` covering config validation, prompt
  building, response parsing, and error handling
- BDD feature in `tests/features/llm_integration.feature` with scenarios for
  happy path, timeout handling, and error recovery

### Phase 2: Define configuration and errors

Create configuration dataclass and error classes following the GitHub client
pattern.

**`ghillie/status/config.py`:**

- `OpenAIStatusModelConfig` frozen dataclass with `api_key`, `endpoint`,
  `model`, `timeout_s`, `temperature`, `max_tokens`
- `from_env()` classmethod reading `GHILLIE_OPENAI_*` environment variables

**`ghillie/status/errors.py`:**

- `OpenAIAPIError` for HTTP and API errors (with `http_error()`,
  `rate_limited()`, `timeout()` classmethods)
- `OpenAIResponseShapeError` for response parsing errors (with `missing()`,
  `invalid_json()` classmethods)
- `OpenAIConfigError` for configuration validation errors

### Phase 3: Create prompt templates

**`ghillie/status/prompts.py`:**

Define prompt templates that transform evidence bundles into model-consumable
context:

- `SYSTEM_PROMPT`: Instructions for JSON output format, status determination
  guidelines, and rules to avoid repetition
- `build_user_prompt(evidence: RepositoryEvidenceBundle) -> str`: Serializes
  evidence bundle into structured text with sections for previous reports,
  activity summary, work type breakdown, PRs, and issues

### Phase 4: Implement OpenAIStatusModel

**`ghillie/status/openai_client.py`:**

- `LLMStatusResponse` msgspec.Struct for parsing JSON responses
- `OpenAIStatusModel` class implementing `StatusModel` protocol:
  - Constructor accepts config and optional `http_client` for testing
  - `aclose()` method for resource cleanup
  - `summarize_repository()` async method orchestrating the full flow
  - Private helpers: `_call_chat_completion()`, `_extract_content()`,
    `_parse_response()`, `_build_result()`

### Phase 5: Implement VidaiMock fixture and integration tests

**`tests/integration/conftest.py`:**

- Session-scoped `vidaimock_server` fixture that:
  - Binds to ephemeral port to avoid conflicts
  - Writes YAML configuration to temp directory
  - Starts VidaiMock subprocess
  - Polls health endpoint until ready
  - Yields base URL
  - Terminates subprocess on teardown

**VidaiMock configuration:**

Uses the `providers` list structure per ADR-002:

```yaml
providers:
  - name: openai
    base_url: /v1
    endpoints:
      - path: /chat/completions
        method: POST
        response:
          status: 200
          body:
            id: "chatcmpl-mock"
            object: "chat.completion"
            created: 1700000000
            model: "gpt-5.1-thinking"
            choices:
              - index: 0
                message:
                  role: "assistant"
                  content: '{"status": "on_track", ...}'
                finish_reason: "stop"
            usage:
              prompt_tokens: 500
              completion_tokens: 100
              total_tokens: 600
```

**`tests/integration/test_openai_vidaimock.py`:**

- Integration tests verifying round-trip inference with VidaiMock

### Phase 6: Update documentation and roadmap

- Add Section 9.5 to `docs/ghillie-design.md` documenting the OpenAI integration
- Update ADR-002 status from "Proposed" to "Accepted"
- Mark Task 2.2.b as done in `docs/roadmap.md`

## Concrete steps

1. Create `tests/unit/status/test_openai_config.py` with failing tests:
   - `test_config_from_env_requires_api_key`
   - `test_config_from_env_uses_defaults`
   - `test_config_from_env_reads_custom_values`
   - `test_config_rejects_empty_api_key`

2. Create `tests/unit/status/test_openai_prompts.py` with failing tests:
   - `test_system_prompt_contains_json_schema`
   - `test_user_prompt_includes_repository_slug`
   - `test_user_prompt_includes_previous_reports`
   - `test_user_prompt_includes_activity_summary`
   - `test_user_prompt_includes_work_type_breakdown`

3. Create `tests/unit/status/test_openai_parsing.py` with failing tests:
   - `test_parse_valid_json_response`
   - `test_parse_response_with_all_fields`
   - `test_parse_response_with_minimal_fields`
   - `test_parse_invalid_json_raises_error`
   - `test_parse_missing_status_raises_error`
   - `test_status_enum_parsing_normalizes_values`
   - `test_unknown_status_falls_back_to_unknown`

4. Create `tests/unit/status/test_openai_errors.py` with failing tests:
   - `test_api_error_http_error_factory`
   - `test_api_error_rate_limited_factory`
   - `test_api_error_timeout_factory`
   - `test_response_shape_error_missing_factory`
   - `test_response_shape_error_invalid_json_factory`
   - `test_config_error_missing_api_key_factory`

5. Create `tests/features/llm_integration.feature` with scenarios:
   - Scenario: Generate status using OpenAI model
   - Scenario: Handle API timeout gracefully
   - Scenario: Handle malformed response gracefully

6. Create `ghillie/status/errors.py`:

   ```python
   class OpenAIAPIError(RuntimeError):
       @classmethod
       def http_error(cls, status_code: int) -> OpenAIAPIError: ...
       @classmethod
       def rate_limited(cls, retry_after: int | None = None) -> OpenAIAPIError: ...
       @classmethod
       def timeout(cls) -> OpenAIAPIError: ...

   class OpenAIResponseShapeError(RuntimeError):
       @classmethod
       def missing(cls, field: str) -> OpenAIResponseShapeError: ...
       @classmethod
       def invalid_json(cls, content: str) -> OpenAIResponseShapeError: ...

   class OpenAIConfigError(RuntimeError):
       @classmethod
       def missing_api_key(cls) -> OpenAIConfigError: ...
       @classmethod
       def empty_api_key(cls) -> OpenAIConfigError: ...
   ```

7. Create `ghillie/status/config.py`:

   ```python
   @dataclasses.dataclass(frozen=True, slots=True)
   class OpenAIStatusModelConfig:
       api_key: str
       endpoint: str = "https://api.openai.com/v1/chat/completions"
       model: str = "gpt-5.1-thinking"
       timeout_s: float = 120.0
       temperature: float = 0.3
       max_tokens: int = 2048

       @classmethod
       def from_env(cls) -> OpenAIStatusModelConfig: ...
   ```

8. Create `ghillie/status/prompts.py`:

   ```python
   SYSTEM_PROMPT: str = """..."""

   def build_user_prompt(evidence: RepositoryEvidenceBundle) -> str: ...
   ```

9. Create `ghillie/status/openai_client.py`:

   ```python
   class LLMStatusResponse(msgspec.Struct, kw_only=True):
       status: str
       summary: str
       highlights: list[str] = []
       risks: list[str] = []
       next_steps: list[str] = []

   class OpenAIStatusModel:
       def __init__(
           self,
           config: OpenAIStatusModelConfig,
           *,
           http_client: httpx.AsyncClient | None = None,
       ) -> None: ...

       async def aclose(self) -> None: ...

       async def summarize_repository(
           self,
           evidence: RepositoryEvidenceBundle,
       ) -> RepositoryStatusResult: ...
   ```

10. Update `ghillie/status/__init__.py` with new exports:
    - `OpenAIStatusModel`, `OpenAIStatusModelConfig`
    - `OpenAIAPIError`, `OpenAIResponseShapeError`, `OpenAIConfigError`

11. Create `tests/integration/conftest.py` with VidaiMock fixture:

    ```python
    @pytest.fixture(scope="session")
    def vidaimock_server(tmp_path_factory) -> Iterator[str]:
        port = _bind_ephemeral_port()
        # ... start subprocess, wait for health, yield URL, cleanup
    ```

12. Create `tests/integration/test_openai_vidaimock.py`:
    - `test_round_trip_inference_with_vidaimock`
    - `test_openai_client_uses_configured_endpoint`
    - `test_openai_client_sends_correct_headers`

13. Create `tests/features/steps/test_llm_integration_steps.py` with step
    definitions.

14. Update `docs/ghillie-design.md` Section 9.5 with OpenAI integration design.

15. Update `docs/adr-002-vidaimock-integration-testing.md`:
    - Change status from "Proposed" to "Accepted"
    - Add implementation notes

16. Mark Task 2.2.b as done in `docs/roadmap.md`.

17. Run quality gates:

    ```bash
    set -o pipefail; make check-fmt 2>&1 | tee /tmp/ghillie-check-fmt.log
    set -o pipefail; make typecheck 2>&1 | tee /tmp/ghillie-typecheck.log
    set -o pipefail; make lint 2>&1 | tee /tmp/ghillie-lint.log
    set -o pipefail; make test 2>&1 | tee /tmp/ghillie-test.log
    set -o pipefail; make markdownlint 2>&1 | tee /tmp/ghillie-mdlint.log
    set -o pipefail; make nixie 2>&1 | tee /tmp/ghillie-nixie.log
    ```

## Validation and acceptance

The change is accepted when:

1. `OpenAIStatusModel` implements `StatusModel` protocol (verified by isinstance
   check)
2. Configuration supports environment variables `GHILLIE_OPENAI_API_KEY`,
   `GHILLIE_OPENAI_ENDPOINT`, `GHILLIE_OPENAI_MODEL`
3. Prompt templates correctly serialize evidence bundles with previous reports,
   activity summary, and work type breakdown
4. Response parsing handles valid JSON, extracts all fields, and gracefully
   handles malformed responses
5. Custom exceptions provide clear error context with classmethod factories
6. VidaiMock fixture starts/stops cleanly as session-scoped fixture
7. Integration tests demonstrate round-trip inference
8. Unit tests cover config, prompts, parsing, and errors
9. BDD scenarios cover happy path and error handling
10. All quality gates pass: `make check-fmt`, `make typecheck`, `make lint`,
    `make test`, `make markdownlint`, `make nixie`

Expected test output:

```text
$ pytest tests/unit/status/test_openai*.py -v
~20 passed

$ pytest tests/integration/test_openai_vidaimock.py -v
~5 passed

$ pytest tests/features -k llm_integration
~3 passed
```

## Idempotence and recovery

All steps are safe to rerun:

- File creation is additive
- Tests can be run incrementally
- VidaiMock fixture cleans up on teardown
- Quality gates are read-only validations

If tests fail:

1. Check VidaiMock binary availability (`which vidaimock`)
2. Check port conflicts for ephemeral port allocation
3. Verify YAML configuration syntax
4. Review fixture scope (session vs function)
5. Check httpx timeout configuration matches VidaiMock latency

## Artefacts and notes

**Key design decisions:**

1. **Model identifier**: Use `"gpt-5.1-thinking"` as specified in requirements
2. **JSON mode**: Request `response_format: {"type": "json_object"}` for
   structured output
3. **Temperature**: Use 0.3 for consistency (lower than typical for reliability)
4. **Timeout**: 120s to accommodate thinking models
5. **Max tokens**: 2048 to allow detailed summaries

**Prompt design principles:**

1. Explicit JSON schema in system prompt with field descriptions
2. Previous report context for continuity (status, highlights, risks)
3. Work type breakdown for status inference
4. Clear instructions to avoid repetition of unchanged information
5. Activity summary with counts before detailed listings

**Error handling strategy:**

1. Classify HTTP errors by status code (429 rate limit, 5xx server, 4xx client)
2. Separate timeout from other request errors for clarity
3. Validate response shape before JSON parsing
4. Fall back to `UNKNOWN` status for unparseable values
5. Truncate long content in error messages for readability

## Interfaces and dependencies

**New public API:**

- `ghillie.status.OpenAIStatusModel` - OpenAI implementation
- `ghillie.status.OpenAIStatusModelConfig` - Configuration dataclass
- `ghillie.status.OpenAIAPIError` - API error exception
- `ghillie.status.OpenAIResponseShapeError` - Response parsing error
- `ghillie.status.OpenAIConfigError` - Configuration error

**Environment variables:**

- `GHILLIE_OPENAI_API_KEY` - Required API key
- `GHILLIE_OPENAI_ENDPOINT` - Optional endpoint override (default: OpenAI)
- `GHILLIE_OPENAI_MODEL` - Optional model override (default: gpt-5.1-thinking)

**External dependencies:**

- VidaiMock binary for integration testing (pre-installed in environment)
- httpx (already in dependencies)
- msgspec (already in dependencies)

**Downstream consumers (Phase 2.3):**

- Reporting scheduler will instantiate `OpenAIStatusModel` or `MockStatusModel`
  based on configuration
- Report storage unchanged (uses `to_machine_summary()`)

## Critical files

| File                                                 | Action | Purpose                           |
| ---------------------------------------------------- | ------ | --------------------------------- |
| `ghillie/status/errors.py`                           | Create | Custom exception classes          |
| `ghillie/status/config.py`                           | Create | OpenAIStatusModelConfig dataclass |
| `ghillie/status/prompts.py`                          | Create | System and user prompt templates  |
| `ghillie/status/openai_client.py`                    | Create | OpenAIStatusModel implementation  |
| `ghillie/status/__init__.py`                         | Modify | Add new exports                   |
| `tests/unit/status/test_openai_config.py`            | Create | Config unit tests                 |
| `tests/unit/status/test_openai_prompts.py`           | Create | Prompt unit tests                 |
| `tests/unit/status/test_openai_parsing.py`           | Create | Parsing unit tests                |
| `tests/unit/status/test_openai_errors.py`            | Create | Error unit tests                  |
| `tests/integration/conftest.py`                      | Create | VidaiMock pytest fixture          |
| `tests/integration/test_openai_vidaimock.py`         | Create | Integration tests                 |
| `tests/features/llm_integration.feature`             | Create | BDD scenarios                     |
| `tests/features/steps/test_llm_integration_steps.py` | Create | BDD steps                         |
| `docs/ghillie-design.md`                             | Modify | Add Section 9.5                   |
| `docs/adr-002-vidaimock-integration-testing.md`      | Modify | Update status                     |
| `docs/roadmap.md`                                    | Modify | Mark Task 2.2.b done              |
