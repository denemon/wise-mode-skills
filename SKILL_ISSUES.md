# Skill Problem Ledger

## Resolved — 2026-08-23 review

2026-08-23 のレビューで報告された指摘。各エントリは修正当日に `./check.sh`
(全スイート PASS)と `./check.sh --mutants`(登録全件 killed)で回帰検証した。
スイート・変異の件数は以後の変更で増減するため、この台帳には記録しない —
現在値は `./check.sh` / `./check.sh --mutants` の実行結果が唯一の正。
各エントリの Evidence は修正前のレビュー報告の再現結果。

ID: SKILL-REVIEW-008
Severity: P0
Status: Resolved (2026-08-23, commit a86d8c2 — `.github/workflows/ci.yml` を追加。`./check.sh` と `./check.sh --mutants` の 2 ジョブ。`tests/test_packaging.py::test_ci_calls_check_sh` が固定)
Category: CI / Verification integrity
Location: `tests/test_packaging.py:47`; `README.md:694`; `.github/workflows/ci.yml`(不存在)
Problem: `tests/test_packaging.py:47` が `.github/workflows/ci.yml` を必須として読み込むが、そのファイルは存在せず、コミット履歴にもない。標準検証 `./check.sh` が最初から失敗する。
Evidence (as reported): sandbox外で `./check.sh` を実行した結果 — tests: 113件、1エラー(`ci.yml` の `FileNotFoundError`)。hooks: 90件 PASS。benchmarks: 17件 PASS。さらに `README.md:694` は「CI runs the same script」と主張している。
Recommended fix: CI workflow を追加し、`./check.sh` と `./check.sh --mutants` を実行させる。

---

