# Quick Reference Checklists

## Pre-Implementation Checklist

- [ ] Searched for project guidance docs (CLAUDE.md, CONTRIBUTING.md, README.md, etc.)
- [ ] Read relevant project documentation
- [ ] Assessed complexity (simple → lightweight / medium / complex → full process)
- [ ] Created/found GitHub issue (only if the user explicitly requested it)
- [ ] Created todo list with phases
- [ ] Verified all methods/APIs exist via grep — no assumptions
- [ ] Identified codebase patterns to follow
- [ ] Listed files to modify and their callers/dependents

## TDD Checklist

- [ ] **RED**: Wrote failing test FIRST
- [ ] Test fails for the RIGHT reason (not import error, not syntax error)
- [ ] **GREEN**: Implemented minimal code to pass
- [ ] Test passes
- [ ] **REFACTOR**: Cleaned up code structure under green tests
- [ ] Tests still pass after refactoring
- [ ] Added boundary condition tests (0, 1, -1, null, empty, max)
- [ ] Added side effect assertions (all modified fields checked)
- [ ] Isolated tests from external dependencies

## Legacy Code (No Existing Tests)

- [ ] Wrote characterization tests capturing current behavior
- [ ] Confirmed characterization tests pass on unmodified code
- [ ] Proceeded with changes
- [ ] Verified characterization tests identify behavioral changes

## Implementation Checklist

- [ ] Using constants/enums, not hard-coded strings
- [ ] Using project's logging patterns
- [ ] Following project's UI framework conventions
- [ ] Input validation is complete
- [ ] Error handling is complete
- [ ] Race conditions checked for shared state
- [ ] Transaction side-effects considered (audit records persist on error?)
- [ ] Shared state actors and invariants documented (if applicable)

## Pre-Commit Checklist

- [ ] All acceptance criteria addressed
- [ ] No hard-coded values that should be constants
- [ ] No assumptions made without verification
- [ ] All edge cases handled
- [ ] No security vulnerabilities
- [ ] Tests cover new functionality
- [ ] Appropriate test suite passes
- [ ] Documentation updated
- [ ] GitHub issue updated (if applicable)

## Adversarial Questions

Before committing, ask yourself:

1. What happens if this runs twice concurrently?
2. What if the input is null? Empty? Zero? Negative? Enormous?
3. What assumptions am I making that could be wrong?
4. If I were trying to break this, how would I?
5. What other code touches this same data?
6. Would I be embarrassed if this broke in production?

## Design Breakpoint Check

If during implementation you realize the design is wrong:

1. Stop coding immediately
2. Keep the worktree intact; do not stash unrelated user changes
3. Return to Phase 2 (Codebase Exploration)
4. Update the todo list and, only if issue tracking was explicitly requested,
   the GitHub issue with revised scope
5. Resume from Phase 3 with corrected tests

## Test Strategy Quick Reference

| Change Scope | Strategy |
|-------------|----------|
| < 20 lines, single file | Related test only |
| 20–50 lines, single file | Related + sanity |
| Multiple files, same feature | Feature suite |
| Cross-cutting | Full affected modules |
| Database / schema changes | Full affected modules |
| Auth / security | Full affected modules |

## GitHub Issue Commands

Run these only when the user explicitly requests the corresponding GitHub
issue action. Do not create, edit, comment on, label, or close an issue merely
because wise mode is active.

```bash
# List issues
gh issue list --search "keyword"

# Create issue
gh issue create --title "Title" --body "Body"

# Update issue body
gh issue edit <number> --body "..."

# Add comment
gh issue comment <number> --body "Progress update..."

# Add labels
gh issue edit <number> --add-label "in-progress"

# Close issue
gh issue close <number> --comment "Completed in PR #123"
```
