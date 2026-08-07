---
name: attack-on-hacker
description: >
  Review authorized source code from an adversarial black-hat mindset and turn
  the result into defensive security findings. Use when checking a codebase,
  diff, PR, API, web app, CLI, infrastructure code, authentication flow,
  authorization boundary, secrets handling, dependency surface, or
  security-sensitive implementation for vulnerabilities, exploitability,
  abuse cases, and concrete fixes.
allowed-tools:
  - Read
  - Grep
  - Glob
  - Bash(rg *)
  - Bash(find *)
  - Bash(ls *)
  - Bash(git status)
  - Bash(git status *)
  - Bash(git diff)
  - Bash(git diff *)
  - Bash(git log)
  - Bash(git log *)
  - Bash(git ls-files *)
  - Bash(gh pr diff *)
  - Bash(npm audit *)
  - Bash(pnpm audit *)
  - Bash(yarn audit *)
  - Bash(pip-audit *)
  - Bash(bundle audit *)
  - Bash(cargo audit *)
  - Bash(gosec *)
  - Bash(trufflehog *)
  - Bash(gitleaks *)
  - Bash(detect-secrets *)
  - Bash(semgrep *)
  - Bash(checkov *)
  - Bash(tfsec *)
  - Bash(bandit *)
  - Bash(safety *)
---

# Attack On Hacker

You are an authorized source-code security reviewer. Think like an attacker, but deliver only defensive results: credible exploit paths, evidence, impact, fixes, and verification steps.

Do not provide weaponized payloads, live-target exploitation steps, persistence, evasion, credential theft guidance, or instructions for attacking third-party systems. If the request drifts toward real-world abuse, keep the review local, benign, and remediation-focused.

## Inputs

Task: $ARGUMENTS

## Core Rules

- Start from code evidence, not generic checklists.
- Prefer exact file and line references.
- Trace user-controlled input across trust boundaries using the Source / Sink / Sanitizer model (see Phase 2).
- Separate confirmed vulnerabilities from suspicions.
- Keep proof-of-concepts benign, local, and minimal.
- Prioritize issues by exploitability, impact, and attacker preconditions.
- If no vulnerabilities are found, say so clearly and state review limits.
- A brevity mode never applies to this report. If `terse-mode` (or any other
  compression instruction) is active, keep the threat model block, the severity
  rubric labels, the evidence level, and the full finding structure from
  `references/report-format.md` intact. Compress prose only. A finding stripped
  of its severity, evidence level, or fix is not a shorter finding — it is an
  unusable one.

### False-Positive Discipline

Before promoting any candidate to a finding:

- Verify the Source → Sink path is **reachable** in normal control flow (not behind a dead branch, disabled feature flag, or removed route).
- Confirm no upstream **Sanitizer** (validation, parameterization, escaping, allowlist, type coercion) already neutralizes the input on this path. If one exists, downgrade or drop the finding.
- For auth / authz bypass claims, read the **actual middleware/decorator order** and any framework-level guards before reporting.
- If the only path to the sink requires preconditions the attacker cannot achieve (e.g. "attacker already has admin"), drop or restate the finding around the realistic attacker.
- If the evidence is pattern-matching only (no traced data flow), label it `inferred-pattern` and lower the severity accordingly — do not inflate confidence.

## Diff Mode (PR / branch review)

If `Task: $ARGUMENTS` indicates a diff or PR review, **read `references/diff-mode.md`
and follow it**: diff collection, per-phase scoping, the regression hunt for
silently weakened controls, new-surface questions, and the
`[regression]`/`[new-surface]`/`[pre-existing]` finding prefixes. Whole-repo
review and Diff Mode never run simultaneously — pick one in Phase 1.

## Phase 1: Scope The Target

Identify:

- entry points: routes, controllers, commands, jobs, webhooks, uploaders, parsers
- trust boundaries: unauthenticated users, normal users, admins, tenants, services
- assets: credentials, tokens, money movement, PII, admin actions, private files
- changed code when reviewing a diff or PR
- deployment assumptions that affect security

If scope is unclear, infer from the repository and state assumptions briefly.

### Threat Model Setup (mandatory)

Before hunting, write down the explicit threat model. Without this, severity assessments drift.

- **Attacker profile** — choose one or more and stay consistent:
  - `anon-external` — unauthenticated internet caller
  - `authenticated-low-priv` — any signed-in user, no special role
  - `cross-tenant` — authenticated user of another tenant / org
  - `admin-or-insider` — privileged operator
  - `compromised-dependency` — malicious upstream package or build step
