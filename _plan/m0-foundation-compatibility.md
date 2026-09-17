# M0 — Project Foundation and Compatibility Capture

## Objective

Create the executable project skeleton and replace protocol assumptions with captured Claude Code behavior.

## Tasks

1. Initialize Python 3.12 project with `uv`, src layout, pytest, linting and typing.
2. Add CLI entry point with `--help`, config-path option, and placeholder serve/doctor commands.
3. Implement initial Pydantic configuration skeleton sufficient to start tools.
4. Add MIT attribution / third-party notice for the classifier source project.
5. Build a minimal recording/echo proxy for controlled inspection of Claude Code requests and streams.
6. Capture a real logged-in Claude Code session through `ANTHROPIC_BASE_URL`.
7. Sanitize captures into reusable test fixtures.
8. Document observed:
   - request headers
   - OAuth behavior
   - `anthropic-beta` headers
   - model identifiers
   - streaming events
   - tool-use/tool-result shapes
   - meta/internal calls
   - auxiliary endpoints
   - telemetry/observability calls
9. Update specs if observations contradict assumptions.

## Acceptance

- CLI and test skeleton run on Windows and Linux-compatible environments.
- No secrets exist in fixtures.
- At least one streaming and one tool-using session are represented in fixtures.
- Compatibility findings are written down before M2 provider implementation is finalized.
