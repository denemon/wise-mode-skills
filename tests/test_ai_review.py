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
import signal
import shutil
import subprocess
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "skills" / "wise-flow" / "scripts" / "ai_review.sh"


class AiReviewTestCase(unittest.TestCase):
    """一時 git リポジトリ + 偽 claude で ai_review.sh を実際に起動する"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self._tmp.name)
        self.bin = self.repo / "fakebin"
        self.bin.mkdir()
        self._git("init", "-q", ".")
        (self.repo / ".git" / "info" / "exclude").write_text("fakebin/\n")
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

    def fake_git(self, failing_args: tuple[str, ...]) -> None:
        """指定した引数だけ失敗し、それ以外は実gitへ委譲する。"""
        real_git = shutil.which("git")
        assert real_git
        path = self.bin / "git"
        quoted = " ".join(failing_args)
        path.write_text(
            "#!/bin/sh\n"
            f'if [ "$*" = "{quoted}" ]; then exit 2; fi\n'
            f'exec "{real_git}" "$@"\n'
        )
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
        self.fake_claude('cat >/dev/null\necho \'{"summary":"ok","score":8,"coverage":"complete","findings":[],"positive_notes":[]}\'\n')

        result = self.run_review("--lang", "python", "--worktree")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("No diff content found", result.stderr)
        self.assertEqual(json.loads(result.stdout)["score"], 8)

    def test_missing_diff_source_is_rejected(self):
        # 引数なし=worktree 全体の暗黙送信は、スキル側の「毎回 exact diff を
        # 承認」と正面衝突していた。差分源は必須。全体は明示 --worktree のみ。
        (self.repo / "a.txt").write_text("one\ntwo\n")
        self.fake_claude('echo "claude must not run" >&2\nexit 98\n')

        result = self.run_review("--lang", "python")

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stderr)
        self.assertIn("--diff-file", payload["error"])
        self.assertIn("--worktree", payload["error"])
        self.assertNotIn("claude must not run", result.stderr)

    def test_unstaged_change_is_reviewed(self):
        (self.repo / "a.txt").write_text("one\ntwo\n")
        self.fake_claude('cat >/dev/null\necho \'{"summary":"ok","score":5,"coverage":"complete","findings":[],"positive_notes":[]}\'\n')

        result = self.run_review("--worktree")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["score"], 5)

    def test_untracked_file_is_reviewed(self):
        (self.repo / "new file.txt").write_text("new implementation\n")
        self.fake_claude(
            'input=$(cat)\n'
            'case "$input" in\n'
            '  *"new file.txt"*"new implementation"*) '
            'echo \'{"summary":"ok","score":6,"coverage":"complete","findings":[],"positive_notes":[]}\' ;;\n'
            '  *) echo "untracked file missing" >&2; exit 98 ;;\n'
            'esac\n'
        )

        result = self.run_review("--worktree")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["score"], 6)

    def test_tracked_diff_collection_failure_stops_before_review(self):
        (self.repo / "a.txt").write_text("one\ntwo\n")
        (self.repo / "new.txt").write_text("untracked\n")
        self.fake_git(("diff", "--binary", "HEAD"))
        self.fake_claude('echo "claude must not run" >&2\nexit 98\n')

        result = self.run_review("--worktree")

        self.assertEqual(result.returncode, 1)
        self.assertIn("Failed to collect tracked diff", result.stderr)
        self.assertNotIn("claude must not run", result.stderr)

    def test_sensitive_untracked_file_is_not_sent_to_claude(self):
        secret = "super-secret-value"
        (self.repo / "secret.env").write_text(f"API_KEY={secret}\n")
        self.fake_claude('echo "claude must not run" >&2\nexit 98\n')

        result = self.run_review("--worktree")

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stderr)
        self.assertIn("Sensitive-looking", payload["error"])
        self.assertNotIn(secret, result.stderr)
        self.assertNotIn("claude must not run", result.stderr)

    def test_sensitive_staged_file_is_not_sent_to_claude(self):
        secret = "staged-super-secret-value"
        (self.repo / "secret.env").write_text(f"API_KEY={secret}\n")
        self._git("add", "secret.env")
        self.fake_claude('echo "claude must not run" >&2\nexit 98\n')

        result = self.run_review("--worktree")

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stderr)
        self.assertIn("Sensitive-looking", payload["error"])
        self.assertNotIn(secret, result.stderr)
        self.assertNotIn("claude must not run", result.stderr)

    def test_sensitive_path_check_is_case_insensitive(self):
        secret = "uppercase-super-secret-value"
        (self.repo / "SECRET.ENV").write_text(f"API_KEY={secret}\n")
        self.fake_claude('echo "claude must not run" >&2\nexit 98\n')

        result = self.run_review("--worktree")

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stderr)
        self.assertIn("Sensitive-looking", payload["error"])
        self.assertNotIn(secret, result.stderr)
        self.assertNotIn("claude must not run", result.stderr)

    def test_secret_content_in_ordinary_file_is_not_sent_to_claude(self):
        secret = "live-review-credential-4f8c2b91"
        capture = self.repo / "claude-input"
        (self.repo / "config.py").write_text(
            f"AWS_SECRET_ACCESS_KEY={secret}\n")
        self.fake_claude(
            f'cat > "{capture}"\n'
            'echo \'{"summary":"bad","score":0,"coverage":"complete","findings":[],"positive_notes":[]}\'\n'
        )

        result = self.run_review("--worktree")

        self.assertEqual(result.returncode, 1)
        self.assertIn("Sensitive-looking content", result.stderr)
        self.assertNotIn(secret, result.stderr)
        self.assertFalse(capture.exists(), "secret reached the external reviewer")

    def test_sensitive_diff_file_requires_explicit_override(self):
        secret = "reviewed-credential-71d5a620"
        diff = self.repo / "sensitive.diff"
        diff.write_text(f'--- a/x\n+++ b/x\n+password = "{secret}"\n')
        self.fake_claude('echo "claude must not run" >&2\nexit 98\n')

        result = self.run_review("--diff-file", str(diff))

        self.assertEqual(result.returncode, 1)
        self.assertIn("Sensitive-looking content", result.stderr)
        self.assertNotIn(secret, result.stderr)
        self.assertNotIn("claude must not run", result.stderr)

    def test_explicit_sensitive_content_override_is_reviewed(self):
        secret = "approved-credential-918e603a"
        capture = self.repo / "approved-input"
        diff = self.repo / "approved.diff"
        diff.write_text(f'--- a/x\n+++ b/x\n+password = "{secret}"\n')
        self.fake_claude(
            f'cat > "{capture}"\n'
            'echo \'{"summary":"ok","score":7,"coverage":"complete","findings":[],"positive_notes":[]}\'\n'
        )

        result = self.run_review(
            "--diff-file", str(diff), "--allow-sensitive-content")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(secret, capture.read_text())
        self.assertEqual(json.loads(result.stdout)["score"], 7)

    def test_secret_word_without_literal_value_remains_reviewable(self):
        (self.repo / "a.txt").write_text("password = user_input\n")
        self.fake_claude(
            'cat >/dev/null\n'
            'echo \'{"summary":"ok","score":6,"coverage":"complete","findings":[],"positive_notes":[]}\'\n'
        )

        result = self.run_review("--worktree")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["score"], 6)

    def test_reviewer_runs_isolated_from_development_context(self):
        # 通常の `claude -p` はプロジェクトの CLAUDE.md / hooks / skills /
        # memory を読み込むので、「独立レビュー」が開発コンテキストを継承する。
        # --safe-mode がそれらを外し、--tools "" がリポジトリ読み取りを塞ぐ。
        # --bare でないのは意図的: OAuth 認証を読まずサブスク利用者で壊れる。
        # あわせて、開発者が書いた文脈 (旧 --context) が同梱されないことも見る。
        (self.repo / "a.txt").write_text("one\ntwo\n")
        args_file = self.repo / "claude-args"
        stdin_file = self.repo / "claude-stdin"
        self.fake_claude(
            f'printf "%s\\n" "$@" > "{args_file}"\n'
            f'cat > "{stdin_file}"\n'
            'echo \'{"summary":"ok","score":8,"coverage":"complete","findings":[],"positive_notes":[]}\'\n'
        )

        result = self.run_review("--worktree")

        self.assertEqual(result.returncode, 0, result.stderr)
        args = args_file.read_text().split("\n")
        self.assertIn("--safe-mode", args)
        self.assertIn("--tools", args)
        self.assertEqual(args[args.index("--tools") + 1], "")
        self.assertNotIn("--bare", args)
        self.assertNotIn("Untrusted context:", stdin_file.read_text())

    def test_clean_worktree_stops_with_an_error(self):
        self.fake_claude('echo "should not be called" >&2\nexit 1\n')

        result = self.run_review("--worktree")

        self.assertEqual(result.returncode, 1)
        self.assertIn("No diff content found", result.stderr)

    def test_diff_file_overrides_git(self):
        diff = self.repo / "my.diff"
        diff.write_text("--- a/x\n+++ b/x\n+added line\n")
        self.fake_claude('cat >/dev/null\necho \'{"summary":"ok","score":9,"coverage":"complete","findings":[],"positive_notes":[]}\'\n')

        result = self.run_review("--diff-file", str(diff))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["score"], 9)

    def test_missing_diff_file_stops_instead_of_reviewing_git_diff(self):
        (self.repo / "a.txt").write_text("one\ntwo\n")
        self.fake_claude('echo "should not be called" >&2\nexit 97\n')

        result = self.run_review("--diff-file", str(self.repo / "missing.diff"))

        self.assertEqual(result.returncode, 1)
        self.assertIn("Diff file not found", result.stderr)
        self.assertNotIn("should not be called", result.stderr)

    def test_large_diff_is_rejected_before_partial_review(self):
        diff = self.repo / "large.diff"
        diff.write_text(("+" + "x" * 1000 + "\n") * 5000)
        self.fake_claude('echo "claude must not run" >&2\nexit 98\n')

        result = self.run_review("--diff-file", str(diff))

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stderr)
        self.assertIn("5000 lines", payload["error"])
        self.assertIn("partial review is not accepted", payload["error"])
        self.assertNotIn("claude must not run", result.stderr)

    def test_large_single_line_is_rejected_before_claude(self):
        diff = self.repo / "minified.diff"
        diff.write_text("+" + "x" * 600000)
        self.fake_claude('echo "claude must not run" >&2\nexit 98\n')

        result = self.run_review("--diff-file", str(diff))

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stderr)
        self.assertIn("600001 bytes", payload["error"])
        self.assertIn("500000 bytes", payload["error"])
        self.assertIn("partial review is not accepted", payload["error"])
        self.assertNotIn("claude must not run", result.stderr)


class FailureReportingTest(AiReviewTestCase):
    def setUp(self):
        super().setUp()
        (self.repo / "a.txt").write_text("one\ntwo\n")

    def test_claude_exit_code_is_reported_verbatim(self):
        # `if ! cmd; then EXIT_CODE=$?` は必ず 0 になる。認証切れ(1)と
        # rate limit(429 相当)が同じ "exit 0" になると原因が特定できない。
        self.fake_claude('cat >/dev/null\necho "auth failed" >&2\nexit 42\n')

        result = self.run_review("--worktree")

        self.assertEqual(result.returncode, 1)
        self.assertIn("exit 42", result.stderr)
        self.assertNotIn("exit 0", result.stderr)
        self.assertIn("auth failed", result.stderr)

    def test_claude_stderr_is_carried_into_the_error(self):
        self.fake_claude('cat >/dev/null\necho "rate limit exceeded" >&2\nexit 7\n')

        result = self.run_review("--worktree")

        payload = json.loads(result.stderr)
        self.assertIn("rate limit exceeded", payload["error"])
        self.assertEqual(payload["findings"], [])

    def test_int_and_term_stop_and_reap_claude(self):
        entries = os.environ.get("PATH", "").split(os.pathsep)
        env = dict(os.environ, PATH=os.pathsep.join([str(self.bin), *entries]))

        for signal_value, expected_status in (
            (signal.SIGINT, 130), (signal.SIGTERM, 143),
        ):
            with self.subTest(signal=signal_value):
                marker = self.repo / f"started-{expected_status}"
                pid_file = self.repo / f"pid-{expected_status}"
                self.fake_claude(
                    'trap "exit 0" INT TERM\n'
                    'cat >/dev/null\n'
                    f'printf "%s" "$$" > "{pid_file}"\n'
                    f'printf started > "{marker}"\n'
                    'while :; do sleep 0.1; done\n'
                )
                proc = subprocess.Popen(
                    ["bash", str(SCRIPT), "--worktree"], cwd=self.repo, env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                child_pid = None
                try:
                    for _ in range(150):
                        if marker.is_file() and pid_file.is_file():
                            break
                        time.sleep(0.02)
                    self.assertTrue(marker.is_file(), "fake claude did not start")
                    child_pid = int(pid_file.read_text())
                    proc.send_signal(signal_value)
                    stdout, stderr = proc.communicate(timeout=5)
                    self.assertEqual(proc.returncode, expected_status, stderr)
                    self.assertEqual(stdout, "")
                    with self.assertRaises(ProcessLookupError):
                        os.kill(child_pid, 0)
                finally:
                    if proc.poll() is None:
                        proc.kill()
                        proc.wait()
                    if child_pid is not None:
                        try:
                            os.kill(child_pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass

    def test_term_force_stops_claude_that_ignores_signal(self):
        marker = self.repo / "stubborn-started"
        pid_file = self.repo / "stubborn-pid"
        self.fake_claude(
            'trap "" TERM\n'
            'cat >/dev/null\n'
            f'printf "%s" "$$" > "{pid_file}"\n'
            f'printf started > "{marker}"\n'
            'while :; do sleep 0.1; done\n'
        )
        entries = os.environ.get("PATH", "").split(os.pathsep)
        env = dict(os.environ, PATH=os.pathsep.join([str(self.bin), *entries]))
        proc = subprocess.Popen(
            ["bash", str(SCRIPT), "--worktree"], cwd=self.repo, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        child_pid = None
        try:
            for _ in range(150):
                if marker.is_file() and pid_file.is_file():
                    break
                time.sleep(0.02)
            self.assertTrue(marker.is_file(), "fake claude did not start")
            child_pid = int(pid_file.read_text())
            started_at = time.monotonic()
            proc.terminate()
            stdout, stderr = proc.communicate(timeout=5)
            elapsed = time.monotonic() - started_at
            self.assertEqual(proc.returncode, 143, stderr)
            self.assertEqual(stdout, "")
            self.assertLess(elapsed, 4.0, "cancellation exceeded its bound")
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            if child_pid is not None:
                try:
                    os.kill(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass

    def test_missing_claude_cli_is_reported(self):
        self.remove_claude()

        result = self.run_review("--worktree")

        self.assertEqual(result.returncode, 1)
        self.assertIn("claude CLI not found", result.stderr)

    def test_guard_catches_a_test_that_forgets_the_fake(self):
        # このガードが効いていないと、偽物を置き忘れたテストが本物の claude を
        # 起動して課金される。ガード自体を検査しておく。
        result = self.run_review("--worktree")

        self.assertEqual(result.returncode, 1)
        self.assertIn("test did not install a fake claude", result.stderr)

    def test_unparseable_response_reports_a_preview(self):
        self.fake_claude('cat >/dev/null\necho "I am not JSON at all"\n')

        result = self.run_review("--worktree")

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stderr)
        self.assertIn("Failed to parse", payload["error"])
        self.assertIn("not JSON", payload["raw_preview"])

    def test_missing_option_values_are_json_errors(self):
        for option in ("--diff-file", "--lang"):
            with self.subTest(option=option):
                result = self.run_review(option)
                self.assertEqual(result.returncode, 2)
                payload = json.loads(result.stderr)
                self.assertIn("Missing value", payload["error"])

    def test_unknown_option_is_a_json_error(self):
        result = self.run_review("--unknown")

        self.assertEqual(result.returncode, 2)
        self.assertIn("Unknown option", json.loads(result.stderr)["error"])


class ResponseParsingTest(AiReviewTestCase):
    def setUp(self):
        super().setUp()
        (self.repo / "a.txt").write_text("one\ntwo\n")

    def test_json_wrapped_in_markdown_fence_is_unwrapped(self):
        self.fake_claude(
            'cat >/dev/null\n'
            'printf \'{"result":"```json\\\\n{\\\\"summary\\\\":\\\\"ok\\\\",\\\\"score\\\\":6,\\\\"coverage\\\\":\\\\"complete\\\\",\\\\"findings\\\\":[],\\\\"positive_notes\\\\":[]}\\\\n```"}\\n\'\n'
        )

        result = self.run_review("--worktree")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["score"], 6)

    def test_json_surrounded_by_prose_is_extracted(self):
        self.fake_claude(
            'cat >/dev/null\n'
            'echo \'Here is my review: {"summary":"ok","score":4,"coverage":"complete","findings":[],"positive_notes":[]} Hope it helps.\'\n'
        )

        result = self.run_review("--worktree")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["score"], 4)

    def test_incomplete_schema_is_rejected(self):
        for response in (
            '{"score":100}',
            '{"summary":"ok","score":101,"findings":[],"positive_notes":[]}',
            '{"summary":"ok","score":90,"findings":[{}],"positive_notes":[]}',
        ):
            with self.subTest(response=response):
                self.fake_claude(f"cat >/dev/null\necho '{response}'\n")
                result = self.run_review("--worktree")
                self.assertEqual(result.returncode, 1)
                self.assertIn("validate", json.loads(result.stderr)["error"])

    def test_partial_review_is_rejected_even_with_valid_score(self):
        response = {
            "summary": "Diff too large; reviewed only highest-risk files.",
            "score": 95,
            "coverage": "partial",
            "findings": [],
            "positive_notes": [],
        }
        self.fake_claude(f"cat >/dev/null\necho '{json.dumps(response)}'\n")

        result = self.run_review("--worktree")

        self.assertEqual(result.returncode, 1)
        self.assertIn("validate", json.loads(result.stderr)["error"])

    def test_complete_finding_schema_is_accepted(self):
        response = {
            "summary": "one issue",
            "score": 70,
            "coverage": "complete",
            "findings": [{
                "id": "F001",
                "category": "correctness",
                "severity": "high",
                "file": "a.txt",
                "line": 2,
                "title": "Wrong result",
                "description": "The result is incorrect.",
                "suggestion": "Return the expected value.",
            }],
            "positive_notes": [],
        }
        self.fake_claude(f"cat >/dev/null\necho '{json.dumps(response)}'\n")

        result = self.run_review("--worktree")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["findings"][0]["id"], "F001")


if __name__ == "__main__":
    unittest.main()