ID: SKILL-REVIEW-009
Severity: P0
Status: Resolved (2026-08-23, commit a86d8c2 — `ai_review.sh` を allowed-tools から全形削除し、毎回の Bash 権限プロンプトを外部送信の境界にした。--allow-sensitive-content は「ユーザーが直接実行する経路のみ」と明文化。その後の再編で規律ごと `skills/wise-flow/references/independent-review.md` へ移設)
Category: Security / Permission boundary bypass
Location: `skills/dev-with-review/SKILL.md:46`; `skills/dev-with-review/scripts/ai_review.sh:131,329`; `tests/test_ai_review.py:245`
Problem: `SKILL.md:46` が `ai_review.sh *` を事前承認している一方、スクリプトは任意の `--diff-file` を受け取り、`--allow-sensitive-content` で秘密検査を無効化できる。Claude Code 公式仕様上、`allowed-tools` は該当コマンドを確認なしで実行可能にする(https://code.claude.com/docs/en/slash-commands)ため、スキル本文の「ユーザー承認後のみ」という文章は権限境界になっていない。レビュー中の prompt injection から任意のローカルファイルを外部レビュアーへ送信できる。
Evidence (as reported): 既存テスト `tests/test_ai_review.py:245` が、override 付きで秘密値が外部レビュアー入力へ到達することを確認している。
Recommended fix: `ai_review.sh *` を `allowed-tools` から削除し、外部送信を毎回の明示承認対象にする。override はユーザーが直接実行する経路だけに分離する。

---

ID: SKILL-REVIEW-010
Severity: P1
Status: Resolved (2026-08-23 — attack-on-hacker / swarm の方法論を副作用のない共通 reference `references/methodology.md` へ抽出。SKILL.md は権限とポインタだけの薄いラッパーになり、wise-flow はスキル起動ではなく reference を読む。`test_wise_flow_delegates_via_side_effect_free_references` と 4 件のミュータントで固定)
Category: Design / Broken delegation contract
Location: `skills/wise-flow/references/security-gate.md:34`; `skills/attack-on-hacker/SKILL.md:10`; `skills/wise-flow/SKILL.md:47`; `skills/swarm/SKILL.md:8`
Problem: `security-gate.md:34` は `attack-on-hacker` の実行を要求するが、同スキルは `disable-model-invocation: true` であり、公式仕様ではユーザーだけが呼び出せる。`swarm`(`wise-flow/SKILL.md:47` → `swarm/SKILL.md:8`)も同じ構造。親スキルからの正規委譲は成立せず、ファイルを直接読んで再実装する回避策は委譲設計を無意味にする。
Recommended fix: 方法論を副作用のない共通 reference へ抽出し、ユーザー向けコマンドと wise-flow の双方がそれを読む構造にする。

---

ID: SKILL-REVIEW-011
Severity: P1
Status: Resolved (2026-08-23 — ログファイル名を session_id の sha256 から直接導出(`session-<hash>.md`)。`.sessions` レジストリとマーカースキャンを削除、作成は open('x') で原子的。20 並行セッション/10 並行イベントの回帰テストを追加、`hook: セッション別ログファイル` ミュータントで固定)
Category: Reliability / Concurrency data loss
Location: `hooks/session_log.py:186,218`
Problem: ログ名を `exists()` で確認してから作成し、`.sessions` を read-modify-write している。排他制御も原子的作成もないため、並行セッションで静かにログを失う。
Evidence (as reported): 40セッション同時開始の再現結果 — `processes=40 logs=12 map_entries=2 session_markers=12 exit_failures=0`。成功扱いのまま28セッション分以上を喪失。
Recommended fix: セッションIDのハッシュからファイル名を直接決め、`.sessions` レジストリを削除する。

---

ID: SKILL-REVIEW-012
Severity: P1
Status: Resolved (2026-08-23 — 単一 tar.gz スナップショット取得に変更(混在バージョン排除)、WISE_MODE_REF / WISE_MODE_SHA256 で commit 固定と checksum 検証に対応。設定 JSON 検証・マニフェスト検証・settings マージ計算をすべて配置前に移動し、settings 書き込みは最終ステップ。壊れた settings で「何も置かれない」ことを `test_broken_settings_json_aborts_before_placement` が実行検証、install 系ミュータント 6 件追加)
Category: Reliability / Non-atomic install
Location: `install.sh:184,14,201`
Problem: `install.sh:184` は atomic install を名乗るが、ファイル配置後に設定JSONを解析する。また全ファイルを可変な main ブランチから個別取得するため(`install.sh:14,201`)、更新途中の混在バージョンも起こり得る。
Evidence (as reported): 設定JSONを壊した状態で実行すると `status=1`、`installed_file_count=27` — 失敗後に27ファイルが残留。
Recommended fix: 単一のリリースアーカイブを commit SHA/checksum で固定し、設定検証を配置前に行う。

---

ID: SKILL-REVIEW-013
Severity: P1
Status: Resolved (2026-08-23 — `git diff *` / `git log *` / `git show *` を pr-self-review の allowed-tools から削除。素の flagless 形だけ残し、ranged 形は毎回の権限プロンプトへ。本文に権限モデルを明記。`test_pr_review_does_not_preapprove_writable_git_forms` とミュータントで固定)
Category: Security / Permission boundary
Location: `skills/pr-self-review/SKILL.md:18`
Problem: read-only レビューのはずが `git diff *`、`git log *`、`git show *` を事前承認している。`git diff --output=<new-file>` で任意ファイルを作成できることを実証済み。attack-on-hacker では同じ理由でこれらを除外しているのに、こちらには基準が適用されていない。
Recommended fix: wildcard 形式を削除し、引数付き diff は通常の許可確認に戻す。

---

ID: SKILL-REVIEW-014
Severity: P1
Status: Resolved (2026-08-23 — opt-in なしの再インストールが、インストーラ自身が書く正規 PostToolUse/Stop コマンドだけを**完全一致**で配線から外すよう修正。部分一致は第三者 hook(例: /opt/acme/session_log.py)まで消すため使わない。ファイルはユーザー所有の可能性があるため削除せず警告で案内する。opt-in 継続時は配線を維持し重複させない。`test_reinstall_without_flag_unwires_only_the_canonical_commands` / `test_reinstall_with_flag_keeps_legacy_session_log_wiring_once` とミュータント 2 件で固定)
Category: Privacy / Migration
Problem: session_log の opt-in 化は新規配置だけを除外し、旧デフォルトインストールが残したファイルと配線を削除しなかった。旧ユーザーは明示同意なしにツール出力を記録し続ける。
Evidence (as reported): デフォルト再インストールが終了 0 でも、ファイルと PostToolUse / Stop 配線がすべて残った。

---

ID: SKILL-REVIEW-015
Severity: P1
Status: Resolved (2026-08-23 — methodology.md 冒頭に「`references/<name>.md` は attack-on-hacker の skill ディレクトリ基準で解決する(repo: `skills/attack-on-hacker/`、installed: `.claude/skills/attack-on-hacker/`)。caller 基準にしない」と結合例つきで明示し、wise-flow から読む場合に quick-wins / language-hints / report-format / diff-mode を同所から読むことを要求。テストは宣言された基準に対して実際にパスを結合して存在検証する。`test_methodology_sibling_references_resolve_for_external_callers` とミュータント 2 件で固定)
Category: Design / Reference resolution
Problem: methodology.md が要求する `references/quick-wins.md` 等は wise-flow 配下に存在せず、security-gate.md が明示パスを示すのは diff-mode.md のみ。wise-flow 経由のレビューで Quick-Wins と最終レポート契約が欠落し得た。

---

ID: SKILL-REVIEW-016
Severity: P1
Status: Resolved (2026-08-23 — `LC_ALL=C shasum -a 256` に固定。checksum テスト 2 件を `LC_ALL=C.UTF-8` 環境で実行し再現条件ごと固定。Perl の panic は macOS 環境依存のためミュータントは登録せず、テストの env 指定を回帰ガードとする)
Category: Portability / Installer
Problem: `install.sh` の shasum が locale を継承し、`LC_ALL=C.UTF-8` で Perl が panic して終了 9。checksum 付きインストールが macOS の通常環境で失敗した。

---

ID: SKILL-REVIEW-017
Severity: P2
Status: Resolved (2026-08-23 — README と install.sh ヘッダの reproducible 手順を「インストーラと archive を同じ `${REF}` から取得」に変更。`test_reproducible_recipe_pins_the_installer_to_the_same_ref` とミュータント 2 件で固定)
Category: Docs / Reproducibility
Problem: mutable な main の install.sh と任意 commit の archive を組み合わせており、manifest と archive が食い違う。
Evidence (as reported): 現行インストーラに直前 commit a86d8c2 を渡すと、現行 manifest にしかない 3 ファイルが欠けて終了 1。

---

ID: SKILL-REVIEW-018
Severity: P3
Status: Resolved (2026-08-23 — 配置を staging 方式に変更: 完全な payload を同一ファイルシステム上の `.claude/.install-staging` に構築してから、skill/hook 単位の `mv` で swap する。配置途中の失敗(権限・ディスクフル)でも半コピーの skill は残らない。`test_failed_swap_leaves_no_partial_skill` が read-only の skills ディレクトリで実行検証、swap 2 箇所のミュータントで固定)
Category: Reliability / Installer
Problem: 検証はすべて配置前だが、配置中の `cp` 自体の失敗は防げず、半コピーの skill と未配線の hooks が残り得た(敵対的セルフレビューで検出)。

---

ID: SKILL-REVIEW-019
Severity: P3
Status: Resolved (2026-08-23 — REMOVED_SKILLS(dev-with-review 等)の削除を無言で行わず、存在すれば EXISTING=1 に合流させて上書き確認と同じプロンプトで同意を取る。プロンプト経路の実行検証は pty が必要なため対象外(既存方針)、構造は `test_removed_skills_deletion_is_gated_by_the_prompt` とミュータントで固定)
Category: Safety / Installer
Problem: 廃止スキルの削除が確認なしで走り、ユーザーが改造した旧スキルを無警告で消し得た(敵対的セルフレビューで検出)。

---

ID: SKILL-REVIEW-020
Severity: P3
Status: Resolved (2026-08-23 — session_log の追記を「1 エントリ = 1 回の os.write(O_WRONLY|O_APPEND|O_CREAT)」に変更。バッファ付き open("a") は 8KB 超のエントリを複数 write に分割し、並行イベント間でエントリ内部が交錯し得た。約 90KB × 3 並行の回帰テストと O_APPEND ミュータントで固定)
Category: Reliability / Concurrency
Problem: 大きなツール出力を含むエントリが並行イベントと交錯し、ログが読めない断片になる可能性があった(敵対的セルフレビューで検出。喪失はしない)。

---

ID: SKILL-REVIEW-021
Severity: P3
Status: Resolved (2026-08-23 — settings 事前検証を JSON 構文だけでなく hooks セクションの構造(dict → list → dict、マージが参照する形そのもの)まで拡張。壊れた形は配置前に明確なメッセージで中断する。`test_malformed_hooks_section_aborts_before_placement` とミュータントで固定)
Category: UX / Installer
Problem: hooks の値が list でない有効 JSON でマージが traceback で落ちていた。配置前なので安全側だが、原因がユーザーに伝わらなかった(敵対的セルフレビューで検出)。

---

## Accepted risks — 2026-08-23

修正しないと判断した残余リスク。理由ごと記録する:

- **並行インストールの lost-update**: 同一プロジェクトで 2 本の install.sh を
  同時実行すると settings が last-writer-wins になる。flock は macOS の
  stock 環境に無く移植性リスクが上回る。運用エラーの領域として許容。
- **tar 展開はアーカイブ提供元(codeload.github.com)を信頼する**: 従来の
  raw.githubusercontent と同じ信頼モデル。現代の tar は絶対パス・`..` を
  既定拒否し、`WISE_MODE_SHA256` ピン留めで緩和できる。
- **`./check.sh --evals` は自動実行しない**: 課金される実 API 呼び出しのため
  明示実行のみ(既存方針)。今回の再編で eval 対象(wise / pr-self-review)は
  変更していない。
- **opt-out 後の session_log.py 残置**: 名前一致では所有を証明できないため
  削除しない(SKILL-REVIEW-014)。配線は外れ、削除コマンドを警告で案内する。

---

## Recommended restructuring — 2026-08-23 review

同レビューが提案した最小構成と、その採否(2026-08-23 実施):

- dev-with-review: **廃止済み**。外部AIレビューは wise-flow の任意ゲート
  `references/independent-review.md`(+ `scripts/ai_review.sh`)へ移動。
  install.sh の REMOVED_SKILLS が既存インストールを削除する。
- pr-self-review / attack-on-hacker: **採用済み**。attack-on-hacker と swarm の
  方法論は共通 reference `references/methodology.md` へ抽出(SKILL-REVIEW-010)。
- session_log: **opt-in 化済み**。デフォルトインストールから外し、
  `install.sh --with-session-log` の明示指定のみで配置・配線される。
- swarm / terse-mode: 既に明示実行専用の独立機能。変更なし。
- wise の廃止と wise-cont の wise-flow 継続プリセット化: **未実施**。
  wise はこのリポジトリの中核スキルであり、mode_persistence フック・
  wise-cont・多数のテストが依存する。この統合は設計判断としてユーザーの
  明示決定を要するため、台帳に保留として残す。

---

## Resolved — 2026-08-11

All entries below describe behavior reproduced before the fix. Every entry was
resolved and regression-tested on 2026-08-11.

ID: SKILL-REVIEW-001
Severity: High
Category: Security / Sensitive-data disclosure
Location: `skills/dev-with-review/scripts/ai_review.sh:114-156,197-225`
Problem: The review script blocks sensitive-looking file names, but sends secret-looking values found in ordinary source files verbatim to the external `claude -p` process.
Why it is a problem: A credential committed or newly written to a normally named file such as `config.py` can leave the local repository during an automated review. The path gate therefore creates a false assurance that sensitive diff content is protected.
Reproduction / Trigger: In a temporary Git repository, create an untracked `config.py` containing a sentinel `AWS_SECRET_ACCESS_KEY`, replace `claude` with a capture stub, and run `ai_review.sh`. The script exits 0, the path guard does not trigger, and the captured prompt contains the full sentinel value.
Expected: Secret-like content is rejected or redacted before any diff is placed in an external-model prompt, unless the user explicitly approves a reviewed override.
Actual: Only the path is classified; the complete `DIFF_CONTENT` is interpolated into `USER_MSG` and passed to `claude -p`.
Root cause: Sensitive-data detection is implemented only as a file-path allow/deny decision. There is no content-level secret scan or redaction before the external invocation.
Recommended fix: Add a content-level secret detector before building `USER_MSG`, fail closed without echoing the detected value, redact safe-to-review matches where appropriate, and provide only an explicit reviewed override. Add an integration test that asserts the sentinel never reaches the capture stub.
Regression risk: Medium. Over-broad detection can block legitimate test fixtures or remove review context, so tests need representative true positives, false positives, binary diffs, and the explicit override path.

---

ID: SKILL-REVIEW-002
Severity: Medium
Category: Reliability / Process lifecycle
Location: `skills/dev-with-review/scripts/ai_review.sh:86-92,224-225`
Problem: `INT` and `TERM` run temporary-file cleanup but do not terminate the active `claude` child or make the script exit with a cancellation status.
Why it is a problem: A cancelled review can continue consuming time, tokens, and network resources, then emit a successful review result even though the caller requested termination.
Reproduction / Trigger: Use a fake `claude` that writes a start marker, sleeps, and then returns valid JSON. Start `ai_review.sh`, wait for the marker, and send `TERM` to the script. The observed result is exit code 0 after the child finishes, with successful JSON output.
Expected: The signal is forwarded to the child, the child is reaped, temporary files are removed, and the script exits 130 for `INT` or 143 for `TERM` without emitting success.
Actual: `trap cleanup EXIT INT TERM` runs cleanup and returns; the untracked foreground child continues, after which the parent parses its response and exits 0.
Root cause: Signal traps and exit cleanup share the same non-terminating handler, while the `claude` process is invoked in the foreground without a tracked PID.
Recommended fix: Separate `EXIT` cleanup from `INT`/`TERM` handlers, launch and track the child, forward the received signal, wait and reap it, then exit with the conventional signal status. Add cancellation integration tests for both signals.
Regression risk: Medium. Signal delivery and exit-code behavior vary across shells and operating systems, so Linux and macOS-compatible tests are required.

---

ID: SKILL-REVIEW-003
Severity: High
Category: Security / Permission boundary
Location: `skills/attack-on-hacker/SKILL.md:29-43`
Problem: A skill described as read-only preauthorizes wildcard command families that include mutating repair modes.
Why it is a problem: `pip-audit --fix` upgrades vulnerable dependencies, `cargo audit fix` modifies `Cargo.toml`, `detect-secrets scan --baseline ...` updates a baseline, and `safety scan --apply-fixes` edits dependency files. These documented modes can therefore modify the project or environment without a new permission decision. Sources: [pip-audit](https://github.com/pypa/pip-audit), [cargo-audit](https://github.com/rustsec/rustsec/blob/main/cargo-audit/README.md), [detect-secrets](https://github.com/Yelp/detect-secrets), and [Safety](https://docs.safetycli.com/safety-docs/vulnerability-remediation/applying-fixes).
Reproduction / Trigger: Invoke any allowed wildcard with its documented mutation mode, for example `pip-audit --fix`, `cargo audit fix`, `detect-secrets scan --baseline .secrets.baseline`, or `safety scan --apply-fixes`.
Expected: The security-review allowlist preauthorizes only commands that cannot modify repository files or the dependency environment; any repair mode requires separate explicit authorization.
Actual: `Bash(pip-audit *)`, `Bash(cargo audit *)`, `Bash(detect-secrets *)`, and `Bash(safety *)` admit both audit and repair forms.
Root cause: The allowlist treats tool names as if each tool were uniformly read-only instead of constraining subcommands and flags by side effect.
Recommended fix: Remove broad wildcard preauthorization for tools with mutating modes. Allow only verified non-mutating command forms, or require a per-command permission decision; add contract tests that reject each repair flag while accepting the intended audit commands.
Regression risk: Medium. Narrower permissions can add prompts or disable optional automated scans until safe exact forms are documented.

---

ID: SKILL-REVIEW-004
Severity: High
Category: Security / Secret handling
Location: `skills/attack-on-hacker/references/quick-wins.md:3-9`
Problem: The prescribed code and history searches print complete matching lines, including credential values, into the agent's tool output and context.
Why it is a problem: Searching for a leak should not replicate the leaked secret into logs, model context, or captured review artifacts. History scans are especially likely to expose credentials that were deliberately removed from the working tree.
Reproduction / Trigger: Pipe `API_KEY=review-ledger-sentinel-123` into the documented `rg -i "password|secret|api[_-]?key|token|..."` pattern. The complete key and value are printed. The documented `git log -p | rg` route has the same value-bearing behavior for history.
Expected: The sweep reports the file, commit, line, and secret type while suppressing or irreversibly redacting the value.
Actual: The raw matching line is emitted unchanged.
Root cause: The procedure uses content-printing search pipelines rather than metadata-only detection or a redacting secret scanner.
Recommended fix: Replace raw-value searches with filename/location-only output or a redaction step, and configure supported secret scanners not to echo values. Add a sentinel test proving that findings retain location/type while the value is absent from stdout and generated reports.
Regression risk: Medium. Redaction can reduce triage context or obscure false positives, so location, rule identifier, and a non-reversible fingerprint should be preserved.

---

ID: SKILL-REVIEW-005
Severity: Medium
Category: Documentation / Broken dependency reference
Location: `skills/wise-flow/references/security-gate.md:24-35`
Problem: The security gate names cross-skill reference files using paths that resolve inside `wise-flow`, where those files do not exist.
Why it is a problem: An agent following the instructions literally cannot load the required diff-acquisition and Diff Mode contracts, so it may guess the diff range, skip untracked files, or omit the intended security-review mode.
Reproduction / Trigger: Resolve `pr-self-review/references/diff-acquisition.md` and `references/diff-mode.md` relative to `skills/wise-flow/references/security-gate.md` or the `wise-flow` skill directory. Neither target exists there; the actual files are under sibling skill directories.
Expected: Every referenced local file resolves deterministically in both the repository development layout and the installed `.claude/skills` layout.
Actual: The written relative paths are missing, while the intended targets are `skills/pr-self-review/references/diff-acquisition.md` and `skills/attack-on-hacker/references/diff-mode.md`.
Root cause: Cross-skill dependencies were documented as though the referenced files belonged to the current skill.
Recommended fix: Name the sibling skill explicitly and provide deterministic installed paths such as `.claude/skills/pr-self-review/references/diff-acquisition.md` and `.claude/skills/attack-on-hacker/references/diff-mode.md`, with repository-layout equivalents for development. Add a reference-integrity test.
Regression risk: Low. The main risk is choosing a path convention that works only before or only after installation.

---

ID: SKILL-REVIEW-006
Severity: Medium
Category: Contract consistency / Report schema
Location: `skills/wise-flow/references/security-gate.md:36-45,71-105`; `skills/attack-on-hacker/references/report-format.md:18-35`
Problem: The wise-flow security wrapper requires the full attack-on-hacker discipline but its translation schema drops mandatory finding fields.
Why it is a problem: CWE, CVSS, attacker profile, preconditions, and verification steps are mandatory in the canonical attack report but have no place in the Security Gate Report. Translating a valid finding therefore discards evidence needed for prioritization, auditability, and fix verification.
Reproduction / Trigger: Produce an attack-on-hacker finding with every mandatory field, then translate it using the Security Gate Report template. The resulting schema preserves severity and evidence but cannot preserve CWE, CVSS, attacker profile, preconditions, or verification.
Expected: The wrapper carries every mandatory canonical finding field verbatim, or embeds the canonical finding without lossy translation.
Actual: The wrapper contains only severity, evidence, classification, location, Source-to-Sink-to-Sanitizer, impact, and minimal fix.
Root cause: The wrapper duplicates a subset of the canonical schema and has drifted from the report contract it claims to preserve.
Recommended fix: Embed the canonical attack finding unchanged and add wrapper-only classification fields, or extend the Security Gate Report with every canonical mandatory field. Add a contract test comparing required field sets.
Regression risk: Low to Medium. Expanding the artifact can affect downstream parsers or prompts that assume the shorter wrapper schema.

---

ID: SKILL-REVIEW-007
Severity: Medium
Category: Reliability / Cancellation hang
Location: `skills/swarm/SKILL.md:135-161`
Problem: The generated runner sends one ordinary termination signal and then waits forever for every recorded child, with no grace deadline or escalation.
Why it is a problem: A worker that ignores or mishandles `TERM` prevents the runner from completing cancellation, leaves the parent hung in its trap, and blocks automation indefinitely.
Reproduction / Trigger: Replace one example worker with a child that installs `trap '' TERM` and loops, start the generated runner, then send `TERM` to the runner. After 0.7 seconds the parent is still alive inside `cleanup_agents`; it exits 143 only after the test forcibly kills the child.
Expected: Cancellation completes within a bounded interval, all children are terminated and reaped, and the runner exits 130 or 143.
Actual: `cleanup_agents` calls `kill`, immediately performs an unbounded `wait`, and has no escalation path for a surviving child.
Root cause: The cleanup contract assumes every child exits promptly after the first signal.
Recommended fix: Send the initial signal, poll or wait for a documented grace interval, escalate remaining tracked processes to `KILL`, and reap them before exiting. Add a test with a TERM-ignoring child and verify bounded completion with no surviving PID.
Regression risk: Medium. Escalation can interrupt child cleanup or miss descendant processes unless process-group ownership and the grace interval are defined carefully.
