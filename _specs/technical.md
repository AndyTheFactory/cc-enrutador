# cc-enrutador — Technical Specification

## 1. Architecture

`cc-enrutador` is a small Python HTTP proxy that exposes the Anthropic Messages API surface expected by Claude Code and dynamically routes each request to one of three configured backends.

```text
Claude Code
    |
    | Anthropic Messages API
    v
cc-enrutador
    |
    +--> task extraction
    +--> classifier
    +--> routing policy
    |
    +--> SIMPLE  --> LiteLLM --> local model
    +--> MEDIUM  --> LiteLLM --> GPT-OSS-120B / configured provider
    +--> COMPLEX --> direct Anthropic passthrough --> Claude subscription
```

The design goal is minimal custom code around classification and routing. Provider adaptation should be delegated to LiteLLM where possible.

## 2. Language and runtime

- Python 3.12+
- FastAPI for the HTTP server
- Uvicorn for local execution
- Pydantic v2 for request/config models
- HTTPX for direct upstream HTTP/SSE passthrough
- LiteLLM Python SDK for non-Anthropic providers
- PyYAML or equivalent for configuration

Package/dependency management should prefer `uv`.

## 3. API surface

### Required V1 endpoints

- `POST /v1/messages`
  - accepts Claude Code Anthropic Messages requests
  - supports streaming and non-streaming requests
  - preserves tool definitions and relevant Anthropic request fields

- `GET /health`
  - process/config health
  - no model invocation required

- `POST /debug/classify`
  - development-only classification endpoint
  - returns tier, reason, confidence, method
  - must not invoke the routed target model
  - may be disabled in production configuration

Other Claude Code endpoints should only be implemented when required by observed client traffic.

## 4. Core modules

Suggested package structure:

```text
src/cc_enrutador/
├── app.py
├── cli.py
├── doctor.py
├── config.py
├── models.py
├── task_extraction.py
├── classifier.py
├── routing.py
├── telemetry.py
├── providers/
│   ├── base.py
│   ├── litellm_provider.py
│   └── anthropic_passthrough.py
└── __init__.py
```

Tests:

```text
tests/
├── test_task_extraction.py
├── test_classifier_heuristic.py
├── test_classifier_hybrid.py
├── test_routing.py
├── test_auth_isolation.py
├── test_streaming.py
├── test_doctor.py
└── fixtures/
```

## 5. Data models

### Complexity tier

```python
class ComplexityTier(StrEnum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"
```

### Classification result

```python
class ClassificationResult(BaseModel):
    tier: ComplexityTier
    method: Literal["heuristic", "ai", "hybrid"]
    reason: str
    confidence: float
    latency_ms: float
    cached: bool = False
```

### Routing result

```python
class RouteDecision(BaseModel):
    tier: ComplexityTier
    provider: str
    model: str
    fallback_chain: list[ComplexityTier] = []
```

## 6. Task extraction

Classification must not use the complete conversation as raw semantic input.

Implement helpers equivalent in intent to the source project's routing utilities:

- `latest_user_text(request)`
- `is_injected_context(block)`
- `strip_quoted_session(text)`
- `is_agentic(request)`
- `is_mid_loop(request)`

### Injected Claude Code blocks

A text block is treated as injected context when its trimmed content structurally starts with `<system-reminder>` and ends with `</system-reminder>`.

Drop the entire block. Do not parse its contents with a non-greedy regex.

### Quoted session content

Claude Code meta-requests may include a quoted `<session>...</session>` followed by the actual instruction. The quoted session should be removed before semantic classification.

### Tool results

Tool result bodies may contribute to structural/context-size signals, but their content must not be keyword-scored as the user's current task.

## 7. Heuristic classifier

Port the evidence-gate design rather than the old additive-score design.

### Default

`medium` is the default tier.

### Simple gate

A task may route to `simple` only when all required conditions hold. Initial V1 conditions should closely follow the source implementation:

- no tools for ordinary single-turn classification
- one user-turn request / no carried conversation context
- task length <= configurable limit, default 400 characters
- no code fence in task
- system text <= configurable limit, default 400 characters
- no images
- no explicit depth markers
- positive mechanical-transform verb match

Initial transform verb family:

```text
translate, reformat, format, convert, rename, extract,
list, count, spell, capitalize/capitalise,
lowercase, uppercase, sort
```

The exact list should be configuration-overridable later; V1 may keep it in code with tests.

### Complex gate

Route to `complex` on explicit depth/long-horizon evidence.

