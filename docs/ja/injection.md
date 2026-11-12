# インジェクターの構成要素

『Port Royale 2』のローカライズで実行時に働く部分は、**ランチャー + DLL + 言語パックのディレクトリ**です。

**`PR2.exe` は一切書き換えません。** ランチャーが DLL をゲームのプロセスにインジェクトし、実行時に DLL がエンジンの文字列検索を引き継いで、`PR2Packs\` の翻訳を流し込みます。
元の exe は最後まで読み取り専用のままです。

ソースは `src\injector\`、ビルドスクリプトは `src\` にあります。

---

## 3つのコンポーネント

| ファイル | 役割 |
|---|---|
| `PR2Launcher.exe` | ランチャー。`PR2.exe` をサスペンド状態で起動し、DLL をインジェクトしてから実行を再開する |
| `PR2LauncherGUI.exe` | GUI。`PR2Packs\*.txt` を一覧表示し、言語を選ぶと上記のランチャーを呼び出す |
| `ui/<language>.ini` | GUI のインターフェース翻訳（UTF-8 の key=value）。パック先頭の `# pack-meta gui` で選択される |
| `PR2Packs\<language>.txt` の先頭 | `# pack-meta alias=…` / `gui=…` / `min_runtime=…`。GUI とランチャーが読み、ゲーム側はコメントとして無視する |
| `PR2TextSource.dll` | 本体ロジック。エンジンの3つの文字列検索経路をフックし、翻訳で置き換える |
| `PR2Packs\` | 言語パックのディレクトリ。パックと設定を置く。テキストは直接編集でき、再ビルドは不要 |

---

## 仕組み

```
User double-clicks PR2Launcher.exe   (or the GUI calls it with --lang=xx)
   │  CreateProcessA("PR2.exe", CREATE_SUSPENDED)
   │  VirtualAllocEx + WriteProcessMemory + CreateRemoteThread(LoadLibraryA)
   ▼
PR2.exe loads PR2TextSource.dll, DllMain → InstallHook()
   │
   ├─ LoadEditFile()      determines the language (see below), loads PR2Packs\<language>.txt
   │
   ├─ hook #1  IAT: CStringManager::Add
   │            when the engine registers the main string table (MISSION_NPC_GOODS_INFO),
   │            replace_table() rebuilds the whole English table as a translated table
   │
   ├─ hook #2  vtable: CW32StringManager::AddStringRes / LoadStringRes
   │
   └─ hook #3  A2dLib::LoadStringRes function body
                 catches the lookups the two hooks above don't cover;
                 and writes the hashes the pack doesn't cover, together with
                 the English the engine resolved, to PR2TextSource_gap.log
                 in the game directory, as leads for filling in translations
```

DLL が行うのは、**プロセス内のモジュールのインポートテーブルを書き換え**、`A2dLib-2.20A.dll!CStringManager::Add` を指すスロットを自分自身に差し替えることです。これにより、エンジンは文字列を DLL に問い合わせるようになります。インジェクト自体はランチャーが行い、DLL がリモートスレッドを作ることはありません。

翻訳を引く先は **1つだけ**、`PR2Packs\<language>.txt` です。ヒットすれば翻訳で置き換え、ミスした場合はエンジンにそのまま返し、元のテキストが使われます。

---

## パックディレクトリ PR2Packs\

```
PR2Packs\
├─ locale.ini     which pack to use
└─ zh.txt         Simplified Chinese, 3548 entries, format: 0x<hash> = text
                  (the filename is the language code; multiple files are allowed)
