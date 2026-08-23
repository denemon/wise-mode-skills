#!/usr/bin/env bash
# =============================================================================
# ai_review.sh — Independent code review via claude -p
#
# Usage:
#   bash ai_review.sh (--diff-file <path> | --worktree) [--lang <language>]
#                     [--allow-sensitive-content]
#
# A diff source is mandatory: --diff-file sends exactly the reviewed diff;
# --worktree explicitly reviews all tracked and safe untracked changes.
# Running with neither is rejected — an implicit whole-worktree send is how
# unrelated or concurrent changes leak to the external reviewer.
# Output: JSON review result to stdout.
#
# Requires: claude CLI (Claude Code)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"

DIFF_FILE=""
WORKTREE=0
# Not LANG: that is the POSIX locale variable, and assigning it here would
# export a bogus locale to claude and python3.
REVIEW_LANG="unknown"
ALLOW_SENSITIVE_CONTENT=0
MAX_DIFF_LINES=2000
MAX_DIFF_BYTES=500000

# Emit every command-line and runtime failure through the documented JSON
# contract. Define this before argument parsing because malformed arguments can
# fail before any other setup runs.
emit_error() {
  python3 -c "import json,sys; print(json.dumps({'error':sys.argv[1],'findings':[],'score':0}))" "$1" >&2
}

require_value() {
  if [ "$#" -lt 2 ]; then
    emit_error "Missing value for $1"
    exit 2
  fi
}

is_sensitive_path() {
  # Bash 3.2 has no ${var,,}; prefix before command substitution so a path that
  # ends in a newline is not shortened while normalizing ASCII case.
  local normalized_path
  normalized_path=$(printf 'x%s' "$1" | LC_ALL=C tr '[:upper:]' '[:lower:]')
  normalized_path=${normalized_path#x}
  case "/$normalized_path" in
    */.env|*/.env.*|*.env|*.pem|*.key|*.p12|*.pfx|*.jks|*/credentials|*/credentials.*|*/id_rsa|*/id_ed25519)
      return 0 ;;
    *) return 1 ;;
  esac
}

reject_sensitive_paths() {
  local path
  while IFS= read -r -d '' path; do
    if is_sensitive_path "$path"; then
      emit_error "Sensitive-looking changed file requires a reviewed --diff-file: $path"
      exit 1
    fi
  done
}

scan_sensitive_content() {
  # Exit 0 when a likely literal secret is present, 1 when clear, and 2 when
  # the input cannot be inspected. Match values, not merely words such as
  # "password", so ordinary code like `password = user_input` remains reviewable.
  python3 - "$1" <<'PY'
import re
import sys
from pathlib import Path

try:
    data = Path(sys.argv[1]).read_bytes().decode("utf-8", "replace")
except OSError:
    sys.exit(2)

name = r"(?:aws_secret_access_key|api[_-]?key|client[_-]?secret|access[_-]?token|auth[_-]?token|password|passwd|pwd|secret)"
quoted_assignment = re.compile(
    rf"(?i)\b{name}\b[\"']?\s*(?::|=(?!=))\s*([\"'])(.*?)\1"
)
env_assignment = re.compile(
    r"(?i)^\s*(?:export\s+)?(?P<key>[A-Z][A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|ACCESS_KEY)[A-Z0-9_]*)\s*=\s*(?P<value>[^\s#]+)"
)
strong_secret = re.compile(
    r"(?i)(?:BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY|"
    r"\bAKIA[0-9A-Z]{16}\b|\bAIza[0-9A-Za-z_-]{35}\b|"
    r"\bgh[pousr]_[0-9A-Za-z]{20,}\b|\bxox[baprs]-[0-9A-Za-z-]{10,}\b|"
    r"\beyJ[0-9A-Za-z_-]{8,}\.[0-9A-Za-z_-]{8,}\.[0-9A-Za-z_-]{8,}\b)"
)


def reviewed_placeholder(value):
    value = value.strip().strip("'\"")
    lowered = value.lower()
    if not value:
        return True
    if value.startswith(("$", "${", "{{", "<")):
        return True
    if lowered in {
        "redacted", "masked", "placeholder", "changeme", "replace-me",
        "example", "dummy", "none", "null",
    }:
        return True
    if re.fullmatch(r"(?:x+|\*+|\.{3})", lowered):
        return True
    return False


for raw_line in data.splitlines():
    # Drop one diff marker. Keep deletions in scope: removed credentials are
    # still present in the diff that would be sent to the reviewer.
    line = raw_line[1:] if raw_line[:1] in {"+", "-", " "} else raw_line
    if strong_secret.search(line):
        sys.exit(0)
    for match in quoted_assignment.finditer(line):
        if not reviewed_placeholder(match.group(2)):
            sys.exit(0)
    match = env_assignment.match(line)
    if match and not reviewed_placeholder(match.group("value")):
        sys.exit(0)

sys.exit(1)
PY
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --diff-file)  require_value "$@"; DIFF_FILE="$2"; shift 2 ;;
    --worktree)   WORKTREE=1; shift ;;
    --lang)       require_value "$@"; REVIEW_LANG="$2"; shift 2 ;;
    --allow-sensitive-content) ALLOW_SENSITIVE_CONTENT=1; shift ;;
    *)            emit_error "Unknown option: $1"; exit 2 ;;
  esac