Initial depth markers:

```text
architect
system/architecture design intent
prove
derive
critique
trade-off / tradeoffs
end-to-end
from scratch
migration plan
threat model
```

Initial long-horizon markers:

```text
refactor the whole/entire ...
rewrite the whole/entire ...
multi-step
step-by-step plan
across the codebase/repo/repository
```

Do not promote based on isolated technical topic words.

### Agentic policy

When tools exist or tool traffic is present:

1. newest user turn containing a tool result → `medium`
2. fresh instruction with complex gate → `complex`
3. otherwise → `medium`

V1 does not route agentic requests to `simple` unless explicitly enabled later.

## 8. AI classifier

The AI classifier is a secondary classifier, not the main router.

### Input

Build a compact snippet from:

- latest extracted user task
- optionally a small prefix of system instructions

Do not send full prior conversation/tool results unless later evidence shows it improves routing.

Suggested initial limits, adapted from the source project:

- task head: 700 chars
- task tail: 300 chars
- system prefix: 200 chars

### Prompt contract

The classifier should output only one of:

```text
1 = simple
2 = medium
3 = complex
```

V1 prompt should remain intentionally short and model-agnostic.

### Operational constraints

- timeout: default 1500 ms, configurable
- output budget: tiny, enough for one label/digit
- cache: in-process LRU, default 500 entries
- cache key: hash normalized full task/system + message/tool structural counts
- failure/timeout/unparseable response: fall back to heuristic result

The AI classifier may itself use LiteLLM so it can run against a small local model.

## 9. Hybrid classification

Default algorithm:

```python
heuristic = route_by_evidence(request)

if heuristic.is_explicit_gate:
    return heuristic

return ai_classify_or_heuristic_fallback(request)
```

In other words, the AI classifier is used only when the evidence gates return the default/abstain path.

## 10. Provider routing

### Simple and medium

Use LiteLLM Python SDK for `simple` and `medium` targets.

Requirements:

- pass through message/tool semantics as faithfully as supported
- support streaming
- normalize target responses back to Anthropic Messages/SSE format expected by Claude Code
- provider credentials come from environment variables or secret stores, never from incoming Claude OAuth headers

### Complex / Anthropic subscription

Use direct HTTP passthrough to Anthropic for the `complex` route unless LiteLLM can be proven to preserve the subscription OAuth flow without exposing credentials or altering required headers.

For direct passthrough:

- destination: configurable Anthropic upstream, default official Anthropic API
- preserve the inbound Claude subscription `Authorization` header
- preserve required `anthropic-beta` capability values
- preserve `anthropic-version` and content headers as appropriate
- rewrite only what is explicitly required
- support byte/stream-safe SSE forwarding

### Credential isolation

This is a hard security requirement.

Before any request is sent to LiteLLM/non-Anthropic providers:

- remove inbound `Authorization` containing Claude OAuth
- remove inbound `x-api-key` unless explicitly meant for that target
- attach only the configured provider credential

Tests must assert that a fake Claude OAuth token cannot reach a simple/medium upstream.

## 11. Request model handling

The proxy should avoid over-modeling the entire Anthropic request schema in V1.

Preferred approach:

- validate enough fields to classify and route safely
- retain the original request body for forwarding
- preserve unknown/forward-compatible fields where possible

Classification-specific parsing should inspect:

- `messages`
- `system`
- `tools`
- `stream`
- `model`

The inbound requested `model` is not authoritative for target selection in automatic routing mode.

## 12. Streaming

Streaming compatibility is mandatory for practical Claude Code use.

V1 acceptance criteria:

- Claude Code receives incremental SSE events
- tool-use events survive routing through supported providers
- client disconnect cancels/cleans up upstream work where possible
- proxy does not buffer a complete streaming response before returning it

## 13. Configuration

Example initial config:

```yaml
server:
  host: 127.0.0.1
  port: 8787

classifier:
  mode: hybrid
  model:
    provider: litellm
    model: ollama/qwen3:4b
    api_base: http://127.0.0.1:11434
    api_key_env: null
  timeout_ms: 1500
  cache_size: 500
  heuristic:
    simple_max_chars: 400
    system_max_chars: 400
    allow_simple_in_agentic: false

models:
  simple:
    provider: litellm
    model: ollama/qwen3-coder
    api_base: http://127.0.0.1:11434

  medium:
    provider: litellm
    model: openai/gpt-oss-120b
    api_base: ${MEDIUM_BASE_URL}
    api_key_env: MEDIUM_API_KEY

  complex:
    provider: anthropic_subscription
    model: passthrough
    api_base: https://api.anthropic.com

escalation:
  enabled: true
  chain:
    simple: [medium, complex]
    medium: [complex]
    complex: []

telemetry:
  enabled: true
  persist_prompts: false
  preserve_claude_default: true

debug:
  classification_endpoint: true
  capture_bodies: false
```

