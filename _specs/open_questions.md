# cc-enrutador — Open Questions

There are no unresolved V1 release-blocking architecture questions.

## Resolved for V1

### Simple-tier model

V1 does **not** define a mandatory default simple-tier model.

The model in `config.example.yaml` is a reference example only. Operators must choose a
LiteLLM-compatible model that meets their latency, quality, memory, and tool-calling needs.
The router remains model-agnostic.

### Classifier model

V1 does **not** define a mandatory default AI-classifier model.

The model in `config.example.yaml` is a reference example only. The classifier model is
independently configurable and may share infrastructure with the simple execution tier, but
the implementation does not assume that it does.

### Medium-tier deployment

V1 treats the medium tier as a generic LiteLLM target.

The reference GPT-OSS-120B identifier and `MEDIUM_BASE_URL` demonstrate an
OpenAI-compatible remote/self-hosted deployment, but the router does not prescribe whether
that endpoint runs locally, on vLLM, or at a third-party provider.

## Deferred beyond V1

The following are intentionally deferred:

- semantic escalation based on model quality, failed tests, repeated edits, or uncertainty
- SQLite/dashboard telemetry
- hot configuration reload
- learned/adaptive routing
- broader provider capability benchmarking
- automatic provider/model recommendation
