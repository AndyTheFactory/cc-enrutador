# M1 — Configuration, Task Extraction, and Classification

## Objective

Implement a fully testable, provider-independent task classifier.

## Tasks

1. Implement full configuration schema and validation.
2. Implement environment interpolation and secret references.
3. Implement escalation-chain cycle validation and timeout validation.
4. Implement request inspection helpers and forward-compatible raw-body handling.
5. Implement `latest_user_text`.
6. Implement structural removal of injected `<system-reminder>` blocks.
7. Implement quoted `<session>...</session>` removal.
8. Implement agentic and mid-loop detection.
9. Port/adapt heuristic evidence gates from `serhiileniv/claude-router`.
10. Implement configurable AI classifier through LiteLLM.
11. Implement configurable prompt/output mapping.
12. Implement classifier timeout/failure fallback.
13. Implement in-process LRU classifier cache.
14. Implement hybrid classification.
15. Implement `POST /debug/classify`.
16. Add fixture-driven tests including non-English and malformed classifier outputs.

## Acceptance

- Classification can run without starting execution providers.
- All three classifier modes work.
- Hybrid only calls the AI classifier on heuristic abstention/default.
- Every result includes tier, method, reason, confidence, and latency.
- Model/provider names remain outside classifier logic.
