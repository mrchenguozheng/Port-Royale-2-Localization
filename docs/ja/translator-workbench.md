# 翻訳者ワークベンチ

翻訳者が行うのは翻訳と校正だけです。Visual Studio、Node.js、fontTools、ゲーム用
インジェクタは必要ありません。ワークベンチは、翻訳ページだけを公開する小さなローカル
Python サービスです。

## パッケージのビルド

リポジトリのルートで：

```bat
python src\tools\pack\make_translator.py --lang ja --out dist\PR2Translator-ja
```

Python ランタイムを同梱し、翻訳者が Python をインストールしなくて済むようにするには：

```bat
python src\tools\pack\make_translator.py --lang ja --out dist\PR2Translator-ja ^
    --python-dir C:\Python311
```

`--python-dir` に指定するディレクトリには `python.exe` が含まれている必要があります。

## パッケージの内容

```
PR2Translator-ja/
├─ start.bat
├─ README.txt
├─ src/
│  ├─ editor/
│  │  ├─ server.py
│  │  └─ dist/             prebuilt frontend
│  ├─ tools/               translation, validation, terminology
│  ├─ live/ja.toml         current language
│  ├─ orig/                English reference
│  ├─ seed/                initial text
│  └─ find_python.bat
└─ glossary/               terminology
```

`build/`、インジェクタ、フォント、`PR2Packs/`、インストールページは含まれません。

## 翻訳者の使い方

1. パッケージを展開する；
2. `start.bat` をダブルクリックする；
3. ブラウザで `/translate/ja` が開く；
4. 翻訳して保存する；
5. コンソールウィンドウを閉じてサービスを停止する。

表示されるのは翻訳エディタだけです。ビルド／デプロイ／起動の各エンドポイントは 403 を
返します。

## 成果物の返送

翻訳者が返送するファイル：

```
src/live/ja.toml
```

その後、メンテナーが次を行います：

- プレースホルダーと改行の検証；
- 言語パックのコンパイル；
- フォントのビルド；
- リリースパッケージの作成；
- GOG 英語版での検証。

## 注意

- ワークベンチは `127.0.0.1` でのみ待ち受けます；
- ランタイムを同梱しない場合は Python 3.11+ が必要です；
- Git は不要です；
- 他の言語の翻訳ファイルは含まれません。
