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
import time
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


README_JA = (ROOT / "README.ja.md").read_text(encoding="utf-8")
CHECK_SH = (ROOT / "check.sh").read_text(encoding="utf-8")
CI_YML = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def _usage_commands() -> list[str]:
    """install.sh の Usage ブロックが宣伝しているコマンド名。"""
    block = re.search(r'info "Usage:"(.*?)info "Session logs', INSTALL_SH, re.DOTALL)
    assert block, "Usage block not found in install.sh"
    return re.findall(r'^\s*echo "\s+(\S+)', block.group(1), re.MULTILINE)


def _readme_hook_configs() -> list[dict]:
    """README が手動インストール手順でコピーさせるフック設定(登場順)。

    README は settings.local.json 全体を載せるので、install.sh の設定と
    そろえるために hooks の中身だけを返す。1 つ目がデフォルト、2 つ目が
    opt-in の session_log。
    """
    blocks = re.findall(r"```json\n(\{.*?\n\})\n```", README, re.DOTALL)
    assert blocks, "README does not document the hook configuration"
    return [json.loads(block)["hooks"] for block in blocks]


def _readme_hook_config() -> dict:
    return _readme_hook_configs()[0]


def _installer_hook_config() -> dict:
    """install.sh が settings.local.json にマージするフック設定。"""
    block = re.search(r"HOOKS_CONFIG='(.*?)'", INSTALL_SH, re.DOTALL)
    assert block, "HOOKS_CONFIG not found in install.sh"
    return json.loads(block.group(1))


