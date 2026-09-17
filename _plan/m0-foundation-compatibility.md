# M0 — Project Foundation

## Objective

Create the executable project skeleton and the minimum shared infrastructure required by all later milestones.

## Tasks

1. Initialize Python 3.12 project with `uv` and src layout.
2. Add pytest, linting, formatting, and typing configuration.
3. Add the `cc-enrutador` CLI entry point.
4. Add CLI surface for:
   - `cc-enrutador serve`
   - `cc-enrutador doctor`
   - `cc-enrutador --help`
5. Implement the initial Pydantic configuration models and YAML loading path.
6. Add environment-variable interpolation/secrets-by-reference foundation.
7. Add a minimal example configuration matching the three configured levels and classifier.
8. Add package logging setup without prompt/body persistence.
9. Add MIT attribution / third-party notice for the classifier source project.
10. Establish test directory/fixtures structure for later Anthropic request fixtures.
11. Add basic README development instructions.

## Acceptance

- `uv sync` succeeds from a clean checkout.
- `uv run pytest` succeeds.
- lint/type checks can be run locally.
- `uv run cc-enrutador --help` succeeds.
- `uv run cc-enrutador doctor --help` succeeds.
- a minimal YAML configuration loads through Pydantic.
- invalid configuration produces an actionable error.
- no secrets are committed.
- classifier/proxy implementation can begin without additional project-bootstrap work.

## Not part of M0

Real Claude Code traffic capture is not required to start implementation. The documented Anthropic Messages API behavior and the project specifications are the contract.

Real-session compatibility validation belongs to M4 end-to-end hardening. If undocumented Claude Code behavior is discovered there, it should result in focused compatibility fixes and regression fixtures.
