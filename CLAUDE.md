# CLAUDE.md

## Mission

In this repository, Claude Code Skills must be developed to be **reproducible, verifiable, and safe to modify**, rather than merely appearing to work.

Implementation speed is not the highest priority.

The priorities are:

1. Correct understanding of requirements
2. Minimal changes
3. Reproducible verification
4. Preservation of existing behavior
5. Transparent handling of failures

Never declare work complete based on assumptions.

---

# Non-Negotiable Rules

Treat the following requirements as MUST-level rules.

## 1. Never claim something works unless it has been verified

NEVER:

* Say "fixed" or "completed" without running the relevant tests
* Say "verified" after only reading the code
* Assume a Skill works correctly merely because the Skill exists
* Consider normal-path testing alone sufficient
* Ignore errors and continue as though nothing happened
* Treat verification that could not be executed as completed verification

You may only describe something as `PASS` if the relevant verification was **actually executed successfully in the current session**.

---

## 2. Understand the existing system before making changes

Before modifying code or a Skill, inspect the relevant:

* Target files
* Related Skills
* Related `CLAUDE.md` files and rules
* Related scripts
* Existing tests
* Package, runtime, and dependency configuration
* Existing implementations of similar functionality

Do not immediately create or modify files in an unfamiliar codebase.

If an existing implementation or convention exists, prefer its:

* Architecture
* Naming
* Directory structure
* Patterns
* Tooling

over inventing a new approach.

---

# Development Workflow

Follow this sequence for every change.

## Step 1: Goal

Before implementation, internally translate the request into:

* Expected behavior
* Inputs
* Outputs
* Failure behavior
* Non-goals
* Acceptance criteria

Do not silently invent major requirements when the request is ambiguous.

However, if the answer can reasonably be determined from the repository, inspect the repository before asking for additional information.

---

## Step 2: Inspect

Read the relevant implementation before modifying it.

For Skill development, inspect at least the applicable parts of:

```text
.claude/
├── skills/
│   └── <skill-name>/
│       ├── SKILL.md
│       ├── scripts/
│       ├── references/
│       └── assets/
├── rules/
├── settings.json
└── settings.local.json
```

Do not assume a directory, configuration, command, or file exists without checking.

---

## Step 3: Plan

If multiple files need to be changed, determine the scope of the changes before editing.

Follow these principles:

* Minimal diff
* Minimal dependencies
* Least privilege
* Minimal side effects

Do not perform unrelated refactoring.

Do not mix large formatting changes with functional changes unless necessary.

---

## Step 4: Implement

Make the smallest change that satisfies the requirement while preserving the existing design.

If evidence discovered during implementation invalidates the original assumption, do not force the original implementation plan.

Re-evaluate the root cause and update the implementation accordingly.

---

## Step 5: Verify

Verification is mandatory after implementation.

Run all applicable lint, syntax, test, and build checks through this repository's
standard command; that is the single entrypoint `./check.sh`. Do not assemble a
partial replacement by hand.

When applicable, verify in this order:

1. Static validation
2. Unit tests / script tests
3. Skill invocation test
4. Trigger behavior test
5. Negative test
6. Regression test
7. End-to-end behavior

If a verification step fails, investigate the failure before proceeding as though verification succeeded.

Do not hide, suppress, or reinterpret a failure merely to complete the task.

---

# Skill Development Rules

## SKILL.md

Each Skill should generally include:

```yaml
---
name: <skill-name>
description: <what it does AND when it should be used>
---
```

The `description` must explain not only what the Skill does, but also **when Claude should use it**.

Bad:

```yaml
description: Helps with APIs.
```

Good:

```yaml
description: Reviews REST API implementations for request validation, error handling, backwards compatibility, and test coverage. Use when creating or modifying API endpoints.
```

---

## Trigger Precision

For automatic Skill invocation, evaluate both:

* should-trigger cases
* should-not-trigger cases

A Skill being invoked is not sufficient evidence of correctness.

Evaluate these separately:

