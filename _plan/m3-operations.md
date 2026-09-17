# M3 — Task State, Escalation, Telemetry, and Doctor

## Objective

Make routing operationally reliable and diagnosable.

## Tasks

1. Define task/session identity from observed Claude Code traffic.
2. Implement minimum-tier stickiness for an active task.
3. Reset classification floor on a fresh real user instruction.
4. Implement provider-failure escalation chain.
5. Implement per-stage/per-tier timeouts.
6. Implement structured router telemetry.
7. Ensure router telemetry can be disabled independently.
8. Preserve Claude Code default telemetry/observability paths.
9. Implement `cc-enrutador doctor` safe checks.
10. Implement `doctor --live`.
11. Implement `doctor --json`.
12. Add PASS/WARN/FAIL model and documented exit codes.
13. Add endpoint, bind-port, secret-presence, timeout, config and escalation diagnostics.
14. Add minimal live checks for classifier, completion, streaming and tool calling.
15. Add tests proving diagnostics redact all secrets.

## Acceptance

- Configured provider failures escalate correctly.
- Tier never automatically demotes within an active task.
- Doctor safe mode does not intentionally invoke models.
- Live mode uses minimal probes and clearly reports failures.
- No diagnostic or telemetry output contains credentials.
