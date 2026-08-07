# 出力テンプレート

pr-self-review の出力形式。Phase 5 に入る前に読む。

## 出力フォーマット

GitHub PR にそのまま貼れる Markdown 形式。

````markdown
## 🔎 セルフレビュー結果

**対象差分:** `<RANGE_LABEL>` / 変更ファイル N 件 / +X -Y 行
**判定:** ✅ 重大な懸念なし / ⚠️ 要確認 N件 / 🛑 PR前に修正推奨 N件

---

### 🛑 PR前に修正推奨

#### 1. <短い見出し>
- **場所:** `path/to/file.ts:42-48`
- **問題:** <この差分のここで、こういう入力/状況だと、こう壊れる>
- **修正案:**
  ```diff
  - 該当行(現状)
  + 修正後の最小変更
  ```
- **観点:** バグ混入 / 非同期 / 既存仕様破壊 など

(必要に応じて繰り返し)

---

### ⚠️ 要確認(挙動次第で問題化)

#### 1. <短い見出し>
- **場所:** `path/to/file.ts:120`
- **懸念:** <こういう前提が成り立たないと事故る>
- **確認方法:** <呼び出し元/想定入力/データ実例の確認手順>
- **観点:** 境界値 / Null 安全性 など

---

### 💭 未確認の懸念(差分外まで踏み込まないと判断不可)

- <差分外コードを読まないと結論が出せない事項。指摘ではなく共有のみ>

---

### ✅ 良かった点(任意・1〜2行)

- <差分内で良いと感じた変更があれば短く。無理に書かない>
````


---

## wise-flow PR ゲート用テンプレート

`/wise-flow` の pr-gate から呼ばれたときは、上の日本語テンプレートの代わりにこれを返す。

```markdown
## PR Readiness Report

### Verdict
- ready | blocked | needs verification

### Scope
- diff:
- validation:
- security gate:

### Must Fix
#### 1. <title>
- location:
- scenario:
- minimal fix:

### Verify
- assumption:
- how to verify:

### Unconfirmed Concerns
- concern:
- why unconfirmed:

### Good Notes
- <specific positive note>
```

