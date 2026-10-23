# リリース

## 対応ゲームビルド

**対応するのは GOG 英語版 `1.1.2.3` のみです。** GOG フランス語版、Steam 英語版、その他のビルドは対象外です。これらのパッケージをそれらのビルドに導入しないでください。今後の作業は[未解決の課題](pending.md)にあります。

## バージョン番号

最初の公開リリースは `v1.0.0` です。GOG のクリーンなコピーがまだ検証できていない間は `v0.9.0` を使用します。

| バージョン | 用途 |
|---|---|
| `v0.9.0` | RC |
| `v1.0.0` | 最初の公開リリース |
| `v1.0.x` | 修正、ドキュメント、軽微なフォント修正 |
| `v1.1.0` | 新しい言語パックまたは注目すべき機能 |
| `v1.2.0` | 新しいゲームビルド（Steam / GOG フランス語版など） |
| `v2.0.0` | 互換性のないパック形式またはランタイム契約 |

リリースバージョンと `PR2_RUNTIME_VERSION` は別物です。

タグを打つ前に再生成します:

```bat
python src\tools\pack\make_release.py --lang zh --lang ja --version v1.0.0
git tag v1.0.0
git push origin v1.0.0
```

## 目標

プレイヤーは言語パックをダウンロードしてゲームディレクトリに展開するだけで、すぐに使える状態になります:

```
PR2-zh-v1.0.0.zip
├─ PR2Launcher.exe
├─ PR2LauncherGUI.exe      ← GUI: choose a language and launch
├─ PR2TextSource.dll
├─ ui/
│  ├─ zh.ini
│  ├─ en.ini
│  └─ ja.ini
├─ PR2Packs/
│  ├─ zh.txt
│  └─ locale.ini
├─ fonts/
│  └─ zh/
│     ├─ ARIAL.TTF
│     ├─ ELGRECO_.TTF
│     ├─ Tiepolo_black.ttf
│     └─ Tiepolo_bold.ttf
├─ README.txt
├─ NOTO-SOURCES.txt       ← font source notes (not placed in fonts/)
├─ RUNTIME-VERSION        ← runtime version, used for language pack compatibility checks
└─ OFL.txt
```

`fonts/<lang>/` に置くのは TTF 4 ファイルのみで、ドキュメント類は入れません。ゲームはこのディレクトリを走査します。フォントの出典情報は、パックのルートに `NOTO-SOURCES.txt` としてまとめて置きます。

ランチャーはパスのリダイレクトを使うため、ゲームは対応するサブディレクトリを読み込み、`fonts/` ルートにある元のフォントを**上書きしません**。1 つのゲームディレクトリに複数の言語サブディレクトリを置くことができ、ランチャーは `locale.ini` または `--lang` でそのうち 1 つを選択します。一方、オリジナルの起動ではルートディレクトリが使われます。

プレイヤーは `PR2LauncherGUI.exe` をダブルクリックすることもできます。一覧から言語を選んで「選択した言語で起動」を押します。「オリジナルで起動」なら、そのまま英語で起動します。GUI は `PR2Launcher.exe --lang=…` を呼び出しているだけです。

言語パックは自身の表示名と GUI 言語を持ちます:

```toml
# src/packs/zh.toml
alias = "简体中文"
gui = "zh"
```

コンパイル後、これらは言語パックの先頭に書き込まれます:

```
# pack-meta alias=简体中文
# pack-meta gui=zh
```

ゲームは `#` コメントを無視します。GUI はこれを読み取り、次のように動作します:

- 一覧には `alias` が表示されます。
- その言語パックに切り替えると、`gui` に対応する `ui/<gui>.ini` にインターフェースのテキストが切り替わります。

`# pack-meta` のないパックでは、一覧に言語コードがそのまま表示されます。外部からの alias 上書きはもうサポートされていません。

GUI での起動に成功すると、GUI は選択した言語をそのまま書き戻します:

```ini
# PR2Packs/locale.ini
language=zh
```