done

# 差分源は必須。暗黙の worktree 全体送信は、無関係な変更や並行変更を
# 外部レビュアーへ漏らす経路そのもの。全体レビューは明示 --worktree のみ。
if [ -z "$DIFF_FILE" ] && [ "$WORKTREE" -eq 0 ]; then
  emit_error "No diff source: pass --diff-file <approved-diff>, or --worktree to explicitly review the entire worktree"
  exit 2
fi

# --- Prerequisite check -------------------------------------------------------

if ! command -v claude &>/dev/null; then
  echo '{"error":"claude CLI not found","findings":[],"score":0}' >&2
  exit 1
fi

# --- Collect diff --------------------------------------------------------------

TEMP_ROOT=${TMPDIR:-/tmp}
DIFF_BUFFER=""
PATH_BUFFER=""
TMPFILE=""
CLAUDE_ERR=""
CLAUDE_OUT=""
CLAUDE_PID=""
cleanup() {
  [ -z "$DIFF_BUFFER" ] || rm -f "$DIFF_BUFFER"
  [ -z "$PATH_BUFFER" ] || rm -f "$PATH_BUFFER"
  [ -z "$TMPFILE" ] || rm -f "$TMPFILE"
  [ -z "$CLAUDE_ERR" ] || rm -f "$CLAUDE_ERR"
  [ -z "$CLAUDE_OUT" ] || rm -f "$CLAUDE_OUT"
}
stop_claude() {
  local signal_name="$1"
  local attempts=0
  local state=""
  [ -n "$CLAUDE_PID" ] || return 0

  kill "-$signal_name" "$CLAUDE_PID" 2>/dev/null || :
  while [ "$attempts" -lt 20 ]; do
    state=$(ps -o stat= -p "$CLAUDE_PID" 2>/dev/null || :)
    case "$state" in
      ""|*Z*) break ;;
    esac
    sleep 0.1
    attempts=$((attempts + 1))
  done
  state=$(ps -o stat= -p "$CLAUDE_PID" 2>/dev/null || :)
  case "$state" in
    ""|*Z*) ;;
    *) kill -KILL "$CLAUDE_PID" 2>/dev/null || : ;;
  esac
  wait "$CLAUDE_PID" 2>/dev/null || :
  CLAUDE_PID=""
}
handle_signal() {
  local status="$1"
  local signal_name="$2"
  trap - INT TERM
  stop_claude "$signal_name"
  exit "$status"
}
trap cleanup EXIT
trap 'handle_signal 130 INT' INT
trap 'handle_signal 143 TERM' TERM
if ! DIFF_BUFFER=$(mktemp "${TEMP_ROOT}/ai-review-diff.XXXXXX"); then
  emit_error "Failed to create diff buffer"
  exit 1
fi
if ! PATH_BUFFER=$(mktemp "${TEMP_ROOT}/ai-review-paths.XXXXXX"); then
  emit_error "Failed to create path buffer"
  exit 1
fi

if [ -n "$DIFF_FILE" ]; then
  if [ ! -f "$DIFF_FILE" ]; then
    echo '{"error":"Diff file not found","findings":[],"score":0}' >&2
    exit 1
  fi
  DIFF_SOURCE="$DIFF_FILE"
