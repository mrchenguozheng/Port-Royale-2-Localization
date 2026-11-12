# 新しい言語：完全なワークフロー（ゼロからゲーム内まで）

以下のステップを順番に進めてください。各ステップには確認ポイントがあります。例では
`de`（ドイツ語）を追加します。中国語の場合は `zh` に読み替えてください。

> 既存の中国語訳だけを変更したい場合は、ステップ 3 と 4 の presets 設定を省略できます。
> ただし、ステップ 2 のオリジナルフォントとステップ 3 の donor は引き続き必要です。

---

## 0. 環境を準備する

必要なもの:

- ゲームがインストールされた Windows。
- Python 3.11+。
- プロジェクトのソース。
- ステップ 2 と 3 で使用するフォントファイル。

```bash
cd pr2-localization
```

---

## 1. ワークベンチを起動する

`start.bat` をダブルクリックすると、ブラウザでインストールページが開きます（既定は
`http://127.0.0.1:8777/install`）。インストールページの上部には
**インストールウィザード**があり、対象言語を選ぶと、1 ゲームディレクトリの準備 →
2 フォントの準備 → 3 コンテンツの翻訳 → 4 ビルド → 5 インストールと起動 の各セクションの
状態が順に表示され、対応するボタンを直接クリックできます。

**確認**: ページが開き、上部に「翻訳エディタ」と「インストールと起動」の 2 つのタブが
あること。

---

## 2. ゲームのオリジナルフォントをエクスポートする

`assets/fonts/original/` はリポジトリに含まれていないため、先にエクスポートします:

```bash
python src/tools/font/extract_fonts.py --game-dir "<game directory>" --out assets/fonts/original
```

**確認**: ディレクトリに 4 つのファイルが現れること:

```
ARIAL.TTF  ELGRECO_.TTF  Tiepolo_black.ttf  Tiepolo_bold.ttf
```

---

## 3. donor フォントを準備する

フォント縫合とは「オリジナルのラテン系フォント + donor の中国語/日本語フォント」を
組み合わせることです。

- 中国語/日本語フォントをインストールする（Microsoft YaHei、STZhongsong、Source Han
  Serif、Noto Serif JP など）。
- 新しい言語を作成すると `presets/<code>.toml` が自動生成されるので、その言語用に
  `donor_file` を変更する。
- 設定は言語ごとに 1 ファイルで、互いに独立している。

不足しているものを確認します:

```bash
python src/tools/font/subset_fonts.py --check
```

**確認**: 出力が `字体缝合前置条件齐全。`（フォント縫合の前提条件がすべて揃っている）
であること。

fontTools が不足していると報告された場合:

```bash
python -m pip install fonttools
```

---

## 4. 新しい言語を作成する

**翻訳エディタ**ページで:

1. 言語ドロップダウンの横にある **＋** をクリックする。
2. 言語コード（例: `de`）を入力する。
3. テンプレートとして既存の言語を選択する。
4. **作成** をクリックする。

次のファイルが生成されます:

```
src/live/de.toml
```

（現在、新しい言語で自動的に作成されるのは `live` ファイルだけです。`seed` の初版は
生成されないため、必要な場合はテンプレート言語から手作業で `src/seed/de.toml` に
コピーしてください。）

**確認**: 言語ドロップダウンに `de` が表示され、一覧をページ送りできること。

---

## 5. 新しい言語の donor（フォント）を確認する

言語を作成すると、`src/tools/font/fontstitch/presets/de.toml` が自動生成されます:

- 内容は**テンプレート言語**の presets ファイルを雛形にします。テンプレートに presets が
  ない場合は `zh` を使用します。
- presets ディレクトリが存在しない場合は、先に `presets.example.toml` からコピーします。
- ファイルは言語ごとに 1 つで、互いに独立しています。既存の `de.toml` は上書きされません。

構造はどの言語でも共通です:

```toml
[[pair]]
game_file = "ARIAL.TTF"
donor_file = "%WINDIR%\\Fonts\\msyh.ttc"
donor_index = 0

[[supplement]]
game_file = "ELGRECO_.TTF"
donor_file = "%WINDIR%\\Fonts\\STZHONGS.TTF"

[fallback]
donor_file = "%WINDIR%\\Fonts\\NotoSansJP-VF.ttf"
```

要点:

