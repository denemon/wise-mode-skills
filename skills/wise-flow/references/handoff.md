# Wise Flow Handoff

Create a compact continuation note.

## Inputs

Use all available phase artifacts:

- Evidence Pack
- Implementation Plan
- Change Pack
- Validation Report
- Security Gate Report
- PR Readiness Report
- current `git status --short`

If artifacts are missing, reconstruct only the minimum needed from files and
diffs. Do not reread the whole repository.

## Include

- User goal and current status
- Relevant source files and why they matter
- Changes already made
- Validation commands and results
- Review/security findings and unresolved items
- Blockers or decisions needed
- Suggested next skills:
  - the source-recon phase if context is stale
  - the plan phase if design is unresolved
  - the implement-review phase for remaining edits
  - the validate phase before final review
  - the security-gate phase for security-sensitive work
  - the pr-gate (pr-self-review skill) before PR

Reference existing artifacts by path instead of duplicating long content — the
earlier phases of this flow wrote theirs to `.claude/flow/<phase>.md`. List the
ones that exist and note which are stale (see Artifact Persistence in
`SKILL.md`), so the next session knows what it can reuse and what to re-run.

Redact secrets, tokens, credentials, and personal data.

## Output

Return a Handoff Note:

```markdown
## Handoff Note

### Goal
- <user goal>

### Current Status
- done:
- not done:
- branch/worktree:

### Source Context
- `path` -> <why it matters>

### Changes
- `path` -> <change>

### Validation
- command:
- result:
- gaps:

### Review Status
- security:
- PR gate:
- unresolved findings:

### Blockers
- <decision/input/external dependency>

### Suggested Next Skills
- <skill> -> <why>
```

Save the note to `.claude/flow/handoff.md` under the artifact contract in
`SKILL.md`.