```text
Trigger correctness
    ↓
Skill execution correctness
    ↓
Output correctness
```

All three layers matter.

---

## Dangerous / Side-Effect Skills

Skills involving operations such as the following should generally not be automatically invoked:

* deploy
* publish
* release
* database migration
* data deletion
* git push
* production mutation
* billing operations
* destructive filesystem operations

When appropriate, use:

```yaml
disable-model-invocation: true
```

and require explicit user invocation.

---

## Tool Permissions

When specifying `allowed-tools`, follow the principle of least privilege.

NEVER use overly broad permissions such as:

```yaml
allowed-tools: "*"
```

without a demonstrated requirement.

Do not give a Skill write, shell, network, or other capabilities that it does not need.

---

# Skill Verification Matrix

For every new Skill or meaningful Skill behavior change, verify at least the following.

## A. Explicit Invocation

Test explicit invocation:

```text
/<skill-name>
```

Verify that the expected behavior is performed.

---

## B. Should Trigger

Create multiple natural-language prompts that should cause the Skill to be used.

Example:

```text
Review this API endpoint.
```

Expected result:

```text
Skill invoked
Expected procedure followed
Expected output produced
```

Do not rely on a single trigger example.

---

## C. Should NOT Trigger

Test similar prompts that do not require the Skill.

Example:

```text
What is a REST API?
```

The Skill should not be unnecessarily invoked.

Avoid overly broad Skill descriptions that cause unrelated requests to trigger the Skill.

---

## D. Edge Cases

At minimum, consider:

* empty input
* missing files
* invalid arguments
* malformed configuration
* unexpected file structure
* tool failure
* command failure
* partial output

If an edge case is reasonably expected in production usage, test it when practical.

---

## E. Fresh Context

When evaluating a Skill, test it in a fresh context whenever practical.

Do not rely exclusively on the conversation in which the Skill was created.

The Skill must contain enough information to work without hidden context from previous discussion.

---

# Scripts

When a Skill executes scripts, prefer deterministic validation over LLM judgment whenever possible.

Example:

```text
Bad:
Tell Claude to "carefully check whether the JSON is valid."

Good:
Run a JSON parser or schema validator.
```

Prefer deterministic mechanisms for:

* validation
* formatting
* file existence checks
* schema checks
* naming checks
* generated-file checks
* security restrictions

If a requirement can be mechanically enforced, prefer mechanical enforcement over natural-language instructions.

---

# Test Integrity

NEVER:

* Delete a failing test just to make the suite pass
* Weaken assertions just to make the suite pass
* Skip tests just to make the suite pass
* Increase timeouts without understanding the reason
* Catch and silently suppress errors
* Add mocks that eliminate the behavior that actually needs verification

When a test fails, determine whether the problem is:

```text
implementation bug
test bug
environment problem
requirement mismatch
```

If modifying the test itself, confirm whether the specification actually changed.

Do not modify tests merely to match incorrect implementation behavior.

---

# Regression Protection

For bug fixes, follow this sequence whenever practical:

```text
1. Reproduce
2. Add or identify a failing test
3. Implement the minimal fix
4. Confirm the failing test now passes
5. Run related regression tests
```

Do not claim a bug has been fixed if the original failure was never reproduced or otherwise objectively verified.

---

# Command Safety

Do not execute commands such as the following without explicit user authorization:

```bash
git push
git push --force
git reset --hard
git clean -fd
git clean -fdx
git checkout .
rm -rf
npm publish
pnpm publish
yarn publish
```

The same rule applies to equivalent destructive operations.

Never discard existing uncommitted user changes without explicit authorization.

---

# Git Rules

Unless explicitly requested by the user:

* Do not commit
* Do not push
* Do not delete branches
* Do not rewrite history
* Do not revert unrelated changes

When possible, inspect the repository state before starting and before completion:

```bash
git status --short
git diff
```

Distinguish pre-existing changes from changes made during the current task.

Never assume every diff in the working tree was created by Claude.

---

# Security

NEVER:

