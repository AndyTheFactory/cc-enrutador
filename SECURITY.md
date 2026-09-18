# Security

## Credential boundary

Claude Code subscription authorization belongs only on Anthropic-bound traffic.

cc-enrutador must never forward inbound Claude `Authorization`, Anthropic `x-api-key`,
or Anthropic-specific capability headers to LiteLLM/non-Anthropic execution targets.
Non-Anthropic providers receive only credentials configured for that target.

## Logging and telemetry

Router telemetry contains routing metadata only. Authorization headers, API keys, resolved
secret values, prompts, responses, and tool-result bodies are not persisted by default.

`cc-enrutador doctor` checks secret environment variables by presence only and never prints
their values.

## Debugging and captures

Treat any request/response capture as sensitive. Captured real Claude Code traffic must be
sanitized according to `docs/v1-validation.md` before it is committed.

## Reporting

If a credential-isolation issue is discovered, do not publish real credentials or captured
tokens in an issue. Reproduce it with synthetic/fake tokens and add a regression test.
