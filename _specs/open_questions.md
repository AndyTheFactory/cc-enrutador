# cc-enrutador — Open Questions

These questions are intentionally not locked into the V1 functional/technical requirements yet.

## 1. Simple-tier model

Which model should be the default local `simple` backend?

Candidates may include a small coder/instruct model via Ollama or another local OpenAI-compatible server.

Selection criteria:

- reliable Anthropic-style tool calling after LiteLLM translation
- low latency
- small memory footprint
- adequate quality for mechanical coding tasks

## 2. Medium-tier GPT-OSS-120B deployment

Where will GPT-OSS-120B run?

Options:

- local/self-hosted vLLM
- remote OpenAI-compatible endpoint
- third-party inference provider

This affects authentication, expected latency, retry policy, and whether `medium` is always available.

## 3. AI classifier model

Which small model should be used for ambiguous hybrid-classification cases?

Goal: very low latency and cost. It does not need to solve the coding task, only classify `simple / medium / complex`.

Potentially use the same local server as the simple-tier model but a smaller/faster model.

## 4. Escalation in V1 vs V2

Should V1 only perform initial task routing, or also dynamically escalate an ongoing task?

Possible later signals:

- provider failure
- repeated model/tool loop
- failed tests after an attempted edit
- repeated modification of the same files
- explicit model uncertainty
- user correction after a failed attempt

The current spec only requires provider-availability fallback, not semantic task escalation.

## 5. Session stickiness

Should the selected tier be evaluated independently on every Claude Code request, or should a task/session establish a minimum tier for subsequent requests?

The source classifier deliberately handles mid-loop traffic differently, but full session stickiness could prevent route oscillation.

Possible policy:

- classify fresh user instructions
- route tool-result mid-loop requests to the current task tier or at least `medium`
- allow explicit escalation but not automatic demotion until a fresh task begins

Needs real Claude Code traffic testing before locking in.

## 6. Incoming model field

How should explicit Claude Code model selection interact with automatic routing?

Possible policies:

- `auto` mode: ignore requested model for backend selection
- `respect` mode: direct user-selected Opus/Sonnet/etc. to configured matching route
- explicit override header/env/config option for debugging

V1 should likely default to automatic task-aware routing while retaining an escape hatch.

## 7. Claude Code compatibility surface

Start with `POST /v1/messages` and add other endpoints only when actual Claude Code traffic requires them.

We should record a real session through a debug/echo proxy before implementation is considered complete, to identify:

- exact headers Claude Code sends with subscription OAuth
- current `anthropic-beta` capability headers
- meta/classifier requests
- any auxiliary API endpoints that hit `ANTHROPIC_BASE_URL`
- streaming event shapes
- model identifiers used by Claude Code

## 8. LiteLLM boundary

Current preferred design:

- `simple` / `medium` → LiteLLM
- `complex` subscription → direct Anthropic passthrough

Question: can we simplify further by using LiteLLM for the Anthropic subscription leg without altering OAuth/beta headers?

This should only be adopted after an integration test proves credential and header preservation. Simplicity must not come at the expense of leaking the subscription OAuth token or breaking subscription billing.

## 9. Provider capability checks

Should startup validate that configured simple/medium models support the features Claude Code requires?

Potential checks:

- streaming
- tool/function calling
- system messages
- sufficiently large context

This could prevent hard-to-debug failures later but adds startup complexity.

## 10. Telemetry persistence

For V1, is structured console/JSONL logging sufficient, or should routing events be stored in SQLite from the start?

JSONL is simpler; SQLite makes later evaluation of classifier accuracy and escalation patterns easier.

## 11. Windows-first ergonomics

The initial user environment includes Windows development workflows. Decide whether V1 installation should explicitly optimize for:

- `uv run cc-enrutador`
- a PowerShell setup helper
- `.env` support
- optional Docker Compose for LiteLLM/local model components

## 12. Name / package identity

Repository: `cc-enrutador`.

Decide whether the published Python package/CLI should also be `cc-enrutador`, `cc_enrutador`, or use a more descriptive public name later.
