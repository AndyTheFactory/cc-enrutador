# cc-enrutador — Implementation Plan

## Goal

Deliver a small, reliable Claude Code routing proxy that classifies each task as `simple`, `medium`, or `complex`, routes it to configurable backends, preserves Claude subscription OAuth for the complex path, and provides auditable routing, diagnostics, and safe escalation.

Implementation should optimize for simplicity and observability rather than framework depth.

## Delivery principles

- one focused concern per PR where practical
- tests accompany each behavior change
- classification and provider routing remain separate
- no model names hard-coded into classifier logic
- Claude OAuth must never reach non-Anthropic providers
- real Claude Code traffic is the source of truth for compatibility
- LiteLLM is used for provider normalization, not for task classification policy
- direct Anthropic passthrough remains the V1 subscription path
- router telemetry is additive to Claude Code telemetry

## Milestones

### M0 — Project foundation and compatibility capture

Establish the Python project and capture enough real Claude Code traffic to validate the protocol assumptions before building the proxy deeply.

Deliverables:

- Python 3.12 + `uv` project
- package/CLI skeleton
- lint/type/test tooling
- configuration loader skeleton
- third-party MIT attribution for `serhiileniv/claude-router`
- minimal recording/echo proxy for controlled Claude Code traffic capture
- documented observed headers, request shapes, streaming events, tool events, meta-calls, telemetry/auxiliary traffic
- sanitized fixtures derived from captured traffic

Exit criteria:

- `uv run pytest` works
- `uv run cc-enrutador --help` works
- at least one authenticated Claude Code session has been observed through the recorder
- captured observations are reflected back into specs where needed

### M1 — Configuration, task extraction, and classification

Implement the model-agnostic routing brain before provider execution.

Deliverables:

- complete Pydantic configuration model
- YAML + environment interpolation
- validation of classifier, model routes, timeouts, escalation chains, secrets-by-reference
- Anthropic request inspection models/helpers
- actual-task extraction
- injected-context removal
- quoted-session stripping
- agentic and mid-loop detection
- heuristic evidence gates ported/adapted from `serhiileniv/claude-router`
- AI classifier through LiteLLM
- classifier prompt/output mapping
- hybrid mode
- LRU classification cache
- `POST /debug/classify`
- fixture-driven classifier test suite

Exit criteria:

- simple / medium / complex fixtures produce expected decisions
- classifier timeout/error safely falls back to heuristics
- classifier model and prompt can be changed only through configuration
- no provider execution is required to test heuristic classification

### M2 — Provider execution and Anthropic-compatible proxy

Turn routing decisions into working Claude Code responses.

Deliverables:

- FastAPI `POST /v1/messages`
- request preservation / forward-compatible field handling
- LiteLLM provider adapter for simple and medium routes
- direct Anthropic subscription passthrough for complex
- strict credential isolation
- non-streaming response normalization
- streaming/SSE forwarding
- tool-call/tool-result compatibility
- client disconnect handling
- `GET /health`

Exit criteria:

- Claude Code can use `ANTHROPIC_BASE_URL` pointing to cc-enrutador
- each configured tier can complete a real request
- complex requests use the logged-in Claude subscription
- fake Claude OAuth tokens are provably absent from simple/medium upstream requests
- streaming works without whole-response buffering

### M3 — Task state, escalation, telemetry, and doctor

Add operational reliability around the working proxy.

Deliverables:

- task/session minimum-tier state
- no automatic demotion within a task
- provider-failure escalation chain
- configurable timeouts
- structured router telemetry
- preservation/passthrough of Claude Code default telemetry behavior
- `cc-enrutador doctor`
- `doctor --live`
- `doctor --json`
- diagnostics for config, endpoints, credentials presence, ports, timeouts, streaming/tool capabilities
- routing/escalation audit fields

Exit criteria:

- simple failure can escalate to medium, then complex according to config
- fresh real user task resets classification floor
- router telemetry can be disabled independently of Claude Code telemetry
- doctor returns documented exit codes and never prints secrets
- live doctor can verify configured provider capabilities with minimal probes

### M4 — End-to-end hardening and V1 release

Validate the complete system against real Claude Code workflows.

Deliverables:

- end-to-end Claude Code test scenarios
- local simple-model test
- GPT-OSS-120B medium-tier test
- Claude subscription complex-tier test
- mixed multi-turn agentic workflow test
- timeout/failure/escalation tests
- Windows-first usage validation
- example configuration
- README/setup documentation
- security review of credential/header handling
- regression fixtures for observed Claude Code meta/telemetry traffic

Exit criteria:

- all V1 acceptance criteria in the technical spec pass
- representative Claude Code coding sessions work through the router
- no known credential leakage path exists
- routing decisions are auditable
- setup is reproducible from a clean checkout

## Dependency graph

```text
M0 ───────────────┐
 │                │
 ├──► M1 ───────► M2 ───────► M3 ───────► M4
 │                ▲
 └─ wire fixtures ┘
```

M1 classification work can begin once the project skeleton exists, while the M0 traffic-capture work proceeds. M2 must consume the validated M0 fixtures rather than relying only on assumptions from the initial spec.

## PR/task sizing

Implementation tasks should generally be independently reviewable and land via PR. Avoid milestone-sized PRs.

Good task size:

- one configuration subsystem
- one extraction behavior
- one classifier mode
- one provider adapter
- one streaming path
- one diagnostic family

Cross-cutting changes are acceptable when splitting them would create unusable intermediate states, especially around streaming and OAuth passthrough.

## Deferred beyond V1

- semantic escalation based on code quality or failed tests
- learned/adaptive routing from telemetry
- SQLite/dashboard analytics
- hot config reload
- multi-user gateway behavior
- billing/cost accounting