```

`locale.ini`:

```ini
language=zh          # corresponds to PR2Packs\<language>.txt and must match the filename
```

**言語コードの決定順序。** `LoadEditFile()` は次の順に、最初に見つかったものを採用します。

| 順序 | 取得元 | 備考 |
|---|---|---|
| 1 | `PR2_PACK_LANG` 環境変数 | ランチャーの `--lang=xx` が子プロセスの環境に書き込む。今回の起動にだけ影響する |
| 2 | `locale.ini` の `language=` | 既定値。インストールページの「ゲーム言語に設定」が書き込み、リリース版 GUI も起動成功後に書き込む |
| 3 | DLL 内蔵の `zh` | ini がまったく存在しない場合のフォールバック |

1 は環境の受け渡しに IPC を必要としません。ランチャーが `CreateProcessA` に渡す環境ブロックは `NULL`、つまり「自分の環境を継承」なので、`SetEnvironmentVariableA` を1回呼ぶだけで `PR2.exe` から見えます。**`--lang` を付けなければこの変数は存在せず、動作は従来とまったく同じです。**

```c
PR2Launcher.exe --lang=de     runs de.txt for this launch, changes no files
PR2Launcher.exe               uses the language from locale.ini
PR2Launcher.exe --help
```

`--lang` に使えるのは英字・数字・ハイフンだけです。値は `PR2Packs\<code>.txt` に埋め込まれるため、`../` を許すとパストラバーサルになります。不正な値はエラーを表示して終了します。

**「基底言語パック」というものはありません。** パックに含まれないハッシュについては、ゲームが内蔵の英語を表示します。エンジンのメイン文字列テーブルがそのままフォールバックになるので、余分なものを用意する必要はありません。

翻訳の変更に**再ビルドは不要**です。`zh.txt` を編集して保存し、ゲームを起動し直すだけです。

---

## ⚠ 中国語のエントリがまったく表示されない — 原因はタグではなく分かち書き

**エンジンはスペースで単語を区切ります。** 英語はもともとスペース区切りなので、単語が短く、幅からあふれることはほとんどありません。中国語にはスペースがないため、漢字と約物が連続した部分が**1つの単語**としてレイアウトされ、その UI コントロールの幅を超えると**エントリ全体が破棄されます**。切り詰められるのではなく、まったく表示されません。

```
English: Successful battles will boost your reputation more quickly with 5%.
         ^ each word is laid out separately, short

Chinese: 战斗获胜时，你的声望额外提高 5%。
         ^ the whole string is treated as one word, too wide → the entry is dropped
