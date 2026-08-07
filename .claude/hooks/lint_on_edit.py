#!/usr/bin/env python3
"""lint_on_edit.py — PostToolUse: 編集した瞬間にその 1 ファイルだけ検査する

開発用ハーネス。配布物ではない。

Stop ゲートは終端でしか効かないので、壊してから気づくまでに何手も挟まる。
こちらは Edit/Write の直後に、触ったファイルだけを見る速い層。

非ブロッキング（常に exit 0）。指摘は stdout に出るだけで、判断はモデルに任せる。
ここでブロックすると、途中経過として一時的に壊れた状態を作れなくなる。
"""
from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path


def check(path: Path) -> str:
    """問題があればその内容、無ければ空文字。"""
    if path.suffix == ".py":
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            return f"{path.name}: SyntaxError line {exc.lineno}: {exc.msg}"
        except OSError:
            return ""
        return ""

    if path.suffix == ".sh":
        syntax = subprocess.run(["bash", "-n", str(path)],
                                capture_output=True, text=True, timeout=15)
        if syntax.returncode != 0:
            return f"{path.name}: {syntax.stderr.strip()}"
        if shutil.which("shellcheck"):
            lint = subprocess.run(["shellcheck", str(path)],
                                  capture_output=True, text=True, timeout=15)
            if lint.returncode != 0:
                return lint.stdout.strip()
        return ""

    return ""


def main(stdin_text: str | None = None) -> None:
    raw = sys.stdin.read() if stdin_text is None else stdin_text
    try:
        payload = json.loads(raw or "{}")
    except ValueError:
        return
    if not isinstance(payload, dict):
        return

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return
    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str) or not file_path:
        return

    path = Path(file_path)
    if not path.is_file():
        return

    problem = check(path)
    if problem:
        print(f"[lint] {problem}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # フックがセッションを止めることは絶対に避ける
    sys.exit(0)
