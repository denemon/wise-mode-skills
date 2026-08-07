---
name: wise-flow
description: >
  Source-first Claude Code development workflow, from reading the code to opening
  the PR. Runs recon → plan → implement → validate → security gate → PR gate →
  handoff as phases of one skill. Use when the user asks for /wise-flow, a full
  code-development flow, "from reading code to PR", source-first implementation,
  一連の流れ, or names any single phase (recon, plan, validate, handoff).
allowed-tools: Read, Write, Edit, Glob, Grep, Bash, Skill, Agent, TodoWrite, WebFetch, AskUserQuestion
---

# Wise Flow

Route the request through the smallest complete source-first flow. Never skip
source reconnaissance for code-development work; skip later gates only when the
phase does not apply.

## Phase Loading (MANDATORY)

Each phase's instructions live in a reference file next to this one. **Read the
file before running that phase** — do not run a phase from its name alone.

| Phase | File | Artifact | Written to |
|-------|------|----------|------------|
| source-recon | `references/source-recon.md` | Evidence Pack | `.claude/flow/source-recon.md` |
| plan | `references/plan.md` | Implementation Plan | `.claude/flow/plan.md` |
| implement-review | `references/implement-review.md` | Change Pack | `.claude/flow/implement-review.md` |
| validate | `references/validate.md` | Validation Report | `.claude/flow/validate.md` |
| security-gate | `references/security-gate.md` (runs `attack-on-hacker`) | Security Gate Report | `.claude/flow/security-gate.md` |
| pr-gate | the `pr-self-review` skill | PR Readiness Report | `.claude/flow/pr-gate.md` |
| handoff | `references/handoff.md` | Handoff Note | `.claude/flow/handoff.md` |

Installed path: `.claude/skills/wise-flow/references/<phase>.md`. Repository
path during local development: `skills/wise-flow/references/<phase>.md`.

The PR gate is not a separate file: run the `pr-self-review` skill and ask it for
the PR Readiness Report format. That skill cannot write files — wise-flow writes
its report to `.claude/flow/pr-gate.md` after receiving it.

If a phase cannot produce its artifact, stop and explain the blocking unknown.
Do not proceed by guessing.

## Artifact Persistence (MANDATORY)

Artifacts live on disk, not only in the conversation, so a resumed or
`/compact`-ed session does not redo finished phases.

**Check the artifact path is ignored — once per flow, before the first write.**
Many projects commit `.claude/` to share skills and settings, and these artifacts
hold source excerpts, validation output, and security findings that should not
land in a commit:

```bash
git check-ignore -q .claude/flow/ || echo "NOT IGNORED"
```

Keep the trailing slash: a directory-only rule such as `.claude/flow/` does not
match the path `.claude/flow` while that directory does not exist yet, so
dropping it reports "not ignored" for a project that is correctly configured.

If it is not ignored, say so in one line and ask whether to add `.claude/flow/`
to `.gitignore` or to keep the artifacts in-conversation only. Do not edit the
user's `.gitignore` unasked, and do not write artifacts into a tracked path
without telling them.

**Write.** On finishing a phase, `Write` its artifact to the path in the table
above, prefixed with this header:

```
<!-- task: <the flow goal, one line> -->
<!-- state: <state fingerprint, or "n/a"> -->
```

The state fingerprint is the worktree identity:

```bash
{ git rev-parse HEAD && git status --porcelain; } | shasum | cut -c1-12
```

Outside a git repository both commands fail and the hash becomes a constant.
Write `state: unknown` in that case and **never reuse a result artifact** —
re-run the phase. A constant fingerprint would make every stale gate look fresh.

**Reuse.** Before running a phase, read its artifact file if it exists. Two
classes, different invalidation — do not treat them alike:

| Class | Phases | Reuse when |
|-------|--------|------------|
| context | source-recon, plan | `task` matches the current goal. State is irrelevant; recon stays valid after you edit code, so record `state: n/a`. |
| result | implement-review, validate, security-gate, pr-gate, handoff | `task` matches **and** `state` equals the current fingerprint. |

A result artifact whose state no longer matches is stale: **re-run the phase.**
Never report a cached Validation Report or Security Gate Report as the current
state of the code — the worktree changed since it was written.

On reuse, say so in one line (`plan: reusing .claude/flow/plan.md`) and move on.

**Reset.** If `task` does not match the current goal, the directory belongs to a
finished flow: delete `.claude/flow/` and start clean. Same on an explicit
`/wise-flow reset`. Ask before deleting only if the recorded task is unrelated
*and* newer than the last commit — that means another session is mid-flow.

## Sequence

1. source-recon
2. plan
3. If the work splits into non-overlapping write scopes, run `swarm`; otherwise
   stay single-agent.
4. implement-review
5. validate
6. security-gate, if the change is security-sensitive
7. pr-gate (`pr-self-review`)
8. handoff, if the work is incomplete or continuation is requested

## Routing

Classify after source reconnaissance. If several classes apply, take the stricter
route.

| Class | Route |
| --- | --- |
| `simple` | recon → plan (lightweight) → implement-review → validate → pr-gate |
| `normal` | recon → plan → implement-review → validate → pr-gate |
| `complex` | recon → plan → optional swarm → implement-review → validate → pr-gate |
| `security-sensitive` | recon → plan → implement-review → validate → security-gate → pr-gate |
| `review-only` | pr-gate, or security-gate if security-focused |
| `handoff` | handoff |

## Loop Rules

- Validation failure → diagnose from source and logs → fix → validate again.
- Security finding → fix → validate → security-gate again.
- PR finding → fix → validate → pr-gate again.
- New ambiguity → inspect the source first, then ask one question if still stuck.

## Cost Ceiling

This flow adds phases, so it needs an upper bound. Phase stop conditions are
quality-based and have no ceiling on their own.

- **Exploration**: `Read` + `Grep` + `Glob` ≤ **25 calls per phase**. source-recon
  is the phase that normally approaches this; the others should stay well under.
- **Loops**: ≤ **3 rounds** of any fix → re-gate cycle above.

On hitting a ceiling, do not silently stop and do not silently continue. Report
the state and let the user choose:

- (a) continue with a raised budget
- (b) proceed to the next phase with the evidence gathered so far, recording the
  gap as an unknown in the artifact
- (c) narrow the scope

A third failed round of the same gate means the diagnosis is wrong, not that one
more round is needed. Say that instead of looping again.

## Output

Keep updates phase-labeled and concise. Final report: changed behavior, files
changed, validation result, findings and fixes, remaining risks, next action.
