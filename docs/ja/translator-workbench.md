# 翻訳者ワークベンチ

翻訳者が行うのは翻訳と校正だけです。Visual Studio、Node.js、fontTools、ゲーム用
インジェクタは必要ありません。ワークベンチは、翻訳ページだけを公開する小さなローカル
Python サービスです。

## パッケージのビルド

リポジトリのルートで：

```bat
python src\tools\pack\make_translator.py
```

既定の出力は `dist\PR2Translator` で、すべての編集可能な言語を含みます。
既定では現在の Python ランタイムを同梱するため、翻訳者は Python を
インストールする必要がありません。

カスタム Python を使う場合：

```bat
python src\tools\pack\make_translator.py ^
    --python-dir C:\Python311
```

Python を同梱しない場合：

```bat
python src\tools\pack\make_translator.py ^
    --system-python
```

`--python-dir` に指定するディレクトリには `python.exe` が含まれている必要があります。

## パッケージの内容

```
PR2Translator/
├─ start.bat
├─ README.txt
├─ editor/
│  ├─ server.py           標準ライブラリのみの独立サーバー
│  └─ web/                英語 UI
├─ shared/core/           共用の保存・検証
├─ data/
│  ├─ live/*.toml         切り替え可能な言語
│  └─ orig/               英語・フランス語の参考
└─ python/                既定で同梱
```

`build/`、インジェクタ、フォント、`PR2Packs/`、用語集、インストールページは
含まれません。

ソースは `editor/` にあり、単独で起動できます：

```bat
editor\start.bat
```

## 翻訳者の使い方

1. パッケージを展開する；
2. `start.bat` をダブルクリックする；
3. ブラウザで `/translate/ja` が開く；
4. 翻訳して保存する；
5. コンソールウィンドウを閉じてサービスを停止する。

ワークベンチにはインストール・ビルド・起動の入口はありません。

## 複数言語

1 つのエディタで `data/live/*.toml` の複数言語を開けます：

- 上部の **Translation language** で切り替え；
- URL は `/translate/<lang>` に変わります；
- 言語ごとに再起動する必要はありません；
- 起動するたびに言語選択ページを開きます；
- 明示的な `--lang` がある場合だけ、その言語を直接開きます。

参考列は英語の下にフランス語を表示します：

```text
English
French reference
```

フランス語は参照専用です。

## エディタ UI の文言

**Editor UI text** は、このエディタ自身のボタン・ラベル・ヒントだけを変更します。
ゲーム本文の翻訳は変更しません。

- `Interface language` で UI 言語を切り替えます；
- `ko` などの言語を新規作成できます；
- キーは読み取り専用で、空欄は英語にフォールバックします；
- ゲーム本文は **Game translation** のままです。

## 成果物の返送

翻訳者が返送するファイル：

```
data/live/ja.toml
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
