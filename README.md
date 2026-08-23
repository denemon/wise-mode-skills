# wise-mode

English | [日本語](README.ja.md)

**Make Claude Code follow a process.** Fewer changes written before the code was
read, fewer fixes that miss the root cause, fewer problems found after the PR is
open. A set of [Claude Code](https://docs.anthropic.com/en/docs/claude-code)
skills and hooks. Skill invocation and mandated markers are checked with live
evals (`./check.sh --evals`) — invocation-level checks, not output quality; a
git-history heuristic tracks the long-horizon trend
([benchmarks/](benchmarks/)) — a diagnostic, not proof.

7 skills + 3 hooks. Continuous modes are **kept alive by a hook**, so they do not
fade out as the conversation grows.

## Components

| Name | Type | Description |
|------|------|-------------|
| **wise** | Skill (`/wise`) | Architect mode — systematic planning, TDD, adversarial self-review, and quality gates (single task) |
| **wise-cont** | Skill (`/wise-cont`) | Continuous architect mode — activate once, stays on until `/wise-cont-off` (hook-backed) |
| **wise-flow** | Skill (`/wise-flow`) | Source-first flow: recon → plan → implement → validate → security gate → PR gate → handoff, as phases of one skill. Artifacts persist in `.claude/flow/`; the PR gate runs `pr-self-review`, the security gate applies the `attack-on-hacker` methodology reference |
| **attack-on-hacker** | Skill (`/attack-on-hacker`) | Adversarial source-code security review — threat model, taint analysis (Source → Sink → Sanitizer), severity rubric, CWE/CVSS findings, Diff Mode for PRs |
| **pr-self-review** | Skill (`/pr-self-review`) | Self-review of the diff before opening a PR — bug-prevention focused, GitHub-pasteable output (in Japanese). Doubles as the PR gate of `/wise-flow` |
| **swarm** | Skill (`/swarm`) | Low-token subagent orchestration — creates scoped agent briefs plus runnable swarm files |
| **terse-mode** | Skill (`/terse-mode`) | Brevity mode — fewer words, same technical substance, with lite/full/ultra intensity levels (hook-backed) |
| **mode_persistence** | Hook | Keeps `/wise-cont` and `/terse-mode` alive across turns, `/compact`, and session resume — without it the mode decays after a few turns |
| **session_log** | Hook (opt-in) | Records every Claude Code session to `.claude/log/` as Markdown. Secrets are masked before writing. Installed only with `--with-session-log` |
| **flag_guard** | Hook | Blocks flag-level escapes in preapproved read-only commands (`rg --pre`, `git --output`, global `git -c`, scanner report flags) — the layer prefix-match `allowed-tools` rules cannot inspect |

## Quick install

Run this in your **project root** (where `.git/` lives):

```bash
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/install.sh | bash

# with the opt-in session-logging hook:
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/install.sh | bash -s -- --with-session-log

# reproducible: pin the installer AND the snapshot to the same commit, and
# verify the archive checksum. An installer taken from mutable main can
# disagree with a pinned archive's manifest — take both from one ref.
REF=<commit-sha>
curl -fsSL "https://raw.githubusercontent.com/den-emon/wise-mode/${REF}/install.sh" \
  | WISE_MODE_REF="${REF}" WISE_MODE_SHA256=<archive-sha256> bash
```

The installer downloads **one tar.gz snapshot** of the repository (not one file
at a time from the mutable `main` branch, which could interleave with a push
and produce a mixed-version tree), verifies the manifest and your existing
`settings.local.json` **before placing anything**, stages the complete payload
and swaps it in with one `mv` per skill/hook — so an interrupted install never
leaves a half-copied skill — and writes the merged hook configuration into
`.claude/settings.local.json` as the final step. A failure at any check aborts
with nothing installed. Skills that were folded into other skills
(`dev-with-review`, the old `/wise-flow-*` family) are removed on install
after the same consent prompt that guards overwriting — left in place they
keep firing and compete with the router.

The `session_log` hook is **opt-in** (`--with-session-log`): it persists tool
input and output to disk on every tool call, which not every project wants.

Mode flags live in `.claude/.wise-mode` and `.claude/.terse-mode`. If your
repository commits `.claude/`, add both to `.gitignore` — otherwise the mode you
enabled ships to the whole team.

### Manual install

```bash
# wise
mkdir -p .claude/skills/wise
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/wise/SKILL.md \
  -o .claude/skills/wise/SKILL.md
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/wise/CHECKLISTS.md \
  -o .claude/skills/wise/CHECKLISTS.md
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/wise/PATTERNS.md \
  -o .claude/skills/wise/PATTERNS.md

# wise-cont
mkdir -p .claude/skills/wise-cont
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/wise-cont/SKILL.md \
  -o .claude/skills/wise-cont/SKILL.md

# wise-flow (router + phase reference files + independent-review script)
mkdir -p .claude/skills/wise-flow/references .claude/skills/wise-flow/scripts
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/wise-flow/SKILL.md \
  -o .claude/skills/wise-flow/SKILL.md
for phase in source-recon plan implement-review validate security-gate independent-review reviewer_prompt handoff; do
  curl -fsSL "https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/wise-flow/references/${phase}.md" \
    -o ".claude/skills/wise-flow/references/${phase}.md"
done
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/wise-flow/scripts/ai_review.sh \
  -o .claude/skills/wise-flow/scripts/ai_review.sh
chmod +x .claude/skills/wise-flow/scripts/ai_review.sh

# attack-on-hacker
mkdir -p .claude/skills/attack-on-hacker/references
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/attack-on-hacker/SKILL.md \
  -o .claude/skills/attack-on-hacker/SKILL.md
for ref in methodology diff-mode quick-wins language-hints report-format; do
  curl -fsSL "https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/attack-on-hacker/references/${ref}.md" \
    -o ".claude/skills/attack-on-hacker/references/${ref}.md"
done

# pr-self-review
mkdir -p .claude/skills/pr-self-review/references
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/pr-self-review/SKILL.md \
  -o .claude/skills/pr-self-review/SKILL.md
for ref in diff-acquisition output-format; do
  curl -fsSL "https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/pr-self-review/references/${ref}.md" \
    -o ".claude/skills/pr-self-review/references/${ref}.md"
done

# swarm
mkdir -p .claude/skills/swarm/references
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/swarm/SKILL.md \
  -o .claude/skills/swarm/SKILL.md
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/swarm/references/methodology.md \
  -o .claude/skills/swarm/references/methodology.md

# terse-mode
mkdir -p .claude/skills/terse-mode
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/skills/terse-mode/SKILL.md \
  -o .claude/skills/terse-mode/SKILL.md

# hooks (default set)
mkdir -p .claude/hooks
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/hooks/mode_persistence.py \
  -o .claude/hooks/mode_persistence.py
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/hooks/flag_guard.py \
  -o .claude/hooks/flag_guard.py

# session_log hook — opt-in only (it writes tool output to disk)
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/hooks/session_log.py \
  -o .claude/hooks/session_log.py
```

Then add the hook configuration to `.claude/settings.local.json`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/mode_persistence.py\" UserPromptSubmit",
            "timeout": 5
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "matcher": "startup|resume|clear|compact|fork",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/mode_persistence.py\" SessionStart",
            "timeout": 5
          }
        ]
      }
    ],
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/flag_guard.py\" PreToolUse",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

