# Report Format

### Report Structure

```markdown
## Top 3 Fix-First
Ordered triage list. Exactly 0–3 entries pulled from `Findings`. If `Findings` is empty, write "No fix-first items.".
1. [Severity] <Finding title> — <one-line reason this is highest priority>
2. ...
3. ...

## Threat Model
- Attacker profile(s): ...
- Trust zones in scope: ...
- Existing mitigations factored out: ...
- Out of scope: ...

## Findings

### [Severity] Title
- Location: path/to/file:line
- CWE: CWE-XXX — short name (e.g. CWE-89 SQL Injection)
- CVSS (estimate): CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H — score X.X
- Attacker profile: <anon-external | authenticated-low-priv | cross-tenant | admin-or-insider | compromised-dependency>
- Preconditions: <default-config | requires flag X | requires victim action | requires stored taint from path Y>
- Source → Sink: <input origin> → <vulnerable sink>
- Sanitizers observed: <none | only on path Y, not on this one>
- Evidence: <confirmed-by-poc | confirmed-by-read | inferred-pattern>
- Impact: what can be read, changed, executed, bypassed, or disrupted
- Fix: concrete implementation guidance that fits the repo
- Verification: test, command, or review step to confirm the fix

> **CWE / CVSS conventions**
> - **CWE** is mandatory. Pick the most specific identifier from <https://cwe.mitre.org>. If multiple apply, list the primary one and mention secondaries in `Impact`.
> - **CVSS** is an estimate, not a substitute for the Severity Rubric above. Use the standard v3.1 vector string. Environmental and temporal metrics are usually unknown — leave them out. If the rubric and the CVSS score disagree, the **rubric wins** for triage; record the disagreement in `Open Questions`.

## Open Questions / Assumptions

## Reviewed With No Finding
- List entry points / files / classes that were inspected and produced no finding, so the negative result is auditable.

## Residual Risk / Next Checks
```

Use only the severity labels defined in the rubric above: Critical, High, Medium, Low, Info.

If there are no findings, write:

```markdown
## Top 3 Fix-First
No fix-first items.

## Threat Model
- Attacker profile(s): ...
- Trust zones in scope: ...
- Existing mitigations factored out: ...
- Out of scope: ...

## Findings

No confirmed vulnerabilities found in the reviewed scope.

## Reviewed With No Finding
- <enumerate entry points, files, and classes inspected so the negative result is auditable>

## Review Limits

- <tests not run, config missing, dependency audit skipped, or other limits>
```

### Optional: Structured JSON Output

If the caller asks for JSON (e.g. "report as JSON", "for tooling consumption", or `$ARGUMENTS` contains `--format=json`), emit a single JSON object instead of (or in addition to) the markdown report. The Markdown report remains the default.

```json
{
  "threat_model": {
    "attacker_profiles": ["anon-external"],
    "trust_zones": ["public-internet -> web-app -> db"],
    "existing_mitigations": ["WAF blocks well-known signatures"],
    "out_of_scope": ["third-party SaaS identity provider"]
  },
  "top_fixes": [
    {"id": "F001", "title": "Unauth SQL injection in /api/search", "severity": "Critical", "reason": "anon-external, default config, full DB read"}
  ],
  "findings": [
    {
      "id": "F001",
      "title": "Unauth SQL injection in /api/search",
      "severity": "Critical",
      "cwe": "CWE-89",
      "cvss": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
      "cvss_score": 9.8,
      "location": "src/api/search.py:42",
      "attacker_profile": "anon-external",
      "preconditions": "default-config",
      "source": "query string param `q`",
      "sink": "raw SQL string concatenation",
      "sanitizers_observed": "none",
      "evidence": "confirmed-by-poc",
      "evidence_detail": "curl 'https://host/api/search?q=...' returned full row dump",
      "impact": "Full read of `users` table including hashes.",
      "fix": "Switch to parameterized query via `cursor.execute(sql, params)`; reject `q` longer than N chars.",
      "verification": "pytest tests/test_search.py::test_quote_injection",
      "diff_classification": "new-surface"
    }
  ],
  "open_questions": [],
  "reviewed_no_finding": ["src/api/health.py — no user-controlled input"],
  "residual_risk": [],
  "review_limits": ["dependency audit skipped (no lockfile)"]
}
```

Schema rules:

- `severity` ∈ `{"Critical", "High", "Medium", "Low", "Info"}`
- `evidence` ∈ `{"confirmed-by-poc", "confirmed-by-read", "inferred-pattern"}`
- `attacker_profile` ∈ `{"anon-external", "authenticated-low-priv", "cross-tenant", "admin-or-insider", "compromised-dependency"}`
- `diff_classification` ∈ `{"regression", "new-surface", "pre-existing"}` — present only in Diff Mode
- `top_fixes` has 0–3 entries, each referencing a `findings[].id`. Empty only when `findings` is empty.
- All other fields are required. Use `null` rather than omitting a field when a value is genuinely unknown.