def _installer_session_log_config() -> dict:
    """install.sh が --with-session-log で追加マージするフック設定。"""
    block = re.search(r"SESSION_LOG_HOOKS_CONFIG='(.*?)'", INSTALL_SH, re.DOTALL)
    assert block, "SESSION_LOG_HOOKS_CONFIG not found in install.sh"
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

    def test_side_effect_workflows_require_explicit_invocation(self):
        for name in (
            "wise", "wise-flow", "swarm", "wise-cont",
            "terse-mode",
        ):
            with self.subTest(skill=name):
                source = (SKILLS_DIR / name / "SKILL.md").read_text(encoding="utf-8")
                frontmatter = source.split("---\n", 2)[1]
                self.assertIn("disable-model-invocation: true", frontmatter)

    def test_wise_never_stashes_the_users_worktree(self):
        sources = [
            (SKILLS_DIR / "wise" / "SKILL.md").read_text(encoding="utf-8"),
            (SKILLS_DIR / "wise" / "CHECKLISTS.md").read_text(encoding="utf-8"),
        ]
        self.assertNotIn("git stash", "\n".join(sources))

    def test_wise_opens_a_pr_only_on_explicit_request(self):
        source = (SKILLS_DIR / "wise" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Open the PR only when the user explicitly", source)


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

    def test_readme_session_log_config_matches_installer(self):
        # opt-in 側の設定ブロックも同じようにずれる。README の 2 つ目の
        # json ブロックが SESSION_LOG_HOOKS_CONFIG と一致すること。
        configs = _readme_hook_configs()
        self.assertGreaterEqual(len(configs), 2,
                                "README に opt-in session_log の設定ブロックが無い")
        self.assertEqual(configs[1], _installer_session_log_config())

    def test_default_hook_config_omits_session_log(self):
        # session_log は明示 opt-in。デフォルト設定に紛れ込むと全員に配線される。
        self.assertNotIn("session_log", json.dumps(_installer_hook_config()))

    def test_removed_skills_deletion_is_gated_by_the_prompt(self):
        # 廃止スキルの削除は無言で行わない。存在すれば EXISTING=1 に合流させ、
        # 上書き確認と同じプロンプトで同意を取る。プロンプト経路自体の実行は
        # pty が要るのでここでは扱わず(モジュール docstring 参照)、構造を
        # 固定する: 警告 → EXISTING=1 → プロンプトの順。
        marker = ('warn "Retired skills present; continuing will remove them:'
                  '${REMOVED_PRESENT}"')
        self.assertIn(marker, INSTALL_SH)
        self.assertIn(marker + "\n        EXISTING=1", INSTALL_SH)
        self.assertLess(INSTALL_SH.index(marker),
                        INSTALL_SH.index("Overwrite? [y/N]"))

    def test_reproducible_recipe_pins_the_installer_to_the_same_ref(self):
        # mutable main の install.sh に固定 archive を渡すと、インストーラの
        # manifest と archive の中身が食い違う(実再現: 現行インストーラ +
        # 直前 commit の archive で 3 ファイル欠けて終了 1)。reproducible
        # 手順はインストーラと archive を同じ ref から取る。
        for source in (README, INSTALL_SH):
            with self.subTest(source="README" if source is README else "install.sh"):
                self.assertIn(
                    'raw.githubusercontent.com/den-emon/wise-mode/${REF}/install.sh',
                    source)
                self.assertIn('WISE_MODE_REF="${REF}"', source)

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

    def test_check_sh_exposes_the_evals(self):
        # スキル挙動の実測入口。課金される実 API 呼び出しなので CI には入れない
        # — CI_YML への追加はここでは要求しない。
        self.assertIn('exec python3 tools/evals.py', CHECK_SH)

    def test_shell_scripts_avoid_bash4_and_gnu_only_constructs(self):
        # 開発機は bash 3.2、CI は bash 5。CI では通ってローカルで落ちる。
        # 実際 mapfile を書いて macOS で落ちた。timeout も stock macOS に無い。
        # 判定対象はコードだけ — 「使うな」と書いたコメントに反応しては困る。
        scripts = [ROOT / "check.sh", ROOT / "install.sh", ROOT / "uninstall.sh"]
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

    def test_execution_loop_names_check_entrypoint(self):
        # CLAUDE.md の実行ループが「検証コマンド」を抽象的に書いていると、
        # 何を回すかが毎回実行者の裁量になる。唯一の入口を名指しさせる。
        loop = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("./check.sh", loop, "回帰ゲートのコマンドが名指しされていない")

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


class ReadmeJaTest(unittest.TestCase):
    """日本語版 README が英語版・installer から乖離しないための機械検証。

    翻訳の等価性は機械で測れないので、測れる不変条件だけを固定する:
    スキルの網羅、アンインストール一覧、フック設定ブロック、手動インストール
    の配布ファイル網羅、相互リンク。
    """

    def test_language_versions_link_to_each_other(self):
        self.assertIn("README.ja.md", README)
        self.assertIn("(README.md)", README_JA)

    def test_every_skill_is_documented(self):
        for skill in skill_dirs():
            with self.subTest(skill=skill.name):
                self.assertIn(f"**{skill.name}**", README_JA)

    def test_uninstall_lists_every_installed_skill(self):
        block = re.search(r"rm -rf \.claude/skills/\{([^}]*)\}", README_JA)
        self.assertIsNotNone(block, "Uninstall のスキル一覧が見つからない")
        listed = {name.strip() for name in block.group(1).split(",")}
        self.assertEqual(listed, {s.name for s in skill_dirs()})

    def test_hook_configs_match_installer(self):
        blocks = re.findall(r"```json\n(\{.*?\n\})\n```", README_JA, re.DOTALL)
        self.assertGreaterEqual(len(blocks), 2,
                                "フック設定の json ブロックが足りない")
        self.assertEqual(json.loads(blocks[0])["hooks"], _installer_hook_config())
        self.assertEqual(json.loads(blocks[1])["hooks"],
                         _installer_session_log_config())

    def test_manual_install_covers_every_shipped_file(self):
        for entry in _bash_array("SKILLS"):
            source, _, files = entry.split("|")
            for name in files.split(","):
                with self.subTest(file=f"{source}/{name}"):
                    self.assertIn(Path(name).stem, README_JA)

    def test_reproducible_recipe_pins_the_installer_to_the_same_ref(self):
        self.assertIn(
            'raw.githubusercontent.com/den-emon/wise-mode/${REF}/install.sh',
            README_JA)
        self.assertIn('WISE_MODE_REF="${REF}"', README_JA)


class UninstallScriptParityTest(unittest.TestCase):
    """install.sh と uninstall.sh の manifest がドリフトしないよう機械で固定する。

    片方にスキルやフックを足して片方を忘れると、アンインストールが黙って
    残す。実行時の挙動は tests/test_uninstall.py — ここは静的なパリティのみ。
    """

    def setUp(self):
        self.source = (ROOT / "uninstall.sh").read_text(encoding="utf-8")

    def _array(self, name: str) -> list[str]:
        block = re.search(rf"^\s*{name}=\((.*?)\)", self.source,
                          re.DOTALL | re.MULTILINE)
        self.assertIsNotNone(block, f"{name} array not found in uninstall.sh")
        return re.findall(r'"([^"]+)"', block.group(1))

    def test_skill_dirs_match_install_manifest(self):
        install_names = [e.split("|")[1] for e in _bash_array("SKILLS")]
        self.assertEqual(sorted(self._array("SKILL_DIRS")), sorted(install_names))

    def test_removed_skills_match_install_manifest(self):
        self.assertEqual(sorted(self._array("REMOVED_SKILLS")),
                         sorted(_bash_array("REMOVED_SKILLS")))

    def test_hook_files_cover_everything_install_places(self):
        # SESSION_LOG_HOOK は opt-in の単独変数なので配列には出ない。
        placeable = set(_bash_array("HOOK_FILES")) | {"session_log.py"}
        self.assertEqual(set(self._array("HOOK_FILES")), placeable)

    def test_canonical_commands_cover_everything_install_wires(self):
        # 配線解除は完全一致で行う(部分一致は第三者 hook を巻き込む)ので、
        # install が書くコマンド文字列が 1 つでも漏れると外れない。
        written = set()
        for config in (_installer_hook_config(), _installer_session_log_config()):
            for entries in config.values():
                for entry in entries:
                    for hook in entry.get("hooks", []):
                        written.add(hook["command"])
        block = re.search(r"CANONICAL_COMMANDS='(\[.*?\])'", self.source, re.DOTALL)
        self.assertIsNotNone(block, "CANONICAL_COMMANDS not found in uninstall.sh")
        canonical = set(json.loads(block.group(1)))
        self.assertTrue(written <= canonical,
                        f"uninstall が外さない配線: {sorted(written - canonical)}")


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

    # 引数なしで本文が実行するコマンド。`Bash(git diff *)` だけ書いても
    # 素の `git diff` は許可されず、スキル本文の指示が権限確認で止まる。
    BARE_FORMS = (
        "git diff", "git status", "git log",
        "npm test", "npm run lint", "npm run build",
        "pnpm test", "pnpm lint", "pnpm build",
        "yarn test", "yarn lint", "yarn build",
        "cargo test", "cargo clippy",
        "yarn audit", "pip-audit", "bundle audit", "cargo audit",
    )

    def _allowed_tools(self, skill: Path) -> list[str]:
        text = (skill / "SKILL.md").read_text(encoding="utf-8")
        front = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL).group(1)
        block = re.search(r"^allowed-tools:(.*?)(?=^\w|\Z)", front, re.DOTALL | re.MULTILINE)
        return re.findall(r"Bash\(([^)]+)\)", block.group(1)) if block else []

    def test_wildcard_entries_used_bare_have_a_bare_counterpart(self):
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
        text = (SKILLS_DIR / "swarm" / "references" /
                "methodology.md").read_text(encoding="utf-8")
        block = re.search(r"```bash\n(#!/usr/bin/env bash\n.*?)```", text, re.DOTALL)
        assert block, "swarm/references/methodology.md に run.sh のひな型が見つからない"
        return block.group(1)

    def test_template_is_valid_bash(self):
        proc = subprocess.run(["bash", "-n"], input=self._template(),
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_template_fails_when_an_agent_fails(self):
        # claude を「1 体目だけ失敗する」スタブに差し替えて実行する。
        runner = self._template().replace(
            'claude -p --permission-mode acceptEdits "$(cat .swarm/agents/agent-a.md)"',
            "false",
        ).replace(
            'claude -p --permission-mode acceptEdits "$(cat .swarm/agents/agent-b.md)"',
            "true",
        ).replace(
            'claude -p --permission-mode acceptEdits --allowedTools "Bash(npm test)" "Bash(npm test *)" < .swarm/agents/integrator.md',
            'echo INTEGRATOR_RAN'
        )
        proc = subprocess.run(["bash"], input=runner, capture_output=True, text=True)

        self.assertNotEqual(proc.returncode, 0, "失敗した wave で止まっていない")
        self.assertNotIn(
            "INTEGRATOR_RAN", proc.stdout,
            "失敗した wave の上で integrator が走っている",
        )

    def test_template_reaps_every_agent_before_returning_failure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            marker = Path(tmpdir) / "second-finished"
            runner = self._template().replace(
                'claude -p --permission-mode acceptEdits "$(cat .swarm/agents/agent-a.md)"',
                "false",
            ).replace(
                'claude -p --permission-mode acceptEdits "$(cat .swarm/agents/agent-b.md)"',
                '(sleep 0.25; printf done > "$SWARM_MARKER") >/dev/null 2>&1',
            ).replace(
                'claude -p --permission-mode acceptEdits --allowedTools "Bash(npm test)" "Bash(npm test *)" < .swarm/agents/integrator.md',
                'echo INTEGRATOR_RAN',
            )
            proc = subprocess.run(
                ["bash"], input=runner, capture_output=True, text=True,
                env={**os.environ, "SWARM_MARKER": str(marker)},
            )
            reaped = marker.is_file()
            if not reaped:
                # A broken runner has left the second agent behind; let it finish
                # before TemporaryDirectory removes its destination.
                time.sleep(0.3)

        self.assertNotEqual(proc.returncode, 0)
        self.assertTrue(reaped, "runner 終了後も別 agent が動き続けている")

    def test_integrator_brief_is_supplied_on_stdin_after_variadic_tools(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            agents = root / ".swarm" / "agents"
            agents.mkdir(parents=True)
            (agents / "agent-a.md").write_text("worker a", encoding="utf-8")
            (agents / "agent-b.md").write_text("worker b", encoding="utf-8")
            (agents / "integrator.md").write_text(
                "INTEGRATOR_BRIEF", encoding="utf-8")
            fake_bin = root / "bin"
            fake_bin.mkdir()
            claude = fake_bin / "claude"
            claude.write_text(
                "#!/usr/bin/env bash\n"
                "case \" $* \" in\n"
                "  *\" --allowedTools \"*) input=$(cat) ;;\n"
                "  *) exit 0 ;;\n"
                "esac\n"
                "for arg in \"$@\"; do\n"
                "  case \"$arg\" in *INTEGRATOR_BRIEF*) exit 91 ;; esac\n"
                "done\n"
                "case \"$input\" in\n"
                "  *INTEGRATOR_BRIEF*) exit 0 ;;\n"
                "  *) exit 92 ;;\n"
                "esac\n",
                encoding="utf-8",
            )
            claude.chmod(0o755)

            proc = subprocess.run(
                ["bash"], input=self._template(), cwd=root,
                capture_output=True, text=True,
                env={**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}"},
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_template_stops_background_agents_on_term(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            started = root / "started"
            stopped = root / "stopped"
            pid_file = root / "pid"
            runner = self._template().replace(
                'claude -p --permission-mode acceptEdits "$(cat .swarm/agents/agent-a.md)" & pids+=($!)',
                'sh -c \'trap "printf stopped > "$SWARM_STOPPED"; exit 0" TERM; '
                'printf "$$" > "$SWARM_PID"; printf started > "$SWARM_STARTED"; '
                'while :; do sleep 0.1; done\' & pids+=($!)',
            ).replace(
                'claude -p --permission-mode acceptEdits "$(cat .swarm/agents/agent-b.md)" & pids+=($!)',
                'true & pids+=($!)',
            ).replace(
                'claude -p --permission-mode acceptEdits --allowedTools "Bash(npm test)" "Bash(npm test *)" < .swarm/agents/integrator.md',
                'echo INTEGRATOR_RAN',
            )
            proc = subprocess.Popen(
                ["bash"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, text=True, cwd=root,
                env={**os.environ, "SWARM_STARTED": str(started),
                     "SWARM_STOPPED": str(stopped), "SWARM_PID": str(pid_file)},
            )
            try:
                assert proc.stdin
                proc.stdin.write(runner)
                proc.stdin.close()
                for _ in range(50):
                    if started.is_file():
                        break
                    time.sleep(0.02)
                self.assertTrue(started.is_file(), "background agent did not start")
                proc.terminate()
                proc.wait(timeout=3)
            finally:
                if pid_file.is_file() and not stopped.is_file():
                    try:
                        os.kill(int(pid_file.read_text()), 9)
                    except (OSError, ValueError):
                        pass
            stopped_cleanly = stopped.is_file()

        self.assertTrue(stopped_cleanly, "TERM left a background agent running")

    def test_template_force_stops_term_ignoring_agent_within_bound(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            started = root / "stubborn-started"
            pid_file = root / "stubborn-pid"
            runner = self._template().replace(
                'claude -p --permission-mode acceptEdits "$(cat .swarm/agents/agent-a.md)" & pids+=($!)',
                'sh -c \'trap "" TERM; printf "$$" > "$SWARM_PID"; '
                'printf started > "$SWARM_STARTED"; '
                'while :; do sleep 0.1; done\' & pids+=($!)',
            ).replace(
                'claude -p --permission-mode acceptEdits "$(cat .swarm/agents/agent-b.md)" & pids+=($!)',
                'true & pids+=($!)',
            ).replace(
                'claude -p --permission-mode acceptEdits --allowedTools "Bash(npm test)" "Bash(npm test *)" < .swarm/agents/integrator.md',
                'echo INTEGRATOR_RAN',
            )
            proc = subprocess.Popen(
                ["bash"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, text=True, cwd=root,
                env={**os.environ, "SWARM_STARTED": str(started),
                     "SWARM_PID": str(pid_file)},
            )
            child_pid = None
            try:
                assert proc.stdin
                proc.stdin.write(runner)
                proc.stdin.close()
                for _ in range(100):
                    if started.is_file() and pid_file.is_file():
                        break
                    time.sleep(0.02)
                self.assertTrue(started.is_file(), "stubborn agent did not start")
                child_pid = int(pid_file.read_text())
                started_at = time.monotonic()
                proc.terminate()
                proc.wait(timeout=5)
                elapsed = time.monotonic() - started_at
                self.assertEqual(proc.returncode, 143)
                self.assertLess(elapsed, 4.0, "cancellation exceeded its bound")
                with self.assertRaises(ProcessLookupError):
                    os.kill(child_pid, 0)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                if child_pid is not None:
                    try:
                        os.kill(child_pid, 9)
                    except ProcessLookupError:
                        pass

    def test_template_stops_integrator_on_term(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            started = root / "integrator-started"
            stopped = root / "integrator-stopped"
            pid_file = root / "integrator-pid"
            runner = self._template().replace(
                'claude -p --permission-mode acceptEdits "$(cat .swarm/agents/agent-a.md)"',
                "true",
            ).replace(
                'claude -p --permission-mode acceptEdits "$(cat .swarm/agents/agent-b.md)"',
                "true",
            ).replace(
                'claude -p --permission-mode acceptEdits --allowedTools "Bash(npm test)" "Bash(npm test *)" < .swarm/agents/integrator.md & pids=("$!")',
                'sh -c \'trap "printf stopped > "$SWARM_STOPPED"; exit 0" TERM; '
                'printf "$$" > "$SWARM_PID"; printf started > "$SWARM_STARTED"; '
                'while :; do sleep 0.1; done\' & pids=("$!")',
            )
            proc = subprocess.Popen(
                ["bash"], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, text=True, cwd=root,
                env={**os.environ, "SWARM_STARTED": str(started),
                     "SWARM_STOPPED": str(stopped), "SWARM_PID": str(pid_file)},
            )
            try:
                assert proc.stdin
                proc.stdin.write(runner)
                proc.stdin.close()
                for _ in range(50):
                    if started.is_file():
                        break
                    time.sleep(0.02)
                self.assertTrue(started.is_file(), "integrator did not start")
                proc.terminate()
                proc.wait(timeout=3)
            finally:
                if pid_file.is_file() and not stopped.is_file():
                    try:
                        os.kill(int(pid_file.read_text()), 9)
                    except (OSError, ValueError):
                        pass
            stopped_cleanly = stopped.is_file()

        self.assertTrue(stopped_cleanly, "TERM left the integrator running")

    def test_template_propagates_integrator_failure(self):
        runner = self._template().replace(
            'claude -p --permission-mode acceptEdits "$(cat .swarm/agents/agent-a.md)"',
            "true",
        ).replace(
            'claude -p --permission-mode acceptEdits "$(cat .swarm/agents/agent-b.md)"',
            "true",
        ).replace(
            'claude -p --permission-mode acceptEdits --allowedTools "Bash(npm test)" "Bash(npm test *)" < .swarm/agents/integrator.md',
            "false",
        )

        proc = subprocess.run(["bash"], input=runner, capture_output=True, text=True)

        self.assertNotEqual(proc.returncode, 0)

    def test_template_removes_reaped_worker_pids(self):
        self.assertIn('pids=("${pids[@]:1}")', self._template())

class DiffAcquisitionInstructionsTest(unittest.TestCase):
    SOURCE = (SKILLS_DIR / "pr-self-review" / "references" /
              "diff-acquisition.md").read_text(encoding="utf-8")

    def test_head_route_includes_tracked_worktree_changes(self):
        self.assertIn('git diff "$BASE_REF"', self.SOURCE)

    def test_head_route_includes_untracked_files(self):
        self.assertIn("git ls-files --others --exclude-standard", self.SOURCE)
        self.assertIn('git diff --no-index -- /dev/null "$path"', self.SOURCE)

class WiseFlowFingerprintTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = (SKILLS_DIR / "wise-flow" / "SKILL.md").read_text(encoding="utf-8")
        marker = "The state fingerprint is the worktree identity:"
        block = re.search(r"```bash\n(.*?)```", source[source.index(marker):], re.DOTALL)
        assert block, "wise-flow の fingerprint コマンドが見つからない"
        cls.script = block.group(1)

    def _fingerprint(self, cwd: Path) -> str:
        proc = subprocess.run(
            ["bash"], input=self.script, cwd=cwd,
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout.strip()

    def test_content_change_changes_fingerprint_without_status_change(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"],
                           cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
            tracked = repo / "tracked.txt"
            tracked.write_text("base\n")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)

            tracked.write_text("version one\n")
            first = self._fingerprint(repo)
            tracked.write_text("version two\n")
            second = self._fingerprint(repo)

        self.assertNotEqual(first, second)

    def test_untracked_content_and_non_git_state_are_distinct(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "t@example.com"],
                           cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
            tracked = repo / "tracked.txt"
            tracked.write_text("base\n")
            subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
            untracked = repo / "new.txt"
            untracked.write_text("version one\n")
            first = self._fingerprint(repo)
            untracked.write_text("version two\n")
            second = self._fingerprint(repo)

        self.assertNotEqual(first, second)

        with tempfile.TemporaryDirectory() as outside:
            unknown = self._fingerprint(Path(outside))
        self.assertEqual(unknown, "unknown")


class WiseFlowHandoffContractTest(unittest.TestCase):
    def test_handoff_uses_the_declared_artifact_path(self):
        source = (SKILLS_DIR / "wise-flow" / "references" /
                  "handoff.md").read_text(encoding="utf-8")
        self.assertIn("Save the note to `.claude/flow/handoff.md`", source)
        self.assertNotIn("temporary directory", source)


if __name__ == "__main__":
    unittest.main()
