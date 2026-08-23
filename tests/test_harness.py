#!/usr/bin/env python3
"""開発用ハーネス（.claude/hooks/）のテスト

ゲート自身にバグがあると、赤いまま通すか、緑なのに永久にブロックするかの
どちらかになる。前者は無意味、後者はセッションを人質に取る。判定部分は
副作用のない関数に切り出してあるので、そこを直接検査する。

配布物ではないので install.sh の対象外。テストだけ tests/ に置く
（`.claude/` 配下は unittest discover が拾わない）。
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / ".claude" / "hooks"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, HOOKS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load("check_gate")
lint = _load("lint_on_edit")
surface_notice = gate.surface_notice


class _Verify:
    """呼ばれた回数を数える check スタブ。status は pass/fail/inconclusive。"""

    def __init__(self, status: str, output: str = "boom"):
        self.status, self.output, self.calls = status, output, 0

    def __call__(self):
        self.calls += 1
        return self.status, self.output


class GateDecisionTest(unittest.TestCase):
    def test_green_allows_stop_and_records_fingerprint(self):
        run = _Verify("pass")
        code, message, state = gate.decide({}, "abc", run)

        self.assertEqual(code, 0)
        self.assertEqual(message, "")
        self.assertEqual(state["green_fingerprint"], "abc")
        self.assertEqual(state["attempts"], 0)

    def test_red_blocks_the_stop(self):
        code, message, state = gate.decide({}, "abc", _Verify("fail"))

        self.assertEqual(code, 2, "赤いのに停止を許した")
        self.assertIn("Do not report this work as complete", message)
        self.assertEqual(state["attempts"], 1)

    def test_third_consecutive_failure_hands_back(self):
        # 三回直せないなら診断が間違っている。人質にせず人間に渡す。
        code, message, state = gate.decide({"attempts": 2}, "abc", _Verify("fail"))

        self.assertEqual(code, 0, "3 回目でも降参していない")
        self.assertIn("handing back", message)
        self.assertEqual(state["attempts"], 0, "カウンタが戻っていない")

    def test_unchanged_source_skips_the_run(self):
        # 会話だけのターンで毎回 20 秒使わないための最適化。
        run = _Verify("pass")
        code, _, _ = gate.decide({"green_fingerprint": "abc"}, "abc", run)

        self.assertEqual(code, 0)
        self.assertEqual(run.calls, 0, "変更が無いのに check.sh を走らせた")

    def test_changed_source_runs_again(self):
        run = _Verify("pass")
        gate.decide({"green_fingerprint": "old"}, "new", run)
        self.assertEqual(run.calls, 1)

    def test_no_git_always_verifies(self):
        # fingerprint が取れない環境で「変更なし」と誤判定して素通りさせない。
        run = _Verify("pass")
        gate.decide({"green_fingerprint": None}, None, run)
        self.assertEqual(run.calls, 1)

    def test_failure_output_is_carried_into_the_message(self):
        _, message, _ = gate.decide({}, "abc", _Verify("fail", "AssertionError: nope"))
        self.assertIn("AssertionError: nope", message)

    def test_inconclusive_is_not_recorded_as_green(self):
        # 実際に踏んだバグ: timeout を「合格」に丸めていたため、遅い環境で
        # 1 回タイムアウトしただけで緑の fingerprint が保存され、以降ゲートが
        # 検証を永久にスキップした。判定不能は合格ではない。
        code, message, state = gate.decide({}, "abc", _Verify("inconclusive", "timed out"))

        self.assertEqual(code, 0, "セッションを止めてはいけない")
        self.assertNotIn("green_fingerprint", state,
                         "判定不能を緑として記録した — ゲートが無効化される")
        self.assertIn("do not treat this as green", message.lower())

    def test_inconclusive_then_change_still_verifies(self):
        # 判定不能の次のターンで必ずもう一度試みること。
        _, _, state = gate.decide({}, "abc", _Verify("inconclusive"))
        run = _Verify("fail")
        code, _, _ = gate.decide(state, "abc", run)

        self.assertEqual(run.calls, 1, "判定不能の後にスキップした")
        self.assertEqual(code, 2)

    def test_inconclusive_does_not_consume_an_attempt(self):
        # 環境要因のタイムアウトで「3 回失敗」を使い切らせない。
        _, _, state = gate.decide({"attempts": 1}, "abc", _Verify("inconclusive"))
        self.assertEqual(state.get("attempts"), 1)


class SourceFingerprintTest(unittest.TestCase):
    """fingerprint は check.sh が実際に見るものを全部見ること

    check.sh のテスト発見はファイルシステム走査なので、未追跡の test_*.py も
    実行される。fingerprint が追跡ファイルしか見ないと「緑の記録後に未追跡
    ファイルだけを壊した」状態で digest が変わらず、ゲートが検証をスキップして
    緑のまま停止を許す。
    """

    def _repo(self, tmpdir: str) -> Path:
        root = Path(tmpdir)
        subprocess.run(["git", "init", "-q"], cwd=tmpdir, check=True)
        (root / "a.py").write_text("x = 1\n", encoding="utf-8")
        subprocess.run(["git", "add", "a.py"], cwd=tmpdir, check=True)
        return root

    def test_untracked_files_change_the_fingerprint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = self._repo(tmpdir)
            before = gate.source_fingerprint(root)
            (root / "test_new.py").write_text("boom\n", encoding="utf-8")
            after = gate.source_fingerprint(root)
        self.assertIsNotNone(before)
        self.assertNotEqual(before, after, "未追跡ファイルが fingerprint の盲点")

    def test_ignored_files_do_not_change_the_fingerprint(self):
        # .gitignore 対象まで数えると、ログや一時成果物が増えるたびに約 20 秒の
        # 再検証が走る。--exclude-standard を外してはいけない。
        with tempfile.TemporaryDirectory() as tmpdir:
            root = self._repo(tmpdir)
            (root / ".gitignore").write_text("*.log\n", encoding="utf-8")
            subprocess.run(["git", "add", ".gitignore"], cwd=tmpdir, check=True)
            before = gate.source_fingerprint(root)
            (root / "noise.log").write_text("x\n", encoding="utf-8")
            after = gate.source_fingerprint(root)
        self.assertEqual(before, after, "ignore 済みファイルで再検証が走る")


class SurfaceNoticeTest(unittest.TestCase):
    """「テストは緑だが実際には一度も走らせていない」を 1 度だけ知らせる

    回帰ゲートは「壊れていないか」しか答えない。このセッションで見つかった
    「追跡済みログには .gitignore が効かない」はどのテストにも引っかからず、
    インストーラを実際に走らせて初めて出た。その層があることを忘れさせない。
    """

    def test_first_run_records_silently(self):
        notice, state = surface_notice({}, {"install.sh": "a"})
        self.assertEqual(notice, "", "初回から催促している")
        self.assertEqual(state["surfaces"], {"install.sh": "a"})

    def test_changed_surface_is_named(self):
        before = {"surfaces": {"install.sh": "a", "hooks/x.py": "b"}}
        notice, state = surface_notice(before, {"install.sh": "CHANGED",
                                                "hooks/x.py": "b"})
        self.assertIn("install.sh", notice)
        self.assertNotIn("hooks/x.py", notice, "変わっていない面まで挙げている")
        self.assertIn("/verify", notice)

    def test_same_change_is_not_repeated(self):
        _, state = surface_notice({"surfaces": {"install.sh": "a"}},
                                  {"install.sh": "b"})
        notice, _ = surface_notice(state, {"install.sh": "b"})
        self.assertEqual(notice, "", "同じ変更で二度催促している")

    def test_unchanged_surfaces_are_silent(self):
        state = {"surfaces": {"install.sh": "a"}}
        notice, _ = surface_notice(state, {"install.sh": "a"})
        self.assertEqual(notice, "")

    def test_docs_and_tests_are_not_runtime_surfaces(self):
        # /verify 自身が docs-only は SKIP と言っている。Markdown を面に数えると
        # プロンプトを 1 行直すたびに催促が出て、通知そのものが無視される。
        # テストも面ではない — 走らせるのは check.sh の仕事。
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "skills" / "wise" / "scripts").mkdir(parents=True)
            (root / "skills" / "wise" / "SKILL.md").write_text("x")
            (root / "skills" / "wise" / "scripts" / "run.sh").write_text("x")
            (root / "README.md").write_text("x")
            (root / "install.sh").write_text("x")
            (root / "hooks").mkdir()
            (root / "hooks" / "real.py").write_text("x")
            (root / "hooks" / "test_real.py").write_text("x")  # 面ではない

            surfaces = gate.runtime_surfaces(root)

        self.assertIn("install.sh", surfaces)
        self.assertIn("hooks/real.py", surfaces)
        self.assertIn("skills/wise/scripts/run.sh", surfaces)
        self.assertNotIn("README.md", surfaces)
        self.assertNotIn("skills/wise/SKILL.md", surfaces)
        self.assertNotIn("hooks/test_real.py", surfaces, "テストを面に数えている")

    def test_surfaces_survive_the_decide_rebuild(self):
        # `decide` は自分のキーだけで state を作り直す。繰り越しを落とすと
        # 毎回「初回」扱いになり、通知が一度も出なくなる（実装中に踏んだ）。
        previous = {"surfaces": {"install.sh": "a"}, "green_fingerprint": "old"}
        _, _, rebuilt = gate.decide(previous, "new", _Verify("pass"))
        self.assertNotIn("surfaces", rebuilt, "前提が変わった: decide が保持している")

        carried = gate.carry_forward(previous, rebuilt)
        self.assertEqual(carried["surfaces"], {"install.sh": "a"})

        notice, _ = surface_notice(carried, {"install.sh": "CHANGED"})
        self.assertIn("install.sh", notice, "繰り越しが効かず初回扱いになっている")

    def test_carry_forward_handles_a_first_run(self):
        # 初回は previous が空。無条件に previous["surfaces"] を読むと
        # KeyError で落ち、トップの except に飲まれて黙って何もしなくなる。
        carried = gate.carry_forward({}, {"attempts": 0})
        self.assertEqual(carried, {"attempts": 0})

    def test_carry_forward_does_not_resurrect_green_fingerprint(self):
        # 判定不能のとき、次のターンで必ず再検証させるために捨てている。
        previous = {"green_fingerprint": "abc", "surfaces": {}}
        carried = gate.carry_forward(previous, {"attempts": 0})
        self.assertNotIn("green_fingerprint", carried)

    def test_notice_never_changes_the_exit_code(self):
        # 通知は stdout。ここが exit に影響すると停止できなくなる。
        code, message, _ = gate.decide({"surfaces": {"install.sh": "old"}}, "abc",
                                       _Verify("pass"))
        self.assertEqual(code, 0)
        self.assertEqual(message, "")


class GateSafetyTest(unittest.TestCase):
    """どんな入力でもセッションを壊さないこと"""

    def _run(self, payload: str, cwd: Path) -> subprocess.CompletedProcess:
        # CLAUDE_PROJECT_DIR は継承される。消さないと、隔離したはずの一時
        # ディレクトリではなく本物のリポジトリを検証しにいく（＝再帰）。
        env = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDE_PROJECT_DIR", gate.RECURSION_ENV)}
        return subprocess.run(
            ["python3", str(HOOKS / "check_gate.py")], input=payload,
            cwd=str(cwd), capture_output=True, text=True, timeout=120, env=env,
        )

    def test_recursion_guard_short_circuits(self):
        # check.sh の内側から呼ばれたら即 0。これが無いと止まらない。
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                ["python3", str(HOOKS / "check_gate.py")],
                input=json.dumps({"cwd": str(ROOT)}), cwd=tmpdir,
                capture_output=True, text=True, timeout=30,
                env={**os.environ, gate.RECURSION_ENV: "1"},
            )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stderr, "", "再帰ガードが働かず検証を始めた")

    def test_audit_in_progress_makes_the_gate_inconclusive(self):
        # ゲートは毎ターン自動で走る。監査中のツリーは一時的に変異しているので、
        # そのまま検証すると嘘の失敗でセッションを止める。
        # ヘルパーではなく**呼び出し側の配線**を通すこと — 初版はヘルパーだけを
        # 見ていて、分岐を潰しても緑のままだった。
        lock = Path(gate.audit_lock_path(ROOT))
        state = ROOT / ".claude" / ".check-gate"
        saved = state.read_text(encoding="utf-8") if state.is_file() else None
        lock.write_text(str(os.getpid()), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k != gate.RECURSION_ENV}
        env["CLAUDE_PROJECT_DIR"] = str(ROOT)
        try:
            result = subprocess.run(
                ["python3", str(HOOKS / "check_gate.py")],
                input=json.dumps({"cwd": str(ROOT)}), cwd=str(ROOT),
                capture_output=True, text=True, timeout=120, env=env)
        finally:
            lock.unlink(missing_ok=True)
            if saved is None:
                state.unlink(missing_ok=True)
            else:
                state.write_text(saved, encoding="utf-8")

        self.assertEqual(result.returncode, 0, "監査中に停止をブロックしてはいけない")
        self.assertIn("mutation audit is running", result.stderr)
        self.assertIn("do not treat this as green", result.stderr.lower())

    def test_garbage_stdin_allows_stop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = self._run("not json", Path(tmpdir))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_project_without_check_sh_allows_stop(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            payload = json.dumps({"cwd": tmpdir})
            result = self._run(payload, Path(tmpdir))
        self.assertEqual(result.returncode, 0, result.stderr)


class LintOnEditTest(unittest.TestCase):
    def test_broken_python_is_reported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "broken.py"
            path.write_text("def f(:\n")
            self.assertIn("SyntaxError", lint.check(path))

    def test_valid_python_is_silent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "fine.py"
            path.write_text("x = 1\n")
            self.assertEqual(lint.check(path), "")

    def test_broken_shell_is_reported(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "broken.sh"
            path.write_text("if [ 1 -eq 1 ]; then\necho hi\n")  # fi が無い
            self.assertNotEqual(lint.check(path), "")

    def test_unrelated_extension_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "notes.md"
            path.write_text("# hi\n")
            self.assertEqual(lint.check(path), "")

    def test_missing_file_does_not_raise(self):
        lint.main(json.dumps({"tool_input": {"file_path": "/nope/gone.py"}}))

    def test_payload_without_file_path_does_not_raise(self):
        lint.main(json.dumps({"tool_input": {"command": "ls"}}))
        lint.main("not json")


if __name__ == "__main__":
    unittest.main()
