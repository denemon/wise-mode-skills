---
name: wise-flow
description: >
  Source-first Claude Code development workflow, from reading the code to PR
  readiness. Runs recon → plan → implement → validate → security gate → PR gate →
  handoff as phases of one skill. Invoke only through `/wise-flow` when the user
  explicitly requests the full workflow or one of its phases.
disable-model-invocation: true
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
| security-gate | `references/security-gate.md` (applies the `attack-on-hacker` methodology) | Security Gate Report | `.claude/flow/security-gate.md` |
| independent-review | `references/independent-review.md` (runs `scripts/ai_review.sh`) | Independent Review Report | `.claude/flow/independent-review.md` |
| pr-gate | the `pr-self-review` skill | PR Readiness Report | `.claude/flow/pr-gate.md` |
| handoff | `references/handoff.md` | Handoff Note | `.claude/flow/handoff.md` |

Installed path: `.claude/skills/wise-flow/references/<phase>.md`. Repository
path during local development: `skills/wise-flow/references/<phase>.md`.

The PR gate is not a separate file: run the `pr-self-review` skill and ask it for
the PR Readiness Report format. That skill cannot write files — wise-flow writes
its report to `.claude/flow/pr-gate.md` after receiving it.

If a phase cannot produce its artifact, stop and explain the blocking unknown.
Do not proceed by guessing.

## Authorization Invariants (MANDATORY)

This section is the only authority for external or delegated side effects. Phase
references may record eligibility, but must not grant authorization themselves.

- Apply the swarm methodology only if the user explicitly requested delegation,
  subagents, or parallel execution and the work has non-overlapping write
  scopes. The `/swarm` skill is user-invocation-only
  (`disable-model-invocation: true`), so never try to invoke it as a skill;
  read its side-effect-free reference instead
  (repository path: `skills/swarm/references/methodology.md`; installed path:
  `.claude/skills/swarm/references/methodology.md`).
- Run the independent-review gate only when the user explicitly requested an
  independent or external AI review. It sends the diff to an external reviewer
  (`claude -p`, billed): before every run, show the user the exact diff file and
  get approval, per `references/independent-review.md`.
- The PR gate produces readiness evidence only. Create, push, or open a PR only
  when the user explicitly requested that corresponding action.

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
<!-- head: <HEAD commit SHA, or "unknown"> -->
<!-- state: <state fingerprint, or "n/a"> -->
```

The state fingerprint is the worktree identity:

```bash
if git rev-parse --verify HEAD >/dev/null 2>&1; then
  {
    git rev-parse HEAD
    git diff --binary HEAD
    git ls-files --others --exclude-standard -z |
      while IFS= read -r -d '' path; do
        printf 'untracked %s\0' "$path"
        if [ -L "$path" ]; then
          readlink "$path"
        else
          LC_ALL=C shasum "$path"
        fi
      done
  } | LC_ALL=C shasum | cut -c1-12
else
  printf 'unknown\n'
fi
```

Outside a git repository or before the first commit, this prints `unknown`.
**Never reuse a result artifact** in that state — re-run the phase. The diff and
untracked-file hashes make content edits change the fingerprint even while
`git status --porcelain` would keep reporting the same `M` or `??` state.

**Reuse.** Before running a phase, read its artifact file if it exists. Two
classes, different invalidation — do not treat them alike:

| Class | Phases | Reuse when |
|-------|--------|------------|
| context | source-recon, plan | `task` and `head` match the current goal and current HEAD. Record `state: n/a`; uncommitted implementation edits do not invalidate context. |
| result | implement-review, validate, security-gate, independent-review, pr-gate, handoff | `task` matches **and** `state` equals the current fingerprint. |

A result artifact whose state no longer matches is stale: **re-run the phase.**
Never report a cached Validation Report or Security Gate Report as the current
state of the code — the worktree changed since it was written.
If HEAD is unknown, never reuse a context artifact. A branch switch, rebase, or
new commit changes `head` and requires source-recon and planning again.
Before reusing context, re-read cited source paths that are currently modified
or no longer exist. If their evidence no longer matches the artifact, rerun
source-recon and planning; do not trust the matching task and HEAD alone.

On reuse, say so in one line (`plan: reusing .claude/flow/plan.md`) and move on.

**Reset.** The flow owns exactly these artifacts: `source-recon.md`, `plan.md`,
`implement-review.md`, `validate.md`, `security-gate.md`,
`independent-review.md`, `pr-gate.md`, and
`handoff.md` under `.claude/flow/`. Never delete the directory wholesale or
remove an unrecognized file. On `/wise-flow reset`, remove only that exact
manifest. If `task` does not match the current goal, ask before removing the old
manifest because another session may still own it.

## Sequence

1. source-recon
2. plan
3. Apply Authorization Invariants; otherwise stay single-agent.
4. implement-review
5. validate
6. security-gate, if the change is security-sensitive
7. independent-review, only if the user explicitly requested an external AI review
8. pr-gate (`pr-self-review`)
9. handoff, if the work is incomplete or continuation is requested

## Routing

Classify after source reconnaissance. If several classes apply, take the stricter
route.

| Class | Route |
| --- | --- |
| `simple` | recon → plan (lightweight) → implement-review → validate → pr-gate |
| `normal` | recon → plan → implement-review → validate → pr-gate |
| `complex` | recon → plan → explicitly authorized swarm, if eligible → implement-review → validate → pr-gate |
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