次回起動時にはこの値を読み取るため、`PR2.exe` を直接ダブルクリックしても同じ言語が使われます。

表示名はパックの `# pack-meta alias` からのみ取得します。インターフェース言語は `# pack-meta gui` から取得し、`gui` メタデータがない場合は Windows の UI 言語に従い、それもなければ英語にフォールバックします。

言語パックは最小ランタイムバージョンを宣言できます:

```
# pack-meta min_runtime=1
```

`min_runtime` が現在のランタイムバージョンより高い場合、GUI / ランチャーは起動を拒否して更新を促します。これにより「古い DLL + 新しい言語パック」という組み合わせで、テキストが未翻訳のまま黙って表示されることを防げます。

パッケージにはゲーム本体、`.cpr` ファイル、マップ、音楽、その他のゲームアセットは含まれません。

## フォント

リリースはフォントを**合成しません**。完全な Noto フォントで直接置き換えます:

| ゲーム側ファイル | フォント |
|---|---|
| `ARIAL.TTF` | Noto Sans SC/JP Regular |
| `ELGRECO_.TTF` | Noto Serif SC/JP Black |
| `Tiepolo_black.ttf` | Noto Serif SC/JP Black |
| `Tiepolo_bold.ttf` | Noto Serif SC/JP Bold |

- **サブセット化なし**: 文字セット全体を保持します。
- VF ファイルは静的ウェイトにインスタンス化します。
- フォントは SIL OFL 1.1 で提供され、リリースには `OFL.txt` を同梱します。
- 入手先:
  - Google Fonts: Noto Sans SC / Noto Serif SC / Noto Sans JP / Noto Serif JP
  - <https://fonts.google.com/noto>
  - <https://openfontlicense.org/>

フォントは大容量です（中国語 1 セットで約 50 MB、zip で約 32 MB）。これが「サブセット化しない」ことの代償です。

リリースでは 4 つの TTF を別々に保持し、「グリフが同一のファイルをエイリアス／ハードリンクで重複排除する」ことは**しません**。将来、別のゲームファイル名に別のフォントやウェイトを割り当てる可能性があり、重複排除はその柔軟性を奪ってしまうからです。

静的版の `NotoSansSC-Regular`、`NotoSerifSC-Bold`、`NotoSerifSC-Black` などのファイルがマシンに既にある場合、生成はそれらをコピーしてリネームするだけで、**fontTools は不要**です。ソースファイルが `*-VF.ttf` の可変フォントである場合にのみ、静的ウェイトへのインスタンス化に fontTools が必要になります。

### フォントキャッシュ

生成結果は次にキャッシュされます:

```
build/font-cache/noto/
```

キャッシュキーには、ソースフォント内容の SHA-256、ウェイト、対象ファイル名、fontTools のバージョン、キャッシュバージョンが含まれます。再計算が行われるのは、ソースフォントまたはパラメータが変わったときだけです。同じ言語を 2 回パッケージングすると、キャッシュがそのまま使われます。

再計算を強制するには:

```bat
python src\tools\font\make_noto_fonts.py --lang zh --out <directory> --no-cache
```

別のキャッシュディレクトリを使うには:

```bat
python src\tools\font\make_noto_fonts.py --lang zh --out <directory> --cache-dir D:\font-cache
```

`make_release.py` はデフォルトでキャッシュを再利用します。再計算を強制するには:

```bat
python src\tools\pack\make_release.py --lang zh --version v1.0.0 --no-font-cache
```

合成フォント（`subset_fonts.py`）は別に `.stitch.json` キャッシュを持ち、使用中の文字セット、ドナーフォント、バージョンをキーとするため、合成が繰り返されることはありません。

## フォントが見つからない場合

### プログラムによる検出方法

ローカライズ版の起動時には次を確認します:

```
<game directory>\fonts\<lang>\
├─ ARIAL.TTF
├─ ELGRECO_.TTF
├─ Tiepolo_black.ttf
└─ Tiepolo_bold.ttf
```

4 つのファイルのうち 1 つでも欠けていると、そのフォントセットは「不完全」とみなされます。

