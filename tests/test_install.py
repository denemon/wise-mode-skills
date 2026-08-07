#!/usr/bin/env python3
"""install.sh の統合テスト — 唯一残っていた未検証の層

443 行、`curl | bash` で利用者の端末に直接届くのに、検査は `bash -n` と
shellcheck だけだった。実行して初めて分かることしか無い層なので、
リポジトリをローカル HTTP で配信して `REPO_RAW_BASE` だけ差し替え、
本物のスクリプトを最後まで走らせる。

対話プロンプトは踏まない構成にしてある（`.claude/` を先に作れば設置確認は
出ず、既存インストールが無ければ上書き確認も出ない）。プロンプト経路の確認は
pty が要るので、ここでは扱わない。
"""
from __future__ import annotations

import functools
import http.server
import re
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REAL_BASE = "https://raw.githubusercontent.com/den-emon/wise-mode/main"


class _Handler(http.server.SimpleHTTPRequestHandler):
    """リポジトリを配信する。`missing` に一致するパスだけ 404 にする。"""

    missing: str | None = None

    def do_GET(self):
        if self.missing and self.path.endswith(self.missing):
            self.send_error(404)
            return
        super().do_GET()

    def log_message(self, *args):
        pass


class _InstallHarness:
    """install.sh をローカル配信して実行する足回り。TestCase ではないので
    unittest はこのクラス自体を収集しない（継承先で親のテストが再実行
    されるのを防ぐ）。"""

    @classmethod
    def setUpClass(cls):
        handler = functools.partial(_Handler, directory=str(ROOT))
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _Handler.missing = None
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name)
        (self.proj / ".claude").mkdir()  # 「ここに入れる?」プロンプトを回避
        self.script = self.proj / "install.sh"
        source = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn(REAL_BASE, source, "REPO_RAW_BASE の形が変わった")
        self.script.write_text(source.replace(REAL_BASE, self.base))

    def tearDown(self):
        self._tmp.cleanup()

    def install(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(self.script)], cwd=self.proj, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=180,
        )

    def _git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.proj), *args], check=True,
                       capture_output=True)


