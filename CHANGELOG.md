# Changelog

## 1.0.0rc1

Release candidate for the first complete cc-enrutador implementation.

### Included

- heuristic, AI, and hybrid task complexity classification
- simple / medium / complex configurable routing
- LiteLLM execution for simple and medium tiers
- direct Anthropic subscription passthrough for complex work
- streaming and tool-call normalization
- strict credential isolation
- task-level no-demotion policy
- provider-failure escalation
- structured router telemetry
- safe and live doctor diagnostics
- Linux and Windows release-gating CI
- V1 compatibility, security, and release validation documentation

### Known release-signoff requirements

Real Claude Code subscription/tool/stream compatibility must be recorded in
`docs/v1-validation-results.md` before the final `1.0.0` tag.