### プログラムの処理

**GUI（`PR2LauncherGUI.exe`）**

ダイアログを表示します:

> `fonts\zh\ has no TTF fonts. Starting anyway will use the original Latin fonts; Chinese text may be missing. Start anyway?`

*(「fonts\zh\ に TTF フォントがありません。このまま起動すると元のラテン系フォントを使うため、中国語のテキストが欠ける可能性があります。それでも起動しますか？」という意味です。)*

- 「はい」を選ぶ: 起動を続行します。
- 「いいえ」を選ぶ: キャンセルします。

**ランチャー（`PR2Launcher.exe`）**

GUI を迂回した場合でも、再度チェックします:

- フォントが揃っている: `PR2_FONT_DIR=<lang>` を設定し、`fonts\<lang>\` にリダイレクトします。
- フォントが不完全: リダイレクトを設定せず、`fonts\` ルートの元のフォントにフォールバックし、コンソールに出力します:

```
[PR2Launch] fonts\zh\ 字体不完整，回退到原版根目录字体
```

*(このメッセージは「fonts\zh\ のフォントセットが不完全なため、元のルートフォントにフォールバックします」という意味です。)*

これでゲームは起動できますが、中国語のテキストはほぼ確実に空白で描画され、元のラテン文字だけが正しく表示されます。

### ユーザーが行うべきこと

1. **ディレクトリを確認する**
   ゲームディレクトリに本当に以下があるか確認します:

   ```
   fonts\zh\ARIAL.TTF
   fonts\zh\ELGRECO_.TTF
   fonts\zh\Tiepolo_black.ttf
   fonts\zh\Tiepolo_bold.ttf
   ```

2. **フォントを展開し直す**
   リリース zip から `fonts\<lang>\` ディレクトリ全体を展開してください。言語パック `PR2Packs\<lang>.txt` だけをコピーしても足りません。

3. **ルートディレクトリに置かない**
   元のフォントは `fonts\` ルートに残し、ローカライズ版のフォントは `fonts\<lang>\` サブディレクトリに置く必要があります。

4. **ウイルス対策ソフトを確認する**
   フォントファイルは大きく、ときどき隔離されることがあります。復元してから再起動してください。

5. **言語コードが一致しているか確認する**
   `PR2Packs\<lang>.txt`、`fonts\<lang>\`、`locale.ini` の `language=` は同じコード（たとえばすべて `zh`）でなければなりません。

6. **それでも起動したい場合**
   続行することもできますが、表示されるのは元のラテン系フォントだけです。中国語のテキストが欠けていても、ゲームが壊れているわけではありません。

### 元のフォント

元の 4 つの TTF は `fonts\` ルートに残り、ローカライズによって上書きされることはありません。ランチャーは初回の置き換え前に `fonts\_original\` へバックアップします（SHA-256 で検証）。`PR2Launcher.exe --vanilla` はルートディレクトリの元のフォントを使用します。

## パッケージング

### 1. ランタイムをビルドする

C++ デスクトップ開発ワークロードを含む Visual Studio が必要です:

```bat
cd C:\path\to\pr2-localization
src\build_injector.bat
```

出力:

```
build\PR2Launcher.exe
build\PR2LauncherGUI.exe
build\PR2TextSource.dll
build\ui\zh.ini / en.ini / ja.ini
```

翻訳だけを変更した場合は、この手順を省略できます。

### 2. 言語パックとフォントをパッケージングする

```bat
python src\tools\pack\make_release.py --lang zh --lang ja --version v1.0.0
```

1 言語ずつでも構いません:

```bat
python src\tools\pack\make_release.py --lang zh --version v1.0.0
```

出力:

```
dist\PR2-zh-v1.0.0.zip
dist\PR2-ja-v1.0.0.zip
```

`make_release.py` は自動的に次の処理を行います:

- 言語パックをコンパイルする。
- Noto フォントをビルドする（デフォルトは `--fonts noto`）。
- ランタイム、`ui/`、`PR2Packs/`、フォントをコピーする。
- `RUNTIME-VERSION` と対応ビルドの注記を書き込む。
- `README.txt`、`OFL.txt`、`NOTO-SOURCES.txt` を同梱する。

初回の VF インスタンス化には次が必要です:

```bat
python -m pip install fonttools
```

フォントの生成結果は `build\font-cache\noto\` にキャッシュされ、再利用されます。再ビルドを強制するには:

```bat
python src\tools\pack\make_release.py --lang zh --version v1.0.0 --no-font-cache
```

### 3. パッケージングモデル

現在のリリースは 1 言語につき 1 つのバンドル（ランタイム + パック + フォント）を同梱し、プレイヤーが展開してそのまま遊べるようにしています。

ランタイムと言語を分離する構成は将来の選択肢として残してあり、まだ有効化していません。言語の数が増えたときや、ランタイムを頻繁に独立更新する必要が出たときに再検討します。

### 4. 公開前の確認

1. クリーンなゲームコピーに展開する。
2. `PR2LauncherGUI.exe` を実行する。
3. 言語を選んで起動する。
4. UI テキスト、フォント、オリジナル起動を確認する。
5. `README.txt` に対応ビルドが **GOG 英語版 1.1.2.3** と書かれていることを確認する。

合成を実行せずに Noto フォントだけを生成するには:

```bash
python src/tools/font/make_noto_fonts.py --lang zh --out dist/PR2-zh-v1.0.0/fonts
```

### その他の言語

`src/tools/font/make_noto_fonts.py` の `LANGS` にマッピングを追加します。たとえば:

```python
"ko": {
    "sans": ("NotoSansKR", 400),
    "serif": ("NotoSerifKR", (700, 900)),
    "label": "Korean",
},
```

フォント名はローカル環境のインストール内容と一致している必要があります。対応する Noto フォントがない場合は、先に Google Fonts からダウンロードしてインストールしてください。

## 応用: サブセット化と合成

どちらもデフォルトのリリースフローには含まれません:

- **サブセット化**: `fontsubset.py` は使用されている文字に応じてフォントを縮小します。
- **合成**: `subset_fonts.py` は元のラテン系フォントをドナーと合成し、元のグリフを保ちます。

合成フォントは派生著作物です。**個人利用のみとし、公開リリースには絶対に含めないでください。** `make_release.py --fonts stitch` は私的なパッケージ専用です。

## 翻訳者ワークベンチ

翻訳者ワークベンチは `PR2-zh-*.zip` / `PR2-ja-*.zip` には**入れません**。
同じリリースの独立した添付ファイルにします：

```text
PR2-zh-v1.0.0.zip
PR2-ja-v1.0.0.zip
PR2Translator-v1.0.0.zip
```

ビルド：

```bat
python src\tools\pack\make_translator.py --out dist\PR2Translator-v1.0.0
Compress-Archive -Path dist\PR2Translator-v1.0.0\* ^
    -DestinationPath dist\PR2Translator-v1.0.0.zip
```

理由：

- 翻訳者パッケージは約 16 MB で Python を同梱するため、プレイヤーには不要；
- ゲーム zip は「解凍して起動」のまま；
- エディタだけを更新でき、ゲームパックを再ビルドしなくて済む。

GitHub Actions では別 job で `PR2Translator-*.zip` をビルドしてアップロードします。

## GitHub Actions

タグをトリガーとして実行され、1 言語につき 1 パッケージを生成します:

```yaml
on:
  push:
    tags: ['v*']

jobs:
  release:
    runs-on: windows-latest
    strategy:
      matrix:
        lang: [zh, ja]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install fonttools
      - run: python src/tools/pack/make_release.py --lang ${{ matrix.lang }} --version ${{ github.ref_name }}
      - uses: softprops/action-gh-release@v2
        with:
          files: dist/*.zip
```

前提条件: インジェクタがビルド済みで `build/` に置かれていること。Noto フォントがランナー上で利用可能であること（または事前に固定パスへダウンロードしておくこと）。