If you opted into the `session_log` hook, additionally merge these events into
the same `"hooks"` object:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/session_log.py\" PostToolUse",
            "timeout": 10
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/.claude/hooks/session_log.py\" Stop",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

`timeout` is in **seconds**, not milliseconds — a four-digit value there means a
hung hook can block your session for over an hour.

## wise — Architect Mode

When you type `/wise` in Claude Code, the agent shifts into architect mode for a **single task**:

- **Think first, code second** — 70% understanding, 30% coding
- **8-phase workflow** — from planning through PR readiness
- **TDD enforcement** — RED / GREEN / REFACTOR cycle
- **Adversarial self-review** — "What if this runs twice concurrently?"
- **Lightweight mode** — auto-scales down for simple, low-risk changes

```
/wise implement user authentication with JWT
```

| Phase | What happens |
|-------|-------------|
| 1. **Understanding & Planning** | Reads project docs, assesses complexity, creates a plan |
| 2. **Codebase Exploration** | Maps existing patterns, verifies APIs exist, identifies impact zone |
| 3. **TDD** | Writes failing tests first, then minimal implementation, then refactors |
| 4. **Implementation** | Builds following existing patterns — constants, logging, error handling |
| 5. **Test Verification** | Runs the appropriate test suite, fixes regressions |
| 6. **Documentation** | Updates docs and an explicitly requested GitHub issue |
| 7. **Pre-Commit Review** | Adversarial self-review checklist |
| 8. **PR Readiness** | Self-reviews the diff; opens a PR only on explicit request |

Simple changes (single file, < 50 lines, no interface changes) automatically skip the full ceremony — only phases 1, 4, and 7 run.

### Skill files

| File | Purpose |
|------|---------|
| `SKILL.md` | Phases, principles, and when to read the other two files |
| `CHECKLISTS.md` | Per-phase checklists, adversarial questions, test-strategy table, `gh` commands |
| `PATTERNS.md` | Concrete code for TOCTOU, transaction side effects, mutation-resistant assertions, characterization tests |

`SKILL.md` stays short on purpose. Detail lives in the two reference files and is
read when the phase needs it — a long skill file gets diluted in context and its
later phases get skipped.

## wise-cont — Continuous Architect Mode