```

UI コントロールごとに使える幅は異なり、**万能な値はありません**。エントリごとに実際のゲーム内で確認する必要があります。回避策は、適切な位置に `<n>` を入れて手動で改行するか、表現を短くすることです。

---

## ソース

| ファイル | 責務 |
|---|---|
| `pr2_text_source.cpp` | 本体ロジック。3つのフック、テーブル全体の置き換え、未翻訳の捕捉 |
| `pr2_text_pack.c` | パックのローダー（純粋な C89）。INI 解析、`hash = text` の解析、UTF-8→UTF-16 変換 |
| `pr2_launcher.cpp` | ランチャー。サスペンド起動 + リモートインジェクション |

`pr2_text_pack.c` は DLL に組み込んでコンパイルされるため、単独の出力はありません。

### フックの安全性

失敗しうる操作はすべて `__try/__except` で囲んでいます。最悪の場合でも、該当する文字列が空になるか英語にフォールバックするだけで、ゲームがクラッシュすることはありません。

### 既知の問題

- **フック対象はゲームのバージョンに依存します。** コードは `A2dLib-2.20A.dll` のエクスポートを引き、関数本体とシングルトンを固定オフセットで取得します。
  `ResolveByHash` は `+0x25C70`（そのサンクのエントリは `+0x1DC5`）、
  `g_pStringMgr` は `+0x142084` です。
  別バージョンのゲームでこれらが一致しない場合、フックは対象を見つけられず、ローカライズはまったく効きません。
- **`FindOverride` は線形探索**で、`AddEdit` は重複を排除しません。パックに同じハッシュが複数ある場合は、先に書かれたものが返されます。
- **読み込み失敗が無言でした。** ~~`LoadEditFile()` が失敗すると、すべて黙って返っていました~~
  修正済み: `EditLoaded() == 0` のとき、`InstallHook()` が
  `NO pack loaded: language 'xx' from <directory>` という行を書き出すようになりました。以前はこの失敗が画面上まったく見えず、「ローカライズされていない」状態と見分けがつきませんでした。今はログの1行目で判別できます。

---

## ログ

ゲームのディレクトリに出力され、いずれも `PR2TextSource` にちなんだ名前です。

| ファイル | 内容 |
|---|---|
| `PR2TextSource.log` | 1行目 = 実際に読み込んだパックとそのエントリ数。読み込み失敗時は1行目が `NO pack loaded: …` |
| `PR2TextSource_gap.log` | パックにないハッシュ + エンジンが解決した英語。翻訳を埋めるための手がかり |
| `PR2TextSource_lsr.log` | vtable フックの記録 |
| `PR2TextSource_resolve.log` | `ResolveByHash` の記録 |
| `PR2FontPaths.log` | `PR2_FONT_LOG=1` のとき、ゲームが読むフォントパスを記録。`PR2_FONT_LOG_ALL=1` ならすべてのファイル API 呼び出しを記録 |

`gap.log` が、未翻訳を埋めるための主な手がかりになります。

## フォントのバックアップと切り替え

初めてフォントを置き換える前に、ランチャーは元の TTF 4つを次の場所にバックアップします。

```
fonts\_original\
```

受け入れるのは既知の元ファイルのサイズ + SHA-256 のみです。そのため、ルートディレクトリがすでに Noto で上書きされていても、Noto を元ファイルと誤認することはありません。復元前にもバックアップのハッシュを再検証します。

- **元ファイルはルートディレクトリに残し、上書きしません**。
- ローカライズ起動: `fonts\<language>\` が存在すれば、ランチャーが `PR2_FONT_DIR=<language>` を設定し、DLL が `fonts\ARIAL.TTF` などを `fonts\<language>\` にリダイレクトします。
- バニラ起動: `PR2Launcher.exe --vanilla` はリダイレクトを設定せず、ルートディレクトリの元ファイルをそのまま使います。ルートディレクトリがすでに置き換えられている場合は、先に `fonts\_original\` から復元します。

リダイレクトはファイル API 層（`fopen` / `CreateFileA/W` / `FindFirstFileA` / `GetFileAttributesExA`）でのみ有効で、ゲームのファイル自体は変更しません。

ログ:

```bat
set PR2_FONT_LOG=1
PR2Launcher.exe --lang=zh
```

`PR2FontPaths.log` には、`fonts\zh\ARIAL.TTF` のように書き換え後のパスが記録されます。

**ローカライズが有効かどうかを確実に示すのは、`PR2TextSource.log` の1行目だけです。** ゲームを起動したら、まずここを確認してください。

```
[text] pack 'zh' from C:\Games\Port Royale 2\PR2Packs  (3548 entries)
```

このような行があれば、パックが見つかってローカライズが有効であり、画面の中国語はそこから来ています。1行目が `NO pack loaded: language 'xx' from <directory>` なら、そのディレクトリに `<xx>.txt` がないため、DLL はエンジン内蔵のテーブルにフォールバックし、画面には元の英語が表示されます。

---

## ビルド

Visual Studio（C++ によるデスクトップ開発ワークロード）が必要です。

```
src\build_injector.bat
```

スクリプトが MSVC と Windows SDK を自動的に探します。出力はリポジトリルートの `build\` です。
**対象アーキテクチャは x86** です。PR2 は 32ビットプロセスであり、フックのコードは 32ビットの呼び出し規約に依存しています。

「x64 Native Tools Command Prompt for VS」で手動実行することもできます。

```
cd src\injector
cl /nologo /MT /LD /Ox /W3 /utf-8 /D_CRT_SECURE_NO_WARNINGS ^
   pr2_text_source.cpp pr2_text_pack.c ^
   /Fe:PR2TextSource.dll /link /OUT:PR2TextSource.dll psapi.lib

cl /nologo /MT /Ox /W3 /utf-8 /wd4819 /D_CRT_SECURE_NO_WARNINGS ^
   pr2_launcher.cpp ^
   /Fe:PR2Launcher.exe /link /OUT:PR2Launcher.exe
```

`/utf-8` と、ソースファイルの UTF-8 BOM はどちらも必須です。ない場合、`cl` はソースをコードページ 936 として読み込み、コンパイル時に中国語のリテラルが切り詰められます（`到` が半バイトになる）。その結果、ランチャーの中国語メッセージはすべて文字化けします。`/wd4819` は、`/utf-8` を付けてもなお報告される C4819 の誤検出を抑止するためのものです。リテラル自体は壊れていません。

---

関連ドキュメント: [翻訳と言語パック](translation-and-packs.md) · [ビルドとインストール](build-and-install.md)
