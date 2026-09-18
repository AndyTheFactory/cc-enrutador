# cc-enrutador

Task-aware model routing proxy for Claude Code.

The project classifies Claude Code requests into three generic complexity levels and
routes them to independently configured model backends:

- `simple` — inexpensive/local model
- `medium` — stronger general coding/reasoning model
- `complex` — typically direct Claude subscription passthrough

The implementation is being delivered milestone-by-milestone. See
[`_specs/`](_specs/) for the contract and [`_plan/`](_plan/) for the implementation plan.

## Current status

M0 provides the project foundation:

- Python 3.12 + `uv`
- CLI skeleton
- typed YAML configuration loading
- environment interpolation and secret references
- safe logging/redaction helpers
- synthetic Anthropic request fixtures
- third-party attribution

M1 adds task extraction, heuristic/AI/hybrid classification, classifier caching, and the `/debug/classify` development endpoint. M2 adds the runnable `/v1/messages` proxy, LiteLLM simple/medium execution, direct Anthropic subscription passthrough, credential isolation, Anthropic-compatible response normalization, streaming/tool support, and `/health`. M3 adds task-level tier stickiness, provider-failure escalation, effective timeout handling, structured router telemetry, auxiliary Anthropic passthrough, and safe/live/JSON doctor diagnostics.

## Development setup

Requirements:

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

From a clean checkout:

```bash
uv sync
```

Run the test suite:

```bash
uv run pytest
```

Lint:

```bash
uv run ruff check .
```

Check formatting:

```bash
uv run ruff format --check .
```

Type-check:

```bash
uv run mypy
```

## CLI

```bash
uv run cc-enrutador --help
uv run cc-enrutador serve --help
uv run cc-enrutador doctor --help
```

`serve` starts the FastAPI/Uvicorn routing proxy using the configured host and port. `doctor` performs safe local diagnostics by default; `doctor --live` performs minimal provider probes and `doctor --json` emits machine-readable results.

## Configuration

Start from:

```text
config.example.yaml
.env.example
```

For the example config, provide the medium-tier endpoint:

```bash
export GPT_OSS_BASE_URL=http://127.0.0.1:8000/v1
```

On PowerShell:

```powershell
$env:GPT_OSS_BASE_URL = "http://127.0.0.1:8000/v1"
```

You can point the CLI to a configuration file explicitly:

```bash
uv run cc-enrutador doctor --config config.example.yaml
```

or set:

```bash
CC_ENRUTADOR_CONFIG=config.example.yaml
```

Secrets belong in environment variables. The YAML contains only the environment-variable
name (for example `api_key_env: GPT_OSS_API_KEY`), not the secret value.

## Security baseline

- Claude OAuth/API credentials must never be logged.
- Request/response bodies are not persisted by default.
- Router telemetry is separate from Claude Code's own telemetry.
- The proxy strips Claude OAuth before sending requests to non-Anthropic providers.

## Provenance

The classifier design planned for M1 is adapted from
[`serhiileniv/claude-router`](https://github.com/serhiileniv/claude-router), which is
MIT licensed. See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
