# Quick-Wins Sweep — concrete checks

### Secrets in code and history

- Code: `rg -i "password|secret|api[_-]?key|token|aws_access_key|BEGIN (RSA|EC|OPENSSH|PRIVATE) KEY"`
- Untracked candidates: `git ls-files --others --exclude-standard | rg -i "\.env|\.pem$|\.key$|credentials"`
- Git history: `git log --all -p -- '*.env*' '*.pem' '*.key' 2>/dev/null | rg -i "BEGIN (RSA|EC|OPENSSH|PRIVATE) KEY|aws_secret|api_key"`
- Secrets removed from HEAD are still leaked via history — recommend rotation, not just deletion.
- Use `trufflehog`, `gitleaks`, or `detect-secrets` if available in the environment.

### CI / CD pwn-request patterns

- `.github/workflows/*.yml`:
  - `pull_request_target` combined with `actions/checkout` of the PR head — fork PRs can exfiltrate repo secrets.
  - `${{ github.event.* }}`, `${{ github.head_ref }}`, or other untrusted context interpolated directly into a `run:` block — shell injection.
  - Self-hosted runners on public repositories.
  - Missing `permissions:` declaration (defaults to read-write on classic tokens).
- GitLab CI / CircleCI / Buildkite: scan for the same context-injection and over-privileged-runner patterns.

### Container build hygiene

- `Dockerfile` / `Containerfile`:
  - No `USER` directive, or `USER root` at runtime.
  - Secrets passed via `ARG` or `ENV` (they remain in image history).
  - `FROM <image>:latest` with no tag pin, or no digest pin for production images.
  - `ADD <url>` with no checksum verification.
  - `COPY` of the entire build context including `.git/` or `.env*`.

### Infrastructure as Code defaults

- Terraform / CloudFormation / Kubernetes manifests:
  - S3 / GCS buckets without explicit private ACL or `BlockPublicAccess`.
  - Security groups / firewalls allowing `0.0.0.0/0` on management ports (22, 3389, 5432, 6379, etc.).
  - IAM policies with `Action: "*"` or `Resource: "*"`.
  - K8s pods without `securityContext`, running as root, or `hostNetwork: true` / `privileged: true`.
  - Managed databases / object stores with encryption-at-rest disabled.

### Dependency surface

- Run the project's audit tool: `npm audit`, `pnpm audit`, `yarn audit`, `pip-audit`, `bundle audit`, `cargo audit`, `gosec`.
- Lockfile drift: lockfile missing, out of sync with the manifest, or not committed.
- Unpinned VCS dependencies (`git+https://...`, `github:org/repo` without commit pin).
- Newly added third-party packages: review maintainer, download stats, and typosquat similarity to popular packages.
