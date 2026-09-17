# cc-enrutador — Functional Specification

## 1. Purpose

`cc-enrutador` is a lightweight task-aware routing proxy for Claude Code.

Its purpose is to reduce use of expensive remote models while preserving Claude Code as the user-facing coding agent.

For each Claude Code inference request, the router classifies the current task into one of three generic complexity tiers and sends the request to the configured backend for that tier:

- `simple` → inexpensive local model
- `medium` → stronger non-Claude model, initially GPT-OSS-120B
- `complex` → Anthropic Claude using the user's existing Claude Code subscription

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

- short timeout
- small output budget
- deterministic/low-temperature behavior where supported
- local cache
- heuristic fallback on any error or timeout

The classifier backend itself must be configurable and may be a small local model.

## 5. Routing policy

Classification and provider selection are separate concerns.

Example configuration:

```yaml
routes:
  simple:
    model: ollama/qwen3-coder
  medium:
    model: openai/gpt-oss-120b
  complex:
    model: anthropic-subscription
```

Changing providers/models must not require changing classifier code.

## 6. Claude subscription behavior

The `complex` route must support the user's existing Claude Code subscription rather than requiring a separate Anthropic API key.

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
- direct Anthropic subscription passthrough
- routing telemetry

The direct Anthropic subscription route may bypass LiteLLM if that is safer or simpler for OAuth passthrough.

## 8. Failure behavior and escalation

V1 routing must fail safely.

At minimum:

- classifier failure → use heuristic result
- unavailable `simple` backend → configurable fallback to `medium`
- unavailable `medium` backend → configurable fallback to `complex`
- Anthropic subscription route failure → return the upstream error; do not silently replace subscription traffic with paid API credentials

Runtime task escalation based on semantic failure, repeated edits, failed tests, or tool-loop behavior is desirable but not required for the first functional milestone.

A later version may support:

```text
simple → medium → complex
```

based on observable failure signals.

## 9. Auditability and telemetry

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

Configuration should be YAML plus environment variables for secrets.

Configuration should include:

- listen host/port
- classifier mode
- classifier backend/model
- AI classifier timeout
- tier → model mapping
- provider endpoints
- fallback behavior
- logging level
- telemetry enable/disable
- debug request capture enable/disable

Secrets must never be committed to configuration files.

## 11. User-visible diagnostics

The router should make routing observable without disrupting Claude Code.

At minimum provide:

- concise structured application logs
- selected tier/model/reason per request
- health endpoint
- optional debug endpoint or CLI command that classifies a supplied sample request without invoking the target model

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