* Hard-code secrets
* Print values from `.env`
* Log API keys, tokens, or passwords
* Commit credential files
* Copy secrets into test fixtures

If secret-like information is discovered, avoid displaying or duplicating it unnecessarily.

Do not expose a secret merely to explain that a secret exists.

---

# Dependency Policy

Before adding a new dependency, check:

1. Whether the dependency is actually necessary
2. Whether the standard library can solve the problem
3. Whether an existing dependency already solves the problem

Do not perform unrelated package upgrades.

Do not regenerate a lockfile without a reason.

Keep dependency changes scoped to the task.

---

# Failure Protocol

When a command, tool, or test fails, NEVER:

```text
repeat the same operation multiple times without a new hypothesis
```

Instead:

```text
1. Read the error
2. Identify the failure layer
3. Form a hypothesis
4. Run the smallest useful diagnostic
5. Fix the root cause
6. Re-run the original verification
```

Do not treat a workaround designed only to bypass an error as a permanent fix.

Do not hide failures in order to produce a successful-looking result.

---

# Definition of Done

A task is complete only when all applicable conditions are satisfied.

* [ ] The requested behavior has been implemented
* [ ] No unnecessary changes were introduced
* [ ] Syntax / format validation succeeds
* [ ] Relevant tests succeed
* [ ] Explicit Skill invocation has been checked
* [ ] should-trigger behavior has been checked
* [ ] should-not-trigger behavior has been checked
* [ ] Relevant edge cases have been checked
* [ ] Relevant regression tests succeed
* [ ] No secrets were introduced
* [ ] No unauthorized destructive operations were performed
* [ ] The final diff has been reviewed

If any applicable verification cannot be performed, explicitly report that fact.

Do not describe the work as fully verified when applicable verification remains incomplete.

---

# Completion Report

The final response for implementation work must clearly distinguish completed work from verification.

Use the following structure:

```text
Implemented
- What was actually changed

Verified
- What was actually executed and checked
- command: result

Not verified
- Verification that could not be performed
- Reason

Remaining risks
- Known remaining risks
```

Do not invent verification results or risks.

If `Not verified` contains applicable items, do not claim the implementation is "fully verified."

---

# Evidence Rule

Strictly distinguish between the following states:

```text
READ      = The code or configuration was inspected
INFERRED  = A conclusion was derived from inspection
EXECUTED  = A command or behavior was actually run
VERIFIED  = The executed result matched the expected result
```

Never describe `READ` or `INFERRED` evidence as `VERIFIED`.

Examples:

```text
Bad:
"The Skill works correctly."
```

when only the `SKILL.md` file was inspected.

Prefer:

```text
"The Skill definition appears consistent with the expected behavior, but invocation behavior was not executed."
```

Likewise:

```text
Bad:
"All tests pass."
```

unless the relevant tests were actually executed successfully.

---

# Mechanical Enforcement

Natural-language instructions are not sufficient for guarantees.

Whenever an important requirement can be enforced mechanically, prefer:

```text
CLAUDE.md instruction
        +
deterministic script
        +
Claude Code Hook
        +
CI check
```

over relying on `CLAUDE.md` alone.

Examples of behavior that should preferably be mechanically enforced:

* formatting
* linting
* type checking
* test execution
* generated-file consistency
* schema validation
* forbidden files
* protected paths
* secret detection
* destructive command restrictions
* required Skill structure

Claude should not substitute judgment for an available deterministic check.

---

# Verification Before Completion

Before declaring implementation work complete:

1. Review the final diff
2. Identify the commands that prove correctness
3. Run all applicable verification commands
4. Inspect failures instead of ignoring them
5. Confirm that no unrelated files changed
6. Report any validation that could not be performed

The final answer must reflect the actual evidence available.

Never optimize the final report to sound more successful than the underlying verification supports.

---

# Priority

When requirements conflict or judgment is required, use this priority order:

```text
Correctness
> Safety
> Existing behavior
> Testability
> Simplicity
> Maintainability
> Speed
```

Never sacrifice verification, safety, or existing behavior merely to finish faster.
