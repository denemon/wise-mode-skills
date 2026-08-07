#!/usr/bin/env python3
"""ai_review.sh の統合テスト

このリポジトリで唯一の「利用者の環境で実行されるスクリプト」なのに、テストが
`bash -n` しか無かった。そこから見つかったバグ 2 つはどちらもクラッシュせず、
もっともらしい出力を返す型:

- `if ! RESPONSE=$(claude ...)` の直後の `$?` は否定の結果（常に 0）で、
  認証切れも rate limit も「exit 0」と報告していた
- ステージ済みの変更を `git diff` が拾わず、コミット直前という
  このスクリプトを使うまさにその瞬間に「差分なし」で終了していた

読んで気づける種類ではないので、偽の `claude` を PATH に置いて実際に走らせる。
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "dev-with-review" / "scripts" / "ai_review.sh"


class AiReviewTestCase(unittest.TestCase):
    """一時 git リポジトリ + 偽 claude で ai_review.sh を実際に起動する"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.bin = self.repo / "fakebin"
        self.bin.mkdir()
        self._git("init", "-q", ".")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "t")
        (self.repo / "a.txt").write_text("one\n")
        self._git("add", ".")
        self._git("commit", "-qm", "init")
        self._install_guard_claude()

    def tearDown(self):
        self._tmp.cleanup()

    def _git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                       capture_output=True)

    def fake_claude(self, script: str) -> None:
        """PATH の先頭に置く偽 claude を作る。"""
        path = self.bin / "claude"
        path.write_text("#!/bin/sh\n" + textwrap.dedent(script))
        path.chmod(0o755)

    def _install_guard_claude(self) -> None:
        """偽 claude を置き忘れたテストを、本物に到達させず失敗させる。

        開発機には本物の claude が入っている。素通しにすると、偽物を置き忘れた
        テストが本物を起動して課金付きの API 呼び出しになる（実際に一度やった）。

        PATH から claude のあるディレクトリを削る手もあるが、`npm i -g` の
        インストール先（/usr/local/bin, /opt/homebrew/bin）には git も同居しうる。
        巻き添えで git が消えると「差分なし」という無関係な失敗になるので、
        削るのではなく **必ず先頭を偽物で塞ぐ**。
        """
        self.fake_claude('echo "test did not install a fake claude" >&2\nexit 97\n')

    def remove_claude(self) -> None:
        """`claude` がどこにも無い状況を作る。

        ガードを外すだけでは本物に届いてしまうので、このときだけ PATH からも
        claude のあるディレクトリを落とす。この経路が触るのは起動前の
        `command -v claude` チェックだけなので、巻き添えで git が消えても影響しない。
        """
        (self.bin / "claude").unlink(missing_ok=True)
        self._strip_claude_dirs = True

    def run_review(self, *args: str) -> subprocess.CompletedProcess:
        entries = os.environ.get("PATH", "").split(os.pathsep)
        if getattr(self, "_strip_claude_dirs", False):
            entries = [d for d in entries
                       if d and not os.access(os.path.join(d, "claude"), os.X_OK)]
        env = dict(os.environ, PATH=os.pathsep.join([str(self.bin), *entries]))
        return subprocess.run(
            ["bash", str(SCRIPT), *args],
            cwd=self.repo, env=env, capture_output=True, text=True, timeout=30,
        )


class DiffAcquisitionTest(AiReviewTestCase):
    def test_staged_change_is_reviewed(self):
        # コミット直前 = ステージ済み。`git diff` は空になるので、ここを取り違えると
        # スクリプトを一番使いたい瞬間に「差分なし」で終わる。
        (self.repo / "a.txt").write_text("one\ntwo\n")
        self._git("add", "a.txt")
        self.fake_claude('cat >/dev/null\necho \'{"score":8,"findings":[]}\'\n')

        result = self.run_review("--lang", "python", "--context", "test")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("No diff content found", result.stderr)
        self.assertEqual(json.loads(result.stdout)["score"], 8)

    def test_unstaged_change_is_reviewed(self):
        (self.repo / "a.txt").write_text("one\ntwo\n")
        self.fake_claude('cat >/dev/null\necho \'{"score":5,"findings":[]}\'\n')

        result = self.run_review()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["score"], 5)

    def test_clean_worktree_stops_with_an_error(self):
        self.fake_claude('echo "should not be called" >&2\nexit 1\n')

        result = self.run_review()

        self.assertEqual(result.returncode, 1)
        self.assertIn("No diff content found", result.stderr)

    def test_diff_file_overrides_git(self):
        diff = self.repo / "my.diff"
        diff.write_text("--- a/x\n+++ b/x\n+added line\n")
        self.fake_claude('cat >/dev/null\necho \'{"score":9,"findings":[]}\'\n')

        result = self.run_review("--diff-file", str(diff))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["score"], 9)


class FailureReportingTest(AiReviewTestCase):
    def setUp(self):
        super().setUp()
        (self.repo / "a.txt").write_text("one\ntwo\n")

    def test_claude_exit_code_is_reported_verbatim(self):
        # `if ! cmd; then EXIT_CODE=$?` は必ず 0 になる。認証切れ(1)と
        # rate limit(429 相当)が同じ "exit 0" になると原因が特定できない。
        self.fake_claude('cat >/dev/null\necho "auth failed" >&2\nexit 42\n')

        result = self.run_review()

        self.assertEqual(result.returncode, 1)
        self.assertIn("exit 42", result.stderr)
        self.assertNotIn("exit 0", result.stderr)
        self.assertIn("auth failed", result.stderr)

    def test_claude_stderr_is_carried_into_the_error(self):
        self.fake_claude('cat >/dev/null\necho "rate limit exceeded" >&2\nexit 7\n')

        result = self.run_review()

        payload = json.loads(result.stderr)
        self.assertIn("rate limit exceeded", payload["error"])
        self.assertEqual(payload["findings"], [])

    def test_missing_claude_cli_is_reported(self):
        self.remove_claude()

        result = self.run_review()

        self.assertEqual(result.returncode, 1)
        self.assertIn("claude CLI not found", result.stderr)

    def test_guard_catches_a_test_that_forgets_the_fake(self):
        # このガードが効いていないと、偽物を置き忘れたテストが本物の claude を
        # 起動して課金される。ガード自体を検査しておく。
        result = self.run_review()

        self.assertEqual(result.returncode, 1)
        self.assertIn("test did not install a fake claude", result.stderr)

    def test_unparseable_response_reports_a_preview(self):
        self.fake_claude('cat >/dev/null\necho "I am not JSON at all"\n')

        result = self.run_review()

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stderr)
        self.assertIn("Failed to parse", payload["error"])
        self.assertIn("not JSON", payload["raw_preview"])


class ResponseParsingTest(AiReviewTestCase):
    def setUp(self):
        super().setUp()
        (self.repo / "a.txt").write_text("one\ntwo\n")

    def test_json_wrapped_in_markdown_fence_is_unwrapped(self):
        self.fake_claude(
            'cat >/dev/null\n'
            'printf \'{"result":"```json\\\\n{\\\\"score\\\\":6,\\\\"findings\\\\":[]}\\\\n```"}\\n\'\n'
        )

        result = self.run_review()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["score"], 6)

    def test_json_surrounded_by_prose_is_extracted(self):
        self.fake_claude(
            'cat >/dev/null\n'
            'echo \'Here is my review: {"score":4,"findings":[]} Hope it helps.\'\n'
        )

        result = self.run_review()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["score"], 4)


if __name__ == "__main__":
    unittest.main()
