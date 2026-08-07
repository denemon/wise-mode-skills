#!/usr/bin/env python3
"""mutants.py — ガードの棚卸し

「直した」と「戻せない」は別のこと。修正だけしてガードを付けないと、次の編集で
無音で戻る。実際このリポジトリでは、監査した時点で 8 件中 5 件の修正が巻き戻しても
素通りだった。

ここに登録した変異を 1 件ずつ当て、**対応するテストが落ちること**を確認する。
落ちない変異が 1 つでもあれば非ゼロ終了する。

    python3 tools/mutants.py            # 全件
    python3 tools/mutants.py gate       # 名前に "gate" を含むものだけ
    python3 tools/mutants.py --list     # 一覧だけ

このセッション中、同じ内容の使い捨てスクリプトを 5 回書き直した。5 回目でようやく
`carry_forward({})` の穴が出た。毎回書き直す前提だと、書き直さなかった回は監査が
存在しないのと同じになる。

安全性:
- 置換は完全一致のみ。見つからなければ「前提崩れ」として失敗する（無言の 0 件置換をしない）
- 原文は try/finally で必ず書き戻す
- 全件終了後に作業ツリーが汚れていないことを確認する
  （以前シェルの heredoc に Python を埋めた監査が session_log.py（当時 sync_to_obsidian.py）を破壊した）
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def lock_path() -> Path:
    """監査中であることを示すロック。

    監査はライブツリーを書き換えるので、同時に走る他の読み手が壊れた状態を見る。
    実際に 2 通りやらかした: 並走した `check.sh` が偽の FAILED を出し、
    `git add -A` が変異したファイルを index にステージした。Stop ゲートは
    自動で発火するので、これは「起きうる」ではなく「いつか必ず起きる」。

    リポジトリ内ではなく一時ディレクトリに置く。実行時の状態であって成果物では
    なく、間違ってコミットされる余地も無い。パスは ROOT から決まるので、
    フック側も同じ場所を見られる。
    """
    digest = hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"wise-mode-mutants-{digest}.lock"


def lock_holder() -> int | None:
    """ロックを握っている生きたプロセスの PID。無ければ None。"""
    try:
        pid = int(lock_path().read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)  # 存在確認だけ。シグナルは送らない
    except ProcessLookupError:
        return None      # 落ちた監査が残した残骸
    except PermissionError:
        return pid       # 別ユーザだが生きている
    return pid

# (名前, ファイル, 置換前, 置換後, テストdir, モジュール)
#
# 「置換後」は挙動を壊すだけでよい。構文が通ればいい。
# 新しいガードを足したら、それを壊す変異をここにも足すこと。
MUTANTS: list[tuple[str, str, str, str, str, str]] = [
    # ── フック: 外部契約 ──────────────────────────────────────
    ("hook: tool_response キー", "hooks/session_log.py",
     'payload.get("tool_response", "")', 'payload.get("tool_result", "")',
     "hooks", "test_contract"),
    ("hook: 記録モード", "hooks/session_log.py",
     "    _record(event_type, stdin_text)\n", "",
     "hooks", "test_contract"),
    ("hook: 例外ガード", "hooks/session_log.py",
     "    try:\n        main()\n    except Exception:",
     "    main()\nif False:\n    try:\n        pass\n    except Exception:",
     "hooks", "test_contract"),
    ("README: ログ形式の実例", "README.md",
     "<details><summary>result</summary>", "<x>",
     "hooks", "test_contract"),

    # ── フック: 継続モードの永続化 ────────────────────────────
    ("mode: 毎ターンの再注入", "hooks/mode_persistence.py",
     "        if flag.exists():\n            level = flag.read_text",
     "        if False:\n            level = flag.read_text",
     "hooks", "test_mode_persistence"),
    ("mode: 解除でフラグ削除", "hooks/mode_persistence.py",
     "                if flag.exists():\n                    flag.unlink",
     "                if False:\n                    flag.unlink",
     "hooks", "test_mode_persistence"),
    ("mode: 起動でフラグ作成", "hooks/mode_persistence.py",
     '                flag.write_text(_level(prompt), encoding="utf-8")',
     "                pass",
     "hooks", "test_mode_persistence"),

    # ── 配布スクリプト ────────────────────────────────────────
    ("ai_review: staged diff", "skills/dev-with-review/scripts/ai_review.sh",
     "git diff HEAD 2>/dev/null || git diff 2>/dev/null", "git diff 2>/dev/null",
     "tests", "test_ai_review"),
    ("ai_review: 終了コードの伝播", "skills/dev-with-review/scripts/ai_review.sh",
     '2>"$CLAUDE_ERR") || EXIT_CODE=$?', '2>"$CLAUDE_ERR") || true',
     "tests", "test_ai_review"),
    ("install: 追跡済みログの案内", "install.sh",
     '                echo "    git rm -r --cached .claude/log"', "                :",
     "tests", "test_install"),
    ("install: 網羅マニフェスト照合", "install.sh",
     '            cp "${TMPDIR_DOWNLOAD}/skills/${source_path}/${file}" "${dest}"',
     "            :",
     "tests", "test_install"),
    ("README: アンインストール一覧", "README.md",
     "rm -rf .claude/skills/{wise,", "rm -rf .claude/skills/{",
     "tests", "test_packaging"),
    ("install: フックの配置", "install.sh",
     '        cp "${TMPDIR_DOWNLOAD}/hooks/${hook_file}" "${dest}"\n        chmod +x "${dest}"',
     "        :",
     "tests", "test_install"),
    ("install: 原子性", "install.sh",
     '        error "One or more files failed to download. Installation aborted."\n        exit 1',
     '        warn "partial"',
     "tests", "test_install"),

    # ── スキル本文の不変条件 ──────────────────────────────────
    ("swarm: run.sh の wait", "skills/swarm/SKILL.md",
     'for pid in "${pids[@]}"; do wait "$pid"; done', "wait",
     "tests", "test_packaging"),
    ("dev-with-review: allowed-tools", "skills/dev-with-review/SKILL.md",
     "  - Bash(git diff)\n", "",
     "tests", "test_packaging"),
    ("attack-on-hacker: allowed-tools", "skills/attack-on-hacker/SKILL.md",
     "  - Bash(git diff)\n", "",
     "tests", "test_packaging"),
    ("wise: Q&A レベル", "skills/wise/SKILL.md",
     "[WISE MODE: Q&A]", "[WISE MODE: XX]",
     "tests", "test_packaging"),

    # ── 配布物のレイアウト ────────────────────────────────────
    ("gitignore: !.github/", ".gitignore", "!.github/", "",
     "tests", "test_packaging"),
    ("gitignore: !.claude/", ".gitignore", "!.claude/", "",
     "tests", "test_packaging"),
    ("gitignore: ローカル状態の再除外", ".gitignore",
     ".claude/settings.local.json\n", "",
     "tests", "test_packaging"),
    # 回帰ジョブと監査ジョブは別々に潰せる。片方だけの変異では、もう片方の記述が
    # 残ってガードが素通りした（監査の初回実行で SURVIVED として出た）。両方登録する。
    ("CI: 回帰ジョブ", ".github/workflows/ci.yml",
     "run: ./check.sh\n", "run: echo skip\n",
     "tests", "test_packaging"),
    ("CI: 変異監査ジョブ", ".github/workflows/ci.yml",
     "./check.sh --mutants", "echo skip",
     "tests", "test_packaging"),
    ("CLAUDE.md: 二層の名指し", "CLAUDE.md",
     "that is the single entrypoint `./check.sh`", "run the tests",
     "tests", "test_packaging"),

    # ── 開発ハーネス ──────────────────────────────────────────
    ("gate: 赤で停止をブロック", ".claude/hooks/check_gate.py",
     '    return 2, message, {"attempts": attempts}',
     '    return 0, message, {"attempts": attempts}',
     "tests", "test_harness"),
    ("gate: 判定不能は緑ではない", ".claude/hooks/check_gate.py",
     '    if status == "inconclusive":', "    if False:",
     "tests", "test_harness"),
    ("gate: 再帰ガード", ".claude/hooks/check_gate.py",
     "    if os.environ.get(RECURSION_ENV):\n        return 0",
     "    if False:\n        return 0",
     "tests", "test_harness"),
    ("gate: 3 回で降参", ".claude/hooks/check_gate.py",
     "    if attempts >= MAX_ATTEMPTS:", "    if False:",
     "tests", "test_harness"),
    ("notice: 初回は黙る", ".claude/hooks/check_gate.py",
     '    if not isinstance(known, dict):\n        return "", {**state, "surfaces": surfaces}',
     "    if not isinstance(known, dict):\n        known = {}",
     "tests", "test_harness"),
    ("notice: 変わった面を挙げる", ".claude/hooks/check_gate.py",
     "    changed = sorted(name for name, digest in surfaces.items()\n"
     "                     if known.get(name) != digest)",
     "    changed = []",
     "tests", "test_harness"),
    ("notice: 二度言わない", ".claude/hooks/check_gate.py",
     '    return message, {**state, "surfaces": surfaces}', "    return message, state",
     "tests", "test_harness"),
    ("notice: テストは面でない", ".claude/hooks/check_gate.py",
     'if not path.is_file() or path.name.startswith("test_")', "if not path.is_file()",
     "tests", "test_harness"),
    ("notice: surfaces の繰り越し", ".claude/hooks/check_gate.py",
     '        state.setdefault("surfaces", previous["surfaces"])', "        pass",
     "tests", "test_harness"),
    ("notice: 繰り越しで緑を復活させない", ".claude/hooks/check_gate.py",
     '        state.setdefault("surfaces", previous["surfaces"])',
     "        state.update(previous)",
     "tests", "test_harness"),
    ("lint_on_edit: 構文エラー検出", ".claude/hooks/lint_on_edit.py",
     '            return f"{path.name}: SyntaxError line {exc.lineno}: {exc.msg}"',
     '            return ""',
     "tests", "test_harness"),

    # ── 検証基盤そのもの ──────────────────────────────────────
    ("check.sh: --mutants の入口", "check.sh",
     '    --mutants) exec python3 tools/mutants.py "${@:2}" ;;',
     "    --mutants) : ;;",
     "tests", "test_packaging"),
    ("check.sh: bash 3.2 縛り", "check.sh",
     "SUITE_TIMEOUT=120", "SUITE_TIMEOUT=120\nmapfile -t _unused < /dev/null",
     "tests", "test_packaging"),
    ("check.sh: スイートのタイムアウト", "check.sh",
     "except subprocess.TimeoutExpired:", "except KeyboardInterrupt:",
     "tests", "test_packaging"),
    ("gate: 監査中は判定不能", ".claude/hooks/check_gate.py",
     "        if audit_in_progress(root):", "        if False:",
     "tests", "test_harness"),
    ("check.sh: 未知フラグの拒否", "check.sh",
     "        printf 'check.sh: unknown option: %s\\n' \"$1\" >&2",
     "        FAST=0",
     "tests", "test_packaging"),
    # `before` はこのファイル自身に一意でなければならない。単に本体の 1 行を
    # 書くと、このレジストリのリテラルと 2 箇所になって的を外す。
    # 自分自身を対象にする変異は、`before` をそのまま書くとレジストリの
    # リテラルと本体の 2 箇所になり AMBIGUOUS になる。連結で書くと
    # ファイル上のリテラル表現が対象テキストと一致しなくなり、一意になる。
    ("mutants: 前提崩れの検出", "tools/mutants.py",
     '"hooks", "test_contract"),\n    ("hook: 記録モード"',
     '"hooks", "test_contract"),\n    ("hook: 存在しない前提", "README.md",\n'
     '     "THIS-STRING-DOES-NOT-EXIST", "x", "hooks", "test_contract"),\n'
     '    ("hook: 記録モード"',
     "tests", "test_packaging"),
]

# 子プロセスに渡す印。テストの中から check.sh / ゲート / この監査器自身を
# 再び起動させないため。
#
# `MUTANT_CHILD` が要るのは、監査器のテスト（tests/test_harness.py の
# MutationRunnerTest）が apply_and_check を呼ぶから。それ自身が
# test_harness を子として起動するので、印が無いと止まらない。
# このセッションで同じ形の再帰を 3 回作った — テストがテストランナーを呼ぶ構造は
# 必ずこうなる。
CHILD_ENV = {
    "WISE_MODE_CHECK_SELFTEST": "1",
    "WISE_MODE_CHECK_GATE_ACTIVE": "1",
    "WISE_MODE_MUTANT_CHILD": "1",
}


def run_suite(test_dir: str, module: str) -> bool:
    """対象モジュールが通れば True。"""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "unittest", module],
            cwd=str(ROOT / test_dir), capture_output=True,
            env={**os.environ, **CHILD_ENV}, timeout=300,
        )
    except subprocess.TimeoutExpired:
        # ハングは「落ちた」と同じ扱い。例外で監査ごと落とすと、ロックと
        # 変異が残って後始末が要る（実際に起きた）。
        return False
    return result.returncode == 0


_BASELINE: dict[tuple[str, str], bool] = {}


def baseline_is_green(test_dir: str, module: str) -> bool:
    """変異を当てる前から対象スイートが緑か。(dir, module) 単位でキャッシュ。

    元から赤いスイートに変異を当てると、当然また赤くなり **全部 killed に
    見える**。監査が丸ごと無意味になるのに、出力は満点になる。実際、無関係な
    テスト 1 件が落ちていたせいで別の変異が killed と誤報された。
    """
    key = (test_dir, module)
    if key not in _BASELINE:
        _BASELINE[key] = run_suite(test_dir, module)
    return _BASELINE[key]


def apply_and_check(name: str, rel: str, before: str, after: str,
                    test_dir: str, module: str) -> str:
    """"killed" / "survived" / "stale" を返す。

    **二重に走らせてはいけない。** 変異は read → write → run → restore で、
    ロックが無い。同じファイルを触る 2 つの実行が重なると、後から restore した
    側が先の変更を「原文」として書き戻し、差分が蓄積する。実際、再帰実行で
    README の 1 行目に末尾空白が 93 個溜まった。
    """
    if os.environ.get("WISE_MODE_MUTANT_CHILD"):
        raise RuntimeError(
            "変異監査の内側から apply_and_check が呼ばれた。"
            "入れ子で走らせるとファイルが壊れる。")

    path = ROOT / rel
    original = path.read_text(encoding="utf-8")
    occurrences = original.count(before)
    if occurrences == 0:
        return "stale"
    if not baseline_is_green(test_dir, module):
        return "baseline-red"
    if occurrences > 1:
        # 曖昧な変異は「効いていないのに緑」を作る。実際、このファイル自身を
        # 対象にした変異で `before` がレジストリのリテラルにも現れ、
        # replace(..., 1) が本体ではなくレジストリを書き換えていた。
        # テストは当然通り、SURVIVED という嘘の発見が出た。
        return "ambiguous"

    try:
        path.write_text(original.replace(before, after, 1), encoding="utf-8")
        return "survived" if run_suite(test_dir, module) else "killed"
    finally:
        path.write_text(original, encoding="utf-8")


def dirty_paths() -> set[str]:
    """作業ツリーで内容が変わっているパス。git が無ければ空集合。

    真偽値ではなく集合を返す。当初 `worktree_is_clean() -> bool` にしていたが、
    未コミットの変更がある状態（＝普段）では監査前から False になり、
    「監査がツリーを汚したか」の判定が常に無効化されていた。安全網が必要な
    場面でだけ働かない、という壊れ方をしていた。
    """
    result = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        return set()
    return {line[3:] for line in result.stdout.splitlines() if line.strip()}


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("-")]
    if "--lock-held" in argv:
        # check.sh から呼ばれる。出力は無し、終了コードだけが答え。
        return 0 if lock_holder() is not None else 1
    if "--list" in argv:
        for entry in MUTANTS:
            print(f"  {entry[0]}")
        return 0

    selected = [m for m in MUTANTS if not args or any(a in m[0] for a in args)]
    if not selected:
        print(f"no mutant matches {args}", file=sys.stderr)
        return 1

    holder = lock_holder()
    if holder is not None:
        print(f"別の監査が実行中 (pid {holder})。同時に走らせるとツリーが壊れる。",
              file=sys.stderr)
        return 1
    if lock_path().exists():
        # holder が None なのにファイルがある = 前回の監査が異常終了した。
        # SIGKILL は finally を飛ばすので、変異が当たったままのファイルが残る
        # （実測: install.sh が変異したまま残り、check.sh が落ちた）。
        print("警告: 前回の監査が異常終了した形跡がある。"
              "変異が当たったままのファイルが残っている可能性がある。",
              file=sys.stderr)
        print("  git status / git diff で確認すること。", file=sys.stderr)
    lock_path().write_text(str(os.getpid()), encoding="utf-8")
    try:
        return _audit(selected)
    finally:
        lock_path().unlink(missing_ok=True)


def _audit(selected: list) -> int:
    dirty_before = dirty_paths()
    survived, stale, ambiguous, baseline_red = [], [], [], []

    print(f"{len(selected)} mutants\n")
    for index, entry in enumerate(selected, 1):
        name = entry[0]
        outcome = apply_and_check(*entry)
        mark = {"killed": "killed ", "survived": "SURVIVED",
                "stale": "STALE  ", "ambiguous": "AMBIG  ",
                "baseline-red": "BASE-RED"}[outcome]
        print(f"  [{index:2}/{len(selected)}] {mark}  {name}", flush=True)
        if outcome == "survived":
            survived.append(name)
        elif outcome == "stale":
            stale.append(name)
        elif outcome == "ambiguous":
            ambiguous.append(name)
        elif outcome == "baseline-red":
            baseline_red.append(name)

    print()
    if stale:
        print("STALE — 「置換前」の文字列がもう存在しない。変異を書き直すこと:")
        for name in stale:
            print(f"  - {name}")
    if baseline_red:
        print("BASELINE RED — 変異前からスイートが落ちている。"
              "この状態では全部 killed に見えるだけで何も検証していない:")
        for name in baseline_red:
            print(f"  - {name}")
    if ambiguous:
        print("AMBIGUOUS — 「置換前」が複数箇所に出る。的を外して緑になる:")
        for name in ambiguous:
            print(f"  - {name}")
    if survived:
        print("SURVIVED — 壊してもテストが緑。そのガードは存在しない:")
        for name in survived:
            print(f"  - {name}")

    # 監査の前後で「汚れているパスの集合」を比べる。増えていたら復元漏れ。
    leaked = sorted(dirty_paths() - dirty_before)
    if leaked:
        print("\nERROR: 監査が作業ツリーを汚したまま終わった。復元漏れ:")
        for path in leaked:
            print(f"  - {path}")

    if not survived and not stale and not ambiguous and not baseline_red \
            and not leaked:
        print(f"all {len(selected)} mutants killed")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
