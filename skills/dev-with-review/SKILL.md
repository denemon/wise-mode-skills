---
name: dev-with-review
description: Implement code changes while continuously reviewing diffs for correctness, regressions, and maintainability. At the final gate, invoke a separate Claude instance via claude -p for an independent review free from development-context bias. Use when doing feature work, bug fixes, refactors, or multi-file edits that require both coding and review.
disable-model-invocation: true
allowed-tools:
  - Read
  - Grep
  - Glob
  - Edit
  - Write
  - Bash(git status)
  - Bash(git status *)
  - Bash(git diff)
  - Bash(git diff *)
  - Bash(git add *)
  - Bash(npm test *)
  - Bash(npm run lint *)
  - Bash(npm run build *)
  - Bash(pnpm test *)
  - Bash(pnpm lint *)
  - Bash(pnpm build *)
  - Bash(yarn test *)
  - Bash(yarn lint *)
  - Bash(yarn build *)
  - Bash(npx tsc *)
  - Bash(pytest *)
  - Bash(python -m pytest *)
  - Bash(ruff check *)
  - Bash(ruff format *)
  - Bash(mypy *)
  - Bash(shellcheck *)
  - Bash(cargo test *)
  - Bash(cargo clippy *)
  - Bash(go test *)
  - Bash(go vet *)
  - Bash(bash *ai_review.sh *)
  - Bash(cat *)
  - Bash(wc *)
  - Bash(head *)
  - Bash(tail *)
---

You are responsible for **both implementation and continuous review**.

Your role is not only to write code, but also to monitor your own changes and review them critically as if you were a separate reviewer. At the final gate, you will invoke a genuinely separate Claude instance to review the completed diff — providing an independent perspective free from your development-context bias.

Follow this workflow strictly.

## Inputs

Task: $ARGUMENTS

## Core operating rules

- Do not jump into editing immediately.
- First understand the target area, constraints, and likely impact.
- Prefer small, reversible edits over large speculative rewrites.
- After every meaningful code change, switch into review mode and inspect the diff.
- Treat review as adversarial: assume the change may be wrong until verified.
- If you find a problem during review, fix it before continuing.
- Do not claim completion without passing both self-review and independent review.
- If tests or validation commands cannot run, say so explicitly and explain why.

---

## Phase 1: Understand before editing

1. Restate the task in one short paragraph.
2. Identify:
   - files likely involved
   - language and toolchain (needed for Phase 4 validation commands)
   - risks and assumptions
   - validation strategy
3. Read the smallest relevant set of files first.
4. Avoid broad edits unless codebase evidence supports them.

---

## Phase 2: Make changes in small batches

When implementing:

- Change the smallest useful unit first.
- Preserve existing conventions unless there is a strong reason not to.
- Keep naming, error handling, and boundaries consistent with nearby code.
- Avoid mixing unrelated refactors into the same batch.

After each meaningful batch of edits, immediately enter review mode (Phase 3).

---

## Phase 3: Continuous self-review loop

After each edit batch:

1. Run `git diff -- <changed files>` (or `git diff` if broad).
2. Review the diff from the perspective of:
   - correctness
   - regression risk
   - edge cases and error handling
   - security / unsafe assumptions
   - performance
   - readability / maintainability
   - test impact
3. Explicitly ask yourself:
   - Did I break existing behavior?
   - Did I change an interface or contract?
   - Did I update all call sites?
   - Are null / empty / error cases handled?
   - Is naming still clear?
   - Is there duplicated logic that should be consolidated?
   - Does this require tests to be added or updated?
4. If any issue is found → fix it now → review the new diff again.
5. Repeat until the current batch is review-clean.

---

## Phase 4: Validation

Before entering the final gate, run the most relevant validation commands.

### Choosing commands

Infer the appropriate commands from the repo. Prefer the smallest sufficient scope.

**JS / TS repos** (detect via package.json):
- lint → `npm run lint` / `pnpm lint` / `yarn lint`
- test → `npm test` / `pnpm test` / `yarn test`
- typecheck → `npx tsc --noEmit`
- build → `npm run build` (if it exists)

**Python repos** (detect via pyproject.toml, setup.py, requirements.txt):
- lint → `ruff check .`
- format → `ruff format --check .`
- type → `mypy .` (with `--ignore-missing-imports`)
- test → `pytest -v --tb=short`

**Rust repos**: `cargo clippy`, `cargo test`
**Go repos**: `go vet ./...`, `go test ./...`
**Shell scripts**: `shellcheck <file>`

### Handling failures

- Determine whether failure is caused by your change.
- Fix if in scope.
- Otherwise report clearly and continue.
- All validation must pass (or be explicitly excused) before Phase 5.

---

## Phase 5: Independent review gate (claude -p)

This is what separates this workflow from ordinary self-review.
You invoke a **separate Claude instance** that has zero knowledge of your development context, your intent, or your prior reasoning. It sees only the code.

### Why this matters

Self-review — no matter how disciplined — carries the bias of the author. The separate instance provides a genuinely independent perspective, similar to a real code review from a colleague.

### How to execute

Run the script this skill ships — do not hand-assemble the `claude -p` call.
It already handles diff collection, large-diff truncation, system-prompt
extraction from `references/reviewer_prompt.md`, error classification, and
tolerant JSON extraction from the response:

```
bash <skill-dir>/scripts/ai_review.sh --lang <language> --context "<one-sentence summary of the change>"
```

`<skill-dir>` is this skill's directory (installed at
`.claude/skills/dev-with-review`). With no `--diff-file`, the script reviews
`git diff` in the current directory. To review something else, write the diff to
a file first and pass `--diff-file <path>`.

Read the JSON it prints on stdout:

- `summary`
- `score` (0–100)
- `findings` (array: id, category, severity, file, line, title, description, suggestion)
- `positive_notes`

On failure the script prints a JSON error object to **stderr** and exits
non-zero. Report that outcome; do not fall back to an improvised invocation.

### Acting on findings

- `critical` / `high` → fix now, then re-run validation (Phase 4), then re-run this gate.
- `medium` → fix if straightforward; otherwise note in final report.
- `low` / `info` → report only.

After fixing critical/high findings, you may re-run the independent review to confirm, or proceed if the fixes are clearly correct.

---

## Phase 6: Final report

Use this structure in your final response:

```
### Task understanding
- brief restatement

### Plan
- files and approach

### Changes made
- concise summary

### Self-review findings (Phase 3)
- issues found during continuous self-review
- fixes applied

### Validation (Phase 4)
- commands run and results

### Independent review (Phase 5)
- score: XX / 100
- findings addressed: X critical, X high, X medium
- remaining: low/info items

### Remaining risks
- concise bullets

### Ready for review
- yes / no, with one-sentence reason
```

---

## Behavioral constraints

- Do not skip the self-review loop even for small edits.
- Do not skip the independent review gate even if self-review found nothing.
- Do not say "done" immediately after writing code.
- Do not hide uncertainty.
- If the task is ambiguous, choose the safest reasonable interpretation and state it.
- Favor production-safe code over clever code.
- If `claude -p` is unavailable or fails, state it explicitly in the report. Do not silently skip Phase 5.