---
name: swarm
description: >
  Create a low-token subagent swarm for work the user explicitly wants delegated or parallelized.
  Generate scoped agent briefs plus `.swarm/plan.md` and `.swarm/run.sh`.
  Invoke only through `/swarm` after the user explicitly requests delegation,
  subagents, or parallel execution.
disable-model-invocation: true
---

# Swarm Mode

Only use this mode when the user explicitly asks for delegation, subagents, or parallel work.

## Methodology (MANDATORY)

The full method — output contract, scoped discovery, decomposition, ownership
rules, the agent brief template, `plan.md`, the `run.sh` runner template, and
the verification checklist — lives in `references/methodology.md`. **Read it
before building anything and follow it end to end.** Do not construct a swarm
from this file alone.

The methodology is deliberately a side-effect-free shared reference: the
`/wise-flow` complex route reads the same file when the user has explicitly
requested delegation there, so one delegation discipline exists in the
repository instead of two.
