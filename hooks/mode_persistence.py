#!/usr/bin/env python3
"""mode_persistence.py — 継続モード（wise-cont / terse-mode）を実際に永続化するフック

UserPromptSubmit / SessionStart で呼ばれ、フラグファイルが存在する間は
毎ターン、そのモードの要約を additionalContext として注入する。
SKILL.md の「以降ずっと適用する」という指示だけではモデルが数ターンで
素の応答に戻るため、フック側で毎回貼り直す。

使い方: python3 mode_persistence.py UserPromptSubmit   # stdin に payload JSON
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

# プロジェクト単位の状態。同一プロジェクトの全セッションで共有される。
STATE_DIR = ".claude"

WISE_REMINDER = """WISE MODE ACTIVE — architect mode persists for this session.

Apply to THIS message before answering:
- Assess complexity, then prefix the response with `## [WISE MODE: Q&A]`
  (no code change), `## [WISE MODE: LIGHT]` (single file, < 50 lines, low risk),
  or `## [WISE MODE] Phase N: Name` (2+ files / shared state / new API).
- Think systemically: find the root cause and the blast radius, not the local
  symptom. Grep every caller before editing a shared function.
- Be your own adversary before you finish: concurrent runs, null/zero/huge
  inputs, assumptions that could be wrong.
- Phase details are in `.claude/skills/wise/SKILL.md` — read it when running the
  full process. Do not re-derive the phases from memory.

Still active if unsure. Off only: `/wise-cont-off` or "normal mode"."""

TERSE_REMINDER = """TERSE MODE ACTIVE — level: {level}.

Apply to THIS message: fewer words, same technical substance. Keep identifiers,
commands, paths, and quoted errors exact. Keep the user's language. Prefer direct
statements over hedging; code blocks stay normal.

Drop terse mode temporarily for security warnings, destructive or irreversible
actions, privacy/compliance disclosures, and multi-step instructions where
compression could scramble the order. Correctness beats brevity.

Never compress a structured report another skill defines (attack-on-hacker
findings, pr-self-review output, wise-flow phase artifacts). Shorten the prose
inside a field; never drop a field, a severity label, or a required table.

Level details are in `.claude/skills/terse-mode/SKILL.md`.
Off only: "normal mode" or "stop terse mode"."""

# name -> (flag file, activation pattern, deactivation pattern, reminder)
MODES = {
    "wise": (
        ".wise-mode",
        re.compile(r"^[/$@]?wise-cont\b", re.IGNORECASE),
        re.compile(r"^[/$@]?wise(-cont)?[- ]off\b|^(stop|turn off) wise\b", re.IGNORECASE),
        WISE_REMINDER,
    ),
    "terse": (
        ".terse-mode",
        re.compile(r"^[/$@]?terse-mode\b(?!\s+off)", re.IGNORECASE),
        re.compile(r"^[/$@]?terse-mode\s+off\b|^stop terse\b", re.IGNORECASE),
        TERSE_REMINDER,
    ),
}

# どのモードも落とす共通の合図。wise-cont/SKILL.md が案内する
# "back to normal mode" も拾う（先頭アンカーだけだと外れる）。
DEACTIVATE_ALL = re.compile(r"^(?:back to )?(?:normal mode\b|通常モード)", re.IGNORECASE)

LEVELS = ("lite", "full", "ultra")


def _payload(stdin_text: str | None = None) -> dict[str, Any]:
    raw = sys.stdin.read() if stdin_text is None else stdin_text
    try:
        payload = json.loads(raw or "{}")
    except (json.JSONDecodeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _record(event: str, raw: str) -> None:
    """`CLAUDE_HOOK_RECORD` が指すディレクトリに実ペイロードを保存する。

    session_log._record と同じ理由・同じ数行。フック同士を import で
    結合させたくないので複製している（_state_dir と同じ方針）。
    """
    dest = os.environ.get("CLAUDE_HOOK_RECORD")
    if not dest:
        return
    try:
        directory = Path(dest)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{event or 'unknown'}.json").write_text(raw, encoding="utf-8")
    except OSError:
        pass  # 記録は best-effort。


def _state_dir(payload: dict[str, Any]) -> Path:
    # session_log._project_root と同じ優先順位。フック同士を import で
    # 結合させたくないので数行だけ複製している。
    root = os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or os.getcwd()
    return Path(root) / STATE_DIR


def _level(prompt: str) -> str:
    parts = prompt.split()
    return parts[1].lower() if len(parts) > 1 and parts[1].lower() in LEVELS else "full"


def main(argv: list[str] | None = None, stdin_text: str | None = None) -> None:
    argv = list(sys.argv if argv is None else argv)
    event = argv[1] if len(argv) > 1 else ""
    if event not in {"UserPromptSubmit", "SessionStart"}:
        return

    raw = sys.stdin.read() if stdin_text is None else stdin_text
    _record(event, raw)
    payload = _payload(raw)
    state_dir = _state_dir(payload)
    prompt = str(payload.get("prompt") or "").strip()
    kill_all = bool(prompt) and event == "UserPromptSubmit" and bool(DEACTIVATE_ALL.match(prompt))

    contexts = []
    for name, (flag_name, activate, deactivate, reminder) in MODES.items():
        flag = state_dir / flag_name
        if event == "UserPromptSubmit" and prompt:
            if kill_all or deactivate.match(prompt):
                if flag.exists():
                    flag.unlink(missing_ok=True)
                    contexts.append(f"{name.upper()} MODE OFF — deactivated. Respond normally.")
                continue
            if activate.match(prompt):
                flag.parent.mkdir(parents=True, exist_ok=True)
                flag.write_text(_level(prompt), encoding="utf-8")
        if flag.exists():
            level = flag.read_text(encoding="utf-8").strip() or "full"
            # str.replace, not str.format: the reminders are prose full of braces
            # in code examples, and a stray `{` would raise inside the bare
            # `except` below and silently kill the mode.
            contexts.append(reminder.replace("{level}", level))

    if contexts:
        json.dump(
            {
                "hookSpecificOutput": {
                    "hookEventName": event,
                    "additionalContext": "\n\n".join(contexts),
                }
            },
            sys.stdout,
        )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # フックがセッションを止めることは絶対に避ける