class InstallScriptIntegrationTest(_InstallHarness, unittest.TestCase):
    """配置・設定・原子性"""

    def test_fresh_install_places_every_shipped_file(self):
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.proj / ".claude"

        skills = sorted(p.name for p in (installed / "skills").iterdir())
        expected = sorted(p.parent.name for p in (ROOT / "skills").glob("*/SKILL.md"))
        self.assertEqual(skills, expected)

        for entry in re.findall(r'"([^"]+)"', re.search(
                r"^\s*SKILLS=\((.*?)\)", self.script.read_text(),
                re.DOTALL | re.MULTILINE).group(1)):
            source, name, files = entry.split("|")
            for f in files.split(","):
                with self.subTest(file=f"{name}/{f}"):
                    self.assertTrue((installed / "skills" / name / f).is_file())

        settings = (installed / "settings.local.json").read_text()
        for event in ("UserPromptSubmit", "SessionStart", "PostToolUse", "Stop"):
            with self.subTest(event=event):
                self.assertIn(event, settings)
        self.assertIn("mode_persistence.py", settings)
        self.assertIn("session_log.py", settings)

        script = installed / "skills" / "dev-with-review" / "scripts" / "ai_review.sh"
        self.assertTrue(script.stat().st_mode & 0o111, "実行ビットが立っていない")

    def test_installed_tree_matches_the_manifest(self):
        """宣言したファイルと、実際に置かれたファイルを**網羅で**突き合わせる。

        抜き取り検査だと、見ていない箇所が消えても緑のまま。実際そうなった —
        Obsidian 機能を削るときに巻き添えで `cp`/`chmod` を消し、フックが
        1 つも配置されない状態になったが、テストは settings.local.json に
        名前が書かれているかしか見ておらず通ってしまった。
        「設定に書かれている」と「置かれている」は別のこと。

        install.sh の SKILLS / HOOK_FILES を唯一の正として、両方向で比較する。
        足りなくても余分でも落ちるので、次にどの cp が消えても捕まる。
        """
        self.assertEqual(self.install().returncode, 0)
        installed = self.proj / ".claude"
        source = self.script.read_text()

        declared = set()
        for entry in re.findall(r'"([^"]+)"', re.search(
                r"^\s*SKILLS=\((.*?)\)", source, re.DOTALL | re.MULTILINE).group(1)):
            _src, name, files = entry.split("|")
            declared |= {f"skills/{name}/{f}" for f in files.split(",")}
        hooks = re.findall(r'"(\w+\.py)"', re.search(
            r"^\s*HOOK_FILES=\((.*?)\)", source, re.DOTALL | re.MULTILINE).group(1))
        self.assertTrue(hooks, "HOOK_FILES が読めていない")
        declared |= {f"hooks/{h}" for h in hooks}

        actual = {p.relative_to(installed).as_posix()
                  for p in installed.rglob("*") if p.is_file()}
        actual.discard("settings.local.json")  # 生成物であって配布物ではない

        self.assertEqual(actual, declared)

        for h in hooks:
            with self.subTest(hook=h):
                self.assertTrue((installed / "hooks" / h).stat().st_mode & 0o111,
                                f"{h} に実行ビットが無い")

    def test_partial_download_installs_nothing(self):
        # 「先に temp へ落としてから配置する」と自称している。1 ファイル欠けた
        # だけで壊れた .claude/ が残ると、利用者は読めない参照を持つことになる。
        _Handler.missing = "report-format.md"

        result = self.install()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("aborted", result.stderr.lower() + result.stdout.lower())
        self.assertEqual(
            list((self.proj / ".claude").iterdir()), [],
            "中断したのにファイルが残っている",
        )

    def test_second_install_does_not_duplicate_hook_entries(self):
        self.assertEqual(self.install().returncode, 0)
        settings = self.proj / ".claude" / "settings.local.json"
        before = settings.read_text()
        # 既存インストールがあると上書き確認が出るので、直接マージ部分だけを
        # 再実行できるよう .claude/skills を消してプロンプトを回避する。
        shutil.rmtree(self.proj / ".claude" / "skills")
        (self.proj / ".claude" / "hooks").rename(self.proj / ".claude" / "hooks.bak")

        self.assertEqual(self.install().returncode, 0)

        self.assertEqual(settings.read_text(), before, "フック設定が重複した")


class GitIgnoreAdviceTest(_InstallHarness, unittest.TestCase):
    """ログが git に載らないための助言が、実際に効く内容になっているか"""

    def test_ignored_log_dir_is_reported_as_safe(self):
        self._git("init", "-q", ".")
        (self.proj / ".gitignore").write_text(".claude/log/\n")

        out = self.install().stdout

        self.assertIn("git-ignored", out)
        self.assertNotIn("NOT git-ignored", out)

    def test_already_tracked_logs_get_the_untrack_command(self):
        # `.claude/` をコミットして共有する運用は README が普通だと書いている。
        # その場合ログは追跡済みになり、.gitignore を足しても止まらない。
        self._git("init", "-q", ".")
        self._git("config", "user.email", "t@example.com")
        self._git("config", "user.name", "t")
        log_dir = self.proj / ".claude" / "log"
        log_dir.mkdir()
        (log_dir / "session.md").write_text("AWS_SECRET=leak\n")
        self._git("add", "-A")
        self._git("commit", "-qm", "share .claude/")
        (self.proj / ".gitignore").write_text(".claude/log/\n")

        out = self.install().stdout

        self.assertIn("ALREADY TRACKED", out)
        self.assertIn("git rm -r --cached .claude/log", out)


if __name__ == "__main__":
    unittest.main()
