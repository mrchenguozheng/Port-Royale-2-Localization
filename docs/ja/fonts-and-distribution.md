# フォントと配布の制限

## 概要

**合成フォントはローカルでの使用に限ります。配布しないでください。**

リリースビルドは既定ではフォントを**合成しません**。ゲームの 4 つのフォントを完全な Noto フォントに置き換えるだけで、これらはパッケージに同梱して再配布できます
（[`release.md`](release.md) を参照）。以下では、任意で利用できる合成の手順について説明します。

`build/fonts/<lang>/*.ttf` は fontstitch で生成された二次的著作物です。

- ベースとなるのはゲーム本来のラテン文字フォント（Ascaron / Port Royale 2）です。
- ドナーとなるのはシステムフォントまたは商用フォントです。Microsoft YaHei、STZhongsong、
  Source Han Serif、ZhongQi ZhiMang、Noto Serif JP などがあります。
- **言語ごとに 1 つの `presets/<lang>.toml`**：このディレクトリはリポジトリにコミットされておらず、
  `presets.example.toml` をコピーして作成します。現在は `zh` と `ja` があり、互いに独立しています。

これらのフォント自体のライセンスは通常、**改変後の再配布を許可していません**。合成結果を
アップロードする、パッケージに同梱する、リリースで頒布する、リポジトリにコミットする、
といった行為はいずれもライセンス違反となる可能性があります。

## すでに講じられている防止策

- `.gitignore` は `assets/fonts/original/` と `build/fonts/` を無視します。
- `subset_fonts.py` は出力ディレクトリに `不要分发.txt`（「配布しないこと」）というファイルを書き出します。
- デプロイスクリプトは 4 つの `.ttf` ファイルだけをゲームディレクトリの `fonts/<lang>/` にコピーし、この注意書きファイルはフォントディレクトリに持ち込みません。
- リポジトリがコミットするのは合成コードとプリセットのみで、フォントファイルは一切コミットしません。

## 第三者が利用したい場合

利用を希望する人には、自分のマシンで次の準備をしてもらいます。

1. 自分のゲームのコピーから元のフォントを抽出します。
   ```bash
   python src/tools/font/extract_fonts.py --game-dir "<game dir>" --out assets/fonts/original
   ```
2. 言語ごとに `src/tools/font/fontstitch/presets/<lang>.toml` を用意し
   （`presets.example.toml` からコピーできます）、ドナーフォントはインストールするなどして自分で用意します。
3. 前提条件を確認して生成します。

```bash
python src/tools/font/subset_fonts.py --check
python src/tools/font/subset_fonts.py --all
```

各言語の出力は `build/fonts/<lang>/` に書き出され、デプロイ時にゲームディレクトリの
`fonts/<lang>/` へコピーされます。ルートディレクトリにある元のフォントは上書きしません。
詳しいチェックリストは [`new-language-fonts.md`](new-language-fonts.md) を参照してください。

## 関連ファイル

- `src/tools/font/subset_fonts.py`：合成のエントリーポイント。
- `src/tools/font/fontstitch/`：合成エンジンとドナーのプリセット。
- [`build-and-install.md`](build-and-install.md)：ビルド手順におけるフォントの注意事項。
