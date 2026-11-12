# 新しい言語の追加とフォントの縫合：準備するもの

このリポジトリには**フォントのバイナリは一切含まれていません**。クローンして独自の言語パックをビルドし、フォントを縫合したい場合は、以下のものを自分で用意する必要があります。

## 1. ゲーム本来のラテン文字フォント（必須）

`assets/fonts/original/` は `.gitignore` に登録されているため、クローンした時点では空です。自分のゲームのコピーからフォントをエクスポートしてください：

```bash
python src/tools/font/extract_fonts.py --game-dir "<game directory>" --out assets/fonts/original
```

次のファイルが出力されます：

```
ARIAL.TTF  ELGRECO_.TTF  Tiepolo_black.ttf  Tiepolo_bold.ttf
```

`PR2_ORIG_FONTS` を設定するか、`subset_fonts.py --src` を使えば、別の場所にあるオリジナルフォントのディレクトリを指定することもできます。

## 2. donor フォント（必須、リポジトリには含まれません）

言語ごとに 1 つの設定ファイルを用意します：

```
src/tools/font/fontstitch/presets/<language>.toml
```

構造はどの言語でも共通で、`[zh]` のような外側のセクションはもうありません：

```toml
# presets/zh.toml
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

- `[[pair]]`：ゲームフォントごとに 1 つの主要 donor。
- `[[supplement]]`：主要 donor がカバーしていない文字を補う。
- `[fallback]`：最終的なフォールバック。

`presets/` ディレクトリ全体はリポジトリに含めません（パスにマシン固有の情報が入る可能性があるため）。コミットされるのは `presets.example.toml` だけです。新しい言語を追加すると、テンプレート言語の設定が自動的に `presets/<language>.toml` にコピーされるので、その後でその言語用の donor に変更します。

## 3. fontTools（必須）

```bash
python -m pip install fonttools
```

あるいは、fontTools がすでにインストールされている site-packages ディレクトリを `PR2_FONTTOOLS_SITE` に設定して指定することもできます。

## 4. フォントの制約

- donor は TrueType の `glyf` アウトラインを持っていること。
- donor の UPM は、対応するゲームフォントと一致していること：Arial は 2048、ElGreco/Tiepolo は 1000。
- 主要 donor がカバーしていない文字は `[[supplement]]` で補われる。
- 言語ごとに `build/fonts/<language>/` へ個別に生成され、他の言語には影響しません。

## 5. 生成とデプロイ

```bash
# Check the original fonts, the donors, and fontTools
python src/tools/font/subset_fonts.py --check

# Stitch a single language
python src/tools/font/subset_fonts.py --lang zh --force

# Stitch every configured language
python src/tools/font/subset_fonts.py --all --force
```

出力：

```
build/fonts/zh/ARIAL.TTF ...
build/fonts/ja/ARIAL.TTF ...
```

デプロイする際は、**対象言語**のフォントセットだけをゲームの `fonts\` ディレクトリにコピーしてください。

## 6. 配布の制限

縫合したフォントは「ゲームのオリジナルフォント + 商用 donor」の派生著作物であり、**ローカルでの使用に限られます**。アップロードする、パッケージに同梱する、リポジトリにコミットする、といったことは行わないでください。詳しくは [`fonts-and-distribution.md`](fonts-and-distribution.md) を参照してください。

関連ドキュメント：[new-language.md](new-language.md)、[release.md](release.md)、[build-and-install.md](build-and-install.md)。
