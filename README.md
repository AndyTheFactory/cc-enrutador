# cc-enrutador

Task-aware model routing proxy for Claude Code.

cc-enrutador keeps Claude Code as the user-facing agent while routing each inference request
to one of three configurable complexity tiers:

- `simple` — inexpensive/local model
- `medium` — stronger general coding/reasoning model
- `complex` — direct Anthropic subscription passthrough by default

The router is model-agnostic. Model names in `config.example.yaml` are reference examples,
not mandatory defaults.

## Status

Current package version: **1.0.0rc1**.

M0-M3 implementation is complete. M4 adds release hardening, Linux/Windows release gates,
security and compatibility regression tests, release documentation, and explicit external
Claude Code sign-off steps.

The final `1.0.0` tag should not be created until the real Claude Code checks in
`docs/v1-validation-results.md` are completed.

## Architecture

```text
Claude Code
    |
    | Anthropic-compatible traffic
    v
cc-enrutador
    |
    +--> task extraction
    +--> heuristic / AI / hybrid classifier
    +--> task-tier floor + routing policy
    |
    +--> simple  --> LiteLLM --> configured target
    +--> medium  --> LiteLLM --> configured target
    +--> complex --> direct Anthropic passthrough
```

Provider failures may escalate according to the configured chain:

```text
simple -> medium -> complex
medium -> complex
complex -> stop
```

Within one active task, the router does not automatically demote below the highest tier
already required when `never_demote_within_task: true`.

## Requirements

- Python 3.12+
- `uv`
- Claude Code for real end-to-end use
- configured LiteLLM-compatible simple/medium providers
- a normal Claude Code subscription login for the complex subscription route

Linux and Windows are release-gated in CI.

## Quick start

From a clean checkout:

```bash
uv sync
cp config.example.yaml config.yaml
```

The reference configuration uses environment interpolation for the simple and medium model
names and base URLs. Set those four required variables before loading the config. Provider
API keys are optional and are read indirectly from `SIMPLE_API_KEY` and
`MEDIUM_API_KEY` only when those endpoints require authentication.

Bash / zsh:

```bash
export SIMPLE_MODEL=ollama/qwen3-coder
export SIMPLE_BASE_URL=http://127.0.0.1:8000/v1

export MEDIUM_MODEL=openai/gpt-oss-120b
export MEDIUM_BASE_URL=http://127.0.0.1:8000/v1

# Only if the endpoints require authentication:
# export SIMPLE_API_KEY=...
# export MEDIUM_API_KEY=...
```

PowerShell:

```powershell
$env:SIMPLE_MODEL = "ollama/qwen3-coder"
$env:SIMPLE_BASE_URL = "http://127.0.0.1:8000/v1"

$env:MEDIUM_MODEL = "openai/gpt-oss-120b"
$env:MEDIUM_BASE_URL = "http://127.0.0.1:8000/v1"

# Only if the endpoints require authentication:
# $env:SIMPLE_API_KEY = "..."
# $env:MEDIUM_API_KEY = "..."
```

If an endpoint requires authentication, set the environment variable named by
`api_key_env`. The reference config already points to `SIMPLE_API_KEY` and
`MEDIUM_API_KEY`; no key variable is required for an unauthenticated endpoint.

`.env.example` documents the same variables, but cc-enrutador does **not** automatically
load `.env` files. Export the variables in your shell, use your shell's env-file mechanism,
or replace the `${...}` references in `config.yaml` with fixed non-secret values.

Validate configuration:

```bash
uv run cc-enrutador doctor --config config.yaml
```

Start the router:

```bash
uv run cc-enrutador serve --config config.yaml
```

Then point Claude Code at the router using its normal `ANTHROPIC_BASE_URL` configuration.
Authenticate to Claude Code normally. Do **not** place the Claude subscription OAuth token
in `config.yaml`.

## Configuration

See:

- `config.example.yaml`
- `.env.example`
- `_specs/configuration.md`

The main configurable surfaces are:

- classifier mode/model/prompt/output labels
- simple, medium, and complex execution targets
- provider-failure escalation
- classifier/connect/request/stream-idle timeouts
- router telemetry
- doctor behavior
- debug classification endpoint

Secrets are referenced by environment-variable name. Resolved secret values are not stored
in YAML.

## Classifier modes

`heuristic`
: Evidence gates only.

`ai`
: Configured classifier model only, with heuristic fallback on failure.

`hybrid`
: Default. Explicit heuristic gates win; the AI classifier runs only on the default/abstain
path.

Every classification returns a tier, method, reason, confidence, latency, and cache status.