Activate once, and **every subsequent message** is handled with architect-mode standards — no need to type `/wise` each time.

```
/wise-cont
```

The agent assesses each request and applies the appropriate level:

| Request type | Mode applied |
|-------------|--------------|
| Question / discussion (no code changes) | Q&A — architect thinking principles only |
| Single file, < 50 lines, low risk | Lightweight — phases 1, 4, 7 |
| Multi-file, clear scope | Full — phases 1–8 |
| Complex (4+ files, schema changes, etc.) | Full; issue only on explicit request |

Deactivate with `/wise-cont-off` or "normal mode".

**Scope**: the mode is stored as a project-level flag (`.claude/.wise-mode`) and
survives `/compact`, `/clear`, and restarting Claude Code. It stays on until
someone turns it off, including in later sessions and in other sessions open on
the same project. For a single task, use `/wise` instead.

## wise-flow — Source-First Development Flow

`/wise-flow` is one skill; each phase's instructions live in a reference file that
the router reads as it goes. There are no separate `/wise-flow-*` commands
anymore — `install.sh` deletes the old ones.

| Phase | Instructions | Artifact | Written to |
|-------|--------------|----------|------------|
| source-recon | `references/source-recon.md` | Evidence Pack | `.claude/flow/source-recon.md` |
| plan | `references/plan.md` | Implementation Plan | `.claude/flow/plan.md` |
| implement-review | `references/implement-review.md` | Change Pack | `.claude/flow/implement-review.md` |
| validate | `references/validate.md` | Validation Report | `.claude/flow/validate.md` |
| security-gate | `references/security-gate.md` → applies the `attack-on-hacker` methodology | Security Gate Report | `.claude/flow/security-gate.md` |
| independent-review | `references/independent-review.md` → runs `scripts/ai_review.sh` | Independent Review Report | `.claude/flow/independent-review.md` |
| pr-gate | the `pr-self-review` skill | PR Readiness Report | `.claude/flow/pr-gate.md` |
| handoff | `references/handoff.md` | Handoff Note | `.claude/flow/handoff.md` |

