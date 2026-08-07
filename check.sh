#!/usr/bin/env bash
# check.sh — このリポジトリの完全検証コマンド
#
# CLAUDE.md の実行ループ手順6が指す対象。CI と Stop ゲートも同じものを呼ぶ。
# 検証範囲を毎回組み立て直すと、その都度「どこまで見たか」が呼ぶ側の裁量になる。
# 唯一の入口を用意して、範囲を固定する。
#
#   ./check.sh            全層（統合テスト込み、約25秒）
#   ./check.sh --fast     遅い統合スイートを除外（約2秒）。Stop ゲートはこれ
#   ./check.sh --mutants  ガードの棚卸し（約2.5分）。CI と手動のみ
#
# `set -e` は使わない。最初の失敗で止めると残りの状態が分からず、直す順番を
# 決められない。全部走らせてから落とす。
#
# **bash 3.2（macOS 既定）で動くこと。** CI は ubuntu の bash 5 しか見ていないので
# ここが唯一の防波堤になる。`mapfile` / 連想配列 / `${x^^}` は bash 4+ 専用なので
# 使わない（実際 mapfile を書いて macOS で落ちた）。同じ理由で `timeout` コマンドも
# 使わない — GNU coreutils で、stock macOS には入っていない。

set -uo pipefail
cd "$(dirname "$0")" || exit 1

# 未知のフラグは黙って無視しない。`--fsat` と打ち間違えると、`--fast` の
# つもりでフル 25 秒を待たされ、何も言われないまま通っていた。
FAST=0
case "${1:-}" in
    "")        ;;
    --fast)    FAST=1 ;;
    --mutants) exec python3 tools/mutants.py "${@:2}" ;;
    *)
        printf 'check.sh: unknown option: %s\n' "$1" >&2
        printf 'usage: check.sh [--fast | --mutants [name...]]\n' >&2
        exit 2
        ;;
esac

# 監査中のツリーは一時的に変異している。そのまま検証すると偽の FAILED が出る
# （実測: 36 秒かけて FAILED。これがロックを入れた元の症状）。
if python3 tools/mutants.py --lock-held 2>/dev/null; then
    printf 'check.sh: a mutation audit is running — the tree is mutated right now.\n' >&2
    printf 'Wait for it to finish; checking now would report a false failure.\n' >&2
    exit 3
fi

# スイート 1 つあたりの上限。ここで見つかる類のハングは再帰なので、
# 正常時（最長 test_install が約13秒）とは桁が違う。
SUITE_TIMEOUT=120

# 遅い統合スイート。実プロセスを起動するので秒単位でかかる。
SLOW_TESTS="test_install|test_ai_review"

fail=0
step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
note() { printf '   %s\n' "$1"; }

step "bash syntax"
for f in install.sh check.sh skills/*/scripts/*.sh; do
    bash -n "$f" || { note "FAILED: $f"; fail=1; }
done
[ "$fail" -eq 0 ] && note "ok"

step "shellcheck"
if command -v shellcheck >/dev/null 2>&1; then
    shellcheck install.sh check.sh skills/*/scripts/*.sh || fail=1
    note "clean"
else
    # CI には必ず在る。ローカルに無いことを検証の欠落として黙らせない。
    note "SKIPPED — shellcheck not installed (CI runs it)"
fi

step "python syntax"
python3 - <<'PY' || fail=1
import ast, pathlib, sys
bad = []
for p in pathlib.Path(".").rglob("*.py"):
    if "__pycache__" in str(p):
        continue
    try:
        ast.parse(p.read_text(encoding="utf-8"))
    except SyntaxError as e:
        bad.append(f"{p}: {e}")
print("   " + ("ok" if not bad else "\n   ".join(bad)))
sys.exit(1 if bad else 0)
PY

# スイートを上限つきで走らせる。`timeout` コマンドは stock macOS に無いので
# python3 で包む。ハングを無言の停止ではなく明示的な失敗に変えるのが目的 —
# このセッションで再帰バグ 2 件がどちらも「固まる」形で出て、5 分と 2 分を溶かした。
run_suite() {
    python3 - "$SUITE_TIMEOUT" "$@" <<'PY'
import subprocess, sys
seconds, cwd, args = int(sys.argv[1]), sys.argv[2], sys.argv[3:]
try:
    proc = subprocess.run([sys.executable, "-m", "unittest", *args],
                          cwd=cwd, capture_output=True, text=True, timeout=seconds)
except subprocess.TimeoutExpired:
    print(f"   TIMEOUT after {seconds}s — suspect recursion or a hang.")
    print("   Nothing here legitimately takes that long.")
    sys.exit(1)
tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
print("\n".join("   " + line for line in tail))
sys.exit(proc.returncode)
PY
}

for d in tests hooks benchmarks; do
    step "unittest: $d"
    if [ "$FAST" -eq 1 ]; then
        # `mapfile` は bash 4+。macOS の既定は 3.2 なので使わない。
        # モジュール名に空白は入らないので、空白区切りの文字列で足りる。
        suites=$(find "$d" -name 'test_*.py' -exec basename {} .py \; \
            | grep -Ev "^($SLOW_TESTS)$" | sort | tr '\n' ' ')
        if [ -z "${suites// /}" ]; then note "(--fast: all excluded)"; continue; fi
        # shellcheck disable=SC2086  # 意図した単語分割
        run_suite "$d" $suites || fail=1
    else
        run_suite "$d" discover -s . -p 'test_*.py' || fail=1
    fi
done

step "result"
if [ "$fail" -eq 0 ]; then
    printf '   \033[0;32mPASS\033[0m\n'
else
    printf '   \033[0;31mFAIL\033[0m\n'
fi
exit "$fail"