Exact LiteLLM model identifiers are deployment-specific and should not be hard-coded into classifier logic.

## 14. Telemetry

### 14.1 Router telemetry

V1 local router telemetry can be structured JSONL or Python logging output.

Minimum event fields:

```text
request_id
timestamp
classifier_mode
classifier_method
tier
reason
confidence
classifier_latency_ms
target
fallbacks_used
model_latency_ms
total_latency_ms
status
```

Never log authorization headers.

V1 does not persist prompt/response bodies. Reserved prompt/body capture flags must remain
disabled; enabling them fails configuration validation.

### 14.2 Preserve Claude Code default telemetry

`cc-enrutador` routing telemetry is additive. The proxy must not intentionally disable, intercept, rewrite, or replace Claude Code's own default telemetry/observability traffic.

Where Claude Code telemetry or auxiliary observability calls are sent through `ANTHROPIC_BASE_URL`, the proxy must preserve compatibility and forward them appropriately rather than treating them as normal model-routing requests. Where telemetry uses endpoints outside the router, it should remain unaffected.

Setting `telemetry.enabled: false` disables only `cc-enrutador` telemetry.

## 15. Doctor diagnostic CLI

V1 must provide `cc-enrutador doctor`.

The command validates the installation and configured routing stack without requiring the HTTP server to already be running.

Default mode must be non-destructive and avoid billable/model-generating requests where possible. It reports PASS/WARN/FAIL for configuration validation, secret references by presence only, classifier configuration, all three model routes, escalation-chain validity, endpoint syntax/reachability, LiteLLM/provider availability, Anthropic-subscription configuration, bind-port availability, telemetry destination writability, and effective timeouts.

`cc-enrutador doctor --live` may perform minimal real requests to verify the classifier, model completion, streaming, tool/function calling, and Anthropic subscription connectivity. Live probes must use tiny prompts/token budgets and identify checks that may incur provider usage.

`cc-enrutador doctor --json` provides machine-readable output.

Exit codes: `0` = required checks pass (warnings allowed); `1` = one or more required checks fail; `2` = configuration cannot be loaded or parsed.

The doctor command must never print API keys, OAuth tokens, authorization headers, or resolved secret values.

## 16. Testing strategy

Classifier behavior must be fixture-driven.

Include at least:

- clearly simple transforms
- ordinary coding requests
- explicit architecture/depth requests
- long-horizon refactors
- code-fenced tasks
- image-containing requests
- agentic initial turns
- mid-loop tool-result requests
- Claude Code injected `<system-reminder>` fixtures
- quoted `<session>` meta-request fixtures
- non-English requests
- classifier timeout/failure
- malformed classifier output
- credential-isolation tests
- streaming smoke tests

The translated classifier should preserve the intent of the source project's behavior, but Python tests become the authoritative behavior for this repository.

## 17. Licensing / provenance

The classifier/routing design is adapted from:

`serhiileniv/claude-router`

License: MIT.

Before substantial code is translated, include the upstream MIT notice in the repository (for example under `THIRD_PARTY_NOTICES.md` or `licenses/claude-router-MIT.txt`) and note adapted source files where appropriate.

## 18. V1 acceptance criteria

V1 is complete when all of the following work locally:

1. Claude Code can point to the router using `ANTHROPIC_BASE_URL`.
2. A trivial transform routes to the configured simple model.
3. An ordinary coding task routes to the configured medium model.
4. An explicit architecture/deep task routes to Claude through the user's subscription.
5. Streaming works for all supported routes.
6. Tool calls work for the configured simple/medium provider combination used in testing.
7. Claude OAuth credentials are never sent to non-Anthropic targets.
8. Hybrid classification falls back safely on classifier timeout/failure.
9. Every route decision is locally auditable by tier/reason/confidence.
10. Unit/integration tests cover classifier gates, task extraction, auth isolation, and routing.
11. `cc-enrutador doctor` validates configuration and backend setup, and `--live` can perform minimal capability probes.
12. Disabling router telemetry does not disable or replace Claude Code's own default telemetry behavior.
