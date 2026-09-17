# M2 — Provider Execution and Anthropic-Compatible Proxy

## Objective

Make Claude Code usable through cc-enrutador with all three routing levels.

## Tasks

1. Implement FastAPI server and `POST /v1/messages`.
2. Implement routing decision to configured target.
3. Implement LiteLLM adapter for simple/medium execution.
4. Implement direct Anthropic subscription passthrough.
5. Implement strict inbound-auth stripping for non-Anthropic targets.
6. Preserve required Anthropic headers on subscription passthrough.
7. Implement non-streaming response normalization.
8. Implement streaming/SSE path.
9. Implement tool-call translation/forwarding.
10. Handle client disconnect and upstream cancellation where possible.
11. Implement `GET /health`.
12. Add integration tests using fake upstreams.
13. Add explicit credential-leak regression tests.
14. Validate against M0 captured fixtures.

## Acceptance

- Claude Code works through the proxy.
- Simple and medium execute through LiteLLM.
- Complex executes through Claude subscription passthrough.
- OAuth never reaches non-Anthropic targets.
- Streaming and tool calls work on the tested provider combination.