Both gates delegate rather than re-deriving their own method: the PR gate runs
`pr-self-review`, and the security gate reads
`attack-on-hacker/references/methodology.md` in Diff Mode and carries its
severity rubric and evidence levels through verbatim. One security standard,
not two. The methodology lives in a side-effect-free reference (not the
skill's `SKILL.md`) because `attack-on-hacker` is user-invocation-only and its
`allowed-tools` preapprovals must never activate outside `/attack-on-hacker`.
The complex route treats `swarm` the same way: with an explicit delegation
request, wise-flow reads `swarm/references/methodology.md` instead of invoking
the skill.

### Artifacts persist

Each phase writes its artifact to `.claude/flow/`, so a session resumed after
`/compact` does not redo finished phases. Two invalidation rules, because they
are not interchangeable:

| Class | Phases | Reused when |
|-------|--------|-------------|
| context | source-recon, plan | the task is unchanged — these stay valid after you edit code |
| result | implement-review, validate, security-gate, pr-gate, handoff | the task is unchanged **and** the worktree fingerprint still matches |

A cached Validation Report or Security Gate Report is therefore never presented
as the current state of the code — once the worktree changes, that phase re-runs.
`/wise-flow reset` clears the directory.

Before the first write the flow checks `git check-ignore .claude/flow/` and tells
you if the path is tracked; these files hold source excerpts and findings. It will
not edit your `.gitignore` on its own.

### Cost ceiling

The flow adds phases, so it has an upper bound: **25** `Read`/`Grep`/`Glob` calls
per phase, and **3** rounds of any fix → re-gate loop. On reaching a ceiling it
stops and offers a choice — raise the budget, proceed with the evidence gathered
so far and record the gap, or narrow the scope. A third failed round of the same
gate is reported as a wrong diagnosis rather than retried.

The normal route is:

```text
source-recon -> plan -> implement-review -> validate -> optional security-gate -> pr-gate -> optional handoff
```

Use the optional branches only when they fit:

| Situation | Route |
|-----------|-------|
| Small or normal code change | `source-recon -> plan -> implement-review -> validate -> pr-gate` |
| Explicit delegation request with separable write scopes | `source-recon -> plan -> swarm -> implement-review -> validate -> pr-gate` |
| Security-sensitive change | `source-recon -> plan -> implement-review -> validate -> security-gate -> pr-gate` |
| Explicit request for an external AI review | `... -> validate -> independent-review -> pr-gate` |
| Existing diff review only | `pr-gate` |
| Incomplete work or session transfer | `handoff` |

Findings loop back to implementation:

```text
finding -> implement-review -> validate -> relevant gate again
```

If a phase cannot produce its artifact, the flow stops and explains the blocking unknown instead of guessing.

```text
/wise-flow add rate limiting to the login endpoint
/wise-flow fix this failing test from source read to PR review
/wise-flow just run recon and find where this bug comes from
/wise-flow run only the PR gate on my final diff
```

Use it when you want the complete code-development path, not just one phase.
The PR gate reports readiness; it does not create, push, or open a PR unless you
explicitly request the corresponding action.

### Independent review (optional gate)

When you explicitly ask for an external AI review, the flow runs
`references/independent-review.md`: it invokes a **separate Claude instance**
(`claude -p`) via `scripts/ai_review.sh` — a reviewer that receives none of the
session's context or configuration, only the diff. The script returns a JSON
score + findings on stdout, or a JSON error on stderr with a non-zero exit.

The gate calls the script rather than assembling the `claude -p` command
itself, so oversized-diff rejection, system-prompt extraction, and response
parsing have one implementation. Oversized diffs use complete file or hunk
chunks with a coverage manifest; a partial review never passes the gate. Other
failures are reported, never worked around with an improvised second attempt.

The reviewer scores the diff 0–100 and returns findings by severity
(critical/high/medium/low/info). Critical and high findings loop back through
implement-review → validate, and the final diff must pass a re-run of this
gate. Sending a diff to the external reviewer always goes through a per-run
Bash permission prompt showing the exact `--diff-file` — wise-flow preapproves
nothing, and the gate never runs unless you asked for it.

This gate replaced the retired `dev-with-review` skill; `install.sh` removes
old `dev-with-review` installs on upgrade.

## attack-on-hacker — Adversarial Security Review

When you type `/attack-on-hacker`, the agent reviews authorized source code from a black-hat mindset and turns the result into defensive findings: credible attack paths, evidence, impact, fixes, and verification steps. No weaponized payloads — output is always remediation-focused.

```
/attack-on-hacker review the auth flow in src/auth/
/attack-on-hacker audit this PR for security regressions
```

| Phase | What happens |
|-------|-------------|
| **Diff Mode** (optional) | If reviewing a PR or branch diff, scopes every phase to changed code and hunts silently-weakened controls (auth gates removed, `verify=False`, loosened CORS, etc.) |
| 1. **Scope + Threat Model** | Entry points, trust boundaries, attacker profile, mitigations to factor out |
| 1.5. **Quick-Wins Sweep** | High-signal pass: secrets in code & git history, CI pwn-request patterns, container hygiene, IaC defaults, dependency audit |
| 2. **Attacker Map** | Source → Sink → Sanitizer taint analysis required for every candidate |
| 3. **Hunt High-Risk Classes** | OWASP-style categories plus language/framework-specific sinks (Node, Django, Spring, Go, Rust, SQL) |
| 4. **Prove Plausibility** | Pre-Report Sanity Gate — reachability, sanitizer absence, realistic preconditions, evidence taxonomy |
| 5. **Report Findings** | Top-3 Fix-First, Severity Rubric, CWE + CVSS per finding |

### Key features

- **Threat model first** — explicit attacker profile (`anon-external`, `authenticated-low-priv`, `cross-tenant`, `admin-or-insider`, `compromised-dependency`); severity is grounded in it
- **Source → Sink → Sanitizer** — every finding must name all three; missing one means it's a suspicion, not a bug
- **Evidence taxonomy** — `confirmed-by-poc` (executed local PoC) / `confirmed-by-read` (full data-flow with `file:line`) / `inferred-pattern` (auto-downgraded severity)
- **False-positive discipline** — reachability, upstream sanitizer, realistic preconditions are mandatory before reporting
- **CWE + CVSS per finding** — for triage-tool integration; the Severity Rubric wins when CVSS disagrees
- **Diff Mode** — `[regression]` / `[new-surface]` / `[pre-existing]` classification for PR reviews
- **JSON output** — optional `--format=json` for tooling consumption

### Permission model — known limits

`allowed-tools` entries are prefix rules: they match the start of a command and
cannot inspect flags. Two layers compensate:

1. The preapproved list is pinned to read-only forms and deliberately excludes
   commands whose flags escalate them into write or execute primitives: `rg`
   (`--pre <cmd>` runs a command per file) and the report-writing scanners
   (`gosec`, `trufflehog`, `gitleaks`, `checkov`, `tfsec`, `bandit`) are not
   preapproved at all and go through the normal permission prompt. The ranged
   `git diff *` / `git log *` / `bundle audit *` forms are gone too:
   `--output` and `--ext-diff` write or execute, `bundle audit update`
   mutates the advisory database, and `--out${GAP}put`-style expansion can
   smuggle such flags past any string-level check — so only bare, flagless
   forms are preapproved and ranged diffs prompt. The skill
   itself is explicit-invocation only (`disable-model-invocation: true`), so
   these permissions never activate without the user typing
   `/attack-on-hacker`.
2. The `flag_guard` PreToolUse hook (installed by `install.sh`) mechanically
   blocks the known flag-level escapes even when they appear *after* a
   preapproved prefix: `rg -n --pre <cmd>`, `git log --output=<path>`, global
   `git -c key=value`, `git --exec-path`, and the report-output flags of the
   audit scanners. It also rejects flag tokens containing `$`, a backtick, or
   `{` — the guard sees the pre-expansion string, so an expandable flag can
   never be verified as safe. The hook is defense in depth, not a permission
   boundary: it fails open on internal errors, and hook timeouts do not
   block, so nothing is preapproved that would be unsafe without it.

The deny table is a known-vector list, not a proof. When reviewing untrusted or
third-party code — exactly the input a security review sees — keep defense in
depth: run the skill with Bash denied or inside a sandboxed checkout, and never
review a downloaded tree that ships its own `.git` or `.claude` directory
without discarding those first.

### Skill files

| File | Purpose |
|------|---------|
| `SKILL.md` | Thin wrapper: permissions (active only on `/attack-on-hacker`) and the pointer to the methodology |
| `references/methodology.md` | The method itself — phases, threat model, taint vocabulary, sanity gate, severity rubric. Side-effect-free; also read by the `/wise-flow` security gate |
| `references/diff-mode.md` | PR/branch scoping, regression hunt, new-surface questions |
| `references/quick-wins.md` | Secrets, CI/CD, container, IaC, and dependency checks |
| `references/language-hints.md` | Stack-specific sinks (Node, Python, Java, Go, Rust, SQL) |
| `references/report-format.md` | Report template, no-findings template, JSON schema |

### When to use

| Situation | Recommended |
|-----------|-------------|
| Full security audit of a codebase or module | `/attack-on-hacker` |
| Security check on a PR / branch diff | `/attack-on-hacker review this PR` (auto-enters Diff Mode) |
| Auth, authz, crypto, deserialization, or parser changes | `/attack-on-hacker` |
| Dependency or IaC change | `/attack-on-hacker` (Quick-Wins Sweep covers both) |
| Non-security implementation work | `/wise` or `/wise-flow` |

## pr-self-review — Self-Review Before the PR

When you type `/pr-self-review`, the agent reviews **the acquired diff** — an explicit branch / PR / commit range, or, with no arguments, the entire current worktree including untracked files — before you open a PR. It focuses on bug-prevention — not idealism, not large refactor proposals, not nitpicking — and outputs findings at a granularity you can paste straight into a GitHub PR comment. **The report is written in Japanese**; the skill definition documents both languages.

```
/pr-self-review                # diff between current branch and base (origin/main → main → master)
/pr-self-review feature/foo    # diff of the specified branch
/pr-self-review #123           # diff of GitHub PR #123 (uses `gh pr diff`)
/pr-self-review abc123...def456
```

### Phases

| Phase | What happens |
|-------|--------------|
| 1. **Diff acquisition** | Procedure in `references/diff-acquisition.md`: route by argument shape, resolve base (`git merge-base` cascade: `origin/main` → `origin/master` → `main` → `master`), fetch, check size. For >2000-line diffs, ask the user how to proceed (full / chunked / abort) rather than silently stopping |
| 2. **Minimal context read** | Read only the surrounding code needed to judge each diff hunk — never the whole codebase. Capped at 10 `Read`/`Grep` calls |
| 2-B. **Caller sweep** | Only when the diff changes a public signature, type, response shape, or DB schema: `Grep` the changed symbols (max 5) to find callers outside the diff. Used **solely** to judge backward compatibility — the callers themselves are never critiqued. Capped at 15 calls; over 20 callers for one symbol is recorded as unverified |
| 3. **Per-perspective scan** | Bug / Null safety / Branch coverage / Error handling / Async / Regression / Boundary / Performance / Security / Naming / Readability — skip perspectives that have no signal |
| 4. **Triage filter** | Drop preferences, drop out-of-diff issues, drop refactor proposals, demote unverified suspicions |
| 5. **Output** | GitHub-pasteable Markdown from `references/output-format.md` — verdict line + 🛑 must-fix / ⚠️ verify / 💭 unconfirmed / ✅ good |

### Hard rules

- ❌ No critique of code outside the diff — the Phase 2-B caller sweep is the one
  exception, and even then only "this diff breaks that caller" is reportable
- ❌ No "refactor everything" / "redesign this" proposals
- ❌ No standalone "add tests" comments (only paired with a concrete bug scenario)
- ❌ No taste-level naming or readability nitpicks (only when misreading is plausible)
- ❌ No nitpicks added to inflate finding count
- ✅ Every finding must have a **specific line**, a **concrete failure scenario**, and a **minimal fix** — otherwise it's not posted
- ✅ Zero-finding output is allowed and expected when the diff is clean

### Skill files

| File | Purpose |
|------|---------|
| `SKILL.md` | Scope rules, hard rules, review perspectives, phases, behavior |
| `references/diff-acquisition.md` | Phase 1 mechanics — argument routing, base resolution, size check |
| `references/output-format.md` | Japanese PR-comment template and the PR Readiness Report template |

### Output sections

- **🛑 PR前に修正推奨** — must fix before opening the PR
- **⚠️ 要確認(挙動次第で問題化)** — likely fine, but the author should confirm an assumption
- **💭 未確認の懸念** — needs out-of-diff investigation; shared as context only
- **✅ 良かった点** — optional, only when something is genuinely worth noting

### As the wise-flow PR gate

Called from `/wise-flow`, the same skill switches output to a **PR Readiness
Report** (verdict / scope / must-fix / verify / unconfirmed) and refuses to
declare `ready` until diff scope, validation status, and — when required —
security gate status are all known.

### When to use pr-self-review vs others

| Situation | Recommended |
|-----------|-------------|
| Final check on the diff right before pushing / opening a PR | `/pr-self-review` |
| PR gate inside the source-first flow | `/wise-flow` — it calls this skill and asks for the PR Readiness Report |
| Want a more independent review by a separate Claude instance | `/wise-flow` (independent-review gate, on explicit request) |
| Security-focused diff review | `/attack-on-hacker` (Diff Mode) |
| Architect-mode design + TDD for the change itself | `/wise` |

## swarm — Parallel Delegation Mode

When you type `/swarm`, the agent builds a compact parallel-work plan for tasks you explicitly want delegated:

- **Low-token discovery** — reads only the files needed to set agent boundaries
- **Conflict-safe ownership** — each agent gets an explicit write scope
- **Runnable output** — generates human-readable `.swarm/plan.md` and executable `.swarm/run.sh`
- **Smallest useful swarm** — avoids over-fragmenting simple work

```text
/swarm build agents for this feature
/swarm break this task into parallel workers
```

Use it when you want subagents or parallel execution, not for ordinary single-agent coding.

## terse-mode — Brevity Mode

When you type `/terse-mode`, the agent switches into a brevity-first response style:

- **Same technical substance** — removes filler, keeps exact terms, commands, and errors
- **3 intensity levels** — `lite`, `full`, and `ultra`
- **Auto-clarity** — temporarily returns to normal wording for destructive actions and safety warnings, and never compresses a structured report another skill defines (a severity label or a required field is not filler)
- **Language-preserving** — stays in the user's language unless asked to translate
- **Persistent** — the hook re-injects the level every turn, so it survives `/compact`, `/clear`, and resume

```text
/terse-mode
/terse-mode lite
/terse-mode ultra
/terse-mode off      # or "normal mode"
```

Use it when you want faster, tighter answers without losing the actual fix or reasoning.


## mode_persistence — Continuous Mode Hook

`/wise-cont` and `/terse-mode` say they stay on. Without a hook they do not: the
instruction scrolls out of the model's working context and the mode quietly
decays after a few turns. `mode_persistence.py` fixes that at the harness level.

| Event | What it does |
|-------|--------------|
| `UserPromptSubmit` | Detects `/wise-cont`, `/terse-mode [level]`, and their off-switches; writes or deletes the flag; injects the active mode's reminder into **every** prompt |
| `SessionStart` | Re-injects the reminder on `startup`, `resume`, `clear`, `compact`, and `fork` |

- Flags: `.claude/.wise-mode`, `.claude/.terse-mode` (project-scoped, one line each)
- `"normal mode"` turns off **both** modes at once
- The two modes are independent — turning off terse leaves wise running
- Failures are swallowed on purpose: a broken hook must never block a session

## session_log — Session Logger (Hook, opt-in)

`session_log.py` records Claude Code tool usage to `.claude/log/` as Markdown
files. It is **not part of the default install**: it persists tool input and
output to disk on every tool call, so it is installed only when you ask for it
with `install.sh --with-session-log` (or by wiring it manually).

### How it works

- **PostToolUse hook** — logs every tool call with timestamps, input parameters, and execution results
- **Stop hook** — adds turn separators between Claude responses
- **Session detection** — groups entries by `session_id`, one file per session
- **Redaction** — command output is masked before it is written, so `cat .env`,
  an `Authorization` header, a `postgres://user:pass@host` URL, a recognizable
  provider token (`sk-`, `ghp_`, `xoxb-`, `AKIA`…), or a PEM private key does not
  land in the log. What ran and where it connected stay
  readable; only the secret is replaced with `«redacted»`.

> **Redaction is not a secret scanner.** It targets the common shapes above and
> deliberately over-masks rather than under-masks. It does **not** remove
> personal data such as email addresses, and a secret in an unusual format can
> still get through. Treat `.claude/log/` and your vault as sensitive: keep them
> out of commits, and use `gitleaks` / `trufflehog` if you need real coverage.

### What gets recorded

| Tool | Recorded content |
|------|-----------------|
| **Bash** | Command, description, execution result (in `<details>` collapse) |
| **Edit** | File path, diff (`- old` / `+ new`) |
| **Grep** | Pattern, path, glob filter, match results |
| **Glob** | Pattern, path, matched files |
| **Read** | File path |
| **Write** | File path |
| **Agent** | Type, description, prompt |
| **Skill** | Skill name, arguments |
| **Others** | Tool name, input JSON, result |

### Log format

Logs are saved as `.claude/log/session-<hash>.md` — the name is derived from the
session ID alone, so concurrent sessions never race over a shared registry and a
session spanning midnight stays in one file:

````markdown
# Claude Code Session Log
**Date:** 2026-03-20
**Start:** 14:30:22
**Project:** my-project
**Session:** abcdef1234567890

---

### [14:30] `Bash` — Run unit tests
```bash
npm test
```
<details><summary>result</summary>

```
PASS src/app.test.ts
  ✓ renders correctly (12ms)
Tests: 1 passed
```
</details>

### [14:31] `Edit` — `src/app.ts`
```diff
- const x = 1
+ const x = 2
```

### [14:32] `Grep` — `handleError` in `src/` (`*.ts`)
```
src/app.ts:42:  handleError(err)
src/utils.ts:10:export function handleError(e: Error) {
```

---
> Turn ended at 14:32:45
````


## Measuring whether it helps

These skills *add* process. Without a number, "it feels more careful" is all you
get — so there is exactly one metric: **fix-follow rate**, the share of fix
commits that re-touch a file changed shortly before.

```bash
python3 benchmarks/fix_follow_rate.py --since 2026-01-01 --until 2026-04-01 --label before
python3 benchmarks/fix_follow_rate.py --since 2026-04-01 --until 2026-07-01 --label after
```

Measure one period before adopting wise-mode and an equally long one after, with
at least 30 commits **and 10 fix commits** each. One rework moves the rate by
100 / fix-commits points (printed as `rate step`); a gap smaller than twice the
larger of the two periods' steps means no effect. Protocol, interpretation, and known
limits are in [benchmarks/README.md](benchmarks/README.md).

## Development

One command verifies everything — `bash -n`, `shellcheck`, Python syntax, and
all three test suites:

```bash
./check.sh            # everything, ~22s
./check.sh --fast     # skips the slow integration suites, ~3s
./check.sh --mutants  # audits the guards themselves, ~2.5min
./check.sh --evals    # runs real claude -p against the skills (billed) — on demand
```

Each suite runs under a timeout. A hang here has always meant recursion — a test
invoking the tool that runs the tests — and it used to present as a silent stall.
Now it fails in seconds saying so.

CI runs the same script, and so does the Stop gate (below). Assembling the
checks by hand instead leaves the scope up to whoever is running them — which
is how "all tests pass" ends up meaning different things on different days.

Tests sit next to the code they cover, so they are split across three
directories, and one suite at a time still works:

```bash
python3 -m unittest discover -s hooks        # hooks (session log, mode persistence)
python3 -m unittest discover -s tests        # packaging + installer/script integration
python3 -m unittest discover -s benchmarks   # the metric script
```

`-s hooks` holds most of the suite, including the redaction tests. Running only
`-s tests` looks green while leaving it unrun — another reason to use
`check.sh`.

`tests/` catches the boring breakage: a skill whose frontmatter `name` no longer
matches its directory, a skill missing from `install.sh`, an undocumented skill,
a `timeout` written in milliseconds, a `SKILL.md` that grew past 300 lines. Add
a skill, then make that suite green before anything else.

The shellcheck glob inside `check.sh` picks up new scripts automatically, and
the current warning count is zero — a new warning belongs to the diff that
introduced it.

### The Stop gate

`.claude/hooks/check_gate.py` runs `check.sh` when Claude Code tries to end a
turn. Red suite → the hook exits 2, which blocks the stop and feeds the failure
back, so a change cannot be reported as finished while verification is failing.
It gives up after three consecutive failures and hands back to you, and it skips
the run entirely when no tracked source file changed since the last green — so
conversational turns cost nothing.

The gate runs `check.sh --fast`; the slow integration suites are CI's job.
A run that times out is reported as *inconclusive*, never as green — otherwise
one slow machine would cache a false pass and switch the gate off for good.

**A green gate does not mean the change works.** `check.sh` runs tests; it never
executes the change at its real surface. So when the suite passes but a file that
actually gets executed changed — `install.sh`, a hook, a shipped script — the gate
prints one line naming them and suggesting `/verify`. It says it once per change
and never touches the exit code. Markdown is excluded: prompt content has no
runtime surface, and nagging on every doc edit would train you to ignore the line.

`.claude/skills/verify/SKILL.md` is the recipe `/verify` picks up for this repo.

`.claude/hooks/lint_on_edit.py` is the fast half: `PostToolUse` on Edit/Write
runs `bash -n` + `shellcheck` on a `.sh`, or `ast.parse` on a `.py`, for that one
file. Non-blocking — it prints and gets out of the way.

Both are wired in `.claude/settings.json` (tracked, shared) rather than
`settings.local.json` (ignored, per-machine). Delete the entries there to turn
them off. Neither hook is part of what `install.sh` distributes — they are this
repo's own development harness.

### Why the test layers look redundant

Three of them exist because a *unit* test cannot catch a wrong assumption it
shares with the code. The hook read `tool_result` while Claude Code sends
`tool_response`, so tool output was never recorded — and 128 hook tests stayed
green, because they built their payloads with the same wrong key.

| Layer | File | Catches |
|-------|------|---------|
| unit | `hooks/test_*.py` | logic inside a function |
| contract | `hooks/test_contract.py` + `hooks/fixtures/*.json` | the payload shape Claude Code actually sends, and README drifting from real output |
| integration | `tests/test_ai_review.py` | the shipped script run for real, with a fake `claude` on `PATH` |
| integration | `tests/test_install.py` | `install.sh` executed end to end against a locally served copy of the repo |
| mutation | `tools/mutants.py` | guards that don't guard — a "fix" nobody can revert-detect |

`tools/mutants.py` holds one entry per fix this repo has made: the file, the
exact string, and what breaking it should look like. `./check.sh --mutants`
applies each one, runs only the test that should notice, and restores. An entry
that *survives* means that fix has no guard and will silently regress. When it
was first run, 5 of 8 fixes survived.

Writing a fix without registering a mutation is how a fix becomes a coincidence.

`.claude/skills/verify/SKILL.md` is the recipe for driving these by hand —
serving the repo to the installer, answering its prompts with a real pty,
shadowing the real `claude`. Read it before verifying a change manually.

`hooks/fixtures/*.json` is the single source of truth for the external payload
shape. Do not hand-build a hook payload in a test — load the fixture. If the
shape is wrong there, it is wrong in exactly one place, with a citation next to
it.

`tests/test_ai_review.py` strips any `PATH` entry containing a real `claude`
before running, so the suite can never make a billed API call.

## Requirements

- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) CLI
- `python3` (for the hooks and the installer's config merge)
- `curl` or `wget` (for the installer)

## Upgrading from an earlier install

Re-run `install.sh`. It cleans up what earlier versions left behind:

- the `dev-with-review` skill — retired; its external AI review is now the optional `independent-review` gate of `/wise-flow`, and the installer deletes `.claude/skills/dev-with-review`
- the separate `/wise-flow-*` skills — now phases of `/wise-flow`, deleted from `.claude/skills/`
- `hooks/wise_mode.py` — renamed to `mode_persistence.py`; the file and its stale `settings.local.json` entries are removed
- hook `timeout` values written as milliseconds (`5000`) — they mean seconds

Anything older than that is not managed here. If a previous install left
`.claude/skills/caveman`, `.claude/skills/cclog`, or `.claude/hooks/cclog-hook.sh`
behind, delete them manually — the installer no longer carries removal code for
them.

## Uninstall

```bash
curl -fsSL https://raw.githubusercontent.com/den-emon/wise-mode/main/uninstall.sh | bash
```

`uninstall.sh` removes the installed skills, hooks, and mode flags, and unwires
exactly the hook commands `install.sh` writes into `.claude/settings.local.json`
(full-string match — third-party hooks and your other settings are untouched).
It lists everything first and asks for confirmation; pass `--yes` (`bash -s --
--yes`) to skip the prompt in non-interactive runs. Data is never deleted:
`.claude/log/` and `.claude/flow/` are kept, with a cleanup command printed.

### Manual uninstall

```bash
# All components
rm -rf .claude/skills/{wise,wise-cont,wise-flow,attack-on-hacker,pr-self-review,swarm,terse-mode}
rm -f .claude/hooks/session_log.py .claude/hooks/mode_persistence.py .claude/hooks/flag_guard.py
rm -f .claude/.wise-mode .claude/.terse-mode
rm -rf .claude/flow          # wise-flow phase artifacts
rm -rf .claude/log           # session logs (masked, but still sensitive)

# Leftovers install.sh still removes for you
rm -rf .claude/skills/wise-flow-{source-recon,plan,implement-review,validate,security-gate,pr-gate,handoff}
rm -f .claude/hooks/wise_mode.py

# Older still — no longer handled by the installer, remove by hand
rm -rf .claude/skills/caveman .claude/skills/cclog
rm -f .claude/hooks/cclog-hook.sh
```

After removing the hooks, also remove the `hooks` section from `.claude/settings.local.json`.

## License

MIT
