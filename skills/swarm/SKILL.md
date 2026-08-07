---
name: swarm
description: >
  Create a low-token subagent swarm for work the user explicitly wants delegated or parallelized.
  Generate scoped agent briefs plus `.swarm/plan.md` and `.swarm/run.sh`.
  Use when the user asks to create agents, spin up a swarm, parallelize work,
  delegate tasks, break work into subagents, or orchestrate parallel execution.
---

# Swarm Mode

Build a runnable swarm with minimal context and no overlapping ownership.

Only use this mode when the user explicitly asks for delegation, subagents, or parallel work.

## Output Contract

Always create:

- `.swarm/agents/<agent-name>.md`
- `.swarm/plan.md` for humans
- `.swarm/run.sh` for execution

Keep all three short. Do not duplicate long explanations across files.

## 1. Scoped Discovery

Token saving is mandatory.

- Read only files that affect agent boundaries
- Start with at most 5 files: one project overview, one manifest, and up to 3 likely task files
- Prefer `rg`/directory listing over opening many files
- Expand only when blocked or when ownership is still unclear
- If the task is already well-scoped, skip broad discovery and state assumptions

Do not read "all available project context".

## 2. Decompose For Parallelism

Prefer the smallest swarm that still helps:

- small task: 1-2 workers + integrator
- medium task: 2-4 workers + integrator
- large task: 4-6 workers + integrator

Do not create documentation, review, or cleanup agents unless they materially help the end state.

Each agent must have:

- one concern
- one write scope
- clear inputs and outputs
- a wave number
- a blocking condition if it depends on prior work

## 3. Ownership Rules

Parallel safety matters more than symmetry.

- No two agents may own the same writable file
- Prefer directory-level ownership when possible
- Every agent brief must say `May edit:` and `Must not edit:`
- Tell each agent it is not alone in the codebase and must not revert others' changes
- If ownership is fuzzy, reduce agent count until it is not

Always include one final integrator agent that:

- reads outputs from earlier waves
- resolves interface mismatches
- runs validation
- confirms the requested end state

## 4. Agent File Template

Create `.swarm/agents/<agent-name>.md` with this structure:

```markdown
# Agent: <name>

## Role
<one sentence>

## Wave
<wave number and dependencies>

## Inputs
- <files, folders, artifacts>

## Write Scope
- May edit: <exact files or directories>
- Must not edit: <everything else that could conflict>

## Outputs
- <artifact path> — <result>

## Constraints
- You are not alone in the codebase. Do not revert others' edits.
- Stop and report if required inputs are missing.

## Task
<short numbered steps>

## Success Criteria
- [ ] <verifiable outcome>
- [ ] <verifiable outcome>
```

## 5. plan.md

`.swarm/plan.md` is a brief summary, not a shell script.

Include only:

- goal
- assumptions
- wave list
- one-line dependency notes
- agent table: name, role, wave, write scope
- how to run: `bash .swarm/run.sh`

Do not paste the full runner commands into `plan.md`.

## 6. run.sh

`.swarm/run.sh` is the executable runner.

Requirements:

- shebang + `set -euo pipefail`
- run waves sequentially, agents within a wave in parallel
- collect each agent's PID and `wait "$pid"` on each one after the wave.
  **Bare `wait` always returns 0**, so `set -e` does not catch a failed agent and
  the integrator runs on top of a broken wave — the worst outcome, since its job
  is to declare the end state correct.
- invoke `claude -p "$(cat ...)"` unless the project clearly uses another runner
- end with the integrator
- `chmod +x .swarm/run.sh`

Minimal shape:

```bash
#!/usr/bin/env bash
set -euo pipefail

pids=()
claude -p "$(cat .swarm/agents/agent-a.md)" & pids+=($!)
claude -p "$(cat .swarm/agents/agent-b.md)" & pids+=($!)
for pid in "${pids[@]}"; do wait "$pid"; done

claude -p "$(cat .swarm/agents/integrator.md)"
```

## 7. Verification

Before finishing:

- verify `command -v claude` if you emitted `claude` commands
- verify agent files exist
- verify `.swarm/run.sh` exists and is executable
- print a concise handoff with wave count and file paths

If the runner command is unavailable, say so clearly and still generate the files.
