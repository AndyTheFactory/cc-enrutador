# cc-enrutador — Configuration Specification

## 1. Purpose

All model selection and routing policy must be configurable without changing Python code.

V1 must allow configuration of:

- classifier model
- level 1 model (`simple`)
- level 2 model (`medium`)
- level 3 model (`complex`)
- escalation policy
- classification prompt
- timeouts

Configuration is YAML. Secrets are referenced through environment variables and must not be stored directly in the file.

## 2. Terminology

The classifier emits three generic levels:

- `level1` = `simple`
- `level2` = `medium`
- `level3` = `complex`

The implementation should expose the semantic names (`simple`, `medium`, `complex`) internally, while allowing aliases `level1`, `level2`, and `level3` in user-facing documentation where useful.

Model identifiers belong only to configuration.

## 3. Recommended V1 configuration

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

  prompt: |
    Classify the task complexity.

    Return ONLY one digit:
    1 = simple, short, mechanical, self-contained
    2 = normal coding/reasoning task
    3 = architecture, broad, ambiguous, or long-horizon task

    Task:
    {task}

  output:
    simple: "1"
    medium: "2"
    complex: "3"

  timeout_ms: 1500
  max_output_tokens: 4
  temperature: 0
  cache_size: 500

  extraction:
    task_head_chars: 700
    task_tail_chars: 300
    system_prefix_chars: 200

  heuristic:
    simple_max_chars: 400
    system_max_chars: 400
    allow_simple_in_agentic: false

models:
  simple:
    provider: litellm
    model: ollama/qwen3-coder
    api_base: http://127.0.0.1:11434
    api_key_env: null

  medium:
    provider: litellm
    model: openai/gpt-oss-120b
    api_base: ${GPT_OSS_BASE_URL}
    api_key_env: GPT_OSS_API_KEY

  complex:
    provider: anthropic_subscription
    model: passthrough
    api_base: https://api.anthropic.com

escalation:
  enabled: true

  provider_failure:
    simple_to_medium: true
    medium_to_complex: true

  semantic:
    enabled: false
    max_attempts_per_level: 1

  never_demote_within_task: true

  chain:
    simple: [medium, complex]
    medium: [complex]
    complex: []

timeouts:
  classifier_ms: 1500
  connect_ms: 5000
  request_ms:
    simple: 120000
    medium: 300000
    complex: 600000
  stream_idle_ms:
    simple: 60000
    medium: 120000
    complex: 120000

telemetry:
  enabled: true
  persist_prompts: false
  preserve_claude_default: true

doctor:
  live_probes: false
  probe_timeout_ms: 10000
  check_streaming: true
  check_tool_calls: true

debug:
  classification_endpoint: true
  capture_bodies: false
```

## 4. Classifier model

`classifier.model` defines the model used only when AI classification is required.

Required fields:

```yaml
classifier:
  model:
    provider: litellm
    model: ollama/qwen3:4b
```

Optional fields:

```yaml
    api_base: http://127.0.0.1:11434
    api_key_env: CLASSIFIER_API_KEY
```

The classifier model is independent from all three execution models. It may point to the same backend/model as `simple`, but this must not be assumed by the implementation.

In `heuristic` mode the classifier model is not invoked.

## 5. Execution models

The three execution levels are configured independently.

Each route must define:

- provider type
- model identifier or passthrough behavior
- optional endpoint
- optional environment-variable name containing credentials

Example:

```yaml
models:
  simple:
    provider: litellm
    model: ollama/qwen3-coder

  medium:
    provider: litellm
    model: openai/gpt-oss-120b

  complex:
    provider: anthropic_subscription
    model: passthrough
```

The classifier must never contain hard-coded model names.

## 6. Classification prompt

The AI classification prompt must be configurable as a template.

V1 requires at least the following placeholder:

```text
{task}
```

Optional future placeholders may include:

```text
{system}
{is_agentic}
{is_mid_loop}
{message_count}
{tool_count}
```

V1 should keep the template contract deliberately small. Unsupported placeholders must fail validation at startup rather than silently producing a broken prompt.

The prompt should normally ask for exactly one label/digit to minimize latency and parsing ambiguity.

Prompt parsing must be configurable through the `classifier.output` mapping rather than assuming digits internally.

For example this is also valid:

```yaml
classifier:
  prompt: |
    Return only SIMPLE, MEDIUM, or COMPLEX.
    Task: {task}

  output:
    simple: SIMPLE
    medium: MEDIUM
    complex: COMPLEX