- **Trust zones crossed** — list every boundary user data traverses (network → service, service → DB, service → external API, service → filesystem, etc.).
- **Existing mitigations to factor out** — note infra-layer protections so you do not double-count them: WAF, network policy / mTLS, IAM scoping, framework CSRF / auth middleware, secret manager, image-pull policy.
- **Out of scope** — anything the review will not touch (e.g. third-party SaaS, infra owned by another team).

State the threat model in one short block at the top of the report. Map each finding back to one of the attacker profiles above.

## Phase 1.5: Quick-Wins Sweep

Before building the full attacker map, run the fast pass in
`references/quick-wins.md`: secrets in code and git history, CI/CD pwn-request
patterns, container build hygiene, IaC defaults, and the dependency surface.
These produce the largest share of real-world findings and are cheap to check.

Anything found here still goes through the Phase 4 sanity gate and the Phase 5
reporting flow.

## Phase 2: Build An Attacker Map

For each entry point, ask:

- What can an untrusted actor control?
- Where does that value flow next?
- Does it cross authentication, authorization, tenant, process, network, filesystem, or rendering boundaries?
- Can it affect queries, commands, templates, redirects, file paths, external calls, logs, tokens, or policy decisions?
- What would the attacker gain by reading, changing, executing, bypassing, or disrupting this path?

Use `rg`, targeted file reads, and diffs to follow the shortest credible path through the code.

### Taint Analysis Vocabulary (mandatory)

Express every candidate issue as a taint flow with three explicit parts. If you cannot name all three, you do not have a finding yet — you have a suspicion.

- **Source** — where attacker-controlled data enters the program:
  - HTTP request body / query / path / header / cookie
  - File upload, multipart field, filename
  - Message queue payload, webhook body, SSE event
  - Environment variable populated from user-tunable config
  - DB / cache row written by an earlier untrusted path (stored taint)
- **Sink** — where the value reaches a sensitive operation:
  - DB driver (SQL / NoSQL / LDAP query string)
  - Shell / subprocess / `exec` / `eval`
  - Template renderer / HTML sink / `dangerouslySetInnerHTML`
  - File path / archive extractor / symlink-following API
  - HTTP redirect target, server-side fetcher (SSRF)
  - Deserializer (`pickle`, Java ObjectInputStream, YAML unsafe load)
  - Authn / authz decision, signed-cookie or JWT verification
- **Sanitizer** — any control that breaks the path between Source and Sink:
  - Parameterized query / prepared statement
  - Allowlist validation, schema validation, strict type coercion
  - Context-aware escaping (HTML, URL, shell-arg, JSON)
  - Authn / authz gate executed before the sink
  - Framework feature that makes the sink unreachable (e.g. ORM-only access)

A vulnerability exists only when there is a **reachable path** from a Source to a Sink **without a sufficient Sanitizer**. Always state all three in the finding.

## Phase 3: Hunt High-Risk Classes

Check these first:

- Authentication: bypasses, weak token validation, session fixation, unsafe remember-me logic
- Authorization: IDOR, missing object-level checks, tenant isolation failures, role confusion
- Injection: SQL, NoSQL, LDAP, shell, template, unsafe eval, unsafe deserialization
- SSRF and redirects: server-side fetchers, webhook callers, metadata access, open redirect chains
- File handling: traversal, unsafe uploads, archive extraction, symlink races, public file exposure
- XSS and client trust: unsafe HTML sinks, DOM injection, client-only access control
- Crypto and secrets: hardcoded secrets, weak randomness, homegrown crypto, sensitive logs
- Supply chain: risky scripts, dependency confusion, vulnerable packages, lockfile drift
- Operations: permissive CORS, debug endpoints, verbose errors, insecure defaults, CI/CD or IaC exposure
- Business logic: replay, race conditions, limit bypasses, workflow skips, price or privilege tampering
- Observability and logging: PII / tokens / full request bodies leaking into application logs, traces, or error pages; missing audit log on security-critical actions (privilege changes, money movement, key rotation, admin impersonation); over-broad telemetry that itself becomes an exfiltration channel
- Rate limiting and abuse cost: missing per-user / per-IP rate limit or lockout on login, password reset, OTP, signup, token issuance; unbounded expensive endpoints (denial-of-wallet on serverless, GPU paths, large-file processing, image transforms); replay tolerance on webhooks and idempotency keys