## HTTP API

Required V1 endpoints:

- `POST /v1/messages` — Anthropic-compatible routed inference
- `GET /health` — no-provider process health
- `POST /debug/classify` — classify without executing a target model; disable-able

Other Claude Code auxiliary traffic is forwarded directly to the configured Anthropic
upstream rather than being treated as normal model-routing traffic.

## Streaming and tools

The router supports:

- incremental SSE delivery
- direct Anthropic SSE passthrough
- LiteLLM-to-Anthropic streaming normalization
- Anthropic tool definitions to provider function/tool calls
- provider tool calls back to Anthropic `tool_use`
- subsequent `tool_result` turns
- upstream stream cleanup on disconnect where possible

Provider/tool support still depends on the configured simple/medium backend.

## Doctor

Safe diagnostics:

```bash
uv run cc-enrutador doctor --config config.yaml
```

Machine-readable output:

```bash
uv run cc-enrutador doctor --config config.yaml --json
```

Minimal real provider probes:

```bash
uv run cc-enrutador doctor --config config.yaml --live
```

Default doctor mode does not intentionally invoke models.

`--live` may incur provider usage. The Anthropic subscription probe is skipped with a WARN
unless a subscription authorization token is explicitly made available to the doctor CLI.

Exit codes:

- `0` — required checks pass; warnings allowed
- `1` — one or more required checks fail
- `2` — configuration cannot load or parse

Doctor never prints resolved API keys or OAuth token values.

## Telemetry

Router telemetry is local routing metadata and is separate from Claude Code telemetry.

It records fields such as task/request ID, tier, reason, confidence, target, classifier
latency, total latency, status, and fallback path.

It does not persist prompts, responses, tool-result bodies, or authorization headers.

V1 deliberately rejects `telemetry.persist_prompts: true` and
`debug.capture_bodies: true`; sensitive compatibility capture is an external, sanitized
validation workflow rather than an in-router feature.

Setting:

```yaml
telemetry:
  enabled: false
```

disables only cc-enrutador telemetry. Auxiliary Claude Code traffic remains transparently
forwarded.

## Security model

The critical boundary is credential isolation:

- inbound Claude `Authorization` is allowed only on Anthropic-bound traffic;
- inbound Anthropic `x-api-key` and Anthropic protocol headers are stripped before
  non-Anthropic execution;
- simple/medium routes use only their configured provider credentials;
- doctor/logging/telemetry must never print resolved secret values.

See `SECURITY.md`.

## Development and release checks

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv build
```

CI runs these checks on Linux and Windows and also smoke-tests the CLI.

## Troubleshooting

### Configuration fails because an environment variable is missing

The reference YAML requires `SIMPLE_MODEL`, `SIMPLE_BASE_URL`, `MEDIUM_MODEL`, and
`MEDIUM_BASE_URL`. Export those variables before loading the configuration, or replace
the corresponding `${...}` references in `config.yaml`. `SIMPLE_API_KEY` and
`MEDIUM_API_KEY` are only needed when the respective provider requires authentication.

### Doctor warns about a missing provider API key

A referenced `api_key_env` is optional at runtime. If that endpoint is intentionally
unauthenticated, the warning is expected. Otherwise set the environment variable before
starting the router.

### Classifier provider is unavailable

AI/hybrid classification falls back to the heuristic result. The user request should still
route.

### Simple or medium provider is down

If provider-failure escalation is enabled, execution follows the configured fallback chain.
Once a streaming provider has already emitted output, the router does not switch providers
mid-response.

### Complex route fails authentication

Normal Claude Code use relies on inbound subscription authorization. Do not add an
Anthropic API key to the complex route merely to work around a subscription passthrough
problem. Run the real compatibility steps in `docs/v1-validation.md` and inspect sanitized
headers/telemetry.

### Windows path/environment issues

Use PowerShell environment syntax and pass `--config` explicitly when debugging path
resolution. Windows clean install, tests, build, typing, and CLI smoke are release-gated in
GitHub Actions.

## Release validation

See:

- `docs/v1-validation.md`
- `docs/v1-validation-results.md`
- `docs/v1-acceptance-evidence.md`
- `RELEASE_CHECKLIST.md`

Real Claude Code subscription/tool/long-stream behavior cannot be proven by offline CI and
must be recorded before final V1 tagging.

## Provenance

The classifier design is adapted from
[`serhiileniv/claude-router`](https://github.com/serhiileniv/claude-router), MIT licensed.

See `THIRD_PARTY_NOTICES.md` and `licenses/claude-router-MIT.txt`.