- **言語ごとに `presets/<language>.toml` を 1 つ**用意する。
- donor は TrueType（`glyf`）であること。
- donor の UPM はゲームフォントと一致させること: Arial は 2048、ElGreco/Tiepolo は 1000。
- 中国語以外の言語では、自動コピーされた中国語 donor が新しい言語の文字セットを
  カバーしない場合があるため、その言語用の donor に差し替える。

**確認**: `python src/tools/font/subset_fonts.py --check` が donor の不足を報告しなく
なること。

---

## 6. 翻訳する

エディタで項目を 1 件ずつ編集し、`Ctrl+S` を押すか **保存** をクリックします。保存は
`src/live/de.toml` に直接書き込まれます。

**確認**: ページを再読み込みしても翻訳が残っていること。下部のカウンタが正しいこと。

---

## 7. フォントを縫合する

```bash
python src/tools/font/subset_fonts.py --lang de --force
```

**確認**: ログに次が表示されること

```
de：N 个用字
   ARIAL.TTF
   ...
字体已处理：de
```

（`de：N 个用字` は「de: N 文字を使用」、`字体已处理：de` は「フォントを処理しました: de」
の意。）さらに `build/fonts/de/` 配下の 4 つの TTF がすべて更新されていること。

グリフが不足している場合、ログに `U+XXXX` が列挙されます。donor を切り替えるか
`supplement` を追加してから再実行してください。

---

## 8. 言語パックをビルドしてデプロイする

任意: 言語パックに表示名と GUI 言語を設定します:

```toml
# src/packs/de.toml
alias = "Deutsch"
gui = "de"
min_runtime = 1
```

`compile_pack.py` はこれらを言語パックの先頭に `# pack-meta` として書き出します。
`gui` がない場合、GUI は Windows の UI 言語に従います。`alias` がない場合、一覧には
言語コードが表示されます。

インストールページの**インストールと起動**:

1. `de` を選択する。
2. **言語パックをコンパイル** をクリックする。
3. **ゲームディレクトリにデプロイ** をクリックする。

またはコマンドラインから:

```bash
python src/tools/pack/apply_patch.py --langs de --game-dir "<game directory>"
```

**確認**: ログに `PR2Packs\de.txt` がコピーされたこと、フォントが `fonts/de/` に
コピーされたこと、`locale.ini` が `de` を指していることが表示されること。

---

## 9. 起動して確認する

インストールページで**ゲームを起動（インジェクションあり）**をクリックするか、ゲーム
ディレクトリの `PR2Launcher.exe` を実行します。

確認項目:

- メインメニューの文字。
- 設定メニュー。
- タイトルフォントにグリフがあるか。
- 長いテキストに欠字による空白がないか。

**確認**: インターフェースの文字が読め、空白の四角がなく、タイトルフォントが正常に
見えること。

---

## 10. よくある問題

| 症状 | 原因 / 対処 |
|---|---|
| 新しい言語がすべて空白になる | その言語用の presets セクション（`[language]`）が設定されておらず、フォントが縫合されていない。セクションを追加してステップ 7 を再実行する |
| 一部の文字だけが空白になる | donor にグリフがない。`supplement` を追加するか、より広い範囲をカバーする donor に切り替える |
| フォントが UPM の不一致を報告する | donor とゲームフォントの UPM が異なる。donor を切り替えるか、先に donor をスケーリングする |
| 中国語は正常だがタイトルフォントにグリフがない | タイトルフォントに donor がない / `supplement` が不足している |
| フォントをダブルクリックしても Windows のプレビューで開けない | 旧ベースフォントの以前からの問題で、ゲームには影響しない。`fontverify.py info` で確認する |
| フォントが非常に大きい | 現在の翻訳で使用している文字だけを縫合している。文字を追加すると自動的に再縫合される |

---

## 11. 配布に関する注意

縫合したフォントは「ゲームのオリジナルフォント + 商用/システム donor」の派生著作物で
あり、ローカルでの使用に限られます。アップロード、同梱、リポジトリへのコミットは
行わないでください。詳細は [フォントと配布](fonts-and-distribution.md) を参照してください。

---

関連項目: [新しい言語のフォント](new-language-fonts.md) ·
[翻訳と言語パック](translation-and-packs.md) ·
[ビルドとインストール](build-and-install.md) · [リリース](release.md) ·
[フォントと配布](fonts-and-distribution.md)。

---

翻訳者とメンテナーの分担は[言語追加の協力フロー](language-collaboration.md)を参照。
