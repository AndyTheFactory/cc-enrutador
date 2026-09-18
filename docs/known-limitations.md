# V1 known limitations

The `1.0.0rc1` release candidate intentionally has a narrow scope.

- Model quality is not benchmarked by the router. The reference model identifiers are examples
  rather than endorsed/default models.
- Semantic escalation based on answer quality, failed tests, repeated edits, or uncertainty is
  reserved but disabled.
- Task state is in-process and bounded; restarting the router resets task-tier floors.
- No web dashboard, persistent telemetry database, multi-user tenancy, billing, or adaptive
  routing is included.
- Prompt/response body persistence is not implemented in V1. Reserved capture flags are
  rejected if enabled.
- Tool/function behavior depends on the configured LiteLLM provider/model capabilities.
- A streaming route may escalate only before it emits response bytes; the router will not
  splice a second provider into a partially emitted response.
- Real Claude Code subscription, multi-turn tool, long-stream, and auxiliary compatibility
  require external release sign-off and cannot be proven by offline CI alone.
- The final `1.0.0` tag is intentionally blocked until those external checks are recorded in
  `docs/v1-validation-results.md`.
