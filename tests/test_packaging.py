#!/usr/bin/env python3
"""配布物の整合テスト

スキルを足す/消すたびに install.sh と README の更新を忘れる。
静かに壊れるので、リポジトリのレイアウトを唯一の正として突き合わせる。

テストは対象コードの隣に置く方針なので、スイートが 3 ディレクトリに分かれる。
`-s tests` だけでは hooks/ の 100 件超が走らない。全部走らせるコマンド:

  for d in tests hooks benchmarks; do python3 -m unittest discover -s $d -p 'test_*.py' || break; done

TEST_DIRS がその一覧で、4 つ目が増えたら test_all_test_dirs_are_known が落ちる。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import mutants  # noqa: E402  変異レジストリを唯一の正として読む
SKILLS_DIR = ROOT / "skills"
# 走らせるべきテストディレクトリ。モジュール docstring のコマンドと同じ並び。
TEST_DIRS = ("tests", "hooks", "benchmarks")
INSTALL_SH = (ROOT / "install.sh").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _bash_array(name: str) -> list[str]:
    """install.sh の `NAME=( "a" "b" )` を読む。"""
    block = re.search(rf"^\s*{name}=\((.*?)\)", INSTALL_SH, re.DOTALL | re.MULTILINE)
    assert block, f"{name} array not found in install.sh"
    return re.findall(r'"([^"]+)"', block.group(1))


def skill_dirs() -> list[Path]:
    return sorted(p.parent for p in SKILLS_DIR.glob("*/SKILL.md"))


CHECK_SH = (ROOT / "check.sh").read_text(encoding="utf-8")
CI_YML = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def _usage_commands() -> list[str]:
    """install.sh の Usage ブロックが宣伝しているコマンド名。"""
    block = re.search(r'info "Usage:"(.*?)info "Session logs', INSTALL_SH, re.DOTALL)
    assert block, "Usage block not found in install.sh"
    return re.findall(r'^\s*echo "\s+(\S+)', block.group(1), re.MULTILINE)


def _readme_hook_config() -> dict:
    """README が手動インストール手順でコピーさせるフック設定。

    README は settings.local.json 全体を載せるので、install.sh の HOOKS_CONFIG と
    そろえるために hooks の中身だけを返す。
    """
    block = re.search(r"```json\n(\{.*?\n\})\n```", README, re.DOTALL)
    assert block, "README does not document the hook configuration"
    return json.loads(block.group(1))["hooks"]


def _installer_hook_config() -> dict:
    """install.sh が settings.local.json にマージするフック設定。"""
    block = re.search(r"HOOKS_CONFIG='(.*?)'", INSTALL_SH, re.DOTALL)
    assert block, "HOOKS_CONFIG not found in install.sh"
    return json.loads(block.group(1))


def frontmatter_name(skill_md: Path) -> str:
    text = skill_md.read_text(encoding="utf-8")
    match = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)
    assert match, f"{skill_md} has no frontmatter"
    name = re.search(r"^name:\s*(\S+)\s*$", match.group(1), re.MULTILINE)
    assert name, f"{skill_md} frontmatter has no name"
    return name.group(1)


class SkillLayoutTest(unittest.TestCase):
    def test_frontmatter_name_matches_directory(self):
        for skill in skill_dirs():
            with self.subTest(skill=skill.name):
                self.assertEqual(frontmatter_name(skill / "SKILL.md"), skill.name)

    def test_no_nested_skills(self):
        # サブディレクトリに SKILL.md を置くと install.sh の対応漏れが起きる。
        # フェーズ手順は references/*.md（スキルではない）に置くこと。
        nested = [p for p in SKILLS_DIR.glob("*/*/SKILL.md")]
        self.assertEqual(nested, [], f"nested SKILL.md found: {nested}")

    def test_reference_files_are_not_skills(self):
        for ref in SKILLS_DIR.glob("*/references/*.md"):
            with self.subTest(ref=str(ref)):
                self.assertFalse(
                    ref.read_text(encoding="utf-8").startswith("---\nname:"),
                    f"{ref} looks like a skill; reference docs must not declare name:",
                )

    def test_skill_body_stays_readable(self):
        # 長い SKILL.md は文脈で薄まり、後半のフェーズが無視される。
        # 詳細は参照ファイルへ逃がす。
        for skill in skill_dirs():
            lines = len((skill / "SKILL.md").read_text(encoding="utf-8").splitlines())
            with self.subTest(skill=skill.name):
                self.assertLessEqual(lines, 300, f"{skill.name}/SKILL.md is {lines} lines")


class InstallScriptTest(unittest.TestCase):
    def setUp(self):
        self.entries = [e.split("|") for e in _bash_array("SKILLS")]

    def test_entries_point_at_real_files(self):
        for source, _, files in self.entries:
            for name in files.split(","):
                with self.subTest(path=f"{source}/{name}"):
                    self.assertTrue((SKILLS_DIR / source / name).is_file())

    def test_every_skill_is_installed(self):
        installed = {e[0] for e in self.entries}
        self.assertEqual({s.name for s in skill_dirs()}, installed)

    def test_install_names_are_unique(self):
        names = [e[1] for e in self.entries]
        self.assertEqual(len(names), len(set(names)))

    def test_removed_skills_are_cleaned_up(self):
        # 旧バージョンのスキルが残ると発火が競合する。
        removed = _bash_array("REMOVED_SKILLS")
        self.assertTrue(removed)
        live = {e[1] for e in self.entries}
        self.assertFalse(live & set(removed), "a skill is both installed and removed")

    def test_hook_files_exist(self):
        for hook in _bash_array("HOOK_FILES"):
            with self.subTest(hook=hook):
                self.assertTrue((ROOT / "hooks" / hook).is_file())

    def test_hook_timeouts_are_seconds(self):
        # Claude Code の timeout は「秒」。ms のつもりで 5000 と書くと
        # ハングしたフックが 83 分セッションを止める。
        # 配布物だけでなく、このリポジトリ自身の開発ハーネスも対象にする。
        harness = (ROOT / ".claude" / "settings.json").read_text(encoding="utf-8")
        for source in (README, INSTALL_SH, harness):
            for value in re.findall(r'"timeout":\s*(\d+)', source):
                with self.subTest(timeout=value):
                    self.assertLessEqual(int(value), 60)

    def test_readme_hook_config_matches_installer(self):
        # 手動インストールした利用者だけ設定が古い、という壊れ方をする。
        self.assertEqual(_readme_hook_config(), _installer_hook_config())

    def test_configured_hooks_are_shipped(self):
        # README 全体ではなく設定ブロックだけを見る。アンインストール手順は
        # 配布を終えた wise_mode.py を今も名前で挙げている。
        config = json.dumps(_readme_hook_config())
        for hook in set(re.findall(r"\.claude/hooks/(\w+\.py)", config)):
            with self.subTest(hook=hook):
                self.assertIn(hook, _bash_array("HOOK_FILES"))
                self.assertIn(hook, INSTALL_SH)

    def test_usage_block_matches_installed_skills(self):
        # インストーラの Usage が、消したスキルを宣伝したり、入れたスキルを
        # 隠したりする。SKILLS 配列を唯一の正として突き合わせる。
        advertised = set(_usage_commands())
        installed = {f"/{e[1]}" for e in self.entries}
        self.assertEqual(advertised, installed)


class TestLayoutTest(unittest.TestCase):
    def test_all_test_dirs_are_known(self):
        # スイートが増えたのに実行コマンドが追従しないと、静かにテストが走らなくなる。
        found = {
            p.parent.relative_to(ROOT).as_posix()
            for p in ROOT.glob("*/test_*.py")
            if not p.parent.name.startswith(".")
        }
        self.assertEqual(found, set(TEST_DIRS))

    def test_check_sh_runs_every_suite(self):
        # check.sh が検証範囲の唯一の正。4 つ目のスイートを足して
        # ここに通さなければ、CI も Stop ゲートも黙ってそれを走らせない。
        for name in TEST_DIRS:
            with self.subTest(dir=name):
                self.assertIn(name, CHECK_SH)


class SingleCheckEntrypointTest(unittest.TestCase):
    """検証コマンドが 1 つであり続けるか

    手で組み立て直せる状態だと、その都度「どこまで見たか」が実行者の裁量になる。
    CI・README・Stop ゲートが同じ 1 本を指していることを固定する。
    """

    def test_ci_calls_check_sh(self):
        # 「どこかに ./check.sh がある」では不足。回帰ジョブを潰しても監査ジョブの
        # 記述が残って通ってしまう（変異監査が実際にこれを見つけた）。
        # 実行されるコマンドとして 2 つとも在ることを見る。
        runs = [r.strip() for r in re.findall(r"run:\s*(\./check\.sh.*)", CI_YML)]
        self.assertIn("./check.sh", runs, "回帰ジョブ（引数なし）が無い")
        self.assertIn("./check.sh --mutants", runs, "変異監査ジョブが無い")
        # CI が独自にチェックを並べ直していないこと（check.sh を迂回する層を作らない）
        self.assertNotIn("unittest discover", CI_YML)

    def test_readme_documents_check_sh(self):
        self.assertIn("./check.sh", README)

    def test_tests_that_spawn_check_sh_carry_a_recursion_guard(self):
        # このセッションで 4 回、テストがテストランナーを呼んで無限再帰した。
        # 毎回「今回は大丈夫」と思って書いている。クラスごと機械的に止める。
        # 判定は「起動しているか」。単に名前に言及したコメントで発火すると
        # 誰も読まなくなる（bash4 検査で同じ偽陽性を踏んだ）。
        for path in sorted((ROOT / "tests").glob("test_*.py")):
            source = path.read_text(encoding="utf-8")
            if '"./check.sh"' not in source:
                continue
            with self.subTest(test=path.name):
                self.assertIn(
                    "WISE_MODE_CHECK_SELFTEST", source,
                    f"{path.name} は check.sh を起動するのに再帰よけの印が無い。"
                    "子に環境変数を渡し、印があるテストは skip すること")

    def test_mutation_registry_is_not_empty(self):
        self.assertGreater(len(mutants.MUTANTS), 20, "変異レジストリが痩せている")

    def test_every_mutation_targets_text_that_still_exists(self):
        # リファクタで「置換前」が消えると、その変異は黙って無効になる
        # （監査は STALE と言うが、CI を通す前に気づきたい）。
        for name, rel, before, _after, test_dir, module in mutants.MUTANTS:
            with self.subTest(mutant=name):
                path = ROOT / rel
                self.assertTrue(path.is_file(), f"{rel} が無い")
                occurrences = path.read_text(encoding="utf-8").count(before)
                self.assertEqual(
                    occurrences, 1,
                    f"{name}: 「置換前」が {occurrences} 箇所。0 なら前提崩れ、"
                    "2 以上なら別の場所を書き換えて『効いていないのに緑』になる"
                    "（mutants.py 自身を対象にした変異で実際に起きた）")
                self.assertTrue((ROOT / test_dir / f"{module}.py").is_file(),
                                f"{name}: 対象モジュール {test_dir}/{module}.py が無い")

    def test_mutation_names_are_unique(self):
        names = [m[0] for m in mutants.MUTANTS]
        self.assertEqual(len(names), len(set(names)))

    def test_check_sh_exposes_the_audit(self):
        self.assertIn("--mutants", CHECK_SH)
        self.assertIn("--mutants", CI_YML, "CI が変異監査を回していない")

    def test_shell_scripts_avoid_bash4_and_gnu_only_constructs(self):
        # 開発機は bash 3.2、CI は bash 5。CI では通ってローカルで落ちる。
        # 実際 mapfile を書いて macOS で落ちた。timeout も stock macOS に無い。
        # 判定対象はコードだけ — 「使うな」と書いたコメントに反応しては困る。
        scripts = [ROOT / "check.sh", ROOT / "install.sh"]
        scripts += sorted(SKILLS_DIR.glob("*/scripts/*.sh"))
        for script in scripts:
            code = "\n".join(line for line in script.read_text(encoding="utf-8").splitlines()
                             if not line.lstrip().startswith("#"))
            for construct in ("mapfile ", "readarray ", "declare -A", "${!", "timeout "):
                with self.subTest(script=script.name, construct=construct):
                    self.assertNotIn(construct, code,
                                     f"{construct.strip()} は bash 4+ / GNU 依存")

    def test_suites_run_under_a_timeout(self):
        # 再帰バグは無言の停止として出る。落ちてくれないと原因が分からない。
        self.assertIn("SUITE_TIMEOUT", CHECK_SH)
        self.assertIn("TimeoutExpired", CHECK_SH)

    def test_execution_loop_names_both_layers(self):
        # CLAUDE.md の実行ループが「検証コマンド」を抽象的に書いていると、
        # 何を回すかが毎回実行者の裁量になる。回帰と実行観察は別物なので
        # 両方を名指しさせる。
        loop = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("./check.sh", loop, "回帰ゲートのコマンドが名指しされていない")
        self.assertIn("/verify", loop, "実行観察の層が名指しされていない")

    def test_stop_gate_calls_check_sh(self):
        gate = ROOT / ".claude" / "hooks" / "check_gate.py"
        self.assertTrue(gate.is_file(), "Stop ゲートが無い")
        self.assertIn("check.sh", gate.read_text(encoding="utf-8"))

    # このテストは check.sh を子プロセスで起動する。その子も tests/ を走らせる
    # ので、ガードが無いと check.sh → このテスト → check.sh … と無限に再帰する
    # （実際に踏んだ）。子には印を渡し、印がある側では実行しない。
    SELFTEST_ENV = "WISE_MODE_CHECK_SELFTEST"

    @unittest.skipIf(os.environ.get(SELFTEST_ENV), "check.sh の内側では再帰するので走らせない")
    def test_check_sh_reports_failure(self):
        # `|| break` が 0 を返すのと同型の罠。落ちるべきときに落ちるかは
        # 実際に壊して走らせないと分からない。
        with tempfile.TemporaryDirectory() as tmpdir:
            copy = Path(tmpdir) / "repo"
            shutil.copytree(ROOT, copy,
                            ignore=shutil.ignore_patterns(".git", "__pycache__"))
            (copy / "benchmarks" / "test_zz_injected.py").write_text(
                "import unittest\n"
                "class T(unittest.TestCase):\n"
                "    def test_injected_failure(self):\n"
                "        self.fail('injected')\n",
                encoding="utf-8",
            )
            result = subprocess.run(
                ["./check.sh", "--fast"], cwd=copy, capture_output=True, text=True,
                timeout=180, env={**os.environ, self.SELFTEST_ENV: "1"},
            )

        self.assertNotEqual(result.returncode, 0, "壊れたスイートで PASS を返した")
        self.assertIn("FAIL", result.stdout)


class ReadmeTest(unittest.TestCase):
    def test_every_skill_is_documented(self):
        for skill in skill_dirs():
            with self.subTest(skill=skill.name):
                self.assertIn(f"**{skill.name}**", README)

    def test_uninstall_lists_every_installed_skill(self):
        # `rm -rf .claude/skills/{a,b,c}` は手書きの一覧で、スキルを足し引き
        # しても誰も直さない。消し忘れたスキルは発火し続ける。
        block = re.search(r"rm -rf \.claude/skills/\{([^}]*)\}", README)
        self.assertIsNotNone(block, "Uninstall のスキル一覧が見つからない")
        listed = {name.strip() for name in block.group(1).split(",")}
        self.assertEqual(listed, {s.name for s in skill_dirs()})

    def test_no_dead_skill_references(self):
        # README が消したスキルの curl 手順を残していないか
        for name in _bash_array("REMOVED_SKILLS"):
            with self.subTest(skill=name):
                self.assertNotIn(f"skills/{name}/SKILL.md", README)

    def test_manual_install_covers_every_shipped_file(self):
        # 参照ファイルを増やすと install.sh は直しても README の手動手順を忘れる。
        # curl を 1 本落とした利用者は、読めない参照を指すスキルを手に入れる。
        for entry in _bash_array("SKILLS"):
            source, _, files = entry.split("|")
            for name in files.split(","):
                with self.subTest(file=f"{source}/{name}"):
                    self.assertIn(Path(name).stem, README)


class CiIsReachableTest(unittest.TestCase):
    """CI が追跡されているか

    `.gitignore` の `.*` は `.github/` も除外する。`!.github/` を落とすと
    ワークフローが untracked になり、**CI が黙って消える**。そうなると他の
    ガードも全部止まるので、ここが根元の単一障害点になる。
    """

    # (パス, 追跡されるべきか)。`.*` に食われて黙って共有されなくなるものと、
    # 逆に間違って共有されてはいけないローカル状態の両方を押さえる。
    PATHS = (
        (".github/workflows/ci.yml", True),
        (".claude/skills/verify/SKILL.md", True),
        (".claude/settings.local.json", False),
        (".claude/log/session.md", False),
        (".claude/flow/plan.md", False),
        (".claude/.wise-mode", False),
    )

    def test_gitignore_tracks_what_must_be_shared(self):
        # このリポジトリ自体が git リポジトリとは限らないので、使い捨ての
        # リポジトリに .gitignore だけ移して git 本体に判定させる。
        self.assertTrue((ROOT / ".github" / "workflows" / "ci.yml").is_file())
        self.assertTrue((ROOT / ".claude" / "skills" / "verify" / "SKILL.md").is_file())

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            subprocess.run(["git", "init", "-q", str(tmp)], check=True)
            shutil.copy(ROOT / ".gitignore", tmp / ".gitignore")
            for rel, _ in self.PATHS:
                path = tmp / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()

            for rel, should_track in self.PATHS:
                ignored = subprocess.run(
                    ["git", "-C", str(tmp), "check-ignore", "-q", rel]
                ).returncode == 0
                with self.subTest(path=rel):
                    if should_track:
                        self.assertFalse(
                            ignored, f"{rel} が gitignore されている。共有されない"
                        )
                    else:
                        self.assertTrue(
                            ignored, f"{rel} は各自のローカル状態。共有してはいけない"
                        )


class SkillToolPermissionTest(unittest.TestCase):
    """allowed-tools が、その SKILL.md 自身が指示するコマンドを許可しているか"""

    # 引数なしで意味を持つ読み取り専用コマンド。`Bash(git diff *)` だけ書くと
    # 素の `git diff` が許可されず、スキル本文の指示が権限確認で止まる。
    BARE_FORMS = ("git diff", "git status", "git log")

    def _allowed_tools(self, skill: Path) -> list[str]:
        text = (skill / "SKILL.md").read_text(encoding="utf-8")
        front = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL).group(1)
        block = re.search(r"^allowed-tools:(.*?)(?=^\w|\Z)", front, re.DOTALL | re.MULTILINE)
        return re.findall(r"Bash\(([^)]+)\)", block.group(1)) if block else []

    def test_wildcard_git_entries_have_a_bare_counterpart(self):
        for skill in skill_dirs():
            entries = set(self._allowed_tools(skill))
            if not entries:
                continue  # allowed-tools 無し = 全ツール許可
            for bare in self.BARE_FORMS:
                if f"{bare} *" in entries:
                    with self.subTest(skill=skill.name, command=bare):
                        self.assertIn(
                            bare,
                            entries,
                            f"{skill.name}: `Bash({bare} *)` はあるが `Bash({bare})` が無い",
                        )


class ModeVocabularyTest(unittest.TestCase):
    """継続モードの表示マーカーが 4 箇所で一致しているか

    フック・wise・wise-cont・wise-help が同じ 3 種類を指示していないと、
    継続セッションの途中で語彙が変わる。正典であるはずの wise/SKILL.md だけが
    Q&A を持っていない状態が実際に残っていた。
    """

    MARKERS = ("[WISE MODE: Q&A]", "[WISE MODE: LIGHT]", "[WISE MODE] Phase N")
    SOURCES = (
        "hooks/mode_persistence.py",
        "skills/wise/SKILL.md",
        "skills/wise-cont/SKILL.md",
    )

    def test_every_source_declares_the_same_markers(self):
        for source in self.SOURCES:
            text = (ROOT / source).read_text(encoding="utf-8")
            for marker in self.MARKERS:
                with self.subTest(source=source, marker=marker):
                    self.assertIn(marker, text)


class SwarmRunnerTemplateTest(unittest.TestCase):
    """swarm が配る run.sh のひな型が、失敗した wave で止まるか

    裸の `wait` は必ず 0 を返す。`set -euo pipefail` があっても失敗が素通りし、
    integrator が壊れた成果物の上で「完了」を宣言する。Markdown の中の
    テンプレートなので、抜き出して実際に走らせる以外に検査手段が無い。
    """

    def _template(self) -> str:
        text = (SKILLS_DIR / "swarm" / "SKILL.md").read_text(encoding="utf-8")
        block = re.search(r"```bash\n(#!/usr/bin/env bash\n.*?)```", text, re.DOTALL)
        assert block, "swarm/SKILL.md に run.sh のひな型が見つからない"
        return block.group(1)

    def test_template_is_valid_bash(self):
        proc = subprocess.run(["bash", "-n"], input=self._template(),
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_template_fails_when_an_agent_fails(self):
        # claude を「1 体目だけ失敗する」スタブに差し替えて実行する。
        runner = self._template().replace(
            'claude -p "$(cat .swarm/agents/agent-a.md)"', "false"
        ).replace(
            'claude -p "$(cat .swarm/agents/agent-b.md)"', "true"
        ).replace(
            'claude -p "$(cat .swarm/agents/integrator.md)"',
            'echo INTEGRATOR_RAN'
        )
        proc = subprocess.run(["bash"], input=runner, capture_output=True, text=True)

        self.assertNotEqual(proc.returncode, 0, "失敗した wave で止まっていない")
        self.assertNotIn(
            "INTEGRATOR_RAN", proc.stdout,
            "失敗した wave の上で integrator が走っている",
        )


if __name__ == "__main__":
    unittest.main()
