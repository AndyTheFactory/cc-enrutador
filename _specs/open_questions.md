# cc-enrutador — Open Questions

Only genuinely unresolved decisions remain here. Resolved architecture and V1 behavior belong in the functional, technical, and configuration specifications.

## 1. Default simple-tier model

Which concrete model should be used in the reference configuration for the `simple` tier?

Requirements:

- fast local inference
- reliable tool/function calling through LiteLLM
- sufficient quality for short mechanical coding tasks
- modest memory footprint

The router itself must remain model-agnostic.

## 2. Default classifier model

Which concrete small model should be used in the reference configuration for hybrid classification?

Requirements:

- very low latency
- reliable `simple / medium / complex` classification
- deterministic short output
- preferably runnable on the same local inference stack as the simple-tier model

The classifier model remains independently configurable from the simple-tier execution model.

## 3. Medium-tier GPT-OSS-120B deployment

Where will the initial GPT-OSS-120B backend run?

Possible deployments:

- local/self-hosted vLLM
- remote OpenAI-compatible endpoint
- third-party inference provider

This only affects the reference/development configuration. The router treats the medium tier as a generic LiteLLM target.

## 4. Claude Code compatibility observations

Before V1 is considered complete, record a real Claude Code session through a debug/echo proxy and verify the actual compatibility surface.

Confirm:

- exact subscription OAuth/header behavior
- required `anthropic-beta` capability headers
- streaming event shapes
- tool-use event shapes
- Claude Code meta/internal requests
- auxiliary endpoints, if any, that use `ANTHROPIC_BASE_URL`
- default telemetry/observability traffic that may traverse the proxy
- how fresh user instructions can be reliably distinguished from internal/meta turns

Any behavior discovered here that changes routing or passthrough requirements must be folded back into the main specifications.

## Deferred, not open

The following are intentionally deferred rather than unresolved:

- semantic escalation based on model quality, failed tests, repeated edits, or uncertainty
- SQLite/dashboard telemetry
- hot configuration reload
- learned/adaptive routing
- broader provider capability benchmarking
