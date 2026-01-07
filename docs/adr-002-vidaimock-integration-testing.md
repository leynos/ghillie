# ADR-002: Adoption of VidaiMock for LLM integration testing

## Status

Proposed (blocked on Task 2.2.b StatusModel implementation)

## Context

Ghillie's Intelligence Engine (Section 4 of the design document) relies on
Large Language Model (LLM) integration for hierarchical summarization of
repository, project, and estate-level status reports. Task 2.2.b in the roadmap
requires implementing an initial LLM integration behind a `StatusModel`
interface, with prompt templates for evidence bundles.

Testing LLM integrations presents distinct challenges:

- **Cost:** Production APIs charge per token, making integration tests
  expensive.
- **Latency:** Real API calls introduce 1–30 second delays per request, slowing
  CI pipelines.
- **Non-determinism:** Model outputs vary between calls, complicating
  assertions.
- **Availability:** External services may be rate-limited, throttled, or
  unavailable during test runs.
- **Resilience:** Testing failure modes (timeouts, malformed responses, API
  errors) requires controlled injection.

The current testing infrastructure includes:

| Layer | Mechanism | Purpose |
| ----- | --------- | ------- |
| Unit tests | `MockStatusModel` (planned) | Protocol compliance, response parsing |
| Feature tests | pytest-bdd in `tests/features/` | Behavioural verification |
| Helpers | `tests/helpers/event_builders.py` | Deterministic event construction |

Unit tests with in-process mocks verify protocol compliance but cannot exercise:

- HTTP client configuration (timeouts, retries, connection pooling)
- Streaming response handling (Server-Sent Events for per-token delivery)
- JSON schema validation against real provider response shapes
- Error recovery from provider-specific failure modes

### VidaiMock capabilities

VidaiMock[^vidaimock] is a Rust-based LLM mock server with the following
characteristics:

- **Single binary:** ~7MB executable with embedded provider configurations
- **Multi-provider support:** OpenAI, Anthropic, Gemini, Azure, Bedrock,
  Cohere, Mistral, Groq
- **Physics-accurate streaming:** Per-token timing simulation for SSE responses
- **Chaos testing:** Configurable failure injection, latency spikes, malformed
  responses
- **High throughput:** 50,000+ requests/second in benchmark mode
- **YAML configuration:** Response templates with Tera templating for dynamic
  content

## Decision

Adopt VidaiMock as the integration testing backend for Ghillie's LLM
integrations, running as a subprocess fixture during pytest execution.

### Hard dependencies

The following must be in place before implementation can proceed:

1. Task 2.2.a must define the `StatusModel` interface
2. Task 2.2.b must implement at least one LLM provider integration
3. VidaiMock binary must be available (downloaded or built from source)
4. Provider-specific YAML configurations must be created for test scenarios

### Test fixture approach

Integration tests will use a session-scoped pytest fixture that:

1. Downloads or locates the VidaiMock binary
2. Starts VidaiMock as a subprocess on an ephemeral port
3. Configures the `StatusModel` implementation to use `http://127.0.0.1:{port}`
4. Yields control to tests
5. Terminates the subprocess on fixture teardown

```python
@pytest.fixture(scope="session")
def vidaimock_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Start VidaiMock server and yield its base URL."""
    port = find_free_port()
    config_path = tmp_path_factory.mktemp("vidaimock") / "config.yaml"
    config_path.write_text(VIDAIMOCK_CONFIG)

    proc = subprocess.Popen(
        ["vidaimock", "--config", str(config_path), "--port", str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    wait_for_server(f"http://127.0.0.1:{port}/health", timeout=10)

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.wait(timeout=5)
```

### Test categories

| Category | Purpose | VidaiMock configuration |
| -------- | ------- | ----------------------- |
| Happy path | Verify correct request/response flow | Standard responses |
| Streaming | Test SSE handling and token accumulation | Streaming enabled |
| Timeout | Test client timeout handling | Latency injection >30s |
| Malformed | Test JSON parsing error recovery | Invalid JSON responses |
| Rate limit | Test retry/backoff logic | 429 responses |
| Provider errors | Test error classification | 500/503 responses |

### Chaos testing patterns

VidaiMock's chaos capabilities enable systematic resilience testing:

```yaml
# Example: intermittent failures (10% of requests)
chaos:
  failure_rate: 0.1
  failure_modes:
    - type: http_error
      status: 503
      probability: 0.5
    - type: timeout
      delay_ms: 35000
      probability: 0.3
    - type: malformed_json
      probability: 0.2
```

Tests can verify that the `StatusModel` implementation:

- Retries transient failures with exponential backoff
- Degrades gracefully when providers are unavailable
- Logs failures with sufficient context for debugging
- Respects circuit breaker thresholds (when implemented)

## Consequences

### Positive

- **Cost elimination:** Zero API costs during development and CI
- **Deterministic tests:** Reproducible responses enable precise assertions
- **Fast execution:** Local subprocess avoids network latency
- **Resilience coverage:** Chaos testing validates failure handling
- **Provider parity:** Same test suite runs against multiple provider shapes
- **CI integration:** No external dependencies or secrets required for tests

### Negative

- **Binary dependency:** VidaiMock must be downloaded or built, adding setup
  complexity
- **Configuration maintenance:** Provider response shapes may drift from
  production APIs
- **Simulation fidelity:** Mock responses cannot capture all production
  behaviours (for example, content filtering)
- **Learning curve:** Team must understand VidaiMock configuration syntax

### Neutral

- Tests complement, rather than replace, production monitoring and canary
  validation
- VidaiMock configuration files become part of the test suite and require
  versioning
- Integration tests remain separate from unit tests in the test hierarchy

## Alternatives considered

### httpx/respx mocking

The respx library provides in-process HTTP mocking for httpx clients. This
approach was rejected because:

- Mocking bypasses HTTP client configuration (timeouts, connection pooling)
- SSE streaming simulation requires significant custom code
- Provider-specific response shapes must be manually maintained in Python
- No built-in chaos testing capabilities

### Custom mock server

Implementing a bespoke mock server in Python using FastAPI or similar was
considered. This approach was rejected because:

- Development and maintenance burden falls on the Ghillie team
- Performance unlikely to match VidaiMock's Rust implementation
- Streaming and chaos capabilities would require significant engineering
- Provider parity would need to be built from scratch

### WireMock

WireMock is a mature HTTP mock server with Java origins. This approach was
rejected because:

- JVM dependency adds operational complexity
- No native LLM provider awareness or streaming support
- Chaos testing requires additional plugins
- Heavier resource footprint than VidaiMock

### Production API with test accounts

Using real provider APIs with test or low-tier accounts was considered. This
approach was rejected because:

- Costs accumulate during active development and CI runs
- Rate limits may throttle test execution
- Non-determinism complicates assertions
- External availability affects test reliability
- Failure mode testing requires provider-side configuration

## References

- Task 2.2.a: Define status model interface (`docs/roadmap.md`)
- Task 2.2.b: Implement initial LLM integration (`docs/roadmap.md`)
- Intelligence Engine design: Section 4 (`docs/ghillie-design.md`)
- Evidence Bundle Architecture: Section 9 (`docs/ghillie-design.md`)
- Existing test helpers: `tests/helpers/event_builders.py`
- Session fixture pattern: `tests/conftest.py`

[^vidaimock]: VidaiMock repository: <https://github.com/vidaiUK/VidaiMock/>
