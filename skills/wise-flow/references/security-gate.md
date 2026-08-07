# Wise Flow Security Gate

Review security-sensitive changes defensively before PR readiness.

This gate does **not** define its own security methodology. It runs the
`attack-on-hacker` skill in Diff Mode and wraps the result in the flow's
artifact contract. Two competing severity scales in one repository produce
findings that cannot be compared, so there is exactly one: the rubric in
`attack-on-hacker`.

## Inputs

Use:

- Evidence Pack
- Implementation Plan
- Change Pack
- Validation Report
- current diff

If there is no security-sensitive signal, state that this gate is skipped and
why.

## How To Run It

1. Determine the diff range. Local work: `git diff` and `git diff --staged`.
   Branch work: the merge base chosen by the plan. PR work: the provided PR diff.
   If no diff is available, stop and ask for the target range instead of guessing.
2. Run the `attack-on-hacker` skill and tell it this is a diff review, so it
   enters Diff Mode (`references/diff-mode.md`) instead of a whole-repo review.
   Pass the diff range and the security-relevant context from the Change Pack.
3. Require its full discipline — the flow's brevity must not erode it:
   - the Phase 1 threat model block
   - Source → Sink → Sanitizer on every finding
   - the Pre-Report Sanity Gate
   - a severity from its rubric and an evidence level from its taxonomy
     (`confirmed-by-poc` / `confirmed-by-read` / `inferred-pattern`)
   - the Diff Mode prefixes: `[regression]` / `[new-surface]` / `[pre-existing]`
4. Translate its report into the Security Gate Report below. Do not re-score,
   re-label, or soften anything — carry its severities and evidence levels
   through verbatim.

The regression hunt for silently weakened controls, the language-specific sinks,
and the quick-wins sweep all live in that skill's reference files. Do not
re-derive them here.

## Stop Condition

Do not move to the PR gate until:

- the threat model is stated
- changed trust boundaries are identified or explicitly absent
- every finding carries a severity, an evidence level, and a minimal fix
- critical/high findings are fixed or explicitly blocking

## Severity Gate

Critical and high findings must be fixed before continuing. After any fix,
return to implement-review and validate, then rerun this gate.

This gate reports; it does not implement. Severity comes from
`attack-on-hacker`'s rubric, including its downgrades — one level down when the
only evidence is `inferred-pattern`, and one level down when the only viable
attacker is `admin-or-insider` with no privilege boundary crossed.

## Output

Return a Security Gate Report:

```markdown
## Security Gate Report

### Threat Model
- attacker:
- trust boundaries:
- out of scope:

### Changed Security Surface
- `path:line` -> <surface>

### Findings
- severity:        <from the attack-on-hacker rubric>
- evidence:        <confirmed-by-poc | confirmed-by-read | inferred-pattern>
- classification:  <[regression] | [new-surface] | [pre-existing]>
- file/line:
- Source -> Sink -> Sanitizer:
- impact:
- minimal fix:

### Reviewed With No Finding
- <area>

### Gate Result
- pass | blocked
- required fixes:
- residual risk:
```
