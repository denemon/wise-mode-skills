# Wise Flow Independent Review Gate (optional)

Send the task's diff to a **separate Claude instance** (`claude -p`) for an
independent code review, free from this session's development-context bias.
The reviewer receives none of your conversation, intent, or prior reasoning,
and none of your user- or project-level configuration. It sees the diff you
send it — nothing else.

This gate is **optional and explicit**: run it only when the user requested an
independent or external AI review (see the flow's Authorization Invariants).
It submits content to an external service and is billed.

## How To Execute

Run the script this flow ships — do not hand-assemble the `claude -p` call.
It handles diff collection, rejects partial large-diff reviews, extracts the
system prompt from `references/reviewer_prompt.md`, classifies errors, and
extracts tolerant JSON from the response. It invokes the reviewer with
`--safe-mode` and no tools, so the reviewer loads no user or project CLAUDE.md,
hooks, skills, or memory, cannot read the repository, and receives nothing from
you but the diff itself. One documented exception: admin-managed policy
settings — including policy hooks, which can inject context — still apply
under `--safe-mode`, so in a managed environment the isolation covers user and
project customization, not organization policy:

```
bash <skill-dir>/scripts/ai_review.sh --lang <language> --diff-file <approved-diff>
```

`<skill-dir>` is the wise-flow skill directory (installed at
`.claude/skills/wise-flow`; repository path `skills/wise-flow`).

## Containment Rules (MANDATORY)

The script refuses to run without a diff source; its `--worktree` mode collects
the entire worktree — every tracked and untracked change, whoever made it.
Never pass `--worktree` from this gate: a clean baseline at recon time does not
prove ownership at gate time, because the user or another process may have
changed files while you worked. Always build the gate diff from
only the files this task touched — the Change Pack's file list is the
manifest — using `git diff HEAD -- <files>`, plus
`git diff --no-index -- /dev/null <path>` for files you created — write it to a
file, and pass `--diff-file <path>`. File-level separation cannot prove
authorship inside a file: a file that was clean at recon can have been
edited concurrently while you worked, and a file with pre-existing changes
cannot be split at all — `git diff HEAD -- <files>` captures whatever is in
the worktree now, whoever wrote it. So never send unapproved: before every
external review run, show the user the exact diff file you are about to
submit — naming any known overlap. `ai_review.sh` is deliberately **not**
preapproved anywhere — wise-flow declares no `allowed-tools` at all — so every
invocation goes through the normal Bash permission prompt, and that per-run
prompt — showing the exact command and `--diff-file` — is the enforcement
boundary for sending content off this machine. Do not ask for a session-wide
"always allow" for it, and treat a denied prompt as the user rejecting that
submission. Sending first and reporting afterwards is not containment.
Before invoking the external reviewer, the script rejects likely literal
credentials in the diff. Inspect those matches locally and
redact them. Never pass `--allow-sensitive-content` yourself: if the user
decides that exact reviewed content may be sent anyway, the user runs the
command with that flag directly. The option does not weaken the
sensitive-file path gate.

If the script rejects an oversized diff, split it at file boundaries where
possible. If one file exceeds a limit by itself, split that file only at complete
hunk boundaries and repeat its diff headers in each chunk. Maintain a coverage
manifest of file names and hunk ranges: every changed hunk must appear exactly
once, although one file may span multiple chunks. Run every chunk and aggregate
all results; do not claim the gate passed until the manifest is complete and
every chunk passes. Never split inside a hunk.

## Reading The Result

The script prints JSON on stdout:

- `summary`
- `score` (0–100)
- `coverage` (`complete`; `partial` is rejected by the script)
- `findings` (array: id, category, severity, file, line, title, description, suggestion)
- `positive_notes`

On failure the script prints a JSON error object to **stderr** and exits
non-zero. Report that outcome; do not fall back to an improvised invocation.

## Acting On Findings

- `critical` / `high` → return to implement-review, fix, validate, then re-run this gate.
- `medium` → fix if straightforward; otherwise note in the report.
- `low` / `info` → report only.

The gate is passed only by a diff that has itself been reviewed: after fixing
critical/high findings, re-running the independent review on the final diff is mandatory.
Never proceed on the judgment that a fix is clearly correct.

If `claude -p` is unavailable or fails, state it explicitly in the report.
Do not silently skip this gate after the user requested it.

## Output

Write the Independent Review Report to `.claude/flow/independent-review.md`
under the flow's artifact contract (result class):

```markdown
## Independent Review Report

### Submission
- diff file: <path> (user-approved before sending)
- chunks: <n> / coverage manifest complete: yes|no

### Result
- score: XX / 100
- findings addressed: X critical, X high, X medium
- remaining: low/info items

### Gate Result
- pass | blocked
- required fixes:
```
