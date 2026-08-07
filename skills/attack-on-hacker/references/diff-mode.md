# Diff Mode (PR / branch review)

If `Task: $ARGUMENTS` indicates a diff or PR review (e.g. "Review PR #123", "Audit this branch", or a diff is provided directly), switch to **Diff Mode**. Every phase below is then scoped to the changed code and its security-critical neighborhood, not the whole repository. Whole-repo review and Diff Mode never run simultaneously — pick one in Phase 1.

### Collect the diff

- Against a base branch: `git diff <base>...HEAD` (three-dot — diff against the merge base, not the tip)
- Local uncommitted changes: `git diff` / `git diff --staged`
- GitHub PR (if `gh` is authorized in the environment): `gh pr diff <pr-number>`

If the diff exceeds ~2000 lines, ask the requester to narrow scope or focus on the highest-risk files (auth, crypto, deserialization, parsing, file handling, IaC, CI configs). State the truncation explicitly in the report.

### Phase adjustments under Diff Mode

- **Phase 1 (Scope)** — list only the entry points / trust boundaries the diff touches or could reach. Re-check the attacker profile: a small change can move the code into a new trust zone (e.g. an internal-only handler exposed via a new public route).
- **Phase 1.5 (Quick-Wins)** — restrict the Sweep to changed files. Additionally run:
  - `git diff <base>...HEAD -- '*.env*' '*.pem' '*.key' '*.p12'` — accidentally added secrets.
  - `git diff <base>...HEAD -- '.github/workflows/' '.gitlab-ci.yml' '.circleci/'` — a single CI tweak can introduce full repo-secret exfiltration.
  - `git diff <base>...HEAD -- 'Dockerfile' '*.tf' '*.yaml' '*.yml'` — IaC / container regressions.
- **Phase 2 (Attacker Map)** — only build flows for sources the diff introduces or sinks the diff modifies.
- **Phase 3 (Hunt)** — focus on the high-risk classes that match what the diff touches. Skip hunt categories the diff cannot affect.

### Regression hunt (Diff Mode exclusive)

Diff reviews surface a class of bugs that whole-repo reviews miss: **silently weakened security controls**. Hunt for deletions or weakenings of existing protections:

- Removed auth gates: `@login_required`, `@PreAuthorize`, `requires_auth`, `IsAuthenticated`, `Authorize`, `authenticate(...)` middleware
- Removed CSRF protection: `@csrf_exempt` added, `csrf_token` removed, `SameSite` weakened
- Removed validation: schema validators dropped, allowlist shortened, `assert` removed on non-debug paths
- Loosened CORS / CSP: new `Access-Control-Allow-Origin: *`, CSP `unsafe-inline` / `unsafe-eval` added
- Weakened crypto: `bcrypt`/`argon2` → `md5`/`sha1`, IV reuse, CSPRNG → PRNG, hard-coded key
- Removed rate-limit / lockout decorators
- New `*` / `**` wildcards in IAM, security groups, network policies
- New `permitAll()` / `AllowAll` / permissive policies
- Loosened transport: `https` → `http`, `verify=False`, `InsecureSkipVerify: true`, disabled cert verification

Useful starting filter (read context, not just the regex hits):

```bash
git diff <base>...HEAD | rg -i "^-.*(@login_required|@csrf_exempt|@PreAuthorize|verify=False|InsecureSkipVerify|permitAll|AllowAll|bcrypt|argon2|csrf|cors|TLS|HTTPS)"
```

### New attack surface introduced by the diff

For every additive change, ask:

- New routes / handlers / endpoints — are any of them unauthenticated?
- New external callers / fetchers — SSRF surface, retry / timeout / host-allowlist policy?
- New file I/O — path traversal, symlink-follow, archive extraction?
- New deserializers / parsers — what input shape do they trust?
- New dependencies — `git diff <base>...HEAD -- 'package.json' 'package-lock.json' 'pyproject.toml' 'poetry.lock' 'Cargo.toml' 'go.mod'` then audit only the **newly added** packages (maintainer, downloads, typosquat similarity).

### Diff-Mode finding classification

In Diff Mode, prefix every finding title with one of:

- `[regression]` — the diff weakened or removed an existing security control.
- `[new-surface]` — the diff introduced a new vulnerable code path.
- `[pre-existing]` — the issue is in unchanged code adjacent to the diff. Note it once, then move on. Out of scope unless the diff makes it newly reachable — if it does, reclassify as `[new-surface]`.
