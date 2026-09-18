# V1 validation guide

This guide separates automated release gates from checks that require a real Claude Code
installation, real configured providers, or a Claude subscription.

## Automated release gates

Pull requests and `main` must pass:

- Linux Python 3.12 clean dependency sync
- Windows Python 3.12 clean dependency sync
- full pytest suite
- Ruff lint
- Ruff format check
- strict mypy
- wheel/sdist build
- CLI help smoke tests

The automated suite covers classification, task extraction, routing, credential isolation,
provider failure escalation, timeout/fallback behavior, streaming, tool-call translation,
telemetry isolation, auxiliary passthrough, and doctor diagnostics.

## Real Claude Code acceptance

Run the router with a production-like configuration:

```bash
uv sync
uv run cc-enrutador doctor --config config.yaml
uv run cc-enrutador serve --config config.yaml
```

In the shell where Claude Code is launched, point its Anthropic base URL at the router,
using the normal Claude Code configuration mechanism for `ANTHROPIC_BASE_URL`.
Authenticate to Claude Code normally with the user's subscription; do not copy OAuth tokens
into cc-enrutador YAML.

Exercise these representative tasks:

| Case | Example instruction | Expected initial tier |
| --- | --- | --- |
| Simple | `Rename foo to bar.` | `simple` |
| Medium | `Fix the parser bug and add a regression test.` | `medium` |
| Complex | `Design the service architecture end-to-end and discuss trade-offs.` | `complex` |

For each case verify:

1. Claude Code completes the request.
2. Router telemetry records the expected tier/reason/target.
3. The simple/medium provider receives only its configured credentials.
4. The complex route reaches Anthropic using the inbound Claude subscription authorization.
5. Streaming is incremental rather than buffered.

## Multi-turn tool validation

Use a coding task that requires at least one read/edit/test tool loop.

Verify that:

- tool definitions reach the selected provider;
- `tool_use` is returned in Anthropic-compatible form;
- Claude Code sends the corresponding `tool_result`;
- the task identity stays stable through the tool loop;
- the minimum tier never demotes during the active task;
- a new semantic user instruction starts a new task identity.

## Failure validation

Repeat with controlled failures:

- stop the simple provider and verify `simple -> medium` fallback;
- stop simple and medium and verify escalation to `complex`;
- stop the classifier model and verify heuristic fallback;
- interrupt a streaming client and verify upstream cleanup;
- disable `telemetry.enabled` and verify routing still works.

## Compatibility capture policy

Do not archive broad Claude Code traffic.

Create a new regression fixture only if real traffic exposes a compatibility difference that
synthetic fixtures do not already cover. Before committing a captured fixture remove:

- OAuth/API tokens and authorization headers;
- personal paths, usernames, repository names, and hostnames;
- source code and prompts not required to reproduce the protocol behavior;
- account/session identifiers.

Document why each retained fixture exists and the behavior it protects.

## Release evidence

Record the date, platform, Claude Code version, provider combination, configuration commit,
and pass/fail result in `docs/v1-validation-results.md`. Do not record secrets.
