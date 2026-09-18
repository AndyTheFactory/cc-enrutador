# V1 release checklist

## Automated gates

- [ ] Linux CI passes: pytest, Ruff, format, mypy, package build, CLI smoke
- [ ] Windows CI passes: pytest, Ruff, format, mypy, package build, CLI smoke
- [ ] `config.example.yaml` validates with documented environment values
- [ ] credential-isolation and secret-redaction tests pass
- [ ] V1 end-to-end synthetic regression suite passes

## External compatibility gates

- [ ] real Claude Code simple route validated
- [ ] real Claude Code medium route validated
- [ ] real Claude subscription complex route validated
- [ ] real multi-turn tool workflow validated
- [ ] long-running stream/disconnect validated
- [ ] Claude auxiliary/telemetry compatibility checked

Record external evidence in `docs/v1-validation-results.md`.

## Release consistency

- [ ] technical acceptance evidence reviewed
- [ ] no unresolved V1 questions remain in `_specs/open_questions.md`
- [ ] README/config/environment examples match implementation
- [ ] THIRD_PARTY_NOTICES and license attribution are present
- [ ] known limitations are documented
- [ ] version is ready to change from `1.0.0rc1` to `1.0.0`

## Tagging

Do not create the V1 tag until every required release gate is checked. The release tag is a
separate release action, not part of implementation PRs.