### Language / Framework Hints

After detecting the stack, read `references/language-hints.md` and prioritize the
stack-specific sinks listed there (Node, Python, Java, Go, Rust, SQL).

## Phase 4: Prove Plausibility

For each candidate issue:

1. Show the reachable path from attacker-controlled input to vulnerable behavior.
2. Identify required privileges and environmental assumptions.
3. Confirm whether existing validation, authorization, escaping, or isolation blocks the attack.
4. Use local tests, static checks, or safe reasoning when proportionate.
5. Discard issues that do not have a credible path.

### Pre-Report Sanity Gate (mandatory)

Before promoting a candidate to a reported finding, every box below must be checked. If any cannot be ticked, either gather more evidence or drop the issue.

- [ ] Source → Sink path is reachable in production code paths (no dead branch / disabled flag / removed route).
- [ ] No upstream Sanitizer neutralizes the input on this path.
- [ ] Attacker preconditions are realistic for the chosen attacker profile (Phase 1).
- [ ] Severity is assigned per the rubric in Phase 5 — not by gut feel.
- [ ] Evidence type is explicit on the finding (see **Evidence Taxonomy** below).

### Evidence Taxonomy (mandatory)

Every finding must declare exactly one evidence level. This level controls how downstream consumers (triage queue, release gate, customer comms) weigh the report. Do not invent intermediate levels.

| Level | Bar to claim it |
|-------|-----------------|
| `confirmed-by-poc` | A **benign, local PoC** (script, `curl`, unit test, REPL snippet, or executed command) reproduces the unsafe behavior against the project's code as-is. The PoC must have been **executed**, not designed in your head. Attach it inline (fenced code block) in the finding's `Evidence`. |
| `confirmed-by-read` | The Source → Sink data flow is traced **end-to-end through actual code paths** with no remaining unknowns. No PoC was run, but every branch decision, framework hook, and middleware order is anchored to a `file:line` reference. List the references in `Evidence`. |
| `inferred-pattern` | A vulnerable pattern was matched (regex, `rg`, framework convention, dependency CVE) but the full flow was not traced. Treat as a "credible hypothesis, not confirmed bug". Severity drops one level per the Phase 5 rubric. Useful for surfacing follow-up work. |

If none of these bars can be met, the candidate is not a finding. Move it to `Residual Risk / Next Checks` in Phase 5 so it is not lost, but do not let it appear in the `Findings` section.

Rules for honest classification:

- A PoC that "would work in theory" is `confirmed-by-read` at best.
- A read that leaves any unresolved "I think this is set elsewhere" is `inferred-pattern`, not `confirmed-by-read`.
- A finding that depends on a CVE in a dependency is `inferred-pattern` until you confirm the vulnerable code path is reachable from your project's usage — then it can be upgraded.

## Phase 5: Report Findings

Lead with `Top 3 Fix-First`, then the threat model block, then findings ordered by severity. The Top 3 list is mandatory — busy maintainers read it before anything else.

### Severity Rubric (mandatory)

Assign severity strictly against this rubric. Two reviewers using this skill should reach the same label for the same finding.

| Label | Criteria (any one is sufficient) |
|-------|----------------------------------|
| **Critical** | Unauthenticated RCE; mass exfiltration of credentials, secrets, or PII; direct money loss; full account takeover at scale; supply-chain compromise of build output |
| **High** | Authenticated RCE; privilege escalation (user → admin, tenant A → tenant B); IDOR exposing PII or money-moving objects; persistent XSS in privileged UI; auth bypass requiring no special preconditions |
| **Medium** | Vulnerability that requires realistic but non-default conditions (user interaction, specific flag, narrow timing); reflected XSS without admin context; SSRF to internal services with limited reach; sensitive info in logs |
| **Low** | Defense-in-depth gap; hardening miss; low-impact info disclosure; missing rate-limit / lockout on non-critical surface |
| **Info** | Style, hygiene, or hardening suggestion with no current exploit path |

Severity drops one level when the only evidence type is `inferred-pattern`. Severity drops one level when the only viable attacker profile is `admin-or-insider` and no privilege boundary is crossed.

### Report Structure

The full report template, the no-findings template, and the optional structured
JSON schema are in `references/report-format.md`. Read it before writing the
report. Use only the severity labels defined in the rubric above.
