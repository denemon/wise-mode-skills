# Wise Flow Plan

Turn source evidence into an implementation plan.

## Inputs

Use the Evidence Pack from the source-recon phase.

Required inputs:

- request signals
- entry points
- target surface
- current behavior
- patterns to preserve
- risks
- validation candidates
- unknowns

If the Evidence Pack is missing or too weak, return to source reconnaissance
instead of planning from memory.

## Stop Condition

Do not move to implementation until the plan states:

- intended behavior and acceptance criteria
- files likely to change and files that should remain untouched
- test/validation strategy
- risk gates, including whether security review is required
- rollback or compatibility concerns
- delegation_requested from the Evidence Pack and the resulting swarm decision

## Steps

1. Classify the task:
   - `simple`: one file, under 50 changed lines, low risk
   - `normal`: a few files, clear behavior change
   - `complex`: broad impact, public API, schema, concurrency, or shared state
   - `security-sensitive`: auth, authz, secrets, external input, file I/O, CI,
     dependencies, crypto, deserialization
   - `review-only`: user asks only to review existing diff/PR
2. Define intended behavior and acceptance criteria.
3. List files likely to change and files that must not change.
4. Define test strategy before editing.
5. Identify rollback, concurrency, shared-state, API contract, and data risks.
6. Apply the parent skill's Authorization Invariants; do not infer delegation:
   - If `delegation_requested` is not `yes`, set `swarm_candidate: no`.
   - If it is `yes`, use swarm only for separable, non-overlapping write scopes.
7. Define the smallest safe implementation slice.
8. Identify test cases to add, update, or run.

## Output

Return an Implementation Plan:

```markdown
## Implementation Plan

### Classification
- class:
- security_gate_required:
- delegation_requested:
- swarm_candidate:

### Source-Backed Understanding
- <what current code does, with file references>

### Intended Behavior
- <target behavior>

### Acceptance Criteria
- [ ] <observable outcome>

### Planned Edits
- `path` -> <change>

### Files Not To Touch
- `path` -> <reason>

### Test Strategy
- Add/update:
- Run targeted:
- Run broader:

### Risk Gates
- contract/schema/API:
- shared-state/concurrency:
- data/side effects:
- security:

### Implementation Slice
- first safe batch:
- follow-up batches:

### Blocking Unknowns
- <unknown> — ask now? yes/no
```

Ask one question only if source evidence is insufficient and the assumption is
risky.
