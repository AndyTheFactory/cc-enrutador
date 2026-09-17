# M4 — End-to-End Hardening and V1 Release

## Objective

Validate the complete V1 against real Claude Code workflows and produce a reproducible release.

## Tasks

1. Run representative simple, medium, and complex tasks from Claude Code.
2. Capture/sanitize representative real Claude Code traffic only as needed for compatibility regression fixtures.
3. Run multi-turn tool-using coding sessions.
4. Test provider outage and escalation scenarios.
5. Test classifier timeout/failure behavior.
6. Test long-running streaming requests and client disconnects.
7. Validate Claude Code telemetry/auxiliary behavior through the proxy.
8. Perform auth/header security review.
9. Validate Windows-first installation and execution.
10. Add example YAML and `.env.example`.
11. Write README setup, architecture, diagnostics and troubleshooting.
12. Add a V1 end-to-end regression suite.
13. Reconcile all technical-spec acceptance criteria.
14. Resolve or explicitly defer remaining open questions.

## Acceptance

- Clean-checkout setup works.
- All technical V1 acceptance criteria pass.
- No known OAuth/API-key leakage exists.
- Real Claude Code workflows complete across all three tiers.
- Documentation is sufficient to install, configure, diagnose and run the router.
