# CLAUDE.md

@AGENTS.md

## Required Execution Loop

For every implementation task:

1. Convert the request into concrete, testable acceptance criteria.
2. Inspect the relevant code and existing tests before editing.
3. Reproduce the current behavior or failure when possible.
4. Implement the smallest complete change.
5. Run focused checks after each meaningful change.
6. Run all applicable lint, type-check, test, and build commands — in this repo
   that is the single entrypoint `./check.sh`.
7. Compare the results against the acceptance criteria.
8. If any criterion or check fails, diagnose the cause, make a focused
   correction, and repeat from step 5.
9. Review the final diff for unintended changes, obsolete code, and missing tests.

### Closing gate: `/verify`

Before reporting the work as done, run **`/verify`** and record its verdict.
This is the last step, and it is not optional.

`check.sh` proves nothing regressed; it never executes the change. `/verify`
does the other half — it drives the changed code at its real surface and returns
PASS / FAIL / BLOCKED / SKIP. `.claude/skills/verify/SKILL.md` holds the recipe
for driving this repository's artifacts, including the traps (pty prompts,
shadowing the real `claude`, never running alongside the mutation audit).

* **PASS** — report the work, quoting the verdict and what was observed.
* **FAIL / BLOCKED** — do not report completion. Fix and re-run the gate.
* **SKIP** — allowed only when there is genuinely no runtime surface
  (docs-only, tests-only). State the reason in one line.

If `/verify` cannot be invoked in the current session, do the same thing by
hand — install or launch the artifact, drive the changed path, capture the
output — and report the verdict in the same four terms. "The tests are green"
is not a substitute; a green suite has shipped a broken installer in this
repository before.

Then report the verification commands, observations, and results.

Do not declare the implementation complete until:

* all acceptance criteria are satisfied;
* all required automated checks pass (`./check.sh` exits 0);
* the final diff has been reviewed; and
* the closing gate returned PASS, or SKIP with a stated reason.

Stop and ask for human direction when:

* the requirements materially conflict;
* the change requires destructive data loss;
* credentials or production access are required; or
* three correction attempts fail to make measurable progress.
