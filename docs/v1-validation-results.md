# V1 external validation results

Automated CI evidence is recorded by GitHub Actions for the release candidate.

The following checks require an environment outside repository CI and must be filled in when
performed. Do not record credentials, OAuth tokens, source code, or other sensitive payloads.

| Validation | Status | Date | Environment / notes |
| --- | --- | --- | --- |
| Real Claude Code simple route | Pending external validation | — | — |
| Real Claude Code medium route | Pending external validation | — | — |
| Real Claude Code complex subscription route | Pending external validation | — | — |
| Real multi-turn tool workflow | Pending external validation | — | — |
| Real long-running stream + disconnect | Pending external validation | — | — |
| Claude auxiliary/telemetry compatibility | Pending external validation | — | — |
| Windows clean install/runtime | Covered by Windows CI; interactive Claude Code run pending | — | — |

Repository CI is authoritative for synthetic/offline behavior. These external checks are
release sign-off evidence, not substitutes for automated tests.
