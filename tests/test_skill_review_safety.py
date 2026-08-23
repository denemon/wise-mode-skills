#!/usr/bin/env python3
"""Review-gate skill contracts added after real bypasses were reproduced."""

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = ROOT / "skills"


class ExplicitInvocationTest(unittest.TestCase):
    def test_descriptions_match_explicit_only_policy(self):
        for name in (
            "wise", "wise-flow", "swarm", "wise-cont",
            "terse-mode", "attack-on-hacker",
        ):
            with self.subTest(skill=name):
                frontmatter = (SKILLS / name / "SKILL.md").read_text(
                    encoding="utf-8").split("---\n", 2)[1]
                self.assertIn("Invoke only through", frontmatter)
                self.assertIn("disable-model-invocation: true", frontmatter)


class AllowedToolsSyntaxTest(unittest.TestCase):
    def test_scalar_values_use_space_separation(self):
        for skill_md in SKILLS.glob("*/SKILL.md"):
            frontmatter = skill_md.read_text(encoding="utf-8").split("---\n", 2)[1]
            scalar = re.search(r"^allowed-tools:\s+(.+)$", frontmatter, re.MULTILINE)
            if scalar:
                with self.subTest(skill=skill_md.parent.name):
                    self.assertNotIn(",", scalar.group(1))

    def test_side_effect_workflows_do_not_preapprove_bare_bash(self):
        for name in ("wise", "wise-flow", "wise-cont"):
            with self.subTest(skill=name):
                frontmatter = (SKILLS / name / "SKILL.md").read_text(
                    encoding="utf-8").split("---\n", 2)[1]
                self.assertNotIn("allowed-tools:", frontmatter)

    def test_security_review_does_not_preapprove_mutating_commands(self):
        frontmatter = (SKILLS / "attack-on-hacker" / "SKILL.md").read_text(
            encoding="utf-8").split("---\n", 2)[1]

        for unsafe in (
            "Bash(find *)", "Bash(npm audit *)", "Bash(pnpm audit *)",
            "Bash(semgrep *)", "Bash(pip-audit *)", "Bash(cargo audit *)",
            "Bash(detect-secrets *)", "Bash(safety *)",
            # フラグ 1 つで write / execute プリミティブに化けるツール。
            # 唯一の防壁が fail-open な flag_guard になるため事前承認しない。
            "Bash(rg", "Bash(gosec *)", "Bash(trufflehog *)",
            "Bash(gitleaks *)", "Bash(checkov *)", "Bash(tfsec *)",
            "Bash(bandit *)",
            # ranged 形はフラグまで承認する。--output / --ext-diff は
            # write / execute、`bundle audit update` は advisory DB を更新、
            # `yarn audit --mutex` はファイル書き込み/ポート待受け、
            # `--out${GAP}put` の展開で文字列レベルのガードは迂回される。
            "Bash(git diff *)", "Bash(git log *)", "Bash(bundle audit *)",
            "Bash(yarn audit *)",
        ):
            self.assertNotIn(unsafe, frontmatter)

    def test_preapproved_commands_are_pinned_to_documented_forms(self):
        attack = (SKILLS / "attack-on-hacker" / "SKILL.md").read_text(
            encoding="utf-8").split("---\n", 2)[1]
        flow = (SKILLS / "wise-flow" / "SKILL.md").read_text(
            encoding="utf-8").split("---\n", 2)[1]
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        # `rg --pre <cmd>` はファイルごとに任意コマンドを実行する。どの形の
        # rg も事前承認しない — 検索は許可済みの組み込み Grep ツールで足り、
        # フラグで実行プリミティブに化けるコマンドの唯一の防壁を fail-open な
        # hook にしない。
        self.assertNotIn("Bash(rg", attack)
        # ai_review.sh は外部へ diff を送る。allowed-tools に載せると確認なしで
        # 実行可能になり、本文の「ユーザー承認後のみ」が権限境界にならない
        # （--diff-file は任意ファイル、--allow-sensitive-content は秘密検査を
        # 無効化する）。毎回の Bash 権限プロンプトを境界にするため、
        # independent-review ゲートを持つ wise-flow はどの形も事前承認しない。
        self.assertNotIn("ai_review.sh", flow)
        self.assertNotIn("allowed-tools:", flow)
        # prefix-match はフラグを検査できない。残余リスクは README の脅威モデル
        # として明記し、指示レベルの安全と混同させない。
        self.assertIn("cannot inspect flags", readme)

    def test_review_skills_do_not_preapprove_unneeded_git_mutation(self):
        pr_frontmatter = (SKILLS / "pr-self-review" / "SKILL.md").read_text(
            encoding="utf-8").split("---\n", 2)[1]

        self.assertNotIn("Bash(git branch *)", pr_frontmatter)

    def test_pr_review_does_not_preapprove_writable_git_forms(self):
        # read-only を名乗るスキルが `git diff --output=<file>` で任意ファイルを
        # 作れる形を事前承認しない。attack-on-hacker が ranged 形を除外したのと
        # 同じ理由: --output / --ext-diff は write / execute に化け、prefix-match
        # はフラグを見られない。素の flagless 形だけ残し、ranged 形は毎回の
        # 権限プロンプトに戻す。
        pr_frontmatter = (SKILLS / "pr-self-review" / "SKILL.md").read_text(
            encoding="utf-8").split("---\n", 2)[1]
        body = (SKILLS / "pr-self-review" / "SKILL.md").read_text(
            encoding="utf-8").split("---\n", 2)[2]

        for unsafe in ("Bash(git diff *)", "Bash(git log *)", "Bash(git show *)"):
            self.assertNotIn(unsafe, pr_frontmatter)
        for required in ("Bash(git diff)", "Bash(git log)", "Bash(git status *)"):
            self.assertIn(required, pr_frontmatter)
        # 本文が ranged 形のプロンプトを前提として明記していること。
        self.assertIn("ranged 形は毎回の権限プロンプト", body)

    def test_security_review_preapproves_required_diff_and_audit_commands(self):
        frontmatter = (SKILLS / "attack-on-hacker" / "SKILL.md").read_text(
            encoding="utf-8").split("---\n", 2)[1]
        quick_wins = (SKILLS / "attack-on-hacker" / "references" /
                      "quick-wins.md").read_text(encoding="utf-8")

        for required in (
            "Bash(git merge-base *)", "Bash(yarn audit)", "Bash(pip-audit)",
            "Bash(bundle audit)", "Bash(cargo audit)",
            # ranged 形の削除後も、引数なしの素の形は本文の指示が使う。
            "Bash(git diff)", "Bash(git log)",
        ):
            self.assertIn(required, frontmatter)
        self.assertIn("`gosec ./...`", quick_wins)

    def test_secret_sweep_command_keeps_identifier_only_flag(self):
        # 下の実行テストは rg が無い環境(Claude Code は rg をシェル関数と
        # してのみ公開する)では skip される。skip 環境でも変異監査が緑に
        # ならないよう、値ではなく識別子だけを出力させる -o は静的にも固定する。
        quick_wins = (SKILLS / "attack-on-hacker" / "references" /
                      "quick-wins.md").read_text(encoding="utf-8")
        command = re.search(
            r"Code identifiers only: `([^`]+)`", quick_wins).group(1)

        self.assertIn(" -o ", command)

    # The documented command needs a real ripgrep binary. Claude Code exposes
    # `rg` only as a shell function, so subprocess.run() cannot see it there.
    @unittest.skipUnless(shutil.which("rg"), "rg not installed (CI runs it)")
    def test_security_review_secret_search_does_not_print_values(self):
        quick_wins = (SKILLS / "attack-on-hacker" / "references" /
                      "quick-wins.md").read_text(encoding="utf-8")
        command = re.search(
            r"Code identifiers only: `([^`]+)`", quick_wins).group(1)
        secret = "do-not-copy-this-credential-48d9"

        with tempfile.TemporaryDirectory() as tmpdir:
            Path(tmpdir, "config.txt").write_text(
                f"API_KEY={secret}\n", encoding="utf-8")
            result = subprocess.run(
                shlex.split(command), cwd=tmpdir,
                capture_output=True, text=True,
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("API_KEY", result.stdout)
        self.assertNotIn(secret, result.stdout)
        self.assertNotIn("git log --all -p", quick_wins)


class DiffAcquisitionTest(unittest.TestCase):
    def test_wise_reuses_the_head_route(self):
        for relative in ("SKILL.md", "PATTERNS.md"):
            source = (SKILLS / "wise" / relative).read_text(encoding="utf-8")
            with self.subTest(source=relative):
                self.assertIn("/pr-self-review", source)
                self.assertNotIn("git diff main...HEAD", source)

    def test_security_diff_routes_include_untracked_files(self):
        sources = (
            SKILLS / "attack-on-hacker" / "references" / "diff-mode.md",
            SKILLS / "wise-flow" / "references" / "security-gate.md",
        )
        for path in sources:
            source = path.read_text(encoding="utf-8")
            with self.subTest(source=str(path.relative_to(ROOT))):
                self.assertIn("git ls-files --others --exclude-standard", source)
                self.assertIn('git diff --no-index -- /dev/null "$path"', source)

    def test_security_diff_checks_reuse_the_acquired_diff(self):
        source = (SKILLS / "attack-on-hacker" / "references" /
                  "diff-mode.md").read_text(encoding="utf-8")

        self.assertIn("same acquired diff", source)
        self.assertIn("TARGET_REF", source)
        self.assertNotIn("git diff <base>...HEAD", source)

    def test_wise_flow_security_references_resolve_in_both_layouts(self):
        gate = (SKILLS / "wise-flow" / "references" /
                "security-gate.md").read_text(encoding="utf-8")
        references = (
            ("skills/pr-self-review/references/diff-acquisition.md",
             ".claude/skills/pr-self-review/references/diff-acquisition.md"),
            ("skills/attack-on-hacker/references/diff-mode.md",
             ".claude/skills/attack-on-hacker/references/diff-mode.md"),
        )

        for repository_path, installed_path in references:
            with self.subTest(reference=repository_path):
                self.assertTrue((ROOT / repository_path).is_file())
                self.assertIn(f"`{repository_path}`", gate)
                self.assertIn(f"`{installed_path}`", gate)

    def test_security_gate_preserves_canonical_finding_fields(self):
        gate = (SKILLS / "wise-flow" / "references" /
                "security-gate.md").read_text(encoding="utf-8")
        output = gate.split("## Output", 1)[1]
        for field in (
            "Title", "Severity", "Location", "CWE", "CVSS (estimate)",
            "Attacker profile", "Preconditions", "Source → Sink",
            "Sanitizers observed", "Evidence", "Impact", "Fix",
            "Verification",
        ):
            with self.subTest(field=field):
                self.assertRegex(output, rf"(?m)^- {re.escape(field)}:")
        self.assertRegex(output, r"(?m)^- Classification:")


class SideEffectScopeTest(unittest.TestCase):
    def test_swarm_agents_have_noninteractive_edit_permission(self):
        source = (SKILLS / "swarm" / "references" /
                  "methodology.md").read_text(encoding="utf-8")
        block = re.search(r"```bash\n(#!/usr/bin/env bash\n.*?)```", source, re.DOTALL)
        self.assertIsNotNone(block)
        commands = [line for line in block.group(1).splitlines()
                    if line.startswith("claude -p")]
        self.assertEqual(len(commands), 3)
        for command in commands:
            self.assertIn("--permission-mode acceptEdits", command)
            self.assertNotIn("bypassPermissions", command)
        integrator = commands[-1]
        self.assertIn('--allowedTools "Bash(npm test)"', integrator)
        self.assertIn('"Bash(npm test *)"', integrator)
        self.assertTrue(
            integrator.endswith(
                '< .swarm/agents/integrator.md & pids=("$!")'), integrator)
        self.assertNotIn("$(cat .swarm/agents/integrator.md)", integrator)

    def test_wise_flow_requires_explicit_delegation(self):
        parent = (SKILLS / "wise-flow" / "SKILL.md").read_text(encoding="utf-8")
        recon = (SKILLS / "wise-flow" / "references" / "source-recon.md").read_text(
            encoding="utf-8")
        plan = (SKILLS / "wise-flow" / "references" / "plan.md").read_text(
            encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("Authorization Invariants (MANDATORY)", parent)
        self.assertIn("only if the user explicitly requested delegation", parent)
        self.assertIn("delegation_requested: yes/no", recon)
        self.assertIn("do not infer delegation", plan)
        self.assertIn("If `delegation_requested` is not `yes`", plan)
        self.assertIn("Explicit delegation request with separable write scopes", readme)
        self.assertNotIn("optional swarm", parent)

    def test_wise_flow_delegates_via_side_effect_free_references(self):
        # attack-on-hacker と swarm は disable-model-invocation: true —
        # 公式仕様上ユーザーだけが起動できるので、wise-flow が「スキルを
        # 実行しろ」と書いても委譲は成立しない。方法論を権限を付与しない
        # 共通 reference に抽出し、双方(ユーザー向けコマンドと wise-flow)が
        # それを読む。reference はスキルではなく、allowed-tools を持たない。
        gate = (SKILLS / "wise-flow" / "references" /
                "security-gate.md").read_text(encoding="utf-8")
        flow = (SKILLS / "wise-flow" / "SKILL.md").read_text(encoding="utf-8")

        for repository_path, installed_path in (
            ("skills/attack-on-hacker/references/methodology.md",
             ".claude/skills/attack-on-hacker/references/methodology.md"),
            ("skills/swarm/references/methodology.md",
             ".claude/skills/swarm/references/methodology.md"),
        ):
            with self.subTest(reference=repository_path):
                self.assertTrue((ROOT / repository_path).is_file())
                methodology = (ROOT / repository_path).read_text(
                    encoding="utf-8")
                self.assertFalse(methodology.startswith("---"))
                self.assertNotIn("allowed-tools:", methodology)
                self.assertIn("side-effect-free", methodology)
        self.assertIn(
            "`skills/attack-on-hacker/references/methodology.md`", gate)
        self.assertIn(
            "`.claude/skills/attack-on-hacker/references/methodology.md`", gate)
        self.assertNotIn("Run the `attack-on-hacker` skill", gate)
        self.assertIn("`skills/swarm/references/methodology.md`", flow)
        self.assertIn("`.claude/skills/swarm/references/methodology.md`", flow)
        self.assertNotIn("Run `swarm`", flow)
        # ユーザー向けコマンド側も同じ reference を正として指す。
        attack_skill = (SKILLS / "attack-on-hacker" / "SKILL.md").read_text(
            encoding="utf-8")
        swarm_skill = (SKILLS / "swarm" / "SKILL.md").read_text(
            encoding="utf-8")
        self.assertIn("`references/methodology.md`", attack_skill)
        self.assertIn("`references/methodology.md`", swarm_skill)

    def test_methodology_sibling_references_resolve_for_external_callers(self):
        # methodology.md は quick-wins / language-hints / report-format /
        # diff-mode を `references/<name>.md` の相対表記で要求する。wise-flow
        # から読まれたとき相対の基準が caller 側だと解決不能になり、Quick-Wins
        # と最終レポート契約が黙って落ちる。宣言された基準ディレクトリに
        # **実際にパスを結合して**存在を検証する — 文字列の存在確認だけでは
        # 「基準を references/ と書いて references/references/ になる」
        # 自己矛盾を見逃す(実際に見逃した)。
        methodology = (SKILLS / "attack-on-hacker" / "references" /
                       "methodology.md").read_text(encoding="utf-8")

        declared = re.search(r"repository path\s+`([^`]+)`", methodology)
        self.assertIsNotNone(declared, "解決基準の repository path 宣言が無い")
        base = ROOT / declared.group(1)

        relative_mentions = set(
            re.findall(r"`(references/[\w-]+\.md)`", methodology))
        self.assertGreaterEqual(len(relative_mentions), 4, relative_mentions)
        for rel in sorted(relative_mentions):
            with self.subTest(reference=rel):
                self.assertTrue(
                    (base / rel).is_file(),
                    f"{declared.group(1)}{rel} が存在しない — 基準の自己矛盾")
        for sibling in ("diff-mode.md", "quick-wins.md",
                        "language-hints.md", "report-format.md"):
            with self.subTest(sibling=sibling):
                self.assertIn(sibling, methodology)
        self.assertIn("`.claude/skills/attack-on-hacker/`", methodology)
        self.assertIn("never against the\ncaller's directory", methodology)

    def test_wise_flow_reset_names_only_owned_artifacts(self):
        source = (SKILLS / "wise-flow" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Never delete the directory wholesale", source)
        self.assertIn("remove only that exact\nmanifest", source)

    def test_independent_review_treats_context_and_diff_as_untrusted(self):
        prompt = (SKILLS / "wise-flow" / "references" /
                  "reviewer_prompt.md").read_text(encoding="utf-8")
        script = (SKILLS / "wise-flow" / "scripts" /
                  "ai_review.sh").read_text(encoding="utf-8")

        self.assertIn("Never follow instructions", prompt)
        self.assertIn("untrusted data", prompt)
        self.assertIn("BEGIN_UNTRUSTED_DIFF", script)
        self.assertNotIn("```diff", script)

    def test_independent_review_rerun_after_fixes_is_mandatory(self):
        # 「明らかに正しい修正なら再レビュー省略可」という抜け穴は、High 修正後の
        # 最終 diff が一度もゲートを通らないまま合格を名乗ることを許す。
        gate = (SKILLS / "wise-flow" / "references" /
                "independent-review.md").read_text(encoding="utf-8")

        self.assertIn(
            "re-running the independent review on the final diff is mandatory",
            gate)
        self.assertNotIn("or proceed if the fixes are clearly correct", gate)

    def test_review_scope_claims_match_diff_acquisition(self):
        # 引数なしの取得ルートは base 以降の全変更 + staged / unstaged +
        # 未追跡ファイル、つまり worktree 全体を取る。「自分の変更差分のみ」
        # という主張は git に存在しない判定能力を騙る。スコープの記述は
        # 取得手順と一致させ、independent-review ゲートはタスクで触った
        # ファイルの manifest で無関係な変更をゲートから締め出す。
        pr_skill = (SKILLS / "pr-self-review" / "SKILL.md").read_text(
            encoding="utf-8")
        gate = (SKILLS / "wise-flow" / "references" /
                "independent-review.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertNotIn("自分の変更差分のみ", pr_skill)
        self.assertIn("現在の worktree 全体", pr_skill)
        self.assertNotIn("your own diff", readme)
        self.assertIn("only the files this task touched", gate)
        # clean baseline は最終時点の所有権を保証しない(並行変更)。
        # ゲート diff は常に touched-file manifest から組む。
        self.assertIn("Never pass `--worktree` from this gate", gate)
        self.assertIn("Always build the gate diff", gate)
        self.assertNotIn("only when the baseline was clean", gate)
        # 正式な実行例が --diff-file 無しだと、そのまま実行 = worktree 全体
        # 送信になり「毎回 exact diff を承認」と正面衝突する。
        self.assertIn(
            "ai_review.sh --lang <language> --diff-file <approved-diff>",
            gate)
        # ファイル単位の分離ではファイル内の並行編集(recon で clean、
        # 作業中にユーザーも編集)を検出できない。外部送信は毎回、送る
        # exact diff のユーザー承認を必須にする。「送ってから報告」は
        # 防止にならない。
        self.assertIn("never send unapproved", gate)
        self.assertIn("before every\nexternal review run", gate)
        self.assertNotIn("note that overlap in the final report", gate)
        # 権限境界は毎回の Bash プロンプト。session-wide allow を求めたり、
        # 秘密検査の override を Claude 自身が付けたりしない — override は
        # ユーザーが直接コマンドを実行する経路だけに残す。
        self.assertIn("deliberately **not**\npreapproved anywhere", gate)
        self.assertIn("no `allowed-tools` at all", gate)
        self.assertIn("Never pass `--allow-sensitive-content` yourself", gate)
        # 外部送信ゲートは明示要求時のみ — wise-flow 本体の Authorization
        # Invariants に載っていること。
        flow = (SKILLS / "wise-flow" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(
            "Run the independent-review gate only when the user explicitly",
            flow)

    def test_benchmark_is_labeled_a_diagnostic_heuristic(self):
        # before/after 比較はタスク難度・人数・コミット分割・メッセージ規約の
        # 影響を除けない。「効果は測定済み」級の主張は、操作可能な
        # ヒューリスティックを証明として売ることになる。
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        bench = (ROOT / "benchmarks" / "README.md").read_text(encoding="utf-8")
        source = (ROOT / "benchmarks" / "fix_follow_rate.py").read_text(
            encoding="utf-8")

        self.assertNotIn("not claimed", readme)
        self.assertIn("a diagnostic, not proof", readme)
        self.assertIn("診断用ヒューリスティック", bench)
        self.assertNotIn("後から改竄できない", bench)
        self.assertIn("診断用ヒューリスティック", source)
        # eval が測るのは invocation とマーカー遵守まで。出力品質は機械判定
        # できないので、「挙動を検証済み」と読める主張はしない。
        self.assertIn("invocation-level checks, not output quality", readme)
        self.assertNotIn("Skill behaviour is checked", readme)
        # 固定 5 ポイント規則は、fix 1 件で率が 10 ポイント以上動く標本と
        # 矛盾する。判定閾値は分母(fix 件数)から導く。
        self.assertNotIn("A gap under 5 points", readme)
        self.assertNotIn("差が 5 ポイント未満", bench)
        self.assertIn("判定の最小差は分母で決める", bench)
        self.assertIn("rate step", bench)

    def test_reviewer_isolation_claims_admit_managed_policy(self):
        # --safe-mode は user/project カスタマイズを外すが、公式仕様上
        # 管理ポリシー由来の settings と hooks は適用されたままになる。
        # 「zero knowledge」「loads no hooks」の絶対断言は管理環境で嘘になる。
        gate = (SKILLS / "wise-flow" / "references" /
                "independent-review.md").read_text(encoding="utf-8")
        script = (SKILLS / "wise-flow" / "scripts" /
                  "ai_review.sh").read_text(encoding="utf-8")

        self.assertIn("admin-managed policy", gate)
        self.assertNotIn("zero knowledge", gate)
        self.assertIn("admin-managed policy", script)

    def test_ai_review_uses_portable_cleaned_temp_files(self):
        script = (SKILLS / "wise-flow" / "scripts" /
                  "ai_review.sh").read_text(encoding="utf-8")

        self.assertNotIn("mktemp /tmp/", script)
        for template in (
            "ai-review-diff.XXXXXX", "ai-review-paths.XXXXXX",
            "ai-review-response.XXXXXX", "ai-review-error.XXXXXX",
            "ai-review-output.XXXXXX",
        ):
            self.assertIn(template, script)
        self.assertLess(
            script.index("trap cleanup EXIT"),
            script.index('DIFF_BUFFER=$(mktemp'),
        )
        self.assertIn("trap 'handle_signal 130 INT' INT", script)
        self.assertIn("trap 'handle_signal 143 TERM' TERM", script)

    def test_wise_flow_context_reuse_is_bound_to_head(self):
        flow = (SKILLS / "wise-flow" / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("<!-- head: <HEAD commit SHA, or \"unknown\"> -->", flow)
        self.assertIn("`task` and `head` match", flow)
        self.assertIn("re-read cited source paths", flow)
        self.assertNotIn("State is irrelevant", flow)

    def test_pr_review_preapproves_untracked_file_listing(self):
        frontmatter = (SKILLS / "pr-self-review" / "SKILL.md").read_text(
            encoding="utf-8").split("---\n", 2)[1]

        self.assertIn("Bash(git ls-files *)", frontmatter)

    def test_verify_recipe_uses_current_review_schema(self):
        verify = (ROOT / ".claude" / "skills" / "verify" /
                  "SKILL.md").read_text(encoding="utf-8")

        for field in ('\\"summary\\"', '\\"score\\"', '\\"coverage\\"',
                      '\\"findings\\"', '\\"positive_notes\\"'):
            self.assertIn(field, verify)

    def test_verify_recipe_prepares_every_prerequisite_before_review(self):
        verify = (ROOT / ".claude" / "skills" / "verify" /
                  "SKILL.md").read_text(encoding="utf-8")
        section = verify.split("## ai_review.sh — fake `claude` on PATH", 1)[1]
        recipe = re.search(r"```bash\n(.*?)```", section, re.DOTALL).group(1)
        review = recipe.index(
            "bash .claude/skills/wise-flow/scripts/ai_review.sh")

        for prerequisite in (
            "cd /tmp/proj", "git init -q", "git add ai-review-fixture.txt",
            "mkdir -p fakebin", "> fakebin/claude",
        ):
            with self.subTest(prerequisite=prerequisite):
                self.assertLess(recipe.index(prerequisite), review)
        self.assertIn(
            "Do not use this fixture recipe in a real working repository", verify)

    def test_verify_recipe_runs_with_an_isolated_installed_skill(self):
        verify = (ROOT / ".claude" / "skills" / "verify" /
                  "SKILL.md").read_text(encoding="utf-8")
        section = verify.split("## ai_review.sh — fake `claude` on PATH", 1)[1]
        recipe = re.search(r"```bash\n(.*?)```", section, re.DOTALL).group(1)

        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir)
            installed = target / ".claude" / "skills" / "wise-flow"
            shutil.copytree(SKILLS / "wise-flow", installed)
            isolated_recipe = recipe.replace(
                "cd /tmp/proj", 'cd "$VERIFY_RECIPE_DIR"')
            proc = subprocess.run(
                ["bash"], input=isolated_recipe, cwd=ROOT,
                capture_output=True, text=True, timeout=30,
                env={**os.environ, "VERIFY_RECIPE_DIR": str(target)},
            )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["score"], 8)

    def test_security_review_only_route_has_self_contained_inputs(self):
        flow = (SKILLS / "wise-flow" / "SKILL.md").read_text(encoding="utf-8")
        gate = (SKILLS / "wise-flow" / "references" /
                "security-gate.md").read_text(encoding="utf-8")

        self.assertIn("`review-only` | pr-gate, or security-gate", flow)
        self.assertIn("security-focused `review-only`", gate)
        self.assertIn("implementation artifacts are not produced", gate)
        self.assertIn("context supplied by the\nrequester", gate)
        self.assertIn("TARGET_REF-based merge-base cascade", gate)

    def test_wise_requires_explicit_issue_request(self):
        skill = (SKILLS / "wise" / "SKILL.md").read_text(encoding="utf-8")
        checklist = (SKILLS / "wise" / "CHECKLISTS.md").read_text(encoding="utf-8")
        wrapper = (SKILLS / "wise-cont" / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(
            "GitHub issue only when the user explicitly requested issue tracking",
            skill,
        )
        self.assertIn(
            "Run these only when the user explicitly requests the corresponding GitHub",
            checklist,
        )
        self.assertIn("only if issue tracking was explicitly requested", skill)
        self.assertIn("only if issue tracking was explicitly requested", checklist)
        self.assertIn(
            "If\nissue tracking was explicitly requested, check off", skill)
        self.assertIn(
            "description and, if\nissue tracking was explicitly requested, the issue",
            skill,
        )
        self.assertIn("issue\nstatus if applicable", skill)
        self.assertIn("issue only on explicit request", wrapper)
        self.assertIn("update an explicitly requested issue", wrapper)
        self.assertIn("issue only on explicit request", readme)
        self.assertIn("explicitly requested GitHub issue", readme)
        for source in (skill, wrapper, readme):
            self.assertNotIn("GitHub issue required", source)
        for stale in (
            "update the todos and issue",
            "Docs and issue reflect reality",
            "description and the issue",
            "issue\nstatus, PR status",
        ):
            self.assertNotIn(stale, skill)
        self.assertNotIn("Update docs and issues", wrapper)
        self.assertNotIn("Updates docs and GitHub issues", readme)

    def test_wise_pr_is_optional_in_every_completion_contract(self):
        skill = (SKILLS / "wise" / "SKILL.md").read_text(encoding="utf-8")
        wrapper = (SKILLS / "wise-cont" / "SKILL.md").read_text(encoding="utf-8")
        flow = (SKILLS / "wise-flow" / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("Otherwise the branch is ready", skill)
        self.assertIn("Without an open PR, skip bot waiting", skill)
        self.assertIn("Open a PR only on explicit request", wrapper)
        self.assertIn("from reading the code to PR\n  readiness", flow)
        self.assertIn("Create, push, or open a PR only", flow)
        self.assertIn("opens a PR only on explicit request", readme)
        self.assertIn("does not create, push, or open a PR", readme)
        self.assertNotIn("PR open and clean, or pending items", skill)
        self.assertNotIn("Open clean PR", wrapper)

    def test_wise_cont_activation_scope_matches_persistence(self):
        wrapper = (SKILLS / "wise-cont" / "SKILL.md").read_text(encoding="utf-8")
        hook = (ROOT / "hooks" / "mode_persistence.py").read_text(encoding="utf-8")

        self.assertIn("Persistent project-wide wise mode", wrapper)
        self.assertIn("Architect mode activated project-wide", wrapper)
        self.assertIn("Current and future sessions in this project", wrapper)
        self.assertNotIn("activated for this session", wrapper)
        self.assertIn("persists project-wide across current and future sessions", hook)
        self.assertNotIn("persists for this session", hook)
        self.assertNotIn("throughout the session", wrapper)

    def test_large_diff_contract_requires_complete_chunks(self):
        gate = (SKILLS / "wise-flow" / "references" /
                "independent-review.md").read_text(encoding="utf-8")
        script = (SKILLS / "wise-flow" / "scripts" / "ai_review.sh").read_text(
            encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("coverage\nmanifest", gate)
        self.assertIn("every changed hunk must appear exactly\nonce", gate)
        self.assertIn("one file may span multiple chunks", gate)
        self.assertIn("Never split inside a hunk", gate)
        self.assertNotIn("Every changed file must appear in exactly one chunk", gate)
        self.assertLess(
            script.index('DIFF_BYTES=$(wc -c < "$DIFF_SOURCE"'),
            script.index('DIFF_CONTENT=$(cat "$DIFF_SOURCE")'),
        )
        self.assertIn("partial review never passes the gate", readme)
        self.assertNotIn("large-diff truncation", gate)
        self.assertNotIn("diff truncation", readme)

    def test_security_gate_requires_complete_diff_coverage(self):
        diff_mode = (SKILLS / "attack-on-hacker" / "references" /
                     "diff-mode.md").read_text(encoding="utf-8")
        gate = (SKILLS / "wise-flow" / "references" /
                "security-gate.md").read_text(encoding="utf-8")

        self.assertIn("coverage: complete|partial", diff_mode)
        self.assertIn("must never satisfy a security or PR gate", diff_mode)
        self.assertIn("diff coverage is `complete`", gate)
        self.assertIn("a partial review is always blocked", gate)
        self.assertIn("unreviewed files/hunks:", gate)


if __name__ == "__main__":
    unittest.main()