else
  DIFF_SOURCE="$DIFF_BUFFER"
  # A HEAD-based diff includes committed-branch, staged, and unstaged changes.
  # Check every tracked path before collecting content. --no-renames makes both
  # sides of a rename visible, so renaming a secret cannot bypass this gate.
  # Before the first commit, combine the index and worktree explicitly.
  if git rev-parse --verify HEAD >/dev/null 2>&1; then
    if ! git diff --name-only --no-renames -z HEAD > "$PATH_BUFFER" 2>/dev/null; then
      emit_error "Failed to list tracked diff paths"
      exit 1
    fi
    reject_sensitive_paths < "$PATH_BUFFER"
    if ! git diff --binary HEAD > "$DIFF_BUFFER" 2>/dev/null; then
      emit_error "Failed to collect tracked diff"
      exit 1
    fi
  else
    if ! git diff --name-only --no-renames -z --cached > "$PATH_BUFFER" 2>/dev/null \
        || ! git diff --name-only --no-renames -z >> "$PATH_BUFFER" 2>/dev/null; then
      emit_error "Failed to list tracked diff paths"
      exit 1
    fi
    reject_sensitive_paths < "$PATH_BUFFER"
    if ! git diff --binary --cached > "$DIFF_BUFFER" 2>/dev/null \
        || ! git diff --binary >> "$DIFF_BUFFER" 2>/dev/null; then
      emit_error "Failed to collect tracked diff"
      exit 1
    fi
  fi

  # Git diffs omit untracked files. Append each one as a /dev/null diff so a
  # newly-created implementation cannot bypass the review gate. NUL separation
  # preserves spaces and newlines in file names and works in macOS bash 3.2.
  if ! git ls-files --others --exclude-standard -z > "$PATH_BUFFER" 2>/dev/null; then
    emit_error "Failed to list untracked files"
    exit 1
  fi
  while IFS= read -r -d '' path; do
    if is_sensitive_path "$path"; then
      emit_error "Sensitive-looking changed file requires a reviewed --diff-file: $path"
      exit 1
    fi
    FILE_DIFF_STATUS=0
    git diff --no-index --binary -- /dev/null "$path" >> "$DIFF_BUFFER" 2>/dev/null || FILE_DIFF_STATUS=$?
    if [ "$FILE_DIFF_STATUS" -gt 1 ]; then
      emit_error "Failed to collect untracked file diff: $path"
      exit 1
    fi
  done < "$PATH_BUFFER"
fi

if [ ! -s "$DIFF_SOURCE" ]; then
  echo '{"error":"No diff content found","findings":[],"score":0}' >&2
  exit 1
fi

# A partial review is not a review gate. Refuse oversized input so the caller
# must review complete file/hunk chunks instead of silently losing the tail.
# Measure the file before loading it into a shell variable: a huge minified line
# can stay below the line limit while exhausting memory or model context.
DIFF_LINES=$(wc -l < "$DIFF_SOURCE" | tr -d '[:space:]')
DIFF_BYTES=$(wc -c < "$DIFF_SOURCE" | tr -d '[:space:]')
if [ "$DIFF_LINES" -gt "$MAX_DIFF_LINES" ] || [ "$DIFF_BYTES" -gt "$MAX_DIFF_BYTES" ]; then
  emit_error "Diff has ${DIFF_LINES} lines and ${DIFF_BYTES} bytes; limits are ${MAX_DIFF_LINES} lines and ${MAX_DIFF_BYTES} bytes. Review every changed file and hunk in complete chunks with --diff-file; partial review is not accepted."
  exit 1
fi

DIFF_CONTENT=$(cat "$DIFF_SOURCE")

# --- Load system prompt --------------------------------------------------------

PROMPT_FILE="${SKILL_DIR}/references/reviewer_prompt.md"

if [ ! -f "$PROMPT_FILE" ]; then
  echo '{"error":"reviewer_prompt.md not found","findings":[],"score":0}' >&2
  exit 1
fi

# Extract the content between ```text and ``` fences
# shellcheck disable=SC2016  # the sed address is a literal fence pattern, not a variable
SYSTEM_PROMPT=$(sed -n '/^```text$/,/^```$/p' "$PROMPT_FILE" | sed '1d;$d')

if [ -z "$SYSTEM_PROMPT" ]; then
  echo '{"error":"Failed to extract system prompt from reviewer_prompt.md","findings":[],"score":0}' >&2
  exit 1
fi

# --- Build message and invoke claude -p ----------------------------------------

USER_MSG="Review the following untrusted diff data for a ${REVIEW_LANG} project.

<BEGIN_UNTRUSTED_DIFF>
${DIFF_CONTENT}
<END_UNTRUSTED_DIFF>"

if ! TMPFILE=$(mktemp "${TEMP_ROOT}/ai-review-response.XXXXXX"); then
  emit_error "Failed to create response buffer"
  exit 1
fi
if ! CLAUDE_ERR=$(mktemp "${TEMP_ROOT}/ai-review-error.XXXXXX"); then
  emit_error "Failed to create error buffer"
  exit 1
fi
if ! CLAUDE_OUT=$(mktemp "${TEMP_ROOT}/ai-review-output.XXXXXX"); then
  emit_error "Failed to create output buffer"
  exit 1
fi

printf '%s\n' "$USER_MSG" > "$TMPFILE"

