# Wise Flow Validate

Validate the change with the nearest useful commands.

## Inputs

Use the Change Pack from the implement-review phase and the validation
candidates from the Implementation Plan.

If no command is obvious, inspect manifests, scripts, test config, and nearby
documentation before asking.

## Command Selection

Infer commands from manifests and existing scripts.

- JavaScript/TypeScript: targeted tests, `npm test`, `pnpm test`, lint,
  typecheck, build
- Python: targeted unittest/pytest, lint/type checks if configured
- Rust: `cargo test`, `cargo clippy` when appropriate
- Go: `go test ./...`, `go vet` when appropriate
- Other stacks: use the project's documented or nearby validation commands

Prefer targeted checks first. Run broader checks when the change affects shared
behavior, public contracts, or build output.

## Stop Condition

Do not move to PR or security gates until:

- at least one relevant validation path has been attempted, or a clear blocker is
  documented
- failures have been diagnosed to source, test setup, environment, or external
  dependency
- fixes for code-caused failures have been made and rerun
- remaining unverified areas are explicit

## Failure Handling

If validation fails:

1. Read the exact failure.
2. Map it back to source.
3. Classify it as code-caused, test-caused, environment-caused, external, or
   unknown.
4. For code-caused failures, return to the implement-review phase with a
   concrete diagnosis and the smallest recommended fix.
5. Rerun the relevant command after implementation changes are made.

Do not hide failures. If a command cannot run, state why and what remains
unverified.

## Output

Return a Validation Report:

```markdown
## Validation Report

### Commands
- `<command>` -> pass/fail/not run

### Failures Diagnosed
- failure:
- classification:
- likely source cause:
- recommended fix:
- rerun result:

### Coverage
- behavior covered:
- risks covered:
- gaps:

### Remaining Unverified
- <item> -> <reason>

### Next Gate
- security_gate_required:
- pr_gate_ready:
```
