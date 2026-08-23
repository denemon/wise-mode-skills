# Wise Flow Security Gate

Review security-sensitive changes defensively before PR readiness.

This gate does **not** define its own security methodology. It applies the
`attack-on-hacker` methodology in Diff Mode and wraps the result in the flow's
artifact contract. Two competing severity scales in one repository produce
findings that cannot be compared, so there is exactly one: the rubric in
`attack-on-hacker`.

The `attack-on-hacker` **skill** is user-invocation-only
(`disable-model-invocation: true`) — this gate cannot start it. Its method is
therefore extracted into a side-effect-free reference that both callers read:
`skills/attack-on-hacker/references/methodology.md` (installed path:
`.claude/skills/attack-on-hacker/references/methodology.md`). That reference
grants no permissions; the skill's `allowed-tools` preapprovals do not apply
here, so expect a normal permission prompt for each command this gate runs.

## Inputs

For an implementation flow, use the Evidence Pack, Implementation Plan, Change
Pack, Validation Report, and current diff. For a security-focused `review-only`
route, those implementation artifacts are not produced; use the requested
branch, PR, range, or local diff plus security-relevant context supplied by the
requester. Do not invent missing implementation artifacts.

If there is no security-sensitive signal, state that this gate is skipped and
why.

## How To Run It

1. Determine the diff range by following the matching route in the
   `pr-self-review` skill's `references/diff-acquisition.md` (repository path:
   `skills/pr-self-review/references/diff-acquisition.md`; installed path:
   `.claude/skills/pr-self-review/references/diff-acquisition.md`). Local work follows its HEAD
   route, including
   `git ls-files --others --exclude-standard` and each untracked file's
   `git diff --no-index -- /dev/null "$path"`; explicit branch work follows its
   TARGET_REF-based merge-base cascade; PR work uses its `gh` route. If an
   Implementation Plan already fixed the same target and base, reuse them. If
   no diff is available, stop and ask for the target range instead of guessing.
2. Read the `attack-on-hacker` methodology reference and apply it as a diff
   review, so it routes through that skill's `references/diff-mode.md`
   (repository path: `skills/attack-on-hacker/references/diff-mode.md`;
   installed path: `.claude/skills/attack-on-hacker/references/diff-mode.md`)
   instead of a whole-repo review.
   Use the diff range and security-relevant context from the Change Pack, or
   from the requester on a `review-only` route.
3. Require its full discipline — the flow's brevity must not erode it:
   - the Phase 1 threat model block
   - Source → Sink → Sanitizer on every finding
   - the Pre-Report Sanity Gate
   - a severity from its rubric and an evidence level from its taxonomy
     (`confirmed-by-poc` / `confirmed-by-read` / `inferred-pattern`)
   - the Diff Mode prefixes: `[regression]` / `[new-surface]` / `[pre-existing]`
4. Embed every canonical finding field in the Security Gate Report below and
   add only the Diff Mode classification. Do not re-score, re-label, soften, or
   drop fields.

The regression hunt for silently weakened controls, the language-specific sinks,
and the quick-wins sweep all live in that skill's reference files. Do not
re-derive them here.

## Stop Condition

Do not move to the PR gate until:

- diff coverage is `complete`; a partial review is always blocked
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
- Title:           <canonical finding title>
- Severity:        <from the attack-on-hacker rubric>
- Classification:  <[regression] | [new-surface] | [pre-existing]>
- Location:        <path:line>
- CWE:             <CWE-XXX — short name>
- CVSS (estimate): <CVSS:3.1 vector — score X.X>
- Attacker profile: <anon-external | authenticated-low-priv | cross-tenant | admin-or-insider | compromised-dependency>
- Preconditions:
- Source → Sink:
- Sanitizers observed:
- Evidence:        <confirmed-by-poc | confirmed-by-read | inferred-pattern, plus canonical evidence detail>
- Impact:
- Fix:
- Verification:

### Reviewed With No Finding
- <area>

### Coverage
- complete | partial
- reviewed files/hunks:
- unreviewed files/hunks:

### Gate Result
- pass | blocked
- required fixes:
- residual risk:
```