```

## 7. Escalation policy

Escalation is separate from initial classification.

### 7.1 Provider-failure escalation

V1 must support escalation when a selected backend cannot successfully process the request because of provider/transport failure.

Examples:

- connection failure
- timeout
- provider unavailable
- retryable 5xx error

Default chain:

```text
simple -> medium -> complex
medium -> complex
complex -> no fallback
```

This chain must be configurable.

### 7.2 Semantic escalation

Semantic escalation means escalating because the selected model appears unable to solve the task, rather than because the provider is unavailable.

Potential signals include:

- repeated unsuccessful tool loops
- repeated test failure
- repeated edits to the same files
- explicit model uncertainty
- task retry after a failed answer

V1 configuration must reserve the policy shape, but semantic escalation may remain disabled until we have reliable signals from real Claude Code traffic.

### 7.3 No automatic demotion

Within an ongoing task, automatic escalation may increase the minimum level. The router should not automatically demote the same task again until a fresh user task is detected when `never_demote_within_task: true`.

This setting depends on session/task tracking and may initially be inactive if V1 does not yet implement task stickiness.

## 8. Timeouts

Timeouts must be configurable by purpose rather than represented by one global timeout.

### Classifier timeout

```yaml
timeouts:
  classifier_ms: 1500
```

A classifier timeout must never fail the user request. Classification falls back to heuristics.

### Connection timeout

```yaml
  connect_ms: 5000
```

Applies when opening upstream connections.

### Request timeout by execution level

```yaml
  request_ms:
    simple: 120000
    medium: 300000
    complex: 600000
```

These limits may be disabled or adjusted for providers whose streaming behavior makes total request time unsuitable as a hard cutoff.

### Streaming idle timeout

```yaml
  stream_idle_ms:
    simple: 60000
    medium: 120000
    complex: 120000
```

This protects against dead streams without imposing an unnecessarily short total duration on valid long-running coding tasks.

## 9. Environment variable interpolation

Configuration values may reference environment variables using:

```text
${NAME}
```

Secrets should normally be referenced indirectly with `api_key_env`:

```yaml
api_key_env: GPT_OSS_API_KEY
```

The application must resolve secrets at runtime and must not emit their values in logs, diagnostics, exceptions, or debug endpoints.

## 10. Validation

Configuration is validated at process startup with Pydantic.

Startup must fail clearly for invalid configuration such as:

- missing execution level
- unsupported provider type
- undefined prompt placeholder
- malformed output mapping
- invalid escalation target
- escalation cycle
- non-positive timeout
- missing required endpoint for a provider
- referenced credential environment variable missing when required

The `complex` Anthropic-subscription route must not require an API-key environment variable.

## 11. Configuration precedence

V1 precedence should be simple:

1. built-in defaults
2. YAML configuration
3. environment variables for secrets and explicitly supported scalar overrides
4. CLI arguments for server/runtime overrides only

Do not implement a broad arbitrary environment-to-YAML override system in V1.

## 12. Reload behavior

V1 may require a process restart after configuration changes.

Hot reload of routing/model configuration is not required.

## 13. Doctor configuration

The diagnostic CLI reads the same configuration as the server. Optional doctor settings:

```yaml
doctor:
  live_probes: false
  probe_timeout_ms: 10000
  check_streaming: true
  check_tool_calls: true
```

CLI flags override these diagnostic defaults for the current invocation, for example `cc-enrutador doctor --live`.

Doctor diagnostics must validate secrets only by presence/readability and must never print resolved values.

## 14. Telemetry compatibility

`telemetry.enabled` controls only router-owned telemetry.

`telemetry.preserve_claude_default` defaults to `true` and documents the invariant that Claude Code's own default telemetry/observability remains unaffected or transparently forwarded when it traverses the proxy. V1 should not expose a supported configuration that intentionally disables Claude Code telemetry.

## 15. Acceptance criteria

Configuration support is complete when:

1. classifier model can be changed without code changes;
2. each of the three execution models can be changed independently;
3. classification prompt can be replaced from YAML;
4. classifier output labels can be remapped;
5. provider-failure escalation chains can be changed from YAML;
6. semantic escalation can be enabled/disabled independently;
7. classifier/connect/request/stream-idle timeouts are independently configurable;
8. invalid configurations fail at startup with actionable errors;
9. secrets are sourced from environment variables and never printed;
10. no classifier code contains provider/model names;
11. doctor settings are configurable and `--live` can override the live-probe default;
12. disabling router telemetry does not disable Claude Code's default telemetry.
