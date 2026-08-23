#!/usr/bin/env python3
"""install.sh の統合テスト — 唯一残っていた未検証の層

`curl | bash` で利用者の端末に直接届くのに、検査は `bash -n` と shellcheck
だけだった。実行して初めて分かることしか無い層なので、リポジトリの tar.gz
スナップショットをローカル HTTP で配信して `REPO_ARCHIVE_BASE` だけ差し替え、
本物のスクリプトを最後まで走らせる。

インストーラは単一アーカイブ方式: ファイルを 1 本ずつ可変 main から取ると
push と交錯して混在バージョンになるが、1 つの tar.gz は 1 つのスナップショット。
配置は「アーカイブ検証 → 設定マージ計算 → 配置 → settings 書き込み(最後)」の
順で、失敗はすべて配置前に起きる。

対話プロンプトは踏まない構成にしてある（`.claude/` を先に作れば設置確認は
出ず、既存インストールが無ければ上書き確認も出ない）。プロンプト経路の確認は
pty が要るので、ここでは扱わない。
"""
from __future__ import annotations

import functools
import hashlib
import http.server
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REAL_BASE = "https://codeload.github.com/den-emon/wise-mode/tar.gz"

_EXCLUDED_PARTS = {".git", "__pycache__"}


def _build_archive(dest: Path, *, arcname: str = "wise-mode-main",
                   omit: str | None = None) -> None:
    """ROOT のスナップショット tar.gz を dest に書く。omit は相対パス 1 件を欠落させる。"""
    def _filter(info: tarfile.TarInfo):
        parts = Path(info.name).parts
        if any(p in _EXCLUDED_PARTS for p in parts):
            return None
        if omit and info.name == f"{arcname}/{omit}":
            return None
        return info

    with tarfile.open(dest, "w:gz") as tar:
        tar.add(ROOT, arcname=arcname, filter=_filter)


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class _InstallHarness:
    """install.sh をローカル配信して実行する足回り。TestCase ではないので
    unittest はこのクラス自体を収集しない（継承先で親のテストが再実行
    されるのを防ぐ）。"""

    @classmethod
    def setUpClass(cls):
        cls._served = tempfile.TemporaryDirectory()
        served = Path(cls._served.name)
        (served / "tar.gz").mkdir()
        cls.archive = served / "tar.gz" / "main"
        _build_archive(cls.archive)

        handler = functools.partial(_Handler, directory=str(served))
        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls._served.cleanup()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.proj = Path(self._tmp.name)
        (self.proj / ".claude").mkdir()  # 「ここに入れる?」プロンプトを回避
        self.script = self.proj / "install.sh"
        source = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn(REAL_BASE, source, "REPO_ARCHIVE_BASE の形が変わった")
        self.script.write_text(source.replace(REAL_BASE, f"{self.base}/tar.gz"))

    def tearDown(self):
        self._tmp.cleanup()

    def install(self, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        run_env = {**os.environ, **(env or {})}
        return subprocess.run(
            ["bash", str(self.script), *args], cwd=self.proj,
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=180, env=run_env,
        )

    def serve_ref(self, ref: str, content: bytes) -> Path:
        """別 ref のアーカイブを配信ディレクトリに置く。"""
        path = Path(self._served.name) / "tar.gz" / ref
        path.write_bytes(content)
        return path

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
        for event in ("UserPromptSubmit", "SessionStart", "PreToolUse"):
            with self.subTest(event=event):
                self.assertIn(event, settings)
        self.assertIn("mode_persistence.py", settings)
        self.assertIn("flag_guard.py", settings)
        # session_log は opt-in — デフォルトでは配線も配置もされない。
        self.assertNotIn("session_log.py", settings)
        self.assertFalse((installed / "hooks" / "session_log.py").exists())

        script = installed / "skills" / "wise-flow" / "scripts" / "ai_review.sh"
        self.assertTrue(script.stat().st_mode & 0o111, "実行ビットが立っていない")
        self.assertFalse((installed / ".install-staging").exists(),
                         "staging ディレクトリが残っている")

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

    def test_gutted_archive_installs_nothing(self):
        # 「先に検証してから配置する」と自称している。1 ファイル欠けただけで
        # 壊れた .claude/ が残ると、利用者は読めない参照を持つことになる。
        gutted = Path(self._served.name) / "tar.gz" / "gutted"
        _build_archive(gutted, arcname="wise-mode-gutted",
                       omit="skills/attack-on-hacker/references/report-format.md")

        result = self.install(env={"WISE_MODE_REF": "gutted"})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("aborted", result.stderr.lower() + result.stdout.lower())
        self.assertEqual(
            list((self.proj / ".claude").iterdir()), [],
            "中断したのにファイルが残っている",
        )

    def test_truncated_archive_installs_nothing(self):
        self.serve_ref("broken", self.archive.read_bytes()[:200])

        result = self.install(env={"WISE_MODE_REF": "broken"})

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list((self.proj / ".claude").iterdir()), [])

    def test_broken_settings_json_aborts_before_placement(self):
        # 再現済みの欠陥: 設定 JSON を配置後に解析していたため、壊れた
        # settings.local.json で exit 1 になりながら 27 ファイルが残った。
        # 検証は配置前 — 失敗時は何も置かれず、元の settings も無傷。
        settings = self.proj / ".claude" / "settings.local.json"
        settings.write_text("{not json", encoding="utf-8")

        result = self.install()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("not valid json", (result.stderr + result.stdout).lower())
        self.assertEqual(
            [p.name for p in (self.proj / ".claude").iterdir()],
            ["settings.local.json"],
            "設定検証で中断したのにファイルが置かれた",
        )
        self.assertEqual(settings.read_text(encoding="utf-8"), "{not json",
                         "壊れた settings が書き換えられた")

    # LC_ALL=C.UTF-8 は再現条件: macOS の shasum(Perl)がこの locale を
    # 継承すると panic して終了 9 になった。インストーラは LC_ALL=C を
    # 固定するので、どの locale から呼ばれても checksum 検証は動く。
    def test_malformed_hooks_section_aborts_before_placement(self):
        # 有効な JSON でも hooks の形が壊れていれば(値が list でない等)、
        # マージ途中の traceback ではなく配置前の明確なエラーで止まる。
        settings = self.proj / ".claude" / "settings.local.json"
        settings.write_text('{"hooks": {"Stop": "not-a-list"}}', encoding="utf-8")

        result = self.install()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("malformed", (result.stderr + result.stdout).lower())
        self.assertEqual(
            [p.name for p in (self.proj / ".claude").iterdir()],
            ["settings.local.json"])
        self.assertEqual(settings.read_text(encoding="utf-8"),
                         '{"hooks": {"Stop": "not-a-list"}}')

    def test_failed_swap_leaves_no_partial_skill(self):
        # 配置は staging → swap。swap が権限で失敗しても、半コピーの skill も
        # staging の残骸も残らず、hooks / settings には到達しない。
        skills_dir = self.proj / ".claude" / "skills"
        skills_dir.mkdir()
        skills_dir.chmod(0o555)
        try:
            result = self.install()

            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(skills_dir.iterdir()), [],
                             "半コピーの skill が残っている")
            self.assertFalse(
                (self.proj / ".claude" / ".install-staging").exists(),
                "staging の残骸が残っている")
            self.assertFalse((self.proj / ".claude" / "hooks").exists())
            self.assertFalse(
                (self.proj / ".claude" / "settings.local.json").exists())
        finally:
            skills_dir.chmod(0o755)

    def test_sha256_mismatch_installs_nothing(self):
        result = self.install(env={"WISE_MODE_SHA256": "0" * 64,
                                   "LC_ALL": "C.UTF-8"})

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("checksum mismatch",
                      (result.stderr + result.stdout).lower())
        self.assertEqual(list((self.proj / ".claude").iterdir()), [])

    def test_sha256_match_installs(self):
        digest = hashlib.sha256(self.archive.read_bytes()).hexdigest()

        result = self.install(env={"WISE_MODE_SHA256": digest,
                                   "LC_ALL": "C.UTF-8"})

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("checksum verified", result.stdout.lower())

    _LEGACY_SESSION_LOG_SETTINGS = {
        "hooks": {
            "PostToolUse": [{"matcher": "", "hooks": [{
                "type": "command",
                "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/session_log.py" PostToolUse',
                "timeout": 10}]}],
            "Stop": [{"hooks": [{
                "type": "command",
                "command": 'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/session_log.py" Stop',
                "timeout": 10}]}],
        }
    }

    def _plant_legacy_session_log(self):
        """旧デフォルトインストールが残す session_log の状態を再現する。"""
        hooks_dir = self.proj / ".claude" / "hooks"
        hooks_dir.mkdir()
        (hooks_dir / "session_log.py").write_text("# legacy install\n")
        (self.proj / ".claude" / "settings.local.json").write_text(
            json.dumps(self._LEGACY_SESSION_LOG_SETTINGS), encoding="utf-8")
        return hooks_dir

    @staticmethod
    def _all_commands(settings: dict) -> list[str]:
        return [
            hook.get("command", "")
            for entries in settings.get("hooks", {}).values()
            for entry in entries
            for hook in entry.get("hooks", [])
        ]

    def test_reinstall_without_flag_unwires_only_the_canonical_commands(self):
        # 旧版はデフォルトで session_log を配線していた。opt-in 移行後の
        # デフォルト再インストールは、インストーラ自身が書く正規コマンドを
        # **完全一致**で外す。部分一致だと session_log.py に言及するだけの
        # 第三者 hook まで消える(実再現: /opt/acme/session_log.py)。
        # ファイルはユーザー所有かもしれないので削除せず、警告だけ出す。
        hooks_dir = self._plant_legacy_session_log()
        settings_path = self.proj / ".claude" / "settings.local.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        third_party = "python3 /opt/acme/session_log.py PostToolUse"
        settings["hooks"]["PostToolUse"][0]["hooks"].append(
            {"type": "command", "command": third_party, "timeout": 10})
        settings_path.write_text(json.dumps(settings), encoding="utf-8")

        result = self.install()

        self.assertEqual(result.returncode, 0, result.stderr)
        merged = json.loads(settings_path.read_text(encoding="utf-8"))
        commands = self._all_commands(merged)
        for canonical in (
            'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/session_log.py" PostToolUse',
            'python3 "$CLAUDE_PROJECT_DIR/.claude/hooks/session_log.py" Stop',
        ):
            self.assertNotIn(canonical, commands, "正規配線が外れていない")
        self.assertIn(third_party, commands, "第三者の hook 配線が消された")
        self.assertEqual((hooks_dir / "session_log.py").read_text(encoding="utf-8"),
                         "# legacy install\n", "ユーザー所有かもしれないファイルが変更/削除された")
        self.assertIn("no longer wired", result.stdout,
                      "残置ファイルへの案内が出ていない")
        # 案内は相対パス固定 — 絶対パスの補間はプロジェクトパスに空白が
        # あるとコピペで複数引数の rm になる。
        self.assertIn("rm .claude/hooks/session_log.py", result.stdout)
        self.assertNotIn(f"rm {self.proj}", result.stdout)

    def test_reinstall_with_flag_keeps_legacy_session_log_wiring_once(self):
        # opt-in を続けるユーザーの再インストールでは配線が消えず、重複もしない。
        # ファイルまで植えると INSTALL_HOOKS と衝突して上書きプロンプトが出る
        # (このテストの対象はマージの配線判定)ので、配線だけを植える。
        (self.proj / ".claude" / "settings.local.json").write_text(
            json.dumps(self._LEGACY_SESSION_LOG_SETTINGS), encoding="utf-8")

        result = self.install("--with-session-log")

        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.proj / ".claude"
        self.assertTrue((installed / "hooks" / "session_log.py").is_file())
        settings = json.loads(
            (installed / "settings.local.json").read_text(encoding="utf-8"))
        for event in ("PostToolUse", "Stop"):
            commands = [
                hook.get("command", "")
                for entry in settings["hooks"].get(event, [])
                for hook in entry.get("hooks", [])
                if "session_log.py" in hook.get("command", "")
            ]
            with self.subTest(event=event):
                self.assertEqual(len(commands), 1, commands)

    def test_with_session_log_installs_and_wires_the_hook(self):
        result = self.install("--with-session-log")

        self.assertEqual(result.returncode, 0, result.stderr)
        installed = self.proj / ".claude"
        self.assertTrue((installed / "hooks" / "session_log.py").is_file())
        settings = json.loads(
            (installed / "settings.local.json").read_text(encoding="utf-8"))
        for event in ("PostToolUse", "Stop"):
            with self.subTest(event=event):
                commands = [
                    hook.get("command", "")
                    for entry in settings["hooks"].get(event, [])
                    for hook in entry.get("hooks", [])
                ]
                self.assertTrue(
                    any("session_log.py" in c for c in commands),
                    f"{event} に session_log.py が配線されていない")

    def test_unknown_option_is_rejected(self):
        result = self.install("--with-sesion-log")  # typo は黙って無視しない

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(list((self.proj / ".claude").iterdir()), [])

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
    """ログが git に載らないための助言が、実際に効く内容になっているか

    助言は session_log を入れたときだけ意味を持つので --with-session-log で走らせる。
    """

    def test_ignored_log_dir_is_reported_as_safe(self):
        self._git("init", "-q", ".")
        (self.proj / ".gitignore").write_text(".claude/log/\n")

        out = self.install("--with-session-log").stdout

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

        out = self.install("--with-session-log").stdout

        self.assertIn("ALREADY TRACKED", out)
        self.assertIn("git rm -r --cached .claude/log", out)

    def test_default_install_stays_silent_about_logs(self):
        # session_log を入れていないのに log の警告を出すと、利用者は
        # 存在しないフックを探すことになる。
        self._git("init", "-q", ".")

        out = self.install().stdout

        self.assertNotIn("NOT git-ignored", out)
        self.assertIn("opt in", out)


if __name__ == "__main__":
    unittest.main()
