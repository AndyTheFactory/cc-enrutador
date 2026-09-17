# M4 — End-to-End Hardening and V1 Release

## Objective

Validate the complete V1 against real Claude Code workflows and produce a reproducible release.

## Tasks

1. Run representative simple, medium, and complex tasks from Claude Code.
2. Run multi-turn tool-using coding sessions.
3. Test provider outage and escalation scenarios.
4. Test classifier timeout/failure behavior.
5. Test long-running streaming requests and client disconnects.
6. Validate Claude Code telemetry/auxiliary behavior through the proxy.
7. Perform auth/header security review.
8. Validate Windows-first installation and execution.
9. Add example YAML and `.env.example`.
10. Write README setup, architecture, diagnostics and troubleshooting.
11. Add a V1 end-to-end regression suite.
12. Reconcile all technical-spec acceptance criteria.
13. Resolve or explicitly defer remaining open questions.

## Acceptance

- Clean-checkout setup works.
- All technical V1 acceptance criteria pass.
- No known OAuth/API-key leakage exists.
- Real Claude Code workflows complete across all three tiers.
- Documentation is sufficient to install, configure, diagnose and run the router.
