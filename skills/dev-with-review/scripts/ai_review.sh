#!/usr/bin/env bash
# =============================================================================
# ai_review.sh — Independent code review via claude -p
#
# Usage:
#   bash ai_review.sh [--diff-file <path>] [--context "<summary>"] [--lang <language>]
#
# If --diff-file is not provided, runs `git diff` in the current directory.
# Output: JSON review result to stdout.
#
# Requires: claude CLI (Claude Code)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_DIR="$(dirname "$SCRIPT_DIR")"

DIFF_FILE=""
CONTEXT="No additional context."
# Not LANG: that is the POSIX locale variable, and assigning it here would
# export a bogus locale to claude and python3.
REVIEW_LANG="unknown"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --diff-file)  DIFF_FILE="$2"; shift 2 ;;
    --context)    CONTEXT="$2"; shift 2 ;;
    --lang)       REVIEW_LANG="$2"; shift 2 ;;
    *)            shift ;;
  esac
done

# --- Prerequisite check -------------------------------------------------------

if ! command -v claude &>/dev/null; then
  echo '{"error":"claude CLI not found","findings":[],"score":0}' >&2
  exit 1
fi

# --- Collect diff --------------------------------------------------------------

if [ -n "$DIFF_FILE" ] && [ -f "$DIFF_FILE" ]; then
  DIFF_CONTENT=$(cat "$DIFF_FILE")
else
  # `git diff HEAD` first: plain `git diff` is empty once the change is staged,
  # which is exactly when a pre-commit review gets run. The fallback is for a
  # repository with no commit yet, where HEAD does not resolve.
  DIFF_CONTENT=$(git diff HEAD 2>/dev/null || git diff 2>/dev/null || echo "")
fi

if [ -z "$DIFF_CONTENT" ]; then
  echo '{"error":"No diff content found","findings":[],"score":0}' >&2
  exit 1
fi

# Truncate very large diffs to stay within context limits
DIFF_LINES=$(echo "$DIFF_CONTENT" | wc -l)
if [ "$DIFF_LINES" -gt 2000 ]; then
  DIFF_CONTENT=$(echo "$DIFF_CONTENT" | head -2000)
  DIFF_CONTENT="${DIFF_CONTENT}

... (truncated: ${DIFF_LINES} total lines. Review focused on first 2000 lines.)"
fi

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

USER_MSG="Review the following diff for a ${REVIEW_LANG} project.

Context: ${CONTEXT}

\`\`\`diff
${DIFF_CONTENT}
\`\`\`"

TMPFILE=$(mktemp /tmp/ai-review-XXXXXX.txt)
CLAUDE_ERR=$(mktemp /tmp/ai-review-err-XXXXXX.txt)
trap 'rm -f "$TMPFILE" "$CLAUDE_ERR"' EXIT INT TERM

echo "$USER_MSG" > "$TMPFILE"

RESPONSE=""

# Helper: emit a JSON error to stderr using python3 to safely escape strings
emit_error() {
  python3 -c "import json,sys; print(json.dumps({'error':sys.argv[1],'findings':[],'score':0}))" "$1" >&2
}

# `--system-prompt` is a supported flag; a failure here is a real failure
# (auth, network, rate limit, model error). Report it instead of retrying with a
# different prompt shape — a retry doubles the token cost and, since no
# documented API honors an inline `<s>` wrapper, degrades the review.
# Capture the status on the same line. Inside `if ! cmd; then`, `$?` is the
# status of the negation (always 0), so the error would report "exit 0".
EXIT_CODE=0
RESPONSE=$(claude -p --system-prompt "$SYSTEM_PROMPT" < "$TMPFILE" 2>"$CLAUDE_ERR") || EXIT_CODE=$?

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
    if "score" in d or "findings" in d:
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
            "error": "Failed to parse review response",
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