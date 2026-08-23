#!/usr/bin/env python3
"""tools/evals.py のハーネス自体のテスト

eval は実 claude を起動する(課金)ので、ここでは PATH の先頭に偽 claude を
置いてハーネスの判定ロジックだけを検証する。実スキルの follow は
`./check.sh --evals` が実測する — このファイルはその測定器が壊れていない
ことを保証する側。
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVALS = ROOT / "tools" / "evals.py"


class EvalHarnessTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.bin = Path(self._tmp.name) / "fakebin"
        self.bin.mkdir()
        # 偽物を置き忘れたテストが本物の claude に到達して課金されるのを防ぐ
        # (test_ai_review と同じガード)。
        self.fake_claude('echo "test did not install a fake claude" >&2\nexit 97\n')
        self._strip_claude_dirs = False

    def tearDown(self):
        self._tmp.cleanup()

    def fake_claude(self, script: str) -> None:
        path = self.bin / "claude"
        path.write_text("#!/bin/sh\n" + textwrap.dedent(script))
        path.chmod(0o755)

    def remove_claude(self) -> None:
        (self.bin / "claude").unlink(missing_ok=True)
        self._strip_claude_dirs = True

    def run_evals(self, *args: str) -> subprocess.CompletedProcess:
        entries = os.environ.get("PATH", "").split(os.pathsep)
        if self._strip_claude_dirs:
            entries = [d for d in entries
                       if d and not os.access(os.path.join(d, "claude"), os.X_OK)]
        env = dict(os.environ, PATH=os.pathsep.join([str(self.bin), *entries]))
        return subprocess.run(
            [sys.executable, str(EVALS), *args],
            env=env, capture_output=True, text=True, timeout=60,
        )

    def test_marker_following_fake_passes_all(self):
        # 各 SKILL.md の必須マーカーどおりに応答する偽物。fixture の構成
        # (enabled 側にはスキルがあり、disabled 側には無い)も検査するので、
        # ペアの無効側が誤ってスキル入り fixture で走ると 97 で落ちる。
        self.fake_claude(
            # personal skill の優先を避けるため、user source の除外が
            # 実際に渡っていることも fixture 側から検査する。
            'case "$*" in\n'
            '  *"--setting-sources project"*) ;;\n'
            '  *) echo "missing --setting-sources project" >&2; exit 97 ;;\n'
            'esac\n'
            'case "$*" in\n'
            '  */wise*)\n'
            '    if [ -f .claude/skills/wise/SKILL.md ]; then\n'
            '      echo "## [WISE MODE: Q&A] 重複排除は Set を使うのが定番です。'
            '順序を保つ必要があるなら dict.fromkeys を使います。"\n'
            '    else\n'
            '      echo "Unknown command: /wise"\n'
            '    fi ;;\n'
            '  */pr-self-review*)\n'
            '    [ -f .claude/skills/pr-self-review/SKILL.md ] || '
            '{ echo "fixture missing pr-self-review" >&2; exit 97; }\n'
            '    echo "対象の変更がありません" ;;\n'
            '  *)\n'
            '    [ -f .claude/skills/wise/SKILL.md ] || '
            '{ echo "fixture missing wise skill" >&2; exit 97; }\n'
            '    echo "重複排除は set が定番です" ;;\n'
            'esac\n'
        )

        result = self.run_evals()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("all 5 evals passed", result.stdout)

    def test_marker_leak_in_baseline_is_a_failure(self):
        # skill を起動していないのにマーカーが出る = baseline 比較が崩れて
        # いる。must_not_contain の判定が生きていないと、これが緑になる。
        self.fake_claude('echo "## [WISE MODE: Q&A] always"\n')

        result = self.run_evals()

        self.assertEqual(result.returncode, 1)
        self.assertIn("FAILED  wise-disabled", result.stdout)
        self.assertIn("forbidden marker present", result.stdout)

    def test_missing_marker_is_a_failure(self):
        # /wise を渡してもマーカー無し = スキル本文が無視されている。
        # min_chars は超える長さにして、失敗が must_contain 判定に帰属する
        # ことを確かめる(短い出力だと min_chars 側で落ちて判定を殺せない)。
        self.fake_claude(
            'echo "重複排除は Set を使うのが定番です。'
            '順序を保つ必要があるなら dict.fromkeys を使います。"\n')

        result = self.run_evals()

        self.assertEqual(result.returncode, 1)
        self.assertIn("FAILED  wise-enabled", result.stdout)
        self.assertIn("missing required marker", result.stdout)

    def test_empty_output_fails_every_eval(self):
        # 無応答の偽 Claude が must_not_contain だけのケースを素通りした
        # (レビューで実証された false green)。空出力は全ケース不合格。
        self.fake_claude('exit 0\n')

        result = self.run_evals()

        self.assertEqual(result.returncode, 1)
        self.assertIn("empty output", result.stdout)
        self.assertEqual(result.stdout.count("FAILED"), 5, result.stdout)

    def test_marker_only_response_is_a_failure(self):
        # マーカーだけ出して回答しない応答が全 eval を通過した(レビュー実証)。
        # min_chars がマーカー単独の長さでは届かない下限を課す。
        self.fake_claude('echo "## [WISE MODE: Q&A]"\n')

        result = self.run_evals("wise-enabled")

        self.assertEqual(result.returncode, 1)
        self.assertIn("marker-only", result.stdout)

    def test_generic_reassurance_is_a_failure(self):
        # 「問題ありません」は "ありません" を含むので、部分一致だと
        # pr-self-review の停止文を騙れる(レビューで実証)。完全一致で落とす。
        self.fake_claude('echo "問題ありません"\n')

        result = self.run_evals()

        self.assertEqual(result.returncode, 1)
        self.assertIn("FAILED  pr-self-review-empty", result.stdout)
        self.assertIn("FAILED  wise-enabled", result.stdout)

    def test_missing_cli_is_an_error(self):
        self.remove_claude()

        result = self.run_evals()

        self.assertEqual(result.returncode, 1)
        self.assertIn("claude CLI not found", result.stderr)

    def test_list_does_not_invoke_claude(self):
        # ガード偽物(exit 97)のまま --list。claude が起動されれば失敗が出る。
        result = self.run_evals("--list")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("wise-enabled", result.stdout)
        self.assertNotIn("FAILED", result.stdout)

    def test_guard_catches_a_test_that_forgets_the_fake(self):
        result = self.run_evals("wise-enabled")

        self.assertEqual(result.returncode, 1)
        self.assertIn("exited 97", result.stdout)


if __name__ == "__main__":
    unittest.main()
