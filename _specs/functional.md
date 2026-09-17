# cc-enrutador — Functional Specification

## 1. Purpose

`cc-enrutador` is a lightweight task-aware routing proxy for Claude Code.

Its purpose is to reduce use of expensive remote models while preserving Claude Code as the user-facing coding agent.

For each Claude Code inference request, the router classifies the current task into one of three generic complexity tiers and sends the request to the configured backend for that tier:

- `simple` → configurable level 1 model
- `medium` → configurable level 2 model
- `complex` → configurable level 3 model

The initial intended mapping is local model / GPT-OSS-120B / Claude subscription, but none of these model names are hard-coded into classifier logic.

The classifier must remain independent of model names. Model/provider selection belongs in configuration.

## 2. Primary user flow

1. User logs in to Claude Code normally with a claude.ai subscription.
2. User points Claude Code at `cc-enrutador` using `ANTHROPIC_BASE_URL` only.
3. Claude Code sends an Anthropic Messages API request to the router.
4. The router extracts the actual user task and structural signals from the request.
5. The router classifies the request as `simple`, `medium`, or `complex`.
6. The routing policy maps the tier to a configured model/backend.
7. The selected backend processes the request.
8. The router returns an Anthropic-compatible response/stream to Claude Code.
9. The routing decision is logged locally with an auditable reason.

Claude Code should not require the user to manually switch models during normal operation.

## 3. Complexity tiers

### 3.1 Simple

Reserved for tasks with positive evidence that they are short, self-contained, and mechanical.

Typical examples:

- rename a symbol
- format/reformat text or code
- extract/list/count/sort information
- translate text
- simple repository/file lookup
- straightforward transformation with little or no reasoning

Absence of complexity signals is **not** sufficient to classify a task as simple.

### 3.2 Medium

The default tier.

Typical examples:

- ordinary coding tasks
- implementing a contained feature
- writing or modifying tests
- debugging a reasonably scoped problem
- moderate refactoring
- code analysis or reasoning
- tool-using steps inside an ongoing coding loop

When the classifier has no positive evidence for either `simple` or `complex`, the task routes to `medium`.

### 3.3 Complex

Reserved for requests with positive evidence of deep, broad, or long-horizon work.

Typical examples:

- architecture or system design
- end-to-end changes
- cross-repository/codebase work
- major migrations
- threat modelling / security-sensitive design
- proving or deriving non-trivial behavior
- explicit trade-off analysis
- broad refactors or rewrites
- ambiguous multi-step work requiring substantial synthesis

## 4. Classification behavior

The initial classifier should be a Python adaptation of the evidence-gate approach used by `serhiileniv/claude-router`, simplified from Claude-specific model tiers to `simple / medium / complex`.

### 4.1 Evidence gates

The classifier must follow these principles:

1. `medium` is the default.
2. Leaving the default requires positive evidence.
3. Gates are conjunctive rather than additive scores.
4. Agentic/tool-using requests and ordinary single-turn requests may use different structural signals.
5. Every decision exposes a human-readable `reason` and numeric `confidence`.

### 4.2 Actual task extraction

The classifier must classify what the user actually asked, not the entire accumulated Claude Code payload.

It must ignore, where structurally detectable:

- Claude Code injected `<system-reminder>...</system-reminder>` blocks
- quoted session/context payloads used by Claude Code meta-requests
- previous tool-result payload contents as semantic task text
- prior turns that are not the latest real user instruction

Structural metadata may still be used as signals, e.g. whether tools exist or whether the newest turn contains a tool result.

### 4.3 Agentic sessions

A request is considered agentic when tool definitions are present or tool traffic already exists in the conversation.

Default V1 behavior:

- mid-loop requests following a tool result → `medium`
- fresh explicit deep/long-horizon instruction inside a tool session → `complex`
- clearly trivial task inside a tool session → remains `medium` by default

Allowing `simple` inside agentic sessions may be exposed later as an opt-in policy setting.

### 4.4 Hybrid classifier

V1 should support three classifier modes:

- `heuristic` — evidence gates only
- `ai` — classifier model only
- `hybrid` — evidence gates first; call the classifier model only when the gates abstain/default

`hybrid` is the intended default.

The AI classifier should return only a three-level complexity verdict. It must have:

- configurable classifier model
- configurable classification prompt
- configurable output-label mapping
- short configurable timeout
- small output budget
- deterministic/low-temperature behavior where supported
- local cache
- heuristic fallback on any error or timeout

The classifier backend itself must be configurable and may be a small local model.

## 5. Routing policy

Classification and provider selection are separate concerns.

The router must independently configure:

- level 1 / `simple` model
- level 2 / `medium` model
- level 3 / `complex` model

Example:

```yaml
models:
  simple:
    model: ollama/qwen3-coder
  medium:
    model: openai/gpt-oss-120b
  complex:
    provider: anthropic_subscription
    model: passthrough
```

Changing providers/models must not require changing classifier code.

## 6. Claude subscription behavior

The `complex` route must support the user's existing Claude Code subscription rather than requiring a separate Anthropic API key when that route is configured as `anthropic_subscription`.

Requirements:

- Claude Code is configured with `ANTHROPIC_BASE_URL` pointing to `cc-enrutador`.
- V1 must not require `ANTHROPIC_AUTH_TOKEN` or `ANTHROPIC_API_KEY` for the user's normal subscription path.
- For the Anthropic route, the inbound Claude Code OAuth authorization must be forwarded to the real Anthropic endpoint with the required Anthropic beta/capability headers preserved.
- The OAuth token must never be forwarded to a local model, GPT-OSS provider, LiteLLM deployment, or any other third party.
- Non-Anthropic routes use only their own configured credentials.

## 7. Provider handling

Use LiteLLM for provider/model protocol normalization wherever practical.

LiteLLM should handle concerns such as:

- OpenAI-compatible providers
- Ollama/local models
- streaming
- tool-call conversion where supported
- provider-specific request/response normalization
- retries/fallback primitives

The router itself owns:

- Claude Code request parsing
- task extraction
- classification
- route selection
- credential isolation
- direct Anthropic subscription passthrough where configured
- routing telemetry

The direct Anthropic subscription route may bypass LiteLLM if that is safer or simpler for OAuth passthrough.

## 8. Failure behavior and escalation

Escalation policy must be configurable independently from classification.

V1 must support provider/transport failure escalation using a configurable chain. Default intent:

```text
simple → medium → complex
medium → complex
complex → stop
```

Examples of provider failure include connection failures, request timeouts, retryable provider errors, and upstream unavailability.

Semantic escalation is a separate policy. It may be disabled in the first implementation but its configuration shape must be reserved. Potential future signals include:

- repeated model/tool loop
- failed tests after an attempted edit
- repeated modification of the same files
- explicit model uncertainty
- retry after an unsuccessful result

Classifier failure never triggers execution escalation; it falls back to heuristic classification.

## 9. Auditability and telemetry

Router telemetry is additive to Claude Code's own default telemetry. `cc-enrutador` must not intentionally disable or replace Claude Code's built-in telemetry/observability behavior. Disabling router telemetry affects only `cc-enrutador`'s local routing records.

Every inference request should produce a local routing record containing at least:

- timestamp
- request/session identifier when available
- selected complexity tier
- classification method (`heuristic`, `ai`, `hybrid`)
- reason
- confidence
- selected backend/model
- classifier latency
- model latency where available
- success/failure
- fallback/escalation path, if any

Prompts and model responses must **not** be persisted by default.

Debug capture of request/response bodies must be an explicit opt-in development feature and should warn that source code and credentials may be sensitive.

## 10. Configuration

Configuration is a first-class requirement and is specified in `_specs/configuration.md`.

V1 must allow configuration without Python code changes of:

- classifier model/provider
- level 1 / `simple` model/provider
- level 2 / `medium` model/provider
- level 3 / `complex` model/provider
- escalation policy and escalation chain
- classification prompt and classifier output labels
- classifier timeout
- upstream connection timeout
- per-level request timeouts
- per-level stream idle timeouts
- classifier cache/output settings
- listen host/port
- logging/telemetry/debug behavior

Configuration should be YAML plus environment variables for secrets.

Secrets must never be committed to configuration files.

Invalid configuration must fail clearly at startup.

## 11. User-visible diagnostics

The router should make routing observable without disrupting Claude Code.

At minimum provide:

- concise structured application logs
- selected tier/model/reason per request
- health endpoint
- optional debug endpoint that classifies a supplied sample request without invoking the target model
- required `cc-enrutador doctor` CLI command for configuration/backend diagnostics

The doctor command must support a safe default mode that does not intentionally spend model tokens, plus an optional `--live` mode for minimal provider/capability probes. It must validate configuration, model endpoints, escalation policy, timeouts, credentials by presence only (never value), and relevant streaming/tool-call capabilities.

A dashboard is out of scope for V1.

## 12. Non-goals for V1

V1 does not aim to:

- replace Claude Code as an agent harness
- implement a general-purpose enterprise LLM gateway
- train a learned router
- provide a web dashboard
- support per-user multi-tenancy
- provide billing
- perfectly predict task complexity
- automatically optimize routing from telemetry
- support more than the three generic tiers

## 13. Attribution

The initial classifier design is intentionally based on the evidence-gate and hybrid-classifier implementation in:

- https://github.com/serhiileniv/claude-router

That project is MIT licensed. If substantial implementation code is ported or translated, the required MIT copyright and license notice must be retained in the repository and/or relevant source files.
