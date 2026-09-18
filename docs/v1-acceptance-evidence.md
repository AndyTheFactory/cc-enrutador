# V1 technical acceptance evidence

This file maps the V1 acceptance criteria in `_specs/technical.md` to release evidence.

| # | Criterion | Automated evidence | External sign-off |
| --- | --- | --- | --- |
| 1 | Claude Code can point to router using `ANTHROPIC_BASE_URL` | HTTP proxy/API tests; auxiliary passthrough tests | Real Claude Code run required |
| 2 | trivial transform routes simple | classifier + V1 acceptance tests | Real provider run required |
| 3 | ordinary coding routes medium | classifier + V1 acceptance tests | Real provider run required |
| 4 | architecture/deep routes Anthropic subscription | classifier/routing/auth tests | Real subscription run required |
| 5 | streaming works for supported routes | streaming/provider/integration tests | Real long-stream check required |
| 6 | tool calls work for simple/medium combination | normalization/provider/tool tests | Real configured provider tool run required |
| 7 | Claude OAuth never reaches non-Anthropic targets | credential-isolation/security tests | Reviewed at release |
| 8 | hybrid classifier safely falls back | classifier fallback + V1 acceptance tests | Optional live failure check |
| 9 | route decision auditable | telemetry tests | Verify local log during real run |
| 10 | classifier/extraction/auth/routing covered | full pytest suite | none |
| 11 | doctor validates stack and supports live probes | doctor tests and CLI smoke | Run `doctor --live` on release environment |
| 12 | router telemetry disable does not disable/replace Claude telemetry | auxiliary passthrough + telemetry isolation tests | Observe real Claude Code auxiliary behavior |

## Release rule

Automated evidence is necessary but not sufficient for the final `1.0.0` tag.

The external checks in `docs/v1-validation-results.md` must be completed for the actual
Claude Code/provider combination used for release sign-off. Until then the package version
remains a release candidate.
