# Wise Flow Implement Review

Implement in small batches and review each diff before moving on.

## Inputs

Use the Implementation Plan from the plan phase.

If the plan is missing acceptance criteria, target files, validation strategy, or
risk gates, return to planning before editing.

## Stop Condition

Do not hand off to validation until:

- all planned edits for the current slice are complete
- `git diff` has been reviewed
- changed behavior is explained
- known self-review issues are fixed or explicitly deferred with reason
- required tests have been added or updated when the plan called for them

## Steps

1. Edit the smallest useful unit.
2. Preserve nearby conventions for naming, errors, logging, constants, tests, and
   abstractions.
3. Avoid unrelated refactors.
4. After each meaningful edit batch, run `git diff -- <changed files>` or
   `git diff`.
5. Review the diff for:
   - correctness
   - regression risk
   - edge cases and null/empty/error handling
   - security assumptions
   - performance
   - readability
   - test impact
6. Fix any issue before continuing.
7. If the diff expands beyond the plan, pause and update the plan before
   continuing.

## Rules

- Do not change public contracts without updating all call sites.
- Do not claim completion without validation.
- If a new ambiguity appears, inspect source first, then ask one question if
  needed.
- Do not mix drive-by cleanup into behavior changes.
- Do not overwrite unrelated user changes in the worktree.

## Output

Return a Change Pack:

```markdown
## Change Pack

### Edited Files
- `path` -> <summary>

### Behavior Changed
- <what changed>

### Tests Added Or Updated
- `path` -> <coverage>

### Diff Self-Review
- reviewed command:
- issues found:
- fixes made:
- deferred issues:

### Ready For Validation
- targeted commands:
- broader commands:
```