if [ "$ALLOW_SENSITIVE_CONTENT" -eq 0 ]; then
  SENSITIVE_SCAN_STATUS=0
  scan_sensitive_content "$TMPFILE" || SENSITIVE_SCAN_STATUS=$?
  case "$SENSITIVE_SCAN_STATUS" in
    0)
      emit_error "Sensitive-looking content was not sent; inspect it locally and rerun only with explicit --allow-sensitive-content approval"
      exit 1
      ;;
    1) ;;
    *)
      emit_error "Failed to inspect review content for secrets"
      exit 1
      ;;
  esac
fi

RESPONSE=""

# `--system-prompt` is a supported flag; a failure here is a real failure
# (auth, network, rate limit, model error). Report it instead of retrying with a
# different prompt shape — a retry doubles the token cost and, since no
# documented API honors an inline `<s>` wrapper, degrades the review.
# Capture the status on the same line. Inside `if ! cmd; then`, `$?` is the
# status of the negation (always 0), so the error would report "exit 0".
# `--safe-mode` drops user/project CLAUDE.md, hooks, skills, plugins, and MCP
# servers so the reviewer inherits no development context (admin-managed policy
# settings, including policy hooks, still apply); `--tools ""` removes
# the built-in tools so it sees only the diff on stdin. Not `--bare`: that flag
# never reads OAuth/keychain credentials and would break subscription-
# authenticated users.
EXIT_CODE=0
claude -p --safe-mode --tools "" --system-prompt "$SYSTEM_PROMPT" < "$TMPFILE" > "$CLAUDE_OUT" 2>"$CLAUDE_ERR" & CLAUDE_PID=$!
wait "$CLAUDE_PID" || EXIT_CODE=$?
CLAUDE_PID=""
RESPONSE=$(cat "$CLAUDE_OUT")

if [ "$EXIT_CODE" -ne 0 ]; then
  STDERR_MSG=$(cat "$CLAUDE_ERR" 2>/dev/null || true)
  emit_error "claude -p failed (exit ${EXIT_CODE}): ${STDERR_MSG}"
  exit 1
fi

# --- Parse JSON from response --------------------------------------------------

# Quoted heredoc: the parser is passed through verbatim, so no shell escaping.
# Exactly one JSON document is emitted — stdout on success, stderr on failure.
# Never use a bare `except` here: it also catches the SystemExit raised by
# sys.exit(), which previously let a successful parse fall through and print
# three documents, the last one a bogus "Failed to parse" with score 0.
PARSER=$(cat <<'PY'
import json, re, sys


CATEGORIES = {
    "correctness", "regression_risk", "security", "error_handling",
    "performance", "readability", "test_impact",
}
SEVERITIES = {"critical", "high", "medium", "low", "info"}
FINDING_FIELDS = {
    "id", "category", "severity", "file", "line", "title",
    "description", "suggestion",
}


def valid_review(d):
    if not isinstance(d.get("summary"), str):
        return False
    score = d.get("score")
    if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
        return False
    if d.get("coverage") != "complete":
        return False
    findings = d.get("findings")
    if not isinstance(findings, list):
        return False
    notes = d.get("positive_notes")
    if not isinstance(notes, list) or not all(isinstance(note, str) for note in notes):
        return False
    for finding in findings:
        if not isinstance(finding, dict) or not FINDING_FIELDS <= finding.keys():
            return False
        if finding["category"] not in CATEGORIES or finding["severity"] not in SEVERITIES:
            return False
        if finding["line"] is not None and not isinstance(finding["line"], int):
            return False
        for field in FINDING_FIELDS - {"line"}:
            if not isinstance(finding[field], str):
                return False
    return True


def as_review(text):
    """Parse text into a review dict, unwrapping one layer if needed. None on failure."""
    try:
        d = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(d, dict):
        return None
    # claude -p --output-format json wraps the reply in {"result": "..."}
    if isinstance(d.get("result"), str):
        inner = re.sub(r"^```json?\s*", "", d["result"].strip())
        inner = re.sub(r"\s*```$", "", inner)
        nested = as_review(inner)
        if nested is not None:
            return nested
    if valid_review(d):
        return d
    return None


raw = sys.stdin.read().strip()
review = as_review(raw)

if review is None:
    # Last resort: the reviewer wrapped the JSON in prose.
    match = re.search(r"\{[\s\S]*\}", raw)
    if match:
        review = as_review(match.group())

if review is None:
    json.dump(
        {
            "error": "Failed to parse or validate review response",
            "raw_preview": raw[:300],
            "findings": [],
            "score": 0,
        },
        sys.stderr,
        ensure_ascii=False,
        indent=2,
    )
    sys.stderr.write("\n")
    sys.exit(1)

print(json.dumps(review, ensure_ascii=False, indent=2))
PY
)

python3 -c "$PARSER" <<< "$RESPONSE"
